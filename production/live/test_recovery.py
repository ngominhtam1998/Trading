"""Disconnect/reconnect recovery test (mock-based, no real API needed).

Simulates: bot has positions -> process dies (disconnect) -> restarts and
runs reconcile(). Verifies the bot:
  1. RESUMES its own position when SL/TP still intact (no duplicate orders)
  2. RE-PLACES protection for its own position when SL/TP went missing
  3. CLEANS UP its own position that closed while it was down
  4. ADOPTS an orphan position (NOT opened by it) with an emergency SL
  5. CANCELS dangling orders that have no position

The key safety property under test:
  * positions are recognized as "ours" iff the symbol is in our DB
  * a position on the exchange that we never opened is treated as an ORPHAN
    and gets an emergency stop (never left unprotected, never confused with ours)

Run:  python -m live.test_recovery     (from D:/Tam/trading/production)
"""
import os
import sys
import time
import tempfile

# ensure we run in a sandbox mode that needs no keys
os.environ.setdefault("BOT_MODE", "dry")
os.environ.setdefault("BOT_STRATEGY", "lv4")

from . import config           # noqa: E402
from .state_db import StateDB  # noqa: E402

OUR_PREFIX = config.ORDER_PREFIX

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


# --------------------------------------------------------------------------
# Fake exchange: records orders placed/cancelled so we can assert behaviour.
# --------------------------------------------------------------------------
class FakeClient:
    def __init__(self, positions, orders):
        # positions: list of dicts as returned by position_risk()
        # orders: dict symbol -> list of open-order dicts
        self._positions = positions
        self._orders = orders
        self.placed = []     # records of (kind, symbol, side, price, client_id)
        self.cancelled = []  # records of (symbol, order_id/client_id)
        self.market_closes = []

    # --- read ---
    def position_risk(self):
        return list(self._positions)

    def open_orders(self, symbol=None):
        if symbol is None:
            out = []
            for s, lst in self._orders.items():
                out.extend(lst)
            return out
        return list(self._orders.get(symbol, []))

    def mark_price(self, symbol):
        for p in self._positions:
            if p["symbol"] == symbol:
                return p.get("mark") or p.get("entry") or 100.0
        return 100.0

    # --- write (recorded) ---
    def set_margin_type(self, symbol, t="ISOLATED"):
        return None

    def set_leverage(self, symbol, lev):
        return None

    def new_stop_market(self, symbol, side, stop_price, client_id=None, close_position=True, qty=None):
        self.placed.append(("SL", symbol, side, stop_price, client_id))
        self._orders.setdefault(symbol, []).append(
            {"symbol": symbol, "type": "STOP_MARKET", "orderId": len(self.placed),
             "clientOrderId": client_id or ""})
        return {"orderId": len(self.placed), "clientOrderId": client_id}

    def new_take_profit_market(self, symbol, side, stop_price, client_id=None, close_position=True, qty=None):
        self.placed.append(("TP", symbol, side, stop_price, client_id))
        self._orders.setdefault(symbol, []).append(
            {"symbol": symbol, "type": "TAKE_PROFIT_MARKET", "orderId": len(self.placed),
             "clientOrderId": client_id or ""})
        return {"orderId": len(self.placed), "clientOrderId": client_id}

    def new_market_order(self, symbol, side, qty, client_id=None, reduce_only=False):
        if reduce_only:
            self.market_closes.append((symbol, side, qty))
        return {"orderId": 999, "avgPrice": str(self.mark_price(symbol))}

    def cancel_order(self, symbol, order_id=None, client_id=None):
        self.cancelled.append((symbol, order_id or client_id))
        # remove from fake open orders
        lst = self._orders.get(symbol, [])
        self._orders[symbol] = [o for o in lst
                                if o.get("orderId") != order_id and o.get("clientOrderId") != client_id]
        return None


class FakeFilters:
    """Minimal filters stub: identity rounding, every symbol valid."""
    def has(self, symbol):
        return True

    def round_price(self, symbol, price):
        return round(float(price), 4)

    def round_qty(self, symbol, qty):
        return round(float(qty), 3)

    def valid_order(self, symbol, qty, price):
        return True, ""


