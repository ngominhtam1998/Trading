"""REALISTIC replay test for strategy_glm — the ONLY number you should trust.

Why this instead of the usual backtest:
  The v7/v8 backtests checked SL/TP on the 1m CLOSE. A live STOP_MARKET triggers
  on the WICK (intrabar). That single difference turned a "91% WR" backtest into
  a losing testnet bot. This harness fills SL/TP INTRABAR (on the 1m high/low),
  charges taker fees BOTH sides, adds slippage on every market fill, and charges
  funding per 8h interval. Entries happen at the NEXT 1m OPEN (like a live market
  order placed right after the signal bar closes), never at a magical close.

It reuses strategy_glm.decide_mtf / compute_trail_sl / btc_context_from_frames
DIRECTLY, so the simulated decisions are byte-for-byte what the live bot does.

USAGE (for another model / operator):
    python test_glm_replay.py [DAYS=7] [N_SYMBOLS=20] [SEED=777]

Examples:
    python test_glm_replay.py            # last 7 days, top-volume symbols
    python test_glm_replay.py 14 30      # last 14 days, 30 symbols

Output: per-symbol + portfolio summary (return %, WR, PF, MaxDD, exits, liq).
Pass criteria suggestion (NOT a backtest fantasy): positive return AND PF > 1.3
AND MaxDD < 25% across at least two DISTINCT recent windows before considering
any real-money deployment.
"""
import sys, os, time, json, pickle
from datetime import datetime, timedelta, timezone
from collections import Counter

import requests
import numpy as np
import pandas as pd
import urllib3
urllib3.disable_warnings()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import strategy_glm as S

# ---- knobs ----
DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 7
N_SYMBOLS = int(sys.argv[2]) if len(sys.argv) > 2 else 12
SEED = int(sys.argv[3]) if len(sys.argv) > 3 else 777
# Optional 4th arg: START_DATE (YYYY-MM-DD) -> test a PAST window starting that day.
# If omitted, the window ends NOW (most recent).
START_DATE = sys.argv[4] if len(sys.argv) > 4 else None

SLIPPAGE_PCT = 0.06           # % adverse on every market fill — bumped to stay
                              # conservative vs real (esp. testnet) fills
FEE_PCT = S.FEE_PCT           # taker fee per side (%)
FUNDING_RATE = S.FUNDING_RATE
ENTRY_EVERY_MIN = S.ENTRY_EVERY_LOOPS   # scan cadence in minutes (loop = 60s)
WARMUP_DAYS = 2               # extra history before the window for indicators

# ---- REALISTIC SIZING (the fix for "+12tr đô in 14d" fantasy) ----
# Live bot COMPOUNDS (margin = equity * pos_pct), which means a winning streak
# inflates every subsequent trade size, and the backtest turns $1000 into
# $12M in 14d — a number no live testnet will ever reproduce because of spread,
# latency, margin release delay, and per-coin avail limits.
# FIX: size each trade off the FIXED starting capital, not the running equity.
# Realized PnL still accrues to `cash` (so daily-halt + MaxDD reflect reality),
# but a winning trade does NOT inflate the next trade's margin. This is the
# standard "fixed-fractional" reporting mode for trading systems.
FIXED_CAPITAL_SIZING = True   # margin = TOTAL_CAPITAL * pos_pct (no compounding)

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_cache_glm")
os.makedirs(CACHE_DIR, exist_ok=True)

BASE = "https://fapi.binance.com"


def _get(path, params):
    r = requests.get(BASE + path, params=params, timeout=20, verify=False)
    r.raise_for_status()
    return r.json()


