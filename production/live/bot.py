"""Live trading bot for Binance USDT-M Futures.

Trading logic is UNCHANGED (reused from strategy_aggressive_lv1.decide_v15).
This file is the execution + safety layer:

  * Real STOP_MARKET / TAKE_PROFIT_MARKET orders on the exchange protect every
    position even if the bot process dies (closePosition=true reduce-only).
  * SQLite state persists position metadata for crash recovery.
  * On startup, reconcile() makes exchange + DB consistent:
      - resume managing known positions (replace missing SL/TP)
      - ADOPT orphan positions (place emergency SL) [user choice]
      - record positions that closed while the bot was down
      - cancel dangling orders with no position
  * Every operation is wrapped so a transient failure never kills the loop.

Run:  python -m live.bot      (from D:/Temp/Trading)
Mode is chosen via BOT_MODE env var (testnet|dry|live), default testnet.
"""
import time
import logging
import signal
from datetime import datetime, timezone

from . import config
from .binance_client import BinanceClient, BinanceError
from .state_db import StateDB
from .exchange_filters import ExchangeFilters
from . import strategy_adapter as sa
from . import telegram as tg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    handlers=[logging.FileHandler(config.LOG_PATH, encoding="utf-8"),
              logging.StreamHandler()],
)
log = logging.getLogger("bot")

RUNNING = True


def _stop(signum, frame):
    global RUNNING
    log.info(f"Signal {signum} received -> graceful shutdown after current cycle")
    RUNNING = False


signal.signal(signal.SIGINT, _stop)
signal.signal(signal.SIGTERM, _stop)