def make_bot(fake_client, fake_filters, db):
    """Build a Bot instance wired to fakes without touching the network."""
    from .bot import Bot
    bot = Bot.__new__(Bot)          # bypass __init__ (which builds a real client)
    bot.client = fake_client
    bot.db = db
    bot.filters = fake_filters
    bot.btc_regime = "neutral"
    bot.last_decision_bar = None
    bot._startup_notified = True    # suppress startup noti in test
    return bot


def fresh_db():
    path = os.path.join(tempfile.gettempdir(), f"recovery_test_{int(time.time()*1000)}.db")
    if os.path.exists(path):
        os.remove(path)
    return StateDB(path), path


def our_sl_orders(orders, symbol):
    return [o for o in orders.get(symbol, []) if o["type"] == "STOP_MARKET"]


# --------------------------------------------------------------------------
# Scenario 1: OUR position survives with intact SL+TP -> resume, NO new orders
# --------------------------------------------------------------------------
def scenario_1_resume_intact():
    print("\n=== Scenario 1: own position, SL/TP intact -> resume (no duplicate orders) ===")
    db, path = fresh_db()
    db.upsert_position({
        "symbol": "BTCUSDT", "direction": "LONG", "entry_price": 45000, "qty": 0.05,
        "leverage": 18, "orig_sl_pct": 1.0, "sl_price": 44550, "tp_price": 48000,
        "be_moved": 0, "trail_moved": 0, "entry_time": int(time.time()*1000),
        "score": 7, "margin": 125, "sl_client_id": f"{OUR_PREFIX}_BTCUSDT_sl_1",
        "tp_client_id": f"{OUR_PREFIX}_BTCUSDT_tp_1", "entry_client_id": f"{OUR_PREFIX}_BTCUSDT_entry_1",
        "adopted": 0,
    })
    positions = [{"symbol": "BTCUSDT", "amt": 0.05, "dir": "LONG", "entry": 45000,
                  "mark": 45200, "upnl": 10, "leverage": 18, "liq": 40000}]
    orders = {"BTCUSDT": [
        {"symbol": "BTCUSDT", "type": "STOP_MARKET", "orderId": 1, "clientOrderId": f"{OUR_PREFIX}_BTCUSDT_sl_1"},
        {"symbol": "BTCUSDT", "type": "TAKE_PROFIT_MARKET", "orderId": 2, "clientOrderId": f"{OUR_PREFIX}_BTCUSDT_tp_1"},
    ]}
    fc = FakeClient(positions, orders)
    bot = make_bot(fc, FakeFilters(), db)
    bot.reconcile()

    check("position still tracked in DB", db.get_position("BTCUSDT") is not None)
    check("NO new protective orders placed", len(fc.placed) == 0,
          f"placed={fc.placed}")
    check("NO orders cancelled", len(fc.cancelled) == 0, f"cancelled={fc.cancelled}")
    db.close(); os.remove(path)


# --------------------------------------------------------------------------
# Scenario 2: OUR position, SL/TP missing -> re-place protection
# --------------------------------------------------------------------------
def scenario_2_replace_missing_protection():
    print("\n=== Scenario 2: own position, protection MISSING -> re-place SL/TP ===")
    db, path = fresh_db()
    db.upsert_position({
        "symbol": "ETHUSDT", "direction": "SHORT", "entry_price": 3000, "qty": 0.5,
        "leverage": 18, "orig_sl_pct": 1.0, "sl_price": 3030, "tp_price": 2800,
        "be_moved": 0, "trail_moved": 0, "entry_time": int(time.time()*1000),
        "score": 6, "margin": 80, "sl_client_id": f"{OUR_PREFIX}_ETHUSDT_sl_1",
        "tp_client_id": f"{OUR_PREFIX}_ETHUSDT_tp_1", "entry_client_id": None, "adopted": 0,
    })
    positions = [{"symbol": "ETHUSDT", "amt": -0.5, "dir": "SHORT", "entry": 3000,
                  "mark": 2990, "upnl": 5, "leverage": 18, "liq": 3300}]
    orders = {"ETHUSDT": []}  # protection gone while bot was down
    fc = FakeClient(positions, orders)
    bot = make_bot(fc, FakeFilters(), db)
    bot.reconcile()

    sl = [p for p in fc.placed if p[0] == "SL"]
    tp = [p for p in fc.placed if p[0] == "TP"]
    check("SL re-placed", len(sl) == 1, f"placed={fc.placed}")
    check("TP re-placed", len(tp) == 1, f"placed={fc.placed}")
    check("position still tracked", db.get_position("ETHUSDT") is not None)
    db.close(); os.remove(path)