def top_symbols(n):
    # Match LIVE: GLM uses a dynamic universe (top-N by 24h quote volume) when
    # USE_DYNAMIC_UNIVERSE is True, falling back to the curated UNIVERSE list.
    # Use the strategy's own getter so replay == live coin set exactly.
    if getattr(S, "USE_DYNAMIC_UNIVERSE", False) and hasattr(S, "get_dynamic_universe"):
        try:
            uni = S.get_dynamic_universe(n=n)
            # Intersect with currently-listed perps so we don't fetch delisted symbols
            info = _get("/fapi/v1/exchangeInfo", {})
            listed = {s["symbol"] for s in info["symbols"]
                      if s.get("status") == "TRADING" and s.get("contractType") == "PERPETUAL"}
            uni = [s for s in uni if s in listed]
            return uni
        except Exception as e:
            print(f"  [warn] dynamic universe failed: {e}; falling back to UNIVERSE")
    pinned = getattr(S, "UNIVERSE", None)
    if pinned:
        try:
            info = _get("/fapi/v1/exchangeInfo", {})
            listed = {s["symbol"] for s in info["symbols"]
                      if s.get("status") == "TRADING" and s.get("contractType") == "PERPETUAL"}
            uni = [s for s in pinned if s in listed]
        except Exception:
            uni = list(pinned)
        return uni
    data = _get("/fapi/v1/ticker/24hr", {})
    rows = [d for d in data if d["symbol"].endswith("USDT")]
    rows.sort(key=lambda d: float(d.get("quoteVolume", 0)), reverse=True)
    out = []
    for d in rows:
        s = d["symbol"]
        if s in ("USDCUSDT", "BTCDOMUSDT"):
            continue
        out.append(s)
        if len(out) >= n:
            break
    return out


def fetch_series(symbol, interval, start_dt, end_dt):
    df = S.fetch_klines_range(symbol, interval, start_dt, end_dt)
    return df


def load_data(symbols, start_dt, end_dt):
    """Fetch + cache 1m/5m/15m/1h for each symbol and BTC context series."""
    key = f"{start_dt:%Y%m%d}_{end_dt:%Y%m%d}_{'_'.join(sorted(symbols))}"
    key = str(abs(hash(key)))
    cp = os.path.join(CACHE_DIR, f"replay_{key}.pkl")
    if os.path.exists(cp):
        with open(cp, "rb") as f:
            return pickle.load(f)

    print(f"  Fetching BTC context series ...")
    btc = {}
    for itv in ("1m", "5m", "15m", "1d"):
        btc[itv] = fetch_series("BTCUSDT", itv, start_dt, end_dt)

    coins = {}
    for i, s in enumerate(symbols, 1):
        print(f"  [{i}/{len(symbols)}] {s} ...")
        d1 = fetch_series(s, "1m", start_dt, end_dt)
        d5 = fetch_series(s, "5m", start_dt, end_dt)
        d15 = fetch_series(s, "15m", start_dt, end_dt)
        d1h = fetch_series(s, "1h", start_dt, end_dt)
        if d1 is None or d5 is None or d15 is None:
            print(f"      skip {s} (missing data)")
            continue
        coins[s] = {"1m": d1, "5m": d5, "15m": d15, "1h": d1h}
    payload = {"btc": btc, "coins": coins}
    with open(cp, "wb") as f:
        pickle.dump(payload, f)
    return payload


def prep_indicators(payload):
    """Add indicators once on full series (causal indicators -> slicing is safe)."""
    btc = {}
    for itv in ("1m", "5m", "15m"):
        df = payload["btc"].get(itv)
        btc[itv] = S.add_indicators(df) if df is not None and len(df) > 25 else None
    # BTC daily regime per day
    dfd = payload["btc"].get("1d")
    regime_by_day = {}
    if dfd is not None and len(dfd) > 50:
        dfd = dfd.copy()
        dfd["ema50"] = dfd["close"].ewm(span=50, adjust=False).mean()
        dfd["ema200"] = dfd["close"].ewm(span=200, adjust=False).mean()
        for _, r in dfd.iterrows():
            reg = "neutral"
            if not pd.isna(r["ema200"]):
                if r["close"] > r["ema50"] > r["ema200"]:
                    reg = "bull"
                elif r["close"] < r["ema50"] < r["ema200"]:
                    reg = "bear"
            regime_by_day[r["open_time"].normalize()] = reg

    coins = {}
    for s, d in payload["coins"].items():
        c = {
            "1m": S.add_indicators(d["1m"]),
            "5m": S.add_indicators(d["5m"]),
            "15m": S.add_indicators(d["15m"]),
            "1h": S.add_indicators(d["1h"]) if d["1h"] is not None and len(d["1h"]) > 25 else None,
        }
        coins[s] = c
    return btc, regime_by_day, coins


