"""Offline self-test for crash-recovery / reconciliation logic.

Uses a fake client so we can verify reconcile() handles all 4 scenarios
WITHOUT real API keys:
  1. position known in DB + protection intact  -> resume
  2. position known in DB + protection missing -> re-place SL/TP
  3. orphan position (not in DB)               -> adopt + place SL
  4. position in DB but gone from exchange     -> record closed + cleanup
  5. dangling orders with no position          -> cancel

Run: python -m live.test_recovery   (from D:/Temp/Trading)
"""
import os
import tempfile
from live import config
from live.state_db import StateDB


class FakeClient:
    def __init__(self, positions, orders):
        self._positions = positions
        self._orders = orders        # dict: symbol -> list of orders
        self.placed = []             # log of placed orders
        self.cancelled = []
        self.market_closes = []

    def position_risk(self):
        return self._positions

    def open_orders(self, symbol=None):
        # real API includes 'symbol' on every order; inject it for fidelity
        if symbol:
            return [dict(o, symbol=symbol) for o in self._orders.get(symbol, [])]
        out = []
        for sym, v in self._orders.items():
            out.extend(dict(o, symbol=sym) for o in v)
        return out

    def mark_price(self, symbol):
        return 100.0

    def new_stop_market(self, symbol, side, stop_price, client_id=None, close_position=True, qty=None):
        self.placed.append(("SL", symbol, stop_price, client_id))
        self._orders.setdefault(symbol, []).append(
            {"type": "STOP_MARKET", "orderId": len(self.placed), "clientOrderId": client_id})
        return {"orderId": len(self.placed)}

    def new_take_profit_market(self, symbol, side, stop_price, client_id=None, close_position=True, qty=None):
        self.placed.append(("TP", symbol, stop_price, client_id))
        self._orders.setdefault(symbol, []).append(
            {"type": "TAKE_PROFIT_MARKET", "orderId": len(self.placed), "clientOrderId": client_id})
        return {"orderId": len(self.placed)}

    def cancel_order(self, symbol, order_id=None, client_id=None):
        self.cancelled.append((symbol, order_id, client_id))
        return {}

    def new_market_order(self, symbol, side, qty, client_id=None, reduce_only=False):
        self.market_closes.append((symbol, side, qty))
        return {"avgPrice": "100.0"}


class FakeFilters:
    def has(self, s): return True
    def round_price(self, s, p): return round(float(p), 4)
    def round_qty(self, s, q): return round(float(q), 3)


def make_bot(client, db):
    """Construct a Bot-like object without network by monkeypatching."""
    from live.bot import Bot
    bot = Bot.__new__(Bot)          # skip __init__ (no network)
    bot.client = client
    bot.db = db
    bot.filters = FakeFilters()
    bot.btc_regime = "neutral"
    return bot


def run():
    config.MODE = "test"
    tmp = tempfile.mktemp(suffix=".db")
    db = StateDB(tmp)

    # --- seed DB with two known positions ---
    db.upsert_position({"symbol": "AAAUSDT", "direction": "LONG", "entry_price": 100,
        "qty": 1, "leverage": 5, "orig_sl_pct": 1.0, "sl_price": 99, "tp_price": 103.5,
        "entry_time": 1, "score": 8, "margin": 70, "sl_client_id": "scbot_AAAUSDT_sl_1",
        "tp_client_id": "scbot_AAAUSDT_tp_1", "entry_client_id": None, "adopted": 0})
    db.upsert_position({"symbol": "BBBUSDT", "direction": "SHORT", "entry_price": 50,
        "qty": 2, "leverage": 5, "orig_sl_pct": 1.0, "sl_price": 50.5, "tp_price": 48.25,
        "entry_time": 1, "score": 7, "margin": 70, "sl_client_id": "scbot_BBBUSDT_sl_1",
        "tp_client_id": "scbot_BBBUSDT_tp_1", "entry_client_id": None, "adopted": 0})
    db.upsert_position({"symbol": "CCCUSDT", "direction": "LONG", "entry_price": 10,
        "qty": 5, "leverage": 5, "orig_sl_pct": 1.0, "sl_price": 9.9, "tp_price": 10.35,
        "entry_time": 1, "score": 7, "margin": 70, "sl_client_id": "scbot_CCCUSDT_sl_1",
        "tp_client_id": "scbot_CCCUSDT_tp_1", "entry_client_id": None, "adopted": 0})

    # --- exchange state ---
    positions = [
        # AAA: known, protection intact
        {"symbol": "AAAUSDT", "amt": 1, "dir": "LONG", "entry": 100, "mark": 101, "upnl": 1, "leverage": 5, "liq": 0},
        # BBB: known, protection MISSING (no orders) -> should re-place
        {"symbol": "BBBUSDT", "amt": -2, "dir": "SHORT", "entry": 50, "mark": 49, "upnl": 2, "leverage": 5, "liq": 0},
        # DDD: ORPHAN (not in DB) -> adopt
        {"symbol": "DDDUSDT", "amt": 3, "dir": "LONG", "entry": 20, "mark": 21, "upnl": 3, "leverage": 5, "liq": 0},
        # CCC is in DB but NOT here -> closed while down
    ]
    orders = {
        "AAAUSDT": [
            {"type": "STOP_MARKET", "orderId": 11, "clientOrderId": "scbot_AAAUSDT_sl_1"},
            {"type": "TAKE_PROFIT_MARKET", "orderId": 12, "clientOrderId": "scbot_AAAUSDT_tp_1"},
        ],
        # BBB: no orders -> missing protection
        # EEE: dangling orders but no position -> cancel
        "EEEUSDT": [
            {"type": "STOP_MARKET", "orderId": 99, "clientOrderId": "scbot_EEEUSDT_sl_1"},
        ],
    }

    client = FakeClient(positions, orders)
    bot = make_bot(client, db)
    bot.reconcile()

    # --- assertions ---
    ok = True
    def check(cond, msg):
        nonlocal ok
        print(("PASS" if cond else "FAIL") + ": " + msg)
        ok = ok and cond

    # AAA intact: no new SL placed for AAA
    check(not any(p[1] == "AAAUSDT" for p in client.placed), "AAA protection left intact (no re-place)")
    # BBB missing -> SL re-placed
    check(any(p[0] == "SL" and p[1] == "BBBUSDT" for p in client.placed), "BBB SL re-placed")
    # DDD orphan -> adopted (SL placed + in DB)
    check(any(p[0] == "SL" and p[1] == "DDDUSDT" for p in client.placed), "DDD orphan SL placed")
    check(db.get_position("DDDUSDT") is not None, "DDD orphan inserted into DB")
    check(db.get_position("DDDUSDT")["adopted"] == 1, "DDD marked adopted")
    # CCC gone -> removed from DB + recorded closed
    check(db.get_position("CCCUSDT") is None, "CCC removed from DB (closed while down)")
    # EEE dangling -> cancelled
    check(any(c[0] == "EEEUSDT" for c in client.cancelled), "EEE dangling order cancelled")

    db.close()
    os.remove(tmp)
    print("\n" + ("ALL RECOVERY TESTS PASSED" if ok else "SOME TESTS FAILED"))
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if run() else 1)