# --------------------------------------------------------------------------
# Scenario 3: OUR position closed while bot was down -> cleanup
# --------------------------------------------------------------------------
def scenario_3_closed_while_down():
    print("\n=== Scenario 3: own position closed while down -> record closed + cleanup ===")
    db, path = fresh_db()
    db.upsert_position({
        "symbol": "SOLUSDT", "direction": "LONG", "entry_price": 150, "qty": 10,
        "leverage": 18, "orig_sl_pct": 1.0, "sl_price": 148.5, "tp_price": 160,
        "be_moved": 0, "trail_moved": 0, "entry_time": int(time.time()*1000),
        "score": 5, "margin": 83, "sl_client_id": f"{OUR_PREFIX}_SOLUSDT_sl_1",
        "tp_client_id": f"{OUR_PREFIX}_SOLUSDT_tp_1", "entry_client_id": None, "adopted": 0,
    })
    positions = []  # SOL no longer on exchange (hit SL/TP while down)
    # a leftover order may linger
    orders = {"SOLUSDT": [
        {"symbol": "SOLUSDT", "type": "TAKE_PROFIT_MARKET", "orderId": 5, "clientOrderId": f"{OUR_PREFIX}_SOLUSDT_tp_1"},
    ]}
    fc = FakeClient(positions, orders)
    bot = make_bot(fc, FakeFilters(), db)
    bot.reconcile()

    check("position removed from DB", db.get_position("SOLUSDT") is None)
    check("leftover order cancelled", any(c[0] == "SOLUSDT" for c in fc.cancelled),
          f"cancelled={fc.cancelled}")
    db.close(); os.remove(path)


# --------------------------------------------------------------------------
# Scenario 4: ORPHAN position (NOT ours) -> adopt with emergency SL
# --------------------------------------------------------------------------
def scenario_4_adopt_orphan():
    print("\n=== Scenario 4: orphan position (we never opened) -> adopt + emergency SL ===")
    db, path = fresh_db()
    # DB is EMPTY -> XRPUSDT on the exchange is an orphan
    positions = [{"symbol": "XRPUSDT", "amt": 100, "dir": "LONG", "entry": 0.5,
                  "mark": 0.51, "upnl": 1, "leverage": 10, "liq": 0.45}]
    orders = {"XRPUSDT": []}  # orphan has no protection
    fc = FakeClient(positions, orders)
    bot = make_bot(fc, FakeFilters(), db)
    bot.reconcile()

    dbp = db.get_position("XRPUSDT")
    check("orphan adopted into DB", dbp is not None)
    check("orphan marked adopted=1", dbp and dbp["adopted"] == 1,
          f"adopted={dbp['adopted'] if dbp else None}")
    sl = [p for p in fc.placed if p[0] == "SL"]
    check("emergency SL placed for orphan", len(sl) == 1, f"placed={fc.placed}")
    db.close(); os.remove(path)


# --------------------------------------------------------------------------
# Scenario 5: dangling orders, NO position -> cancel them
# --------------------------------------------------------------------------
def scenario_5_dangling_orders():
    print("\n=== Scenario 5: dangling orders with no position -> cancel ===")
    db, path = fresh_db()
    positions = []  # nothing open
    orders = {"ADAUSDT": [
        {"symbol": "ADAUSDT", "type": "STOP_MARKET", "orderId": 7, "clientOrderId": f"{OUR_PREFIX}_ADAUSDT_sl_1"},
    ]}
    fc = FakeClient(positions, orders)
    bot = make_bot(fc, FakeFilters(), db)
    bot.reconcile()

    check("dangling order cancelled", any(c[0] == "ADAUSDT" for c in fc.cancelled),
          f"cancelled={fc.cancelled}")
    db.close(); os.remove(path)