def ms(series):
    # Force ms resolution explicitly: pandas >=2.0/3.0 may store datetime64 as
    # [ms]/[us]/[ns] depending on how it was parsed, so a naive int64 cast is
    # resolution-dependent. Casting to datetime64[ms] first makes this robust.
    return series.astype("datetime64[ms]").astype("int64").to_numpy()


def last_closed_idx(times_ms, now_ms, interval_ms):
    """Index of last bar fully CLOSED by now_ms (open+interval <= now)."""
    # bar open o is closed if o <= now - interval
    cutoff = now_ms - interval_ms
    idx = int(np.searchsorted(times_ms, cutoff, side="right")) - 1
    return idx


def run_replay(btc, regime_by_day, coins, window_start):
    INTERVAL_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000}

    # Master clock = BTC 1m bars within the trading window
    btc1 = btc["1m"]
    btc1_ms = ms(btc1["open_time"])
    btc5_ms = ms(btc["5m"]["open_time"]) if btc["5m"] is not None else np.array([])
    btc15_ms = ms(btc["15m"]["open_time"]) if btc["15m"] is not None else np.array([])

    # Precompute per-symbol ms arrays + 1m timestamp->index map
    sym = {}
    for s, c in coins.items():
        t1 = ms(c["1m"]["open_time"])
        sym[s] = {
            "c": c,
            "t1": t1,
            "t1map": {int(t): i for i, t in enumerate(t1)},
            "t5": ms(c["5m"]["open_time"]),
            "t15": ms(c["15m"]["open_time"]),
            "t1h": ms(c["1h"]["open_time"]) if c["1h"] is not None else np.array([]),
            "open1": c["1m"]["open"].to_numpy(),
            "high1": c["1m"]["high"].to_numpy(),
            "low1": c["1m"]["low"].to_numpy(),
            "close1": c["1m"]["close"].to_numpy(),
        }

    capital = S.TOTAL_CAPITAL
    cash = S.TOTAL_CAPITAL
    peak_eq = S.TOTAL_CAPITAL     # highest mark-to-market equity ($)
    trough_eq = S.TOTAL_CAPITAL   # lowest mark-to-market equity ($)
    peak_eq_ts = None
    trough_eq_ts = None
    max_dd_seen = 0.0
    max_dd_seen_ts = None
    max_dd_seen_peak = 0.0
    max_dd_seen_trough = 0.0
    positions = {}     # symbol -> dict
    trades = []
    cooldowns = {}     # symbol -> minute index until which blocked
    consec_sl = {}
    day_start_cap = capital
    cur_day = None
    daily_halt_until = -1
    liq_count = 0

    window_start_ms = int(window_start.timestamp() * 1000)
    gate_stats = {}

    for mi in range(len(btc1_ms)):
        now_open = int(btc1_ms[mi])
        if now_open < window_start_ms:
            continue
        now_close = now_open + 60_000   # this 1m bar closes here

        ts = pd.Timestamp(now_open, unit="ms")
        day = ts.normalize()
        if day != cur_day:
            cur_day = day
            day_start_cap = capital
        # daily halt
        halted = capital < day_start_cap * (1 - S.DAILY_LOSS_LIMIT / 100)

        # ---------- 1) manage open positions (intrabar fills + trailing) ----------
        for s in list(positions.keys()):
            pos = positions[s]
            S_ = sym[s]
            idx = S_["t1map"].get(now_open)
            if idx is None or idx <= pos["entry_idx"]:
                continue  # no bar this minute, or still the entry bar
            hi = S_["high1"][idx]; lo = S_["low1"][idx]; cl = S_["close1"][idx]
            pos["last_close"] = cl
            d = pos["dir"]; sl = pos["sl_price"]; tp = pos["tp_price"]
            ep = None; reason = None
            # intrabar: assume SL checked first (conservative)
            if d == "LONG":
                if lo <= sl:
                    ep = sl; reason = _exit_reason(pos)
                elif hi >= tp:
                    ep = tp; reason = "TP"
            else:
                if hi >= sl:
                    ep = sl; reason = _exit_reason(pos)
                elif lo <= tp:
                    ep = tp; reason = "TP"
            # max hold
            if ep is None and (idx - pos["entry_idx"]) >= S.MAX_HOLD_1M:
                ep = cl; reason = "MaxH"
            if ep is not None:
                _close(pos, s, ep, reason, idx, now_close, trades, consec_sl, cooldowns, mi)
                net = trades[-1]["net_pnl"]
                cash += pos["margin"] + net
                if reason == "LIQ":
                    liq_count += 1
                del positions[s]
                continue
            # trailing on 1m close
            d1_slice = S_["c"]["1m"].iloc[:idx + 1]
            new_sl, be_moved, trail_moved = S.compute_trail_sl(
                d, pos["entry"], pos["orig_sl_pct"], pos["be_moved"], pos["trail_moved"], d1_slice)
            if new_sl is not None:
                # only move favorably
                if d == "LONG" and new_sl > pos["sl_price"]:
                    pos["sl_price"] = new_sl
                elif d == "SHORT" and new_sl < pos["sl_price"]:
                    pos["sl_price"] = new_sl
                pos["be_moved"] = be_moved; pos["trail_moved"] = trail_moved

        # mark-to-market equity: cash + margin + unrealized PnL of open positions
        mtm = cash
        for p in positions.values():
            lc = p.get("last_close", p["entry"])
            if p["dir"] == "LONG":
                upnl = (lc - p["entry"]) * p["units"]
            else:
                upnl = (p["entry"] - lc) * p["units"]
            mtm += p["margin"] + upnl
        capital = cash + sum(p["margin"] for p in positions.values())
        if mtm > peak_eq:
            peak_eq = mtm
            peak_eq_ts = now_open
        if mtm < trough_eq:
            trough_eq = mtm
            trough_eq_ts = now_open
        # live drawdown from running peak
        dd_now = (peak_eq - mtm) / peak_eq * 100 if peak_eq > 0 else 0
        if dd_now > max_dd_seen:
            max_dd_seen = dd_now
            max_dd_seen_ts = now_open
            max_dd_seen_peak = peak_eq
            max_dd_seen_trough = mtm

        # ---------- 2) entry scan ----------
        if halted:
            continue
        if (mi % max(1, ENTRY_EVERY_MIN)) != 0:
            continue

        # BTC context at now
        bi1 = last_closed_idx(btc1_ms, now_close, INTERVAL_MS["1m"])
        bi5 = last_closed_idx(btc5_ms, now_close, INTERVAL_MS["5m"]) if len(btc5_ms) else -1
        bi15 = last_closed_idx(btc15_ms, now_close, INTERVAL_MS["15m"]) if len(btc15_ms) else -1
        bd1 = btc["1m"].iloc[:bi1 + 1] if bi1 >= 30 else None
        bd5 = btc["5m"].iloc[:bi5 + 1] if (btc["5m"] is not None and bi5 >= 25) else None
        bd15 = btc["15m"].iloc[:bi15 + 1] if (btc["15m"] is not None and bi15 >= 25) else None
        regime = regime_by_day.get(day, "neutral")
        btc_ctx = S.btc_context_from_frames(bd1, bd5, bd15, regime)

        max_conc = S.MAX_CONCURRENT
        slots = max_conc - len(positions)
        if slots <= 0:
            continue

        opps = []
        for s, S_ in sym.items():
            if s in positions:
                continue
            if cooldowns.get(s, -1) > mi:
                continue
            idx = S_["t1map"].get(now_open)
            if idx is None or idx < 31 or idx + 1 >= len(S_["t1"]):
                continue
            i5 = last_closed_idx(S_["t5"], now_close, INTERVAL_MS["5m"])
            i15 = last_closed_idx(S_["t15"], now_close, INTERVAL_MS["15m"])
            i1h = last_closed_idx(S_["t1h"], now_close, INTERVAL_MS["1h"]) if len(S_["t1h"]) else -1
            if i5 < 60 or i15 < 60:
                continue
            d15 = S_["c"]["15m"].iloc[:i15 + 1]
            d5 = S_["c"]["5m"].iloc[:i5 + 1]
            d1 = S_["c"]["1m"].iloc[:idx + 1]
            d1h = S_["c"]["1h"].iloc[:i1h + 1] if (S_["c"]["1h"] is not None and i1h >= 25) else None
            opp = S.decide_mtf(s, d15, d5, d1, d1h, btc_ctx, 0.0, gate_stats)
            if opp:
                opps.append((s, opp, idx))
        opps.sort(key=lambda x: -x[1]["score"])

        for s, opp, idx in opps[:slots]:
            if s in positions:
                continue
            pos_pct = opp.get("pos_pct", S.POSITION_PCT)
            if FIXED_CAPITAL_SIZING:
                # Realistic: size off the fixed starting capital, not running equity.
                # A winning streak does NOT inflate subsequent trade size.
                margin = S.TOTAL_CAPITAL * pos_pct / 100.0
            else:
                # Theoretical compounding (matches live bot's `equity * pos_pct`,
                # but inflates numbers fast on a winning streak).
                margin = capital * pos_pct / 100.0
            if cash < margin or margin <= 0:
                continue
            # enter at NEXT 1m open + slippage (like a live market order)
            entry_open = sym[s]["open1"][idx + 1]
            slip = SLIPPAGE_PCT / 100
            if opp["dir"] == "LONG":
                fill = entry_open * (1 + slip)
                sl = fill * (1 - opp["sl"] / 100); tp = fill * (1 + opp["tp"] / 100)
            else:
                fill = entry_open * (1 - slip)
                sl = fill * (1 + opp["sl"] / 100); tp = fill * (1 - opp["tp"] / 100)
            notional = margin * opp["lev"]
            if notional < S.MIN_NOTIONAL:
                continue
            units = notional / fill
            entry_fee = notional * FEE_PCT / 100
            positions[s] = {
                "dir": opp["dir"], "entry": fill, "sl_price": sl, "tp_price": tp,
                "orig_sl_pct": opp["sl"], "units": units, "margin": margin,
                "entry_fee": entry_fee, "entry_idx": idx + 1, "lev": opp["lev"],
                "be_moved": False, "trail_moved": False, "score": opp["score"],
            }
            cash -= margin

    # close leftovers at last price
    for s in list(positions.keys()):
        pos = positions[s]
        last_close = sym[s]["close1"][-1]
        _close(pos, s, last_close, "End", len(sym[s]["t1"]) - 1, None, trades, consec_sl, cooldowns, 10**9)
        cash += pos["margin"] + trades[-1]["net_pnl"]
        del positions[s]

    final_cap = cash
    return trades, final_cap, liq_count, gate_stats, peak_eq, trough_eq, \
           peak_eq_ts, trough_eq_ts, max_dd_seen, max_dd_seen_ts, max_dd_seen_peak, max_dd_seen_trough