class Bot:
    def __init__(self):
        log.info(f"=== Starting bot in MODE={config.MODE} STRATEGY={config.STRATEGY_LEVEL} ===")
        self._acquire_instance_lock()
        self.client = BinanceClient()
        self.db = StateDB(config.STATE_DB_PATH)
        self.filters = ExchangeFilters(self.client)
        self.btc_regime = "neutral"
        self.last_decision_bar = None
        self._startup_notified = False
        self._last_time_sync = time.time()

    def _acquire_instance_lock(self):
        """Prevent two bot processes with the same strategy level from running.
        Uses a file lock on Linux; falls back gracefully on Windows (dev only)."""
        lock_path = f"/tmp/scbot_lock_{config.MODE}_{config.STRATEGY_LEVEL}.lock"
        try:
            import fcntl
            self._lock_fd = open(lock_path, "w")
            try:
                fcntl.flock(self._lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                log.info(f"Acquired instance lock {lock_path}")
            except (IOError, OSError) as e:
                log.critical(f"Another bot instance is already running ({lock_path}). Exiting.")
                raise SystemExit(1) from e
        except ImportError:
            log.warning("fcntl not available (Windows/dev); instance lock disabled")
            self._lock_fd = None

    def _sync_time_if_needed(self):
        """Resync server time periodically to avoid timestamp drift."""
        if time.time() - self._last_time_sync >= 1800:  # 30 min
            try:
                self.client._sync_time()
                self._last_time_sync = time.time()
                log.info("Time resynced")
            except Exception as e:
                log.warning(f"Periodic time sync failed: {e}")

    # ---------------- helpers ----------------
    def _cid(self, symbol, kind):
        """Deterministic-ish clientOrderId with our prefix for recognition."""
        ms = int(time.time() * 1000) % 100000000
        return f"{config.ORDER_PREFIX}_{symbol}_{kind}_{ms}"[:36]

    def _is_our_order(self, order):
        cid = order.get("clientOrderId", "")
        return cid.startswith(config.ORDER_PREFIX)

    def get_equity(self):
        """Account equity (wallet + unrealized PnL) for position sizing."""
        try:
            equity, avail = self.client.equity_usdt()
            return equity, avail
        except BinanceError as e:
            log.error(f"get_equity failed: {e}")
            return None, None

    # ---------------- protective orders ----------------
    def place_protection(self, symbol, direction, sl_price, tp_price):
        """Place SL (STOP_MARKET) + TP (TAKE_PROFIT_MARKET), closePosition=true.
        Returns (sl_cid, tp_cid). Raises if SL cannot be placed (critical)."""
        close_side = "SELL" if direction == "LONG" else "BUY"
        sl_price = self.filters.round_price(symbol, sl_price)
        tp_price = self.filters.round_price(symbol, tp_price)

        sl_cid = self._cid(symbol, "sl")
        self.client.new_stop_market(symbol, close_side, sl_price,
                                    client_id=sl_cid, close_position=True)
        tp_cid = None
        try:
            tp_cid = self._cid(symbol, "tp")
            self.client.new_take_profit_market(symbol, close_side, tp_price,
                                              client_id=tp_cid, close_position=True)
        except BinanceError as e:
            log.warning(f"{symbol} TP placement failed (SL is set, continuing): {e}")
            tp_cid = None
        return sl_cid, tp_cid

    def cancel_protection(self, symbol):
        """Cancel all of OUR protective (algo SL/TP) orders for a symbol.
        Also clears any regular orders we may have placed (defensive)."""
        try:
            for o in self.client.open_algo_orders(symbol):
                if self._is_our_order(o):
                    self.client.cancel_algo_order(symbol, algo_id=o.get("algoId"),
                                                  client_id=o.get("clientAlgoId"))
        except BinanceError as e:
            log.warning(f"cancel_protection (algo) {symbol}: {e}")
        try:
            for o in self.client.open_orders(symbol):
                if self._is_our_order(o):
                    self.client.cancel_order(symbol, order_id=o["orderId"])
        except BinanceError as e:
            log.warning(f"cancel_protection (regular) {symbol}: {e}")

    def has_open_order_type(self, symbol, otype):
        """True if an OUR algo order of the given type (STOP_MARKET/TAKE_PROFIT_MARKET)
        exists for the symbol."""
        try:
            return any(o["type"] == otype for o in self.client.open_algo_orders(symbol))
        except BinanceError:
            return False

    # ---------------- reconciliation (CRASH RECOVERY) ----------------
    def reconcile(self):
        log.info("--- Reconciliation start ---")
        try:
            ex_positions = {p["symbol"]: p for p in self.client.position_risk()}
        except BinanceError as e:
            log.critical(f"Cannot fetch positions for reconciliation: {e}. Aborting startup.")
            raise
        db_positions = {p["symbol"]: p for p in self.db.all_positions()}
        log.info(f"Exchange positions: {list(ex_positions)} | DB positions: {list(db_positions)}")

        # 1) positions in DB but NOT on exchange -> closed while bot was down
        for symbol in list(db_positions):
            if symbol not in ex_positions:
                dbp = db_positions[symbol]
                log.warning(f"{symbol}: in DB but no exchange position -> closed while down")
                self.cancel_protection(symbol)
                pnl, exit_px, _ = self._realized(symbol, dbp)
                self.db.record_closed(symbol, dbp["direction"], dbp["entry_price"],
                                      exit_px or 0, dbp["qty"], pnl or 0.0,
                                      "closed_while_down", dbp["entry_time"])
                self.db.delete_position(symbol)
                self.db.log_event("recover_closed", symbol, {"reason": "closed_while_down", "pnl": pnl})
                self._notify_exit(symbol, dbp, "closed_while_down", pnl, exit_px)

        # 2) positions on exchange
        for symbol, exp in ex_positions.items():
            if symbol in db_positions:
                # known position -> ensure SL/TP exist; replace if missing
                dbp = db_positions[symbol]
                self._ensure_protection(symbol, dbp, exp)
            else:
                # ORPHAN -> adopt per user choice
                self._adopt_orphan(symbol, exp)

        # 3) dangling orders for symbols with no position (check BOTH algo + regular)
        try:
            all_orders = self.client.open_algo_orders()
            try:
                all_orders = all_orders + self.client.open_orders()
            except BinanceError:
                pass
            sym_no_pos = set(o["symbol"] for o in all_orders) - set(ex_positions)
            for symbol in sym_no_pos:
                log.warning(f"{symbol}: open orders but no position -> cancelling dangling")
                self.cancel_protection(symbol)
        except BinanceError as e:
            log.warning(f"dangling-order scan failed: {e}")

        log.info("--- Reconciliation done ---")

    def _ensure_protection(self, symbol, dbp, exp):
        """Make sure a known position still has SL/TP on the exchange."""
        try:
            orders = self.client.open_algo_orders(symbol)
        except BinanceError as e:
            log.warning(f"{symbol}: cannot list algo orders during recovery: {e}")
            orders = []
        has_sl = any(o["type"] == "STOP_MARKET" for o in orders)
        has_tp = any(o["type"] == "TAKE_PROFIT_MARKET" for o in orders)
        if has_sl and has_tp:
            log.info(f"{symbol}: protection intact, resuming management")
            return
        log.warning(f"{symbol}: missing protection (sl={has_sl} tp={has_tp}) -> replacing")
        # cancel whatever is left, re-place both from DB-stored prices
        self.cancel_protection(symbol)
        try:
            sl_cid, tp_cid = self.place_protection(symbol, dbp["direction"],
                                                   dbp["sl_price"], dbp["tp_price"])
            self.db.update_position_fields(symbol, sl_client_id=sl_cid, tp_client_id=tp_cid)
            self.db.log_event("recover_protection", symbol, "re-placed SL/TP")
        except BinanceError as e:
            log.critical(f"{symbol}: FAILED to restore protection: {e}")
            tg.notify_error(symbol, f"recovery: cannot restore SL/TP: {e}")

    def _adopt_orphan(self, symbol, exp):
        """Adopt an orphan position: place emergency SL, register in DB."""
        log.warning(f"{symbol}: ORPHAN position (amt={exp['amt']}), adopting")
        direction = exp["dir"]
        entry = exp["entry"] or exp["mark"]
        qty = abs(exp["amt"])
        lev = exp.get("leverage") or config.MAX_LEVERAGE
        # emergency SL at configured pct; keep direction-aware
        if direction == "LONG":
            sl_price = entry * (1 - config.ORPHAN_SL_PCT / 100)
            tp_price = entry * (1 + config.ORPHAN_SL_PCT * 3.5 / 100)
        else:
            sl_price = entry * (1 + config.ORPHAN_SL_PCT / 100)
            tp_price = entry * (1 - config.ORPHAN_SL_PCT * 3.5 / 100)
        self.cancel_protection(symbol)  # clear any unknown orders first
        try:
            sl_cid, tp_cid = self.place_protection(symbol, direction, sl_price, tp_price)
        except BinanceError as e:
            log.critical(f"{symbol}: cannot protect orphan, closing it for safety: {e}")
            self._market_close(symbol, direction, qty, "orphan_unprotectable")
            return
        self.db.upsert_position({
            "symbol": symbol, "direction": direction, "entry_price": entry,
            "qty": qty, "leverage": lev, "orig_sl_pct": config.ORPHAN_SL_PCT,
            "sl_price": sl_price, "tp_price": tp_price, "be_moved": 0, "trail_moved": 0,
            "entry_time": int(time.time() * 1000), "score": 0, "margin": 0,
            "sl_client_id": sl_cid, "tp_client_id": tp_cid, "entry_client_id": None,
            "adopted": 1,
        })
        self.db.log_event("adopt_orphan", symbol, {"entry": entry, "sl": sl_price})
        tg.notify_orphan_adopted(symbol, direction, qty, entry, lev,
                                 sl_price, tp_price, config.ORPHAN_SL_PCT)

    def _realized(self, symbol, dbp):
        """Best-effort realized PnL + exit price after a close. Never raises."""
        try:
            return self.client.realized_pnl_since(symbol, dbp.get("entry_time"))
        except Exception as e:
            log.debug(f"{symbol}: realized PnL fetch failed (ignored): {e}")
            return None, None, None

    def _notify_exit(self, symbol, dbp, reason, pnl, exit_px):
        """Build a detailed exit notification. Never raises / never blocks."""
        try:
            entry = dbp.get("entry_price")
            qty = dbp.get("qty")
            margin = dbp.get("margin")
            hold_s = None
            if dbp.get("entry_time"):
                hold_s = max(0, time.time() - dbp["entry_time"] / 1000)
            pnl_pct = None
            if entry and exit_px:
                if dbp.get("direction") == "LONG":
                    pnl_pct = (exit_px - entry) / entry * 100
                else:
                    pnl_pct = (entry - exit_px) / entry * 100
            tg.notify_exit(symbol, dbp.get("direction"), reason, pnl=pnl, pnl_pct=pnl_pct,
                           entry_price=entry, exit_price=exit_px, qty=qty,
                           hold_seconds=hold_s, margin=margin)
        except Exception as e:
            log.debug(f"{symbol}: exit noti build failed (ignored): {e}")

    def _market_close(self, symbol, direction, qty, reason):
        close_side = "SELL" if direction == "LONG" else "BUY"
        qty = self.filters.round_qty(symbol, qty)
        try:
            self.cancel_protection(symbol)
            self.client.new_market_order(symbol, close_side, qty,
                                         client_id=self._cid(symbol, "close"), reduce_only=True)
            self.db.log_event("market_close", symbol, reason)
        except BinanceError as e:
            log.error(f"{symbol}: market close failed ({reason}): {e}")

    # ---------------- daily halt ----------------
    def check_daily_halt(self, equity):
        """Returns True if new entries are halted due to daily loss limit."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        state = self.db.get_kv("daily", {})
        if state.get("date") != today:
            state = {"date": today, "start_equity": equity}
            self.db.set_kv("daily", state)
            return False
        start = state.get("start_equity", equity)
        if start > 0 and equity < start * (1 - config.DAILY_LOSS_LIMIT / 100):
            return True
        return False

    # ---------------- cooldown (consecutive SL tracking) ----------------
    def _is_in_cooldown(self, symbol):
        """Check if a symbol is in cooldown (skip re-entry after consecutive SLs)."""
        cooldowns = self.db.get_kv("cooldowns", {})
        entry = cooldowns.get(symbol)
        if not entry:
            return False
        cooldown_until = entry.get("cooldown_until", 0)
        if cooldown_until and time.time() * 1000 < cooldown_until:
            return True
        return False

    def _record_sl_close(self, symbol):
        """Record a SL hit on a symbol; trigger cooldown if threshold reached."""
        cooldowns = self.db.get_kv("cooldowns", {})
        entry = cooldowns.get(symbol, {"consecutive_sls": 0, "cooldown_until": 0})
        entry["consecutive_sls"] = entry.get("consecutive_sls", 0) + 1
        if entry["consecutive_sls"] >= config.COOLDOWN_CONSEC_SL_THRESHOLD:
            cooldown_ms = config.COOLDOWN_BARS * config.BAR_SECONDS * 1000
            entry["cooldown_until"] = int(time.time() * 1000) + cooldown_ms
            log.warning(f"{symbol}: cooldown activated ({entry['consecutive_sls']} consecutive SLs, "
                        f"{config.COOLDOWN_BARS} bars)")
            tg.notify_cooldown(symbol, entry["consecutive_sls"], config.COOLDOWN_BARS)
        cooldowns[symbol] = entry
        self.db.set_kv("cooldowns", cooldowns)

    def _reset_cooldown(self, symbol):
        """Reset consecutive SL counter (e.g. after a TP or successful exit)."""
        cooldowns = self.db.get_kv("cooldowns", {})
        if symbol in cooldowns:
            cooldowns[symbol] = {"consecutive_sls": 0, "cooldown_until": 0}
            self.db.set_kv("cooldowns", cooldowns)

    # ---------------- liquidation warning ----------------
    def _check_liquidation_warning(self, symbol, dbp, mark_price, exchange_liq_price):
        """Warn if price is approaching exchange liquidation price.
        Uses the liquidationPrice reported by Binance positionRisk (most accurate).
        Falls back to get_liquidation_threshold estimate only if exchange value is missing."""
        try:
            lev = dbp["leverage"]
            direction = dbp["direction"]
            if exchange_liq_price and exchange_liq_price > 0:
                liq_price = exchange_liq_price
                distance_pct = abs(mark_price - liq_price) / mark_price * 100
            else:
                # Fallback: estimate from strategy module
                liq_threshold_pct = sa.strat.get_liquidation_threshold(lev)
                entry = dbp["entry_price"]
                if direction == "LONG":
                    liq_price = entry * (1 - liq_threshold_pct / 100)
                else:
                    liq_price = entry * (1 + liq_threshold_pct / 100)
                distance_pct = abs(mark_price - liq_price) / mark_price * 100
            if distance_pct <= config.LIQ_WARN_THRESHOLD_PCT and distance_pct > 0:
                liq_warned = self.db.get_kv("liq_warned", {})
                if not liq_warned.get(symbol):
                    log.warning(f"{symbol}: LIQUATION WARNING — mark={mark_price:.6g} "
                                f"liq~={liq_price:.6g} ({distance_pct:.1f}% away, lev={lev}x)")
                    tg.notify_liq_warning(symbol, direction, mark_price, liq_price,
                                          distance_pct, lev)
                    liq_warned[symbol] = True
                    self.db.set_kv("liq_warned", liq_warned)
        except Exception as e:
            log.debug(f"{symbol}: liq warning check failed: {e}")

    # ---------------- funding cost tracking ----------------
    def _track_funding_cost(self, symbol, dbp, exit_price):
        """Estimate funding cost for a closed position and track daily total."""
        try:
            bars_held = (time.time() * 1000 - dbp["entry_time"]) / 1000 / config.BAR_SECONDS
            funding_intervals = int(bars_held // 16)  # 16 bars = 8h funding interval
            if funding_intervals <= 0:
                return 0.0
            # Use strategy module's FUNDING_RATE (0.0005 = 0.05%)
            fr = getattr(sa.strat, "FUNDING_RATE", 0.0005) / 100  # convert to decimal
            notional = dbp["qty"] * dbp["entry_price"]
            funding_cost = notional * fr * funding_intervals
            # Track daily total
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            funding_state = self.db.get_kv("funding_daily", {})
            if funding_state.get("date") != today:
                funding_state = {"date": today, "total": 0.0, "warned": False}
            funding_state["total"] = funding_state.get("total", 0.0) + funding_cost
            self.db.set_kv("funding_daily", funding_state)
            return funding_cost
        except Exception as e:
            log.debug(f"{symbol}: funding tracking failed: {e}")
            return 0.0

    def _check_funding_warning(self, equity):
        """Warn if daily funding cost exceeds threshold % of equity."""
        funding_state = self.db.get_kv("funding_daily", {})
        if not funding_state or funding_state.get("warned"):
            return
        total = funding_state.get("total", 0.0)
        if equity > 0 and total > equity * config.FUNDING_DAILY_WARN_PCT / 100:
            log.warning(f"Funding cost warning: ${total:.2f} today "
                        f"({total/equity*100:.1f}% of equity ${equity:.2f})")
            tg.notify_funding_warning(total, equity, config.FUNDING_DAILY_WARN_PCT)
            funding_state["warned"] = True
            self.db.set_kv("funding_daily", funding_state)

    # ---------------- entry ----------------
    def try_enter(self, symbol, opp, equity):
        """Open a position for `symbol` based on decision `opp`."""
        direction = opp["dir"]
        lev = opp["lev"]
        # v6+ score-based position sizing: use pos_pct from signal if present
        pos_pct = opp.get("pos_pct", config.POSITION_PCT)
        margin = equity * pos_pct / 100.0
        try:
            price = self.client.mark_price(symbol)
        except BinanceError as e:
            log.warning(f"{symbol}: no mark price, skip entry: {e}")
            return False
        notional = margin * lev
        qty = self.filters.round_qty(symbol, notional / price)
        ok, reason = self.filters.valid_order(symbol, qty, price)
        if not ok:
            log.info(f"{symbol}: skip entry ({reason})")
            return False

        if not config.is_real_orders():
            log.info(f"[DRY] would ENTER {symbol} {direction} qty={qty} @~{price} lev={lev}x "
                     f"sl={opp['sl']}% tp={opp['tp']}% score={opp['score']}")
            return False

        # configure symbol
        self.client.set_margin_type(symbol, "ISOLATED")
        max_lev = self.filters.max_leverage(symbol)
        if lev > max_lev:
            log.info(f"{symbol}: requested leverage {lev}x capped to exchange max {max_lev}x")
            lev = max_lev
        self.client.set_leverage(symbol, lev)

        side = "BUY" if direction == "LONG" else "SELL"
        entry_cid = self._cid(symbol, "entry")
        try:
            resp = self.client.new_market_order(symbol, side, qty, client_id=entry_cid)
        except BinanceError as e:
            log.warning(f"{symbol}: entry order rejected: {e}")
            return False

        fill = float(resp.get("avgPrice") or 0) or price
        if direction == "LONG":
            sl_price = fill * (1 - opp["sl"] / 100)
            tp_price = fill * (1 + opp["tp"] / 100)
        else:
            sl_price = fill * (1 + opp["sl"] / 100)
            tp_price = fill * (1 - opp["tp"] / 100)

        # CRITICAL: protect the freshly opened position
        try:
            sl_cid, tp_cid = self.place_protection(symbol, direction, sl_price, tp_price)
        except BinanceError as e:
            log.critical(f"{symbol}: ENTRY FILLED but SL FAILED -> closing position now: {e}")
            tg.notify_error(symbol, f"ENTRY filled but SL failed: {e}")
            self._market_close(symbol, direction, qty, "sl_place_failed")
            return False

        self.db.upsert_position({
            "symbol": symbol, "direction": direction, "entry_price": fill,
            "qty": qty, "leverage": lev, "orig_sl_pct": opp["sl"],
            "sl_price": sl_price, "tp_price": tp_price, "be_moved": 0, "trail_moved": 0,
            "entry_time": int(time.time() * 1000), "score": opp["score"], "margin": margin,
            "sl_client_id": sl_cid, "tp_client_id": tp_cid, "entry_client_id": entry_cid,
            "adopted": 0,
        })
        self.db.log_event("entry", symbol,
                          {"dir": direction, "qty": qty, "fill": fill, "lev": lev,
                           "sl": sl_price, "tp": tp_price, "score": opp["score"]})
        log.info(f"ENTER {symbol} {direction} qty={qty} @ {fill} lev={lev}x "
                 f"SL={sl_price:.6g} TP={tp_price:.6g} score={opp['score']}")
        tg.notify_entry(symbol, direction, qty, fill, lev, opp["sl"], opp["tp"], opp["score"],
                        margin=margin, notional=qty * fill, sl_price=sl_price, tp_price=tp_price,
                        entry_time=int(time.time() * 1000))
        return True

    # ---------------- manage open positions (BE / trail / max-hold) ----------------
    def manage_positions(self, ex_positions):
        for dbp in self.db.all_positions():
            symbol = dbp["symbol"]
            if symbol not in ex_positions:
                # closed (hit SL/TP) since last cycle
                log.info(f"{symbol}: no longer on exchange -> closed (SL/TP hit)")
                self.cancel_protection(symbol)
                pnl, exit_px, _ = self._realized(symbol, dbp)
                # Determine if SL or TP hit by comparing exit price to SL/TP levels
                sl_price = dbp.get("sl_price", 0)
                tp_price = dbp.get("tp_price", 0)
                direction = dbp.get("direction", "LONG")
                is_sl = False
                is_tp = False
                if exit_px and sl_price and tp_price:
                    # Primary: compare exit price to SL/TP levels (allow 0.2% tolerance)
                    if direction == "LONG":
                        is_sl = exit_px <= sl_price * 1.002
                        is_tp = exit_px >= tp_price * 0.998
                    else:
                        is_sl = exit_px >= sl_price * 0.998
                        is_tp = exit_px <= tp_price * 1.002
                # Fallback: if price not near SL/TP or unavailable, use PnL sign
                if not is_sl and not is_tp and pnl is not None:
                    if pnl < 0:
                        is_sl = True
                    elif pnl > 0:
                        is_tp = True
                    log.debug(f"{symbol}: exit_px={exit_px} not near SL={sl_price}/TP={tp_price}, "
                              f"using PnL sign (pnl={pnl}) -> reason={('SL' if is_sl else 'TP' if is_tp else 'unknown')}")
                reason = "SL hit" if is_sl else ("TP hit" if is_tp else "closed (unknown)")
                self.db.record_closed(symbol, direction, dbp["entry_price"],
                                      exit_px or 0, dbp["qty"], pnl or 0.0,
                                      reason, dbp["entry_time"])
                self.db.delete_position(symbol)
                self.db.log_event("exit", symbol, {"reason": reason, "pnl": pnl})
                self._notify_exit(symbol, dbp, reason, pnl, exit_px)
                # Cooldown tracking: SL → increment, TP → reset
                if is_sl:
                    self._record_sl_close(symbol)
                else:
                    self._reset_cooldown(symbol)
                # Funding cost tracking
                self._track_funding_cost(symbol, dbp, exit_px or 0)
                # Clear liq warning flag
                liq_warned = self.db.get_kv("liq_warned", {})
                if symbol in liq_warned:
                    del liq_warned[symbol]
                    self.db.set_kv("liq_warned", liq_warned)
                continue
            try:
                self._update_stops(symbol, dbp)
                # Liquidation warning: check if price approaching liq
                exp = ex_positions[symbol]
                mark = float(exp.get("markPrice", 0))
                exchange_liq = float(exp.get("liq", 0) or 0)
                if mark > 0:
                    self._check_liquidation_warning(symbol, dbp, mark, exchange_liq)
            except BinanceError as e:
                log.warning(f"{symbol}: manage failed: {e}")

    def _update_stops(self, symbol, dbp):
        """Replicate backtest BE (0.5R) and trail (1.2R) logic on the live SL order."""
        # max hold
        age_ms = int(time.time() * 1000) - dbp["entry_time"]
        if age_ms >= config.MAX_HOLD_BARS * config.BAR_SECONDS * 1000:
            log.info(f"{symbol}: max hold reached -> closing")
            self._market_close(symbol, dbp["direction"], dbp["qty"], "max_hold")
            pnl, exit_px, _ = self._realized(symbol, dbp)
            self.db.record_closed(symbol, dbp["direction"], dbp["entry_price"],
                                  exit_px or 0, dbp["qty"], pnl or 0.0,
                                  "max_hold", dbp["entry_time"])
            self.db.delete_position(symbol)
            self._notify_exit(symbol, dbp, "max_hold", pnl, exit_px)
            self._track_funding_cost(symbol, dbp, exit_px or 0)
            # Clear liq warning flag
            liq_warned = self.db.get_kv("liq_warned", {})
            if symbol in liq_warned:
                del liq_warned[symbol]
                self.db.set_kv("liq_warned", liq_warned)
            return

        # use last closed 15m bar high/low for favorable excursion (matches backtest)
        raw = self.client.klines(symbol, config.BAR_INTERVAL, limit=3)
        df = sa.klines_to_df(raw, drop_forming=True)
        if df is None or len(df) == 0:
            return
        bar = df.iloc[-1]
        entry = dbp["entry_price"]
        orig_sl = dbp["orig_sl_pct"]
        direction = dbp["direction"]
        be_moved = bool(dbp["be_moved"])
        trail_moved = bool(dbp["trail_moved"])

        if direction == "LONG":
            profit_pct = (bar["high"] - entry) / entry * 100
            new_sl = None
            if profit_pct >= config.TRAIL_R_MULTIPLE * orig_sl and not trail_moved:
                new_sl = entry * (1 + orig_sl / 100); trail_moved = True; be_moved = True
            elif profit_pct >= config.BE_R_MULTIPLE * orig_sl and not be_moved:
                new_sl = entry * (1 + 0.01)
                be_moved = True
        else:
            profit_pct = (entry - bar["low"]) / entry * 100
            new_sl = None
            if profit_pct >= config.TRAIL_R_MULTIPLE * orig_sl and not trail_moved:
                new_sl = entry * (1 - orig_sl / 100); trail_moved = True; be_moved = True
            elif profit_pct >= config.BE_R_MULTIPLE * orig_sl and not be_moved:
                new_sl = entry * (1 - 0.01)
                be_moved = True

        if new_sl is not None:
            new_sl = self.filters.round_price(symbol, new_sl)
            close_side = "SELL" if direction == "LONG" else "BUY"

            # CRITICAL: validate new SL is on the correct side of current price.
            # STOP_MARKET BUY (SHORT close) requires trigger ABOVE current price.
            # STOP_MARKET SELL (LONG close) requires trigger BELOW current price.
            # If price bounced back past the intended SL, the order would be invalid
            # and we must NOT cancel the existing SL (leave protection in place).
            try:
                cur_mp = self.client.mark_price(symbol)
            except BinanceError:
                cur_mp = None
            if cur_mp is not None:
                if direction == "SHORT" and new_sl <= cur_mp:
                    log.info(f"{symbol}: skip SL move to {new_sl:.6g} (<= mark {cur_mp:.6g}), "
                             f"keeping current SL")
                    return
                if direction == "LONG" and new_sl >= cur_mp:
                    log.info(f"{symbol}: skip SL move to {new_sl:.6g} (>= mark {cur_mp:.6g}), "
                             f"keeping current SL")
                    return

            # Cancel old SL FIRST, then place new SL.
            # Binance rejects a new closePosition STOP if another exists (-4130),
            # so we accept a tiny protection window and immediately restore it.
            sl_cid = self._cid(symbol, "sl")
            old_sl_cid = dbp.get("sl_client_id")
            old_sl_price = dbp.get("sl_price")
            try:
                if old_sl_cid:
                    self.client.cancel_algo_order(symbol, client_id=old_sl_cid)
                # Small window with no SL; place new immediately
                self.client.new_stop_market(symbol, close_side, new_sl,
                                            client_id=sl_cid, close_position=True)
                self.db.update_position_fields(symbol, sl_price=new_sl, sl_client_id=sl_cid,
                                               be_moved=int(be_moved), trail_moved=int(trail_moved))
                kind = "trail" if trail_moved else "breakeven"
                log.info(f"{symbol}: SL moved to {new_sl:.6g} ({kind})")
                self.db.log_event("move_sl", symbol, {"sl": new_sl, "kind": kind})
                tg.notify_sl_move(symbol, new_sl, kind)
            except BinanceError as e:
                log.warning(f"{symbol}: failed to move SL ({e}), attempting to restore old SL")
                # Try to restore old SL so the position is never left naked
                if old_sl_cid:
                    try:
                        self.client.new_stop_market(symbol, close_side, old_sl_price,
                                                    client_id=old_sl_cid, close_position=True)
                        log.warning(f"{symbol}: restored old SL at {old_sl_price:.6g}")
                    except BinanceError as e2:
                        log.critical(f"{symbol}: CRITICAL — cannot restore old SL ({e2}); "
                                     f"closing position for safety")
                        self._market_close(symbol, dbp["direction"], dbp["qty"], "sl_restore_failed")
                # Clean up the failed new SL if it partially exists
                try:
                    self.client.cancel_algo_order(symbol, client_id=sl_cid)
                except BinanceError:
                    pass

    # ---------------- entry scan ----------------
    def scan_entries(self, ex_positions, equity, avail):
        open_count = len(ex_positions)
        max_conc = (config.MAX_CONCURRENT_NEUTRAL if self.btc_regime == "neutral"
                    else config.MAX_CONCURRENT)
        slots = max_conc - open_count
        if slots <= 0:
            log.info(f"No free slots ({open_count}/{max_conc}), regime={self.btc_regime}")
            return
        # Per-position margin = equity * POSITION_PCT% (matches backtest).
        # For v6+ score-based sizing, use max possible (POS_SCORE_HIGH) for budget check.
        max_pos_pct = max(config.POS_SCORE_HIGH, config.POSITION_PCT)
        margin_per_pos = equity * max_pos_pct / 100.0
        # Reserve a small buffer for fees + maintenance margin on existing positions
        avail_budget = avail * 0.95

        # universe = top volume USDT perps
        try:
            tickers = self.client.ticker_24h()
        except BinanceError as e:
            log.warning(f"ticker fetch failed: {e}")
            return
        universe = [t["symbol"] for t in sorted(
            (t for t in tickers if t["symbol"].endswith("USDT") and self.filters.has(t["symbol"])),
            key=lambda t: float(t.get("quoteVolume", 0)), reverse=True
        )[:config.COINS_UNIVERSE_SIZE]]

        opportunities = []
        for symbol in universe:
            if symbol in ex_positions:
                continue
            if self._is_in_cooldown(symbol):
                log.info(f"{symbol}: in cooldown, skip entry")
                continue
            opp = sa.analyze_symbol(self.client, symbol, self.btc_regime)
            if opp:
                opportunities.append({"symbol": symbol, **opp})
            if not RUNNING:
                return
        opportunities.sort(key=lambda x: -x["score"])
        log.info(f"{len(opportunities)} opportunities, {slots} slots, "
                 f"regime={self.btc_regime}, avail={avail:.2f}, margin/pos={margin_per_pos:.2f}")

        opened = 0
        for opp in opportunities[:slots]:
            if not RUNNING:
                return
            # Backtest-equivalent guard: skip if not enough available margin
            if avail_budget < margin_per_pos:
                log.info(f"Insufficient available margin ({avail_budget:.2f} < {margin_per_pos:.2f}) "
                         f"for more entries; opened {opened}/{slots}")
                break
            if self.try_enter(opp["symbol"], opp, equity):
                opened += 1
                avail_budget -= margin_per_pos  # deduct committed margin

    # ---------------- main loop ----------------
    def run(self):
        self.reconcile()
        listen_key_ts = 0
        while RUNNING:
            cycle_start = time.time()
            try:
                self._sync_time_if_needed()
                self.btc_regime = sa.get_btc_regime_live(self.client)
                ex_positions = {p["symbol"]: p for p in self.client.position_risk()}
                equity, avail = self.get_equity()
                if equity is None:
                    log.warning("equity unavailable, skipping cycle")
                    time.sleep(10); continue

                # Send startup notification once equity is available
                if not self._startup_notified:
                    tg.notify_startup(config.STRATEGY_LEVEL, config.MODE, equity)
                    self._startup_notified = True

                # always manage existing positions first (safety)
                self.manage_positions(ex_positions)

                # check funding cost warning (daily cumulative)
                self._check_funding_warning(equity)

                # entries only on decision bar + not halted
                halted = self.check_daily_halt(equity)
                if halted:
                    log.info(f"DAILY HALT active (equity={equity:.2f}); managing only")
                    state = self.db.get_kv("daily", {})
                    if not state.get("halt_notified"):
                        tg.notify_daily_halt(equity, state.get("start_equity", equity))
                        state["halt_notified"] = True
                        self.db.set_kv("daily", state)
                elif self._is_decision_bar():
                    self.scan_entries(ex_positions, equity, avail)
                else:
                    bars_left = config.DECISION_EVERY_BARS - (self._bar_index() - self.last_decision_bar)
                    log.info(f"Non-decision bar; skip entry scan, manage only "
                             f"(next scan in ~{max(0, bars_left)} bars)")

                # listenKey keepalive every 30 min (kept for future WS use)
                if time.time() - listen_key_ts > 1800:
                    listen_key_ts = time.time()

                log.info(f"Cycle done in {time.time()-cycle_start:.1f}s | "
                         f"equity={equity:.2f} avail={avail:.2f} "
                         f"open={len(ex_positions)} regime={self.btc_regime}")
            except BinanceError as e:
                log.error(f"Cycle BinanceError: {e}")
                tg.notify_error("cycle", str(e))
            except Exception as e:
                log.exception(f"Cycle unexpected error: {e}")
                tg.notify_error("cycle", str(e))

            # sleep until next 15m bar close (+ small buffer)
            self._sleep_to_next_bar()
        log.info("Bot stopped cleanly.")
        tg.notify_shutdown(config.STRATEGY_LEVEL, "manual")
        self.db.close()

    def _bar_index(self):
        """Current bar index (0-based) based on BAR_SECONDS."""
        return int(time.time() // config.BAR_SECONDS)

    def _is_decision_bar(self):
        """True if we should scan entries this bar (matches backtest DECISION_EVERY)."""
        if self.last_decision_bar is None:
            self.last_decision_bar = self._bar_index()
            return True
        current = self._bar_index()
        if current - self.last_decision_bar >= config.DECISION_EVERY_BARS:
            self.last_decision_bar = current
            return True
        return False

    def _sleep_to_next_bar(self):
        now = time.time()
        period = config.BAR_SECONDS
        next_close = (int(now // period) + 1) * period + 5  # +5s buffer for bar finalization
        wait = max(5, next_close - now)
        end = now + wait
        while RUNNING and time.time() < end:
            time.sleep(min(2, end - time.time()))


if __name__ == "__main__":
    Bot().run()