# --------------------------------------------------------------------------
# Scenario 6: MIXED — our position + orphan + closed, all at once
# --------------------------------------------------------------------------
def scenario_6_mixed():
    print("\n=== Scenario 6: MIXED (own intact + own closed + orphan) simultaneously ===")
    db, path = fresh_db()
    now = int(time.time()*1000)
    # own intact
    db.upsert_position({
        "symbol": "BTCUSDT", "direction": "LONG", "entry_price": 45000, "qty": 0.05,
        "leverage": 18, "orig_sl_pct": 1.0, "sl_price": 44550, "tp_price": 48000,
        "be_moved": 0, "trail_moved": 0, "entry_time": now, "score": 7, "margin": 125,
        "sl_client_id": f"{OUR_PREFIX}_BTCUSDT_sl_1", "tp_client_id": f"{OUR_PREFIX}_BTCUSDT_tp_1",
        "entry_client_id": None, "adopted": 0,
    })
    # own closed while down
    db.upsert_position({
        "symbol": "SOLUSDT", "direction": "LONG", "entry_price": 150, "qty": 10,
        "leverage": 18, "orig_sl_pct": 1.0, "sl_price": 148.5, "tp_price": 160,
        "be_moved": 0, "trail_moved": 0, "entry_time": now, "score": 5, "margin": 83,
        "sl_client_id": None, "tp_client_id": None, "entry_client_id": None, "adopted": 0,
    })
    positions = [
        {"symbol": "BTCUSDT", "amt": 0.05, "dir": "LONG", "entry": 45000, "mark": 45200,
         "upnl": 10, "leverage": 18, "liq": 40000},
        # SOL absent -> closed while down
        {"symbol": "DOGEUSDT", "amt": 1000, "dir": "LONG", "entry": 0.1, "mark": 0.102,
         "upnl": 2, "leverage": 10, "liq": 0.09},  # orphan
    ]
    orders = {"BTCUSDT": [
        {"symbol": "BTCUSDT", "type": "STOP_MARKET", "orderId": 1, "clientOrderId": f"{OUR_PREFIX}_BTCUSDT_sl_1"},
        {"symbol": "BTCUSDT", "type": "TAKE_PROFIT_MARKET", "orderId": 2, "clientOrderId": f"{OUR_PREFIX}_BTCUSDT_tp_1"},
    ]}
    fc = FakeClient(positions, orders)
    bot = make_bot(fc, FakeFilters(), db)
    bot.reconcile()

    check("own BTC still tracked", db.get_position("BTCUSDT") is not None)
    check("own BTC untouched (no new orders)",
          not any(p[1] == "BTCUSDT" for p in fc.placed), f"placed={fc.placed}")
    check("closed SOL removed from DB", db.get_position("SOLUSDT") is None)
    doge = db.get_position("DOGEUSDT")
    check("orphan DOGE adopted", doge is not None and doge["adopted"] == 1)
    check("orphan DOGE got emergency SL",
          any(p[0] == "SL" and p[1] == "DOGEUSDT" for p in fc.placed), f"placed={fc.placed}")
    db.close(); os.remove(path)


if __name__ == "__main__":
    print("=" * 70)
    print("  DISCONNECT / RECONNECT RECOVERY TEST (mock exchange, real DB)")
    print("=" * 70)
    scenario_1_resume_intact()
    scenario_2_replace_missing_protection()
    scenario_3_closed_while_down()
    scenario_4_adopt_orphan()
    scenario_5_dangling_orders()
    scenario_6_mixed()
    print("\n" + "=" * 70)
    print(f"  RESULT: {PASS} passed, {FAIL} failed")
    print("=" * 70)
    sys.exit(1 if FAIL else 0)