def _exit_reason(pos):
    return "Trail" if pos.get("trail_moved") else ("BE" if pos.get("be_moved") else "SL")


def _close(pos, symbol, exit_price, reason, idx, now_close, trades, consec_sl, cooldowns, mi):
    """Compute net PnL for a close (fees both sides + funding + exit slippage)."""
    d = pos["dir"]; entry = pos["entry"]; units = pos["units"]
    slip = SLIPPAGE_PCT / 100
    # market-style exits (SL/MaxH/LIQ/End) suffer slippage; TP is a resting taker too -> small slip
    if d == "LONG":
        eff_exit = exit_price * (1 - slip)
        price_pnl = (eff_exit - entry) * units
    else:
        eff_exit = exit_price * (1 + slip)
        price_pnl = (entry - eff_exit) * units
    exit_fee = units * exit_price * FEE_PCT / 100
    bars_held = max(0, idx - pos["entry_idx"])
    funding = units * entry * FUNDING_RATE / 100 * (bars_held // S.FUNDING_INTERVAL_1M)
    if reason == "LIQ":
        net = -pos["margin"]
    else:
        net = price_pnl - pos["entry_fee"] - exit_fee - funding
        if net < -pos["margin"]:
            net = -pos["margin"]; reason = "LIQ"
    trades.append({"coin": symbol, "reason": reason, "net_pnl": net,
                   "hold": bars_held, "score": pos.get("score", 0)})
    if reason in ("SL",):
        consec_sl[symbol] = consec_sl.get(symbol, 0) + 1
        if consec_sl[symbol] >= 2:
            cooldowns[symbol] = mi + S.COOLDOWN_1M
            consec_sl[symbol] = 0
    elif reason == "TP":
        consec_sl[symbol] = 0


def report(trades, final_cap, liq_count, label, peak_eq=None, trough_eq=None):
    if not trades:
        print(f"\n{label}: NO TRADES (gates may be too strict for this window).")
        return
    wins = [t for t in trades if t["net_pnl"] > 0]
    losses = [t for t in trades if t["net_pnl"] <= 0]
    gp = sum(t["net_pnl"] for t in wins)
    gl = abs(sum(t["net_pnl"] for t in losses))
    peak = S.TOTAL_CAPITAL; cap = S.TOTAL_CAPITAL; mdd = 0
    for t in trades:
        cap += t["net_pnl"]
        peak = max(peak, cap)
        mdd = max(mdd, (peak - cap) / peak * 100)
    ret = (final_cap / S.TOTAL_CAPITAL - 1) * 100
    wr = len(wins) / len(trades) * 100
    pf = gp / gl if gl > 0 else 99
    reasons = Counter(t["reason"] for t in trades)
    avg_w = (sum(t["net_pnl"] for t in wins) / len(wins)) if wins else 0
    avg_l = (abs(sum(t["net_pnl"] for t in losses)) / len(losses)) if losses else 0
    coin_stats = {}
    for t in trades:
        coin_stats.setdefault(t["coin"], []).append(t)

    print(f"\n{'='*78}")
    print(f"  {label}")
    print(f"{'='*78}")
    net_pnl = final_cap - S.TOTAL_CAPITAL
    sizing_mode = "FIXED-CAPITAL (realistic)" if FIXED_CAPITAL_SIZING else "COMPOUNDING (theoretical)"
    print(f"SIZING: {sizing_mode}  |  per-trade margin = ${S.TOTAL_CAPITAL * S.POSITION_PCT / 100:.2f}")
    print(f"ACCOUNT: start ${S.TOTAL_CAPITAL:.0f}  ->  end ${final_cap:.2f}")
    print(f"NET PNL: ${net_pnl:+.2f}  ({ret:+.2f}% on starting capital)")
    if peak_eq is not None:
        print(f"EQUITY (mark-to-market):  HIGHEST ${peak_eq:,.2f}  |  LOWEST ${trough_eq:,.2f}")
    print(f"Trades: {len(trades)} | WR: {wr:.1f}% | PF: {pf:.2f} | MaxDD: {mdd:.1f}%")
    if avg_l > 0:
        print(f"AvgWin: ${avg_w:+.2f} | AvgLoss: ${avg_l:.2f} | W/L: {avg_w/avg_l:.2f}")
    print(f"Exits: {dict(reasons)} | Liquidations: {liq_count}")
    print(f"\nPer-coin:")
    print(f"{'Coin':>14} {'Tr':>4} {'WR':>6} {'NetPnL':>10} {'TP':>4} {'SL':>4} {'Trail':>6} {'BE':>4} {'MaxH':>5} {'LIQ':>4}")
    for c in sorted(coin_stats, key=lambda c: -sum(t["net_pnl"] for t in coin_stats[c])):
        ct = coin_stats[c]; cr = Counter(t["reason"] for t in ct)
        net = sum(t["net_pnl"] for t in ct)
        cw = sum(1 for t in ct if t["net_pnl"] > 0) / len(ct) * 100
        print(f"{c:>14} {len(ct):>4} {cw:>5.0f}% {net:>+9.2f} {cr.get('TP',0):>4} "
              f"{cr.get('SL',0):>4} {cr.get('Trail',0):>6} {cr.get('BE',0):>4} "
              f"{cr.get('MaxH',0):>5} {cr.get('LIQ',0):>4}")
    print(f"\nVERDICT: ret {ret:+.2f}% | WR {wr:.1f}% | PF {pf:.2f} | MaxDD {mdd:.1f}% | {len(trades)} trades")
    print("Reminder: run >=2 distinct recent windows; require ret>0, PF>1.3, MaxDD<25% "
          "before any real-money step.")


if __name__ == "__main__":
    if START_DATE:
        window_start = datetime.strptime(START_DATE, "%Y-%m-%d").replace(tzinfo=None)
        end_dt = window_start + timedelta(days=DAYS)
    else:
        end_dt = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0, tzinfo=None)
        window_start = end_dt - timedelta(days=DAYS)
    fetch_start = window_start - timedelta(days=WARMUP_DAYS)
    print(f"GLM REPLAY TEST — realistic intrabar fills")
    print(f"  Window: {window_start:%Y-%m-%d %H:%M} -> {end_dt:%Y-%m-%d %H:%M} UTC ({DAYS}d)")
    print(f"  Symbols: top {N_SYMBOLS} by 24h volume | slippage={SLIPPAGE_PCT}% "
          f"fee/side={FEE_PCT}% | entry scan every {ENTRY_EVERY_MIN}m")
    print(f"  Sizing: {'FIXED-CAPITAL (no compounding)' if FIXED_CAPITAL_SIZING else 'COMPOUNDING (theoretical)'}")
    syms = top_symbols(N_SYMBOLS)
    print(f"  -> {syms}")
    payload = load_data(syms, fetch_start, end_dt)
    if not payload["coins"]:
        print("No coin data fetched."); sys.exit(1)
    btc, regime_by_day, coins = prep_indicators(payload)
    trades, final_cap, liq_count, gate_stats, peak_eq, trough_eq, \
        peak_eq_ts, trough_eq_ts, max_dd_seen, max_dd_seen_ts, max_dd_seen_peak, max_dd_seen_trough = run_replay(
        btc, regime_by_day, coins, window_start)
    report(trades, final_cap, liq_count, f"GLM replay {DAYS}d / {len(coins)} symbols",
           peak_eq, trough_eq)

    # MaxDD timing diagnostics
    print(f"\n=== DRAWDOWN TIMING ===")
    if max_dd_seen_ts is not None:
        from datetime import datetime as _dt
        ts_str = _dt.utcfromtimestamp(max_dd_seen_ts / 1000).strftime("%Y-%m-%d %H:%M UTC")
        peak_str = _dt.utcfromtimestamp(peak_eq_ts / 1000).strftime("%Y-%m-%d %H:%M UTC") if peak_eq_ts else "?"
        print(f"MaxDD = {max_dd_seen:.1f}% occurred at {ts_str}")
        print(f"  Peak equity ${max_dd_seen_peak:,.2f} at {peak_str}")
        print(f"  Trough equity ${max_dd_seen_trough:,.2f} at {ts_str}")
        print(f"  Window start: {window_start:%Y-%m-%d %H:%M} UTC")
        # How many days into the window did MaxDD hit?
        days_in = (max_dd_seen_ts / 1000 - window_start.timestamp()) / 86400
        print(f"  Days into window: {days_in:.1f} / {DAYS}d")
    else:
        print("No drawdown recorded")
    if gate_stats:
        total = sum(gate_stats.values())
        print(f"\nSIGNAL FUNNEL (why setups were rejected; {total} evaluations):")
        for k, v in sorted(gate_stats.items(), key=lambda x: -x[1]):
            print(f"  {k:>18}: {v:>7} ({v/total*100:.1f}%)")
