"""Test SL move logic (BE/trail) with a fake exchange.

Run: python -m live.test_sl_move  (from D:/Tam/trading/production)
"""
import os
import sys
import time
import tempfile

os.environ.setdefault("BOT_MODE", "dry")
os.environ.setdefault("BOT_STRATEGY", "lv4")

from live import config
from live.state_db import StateDB
from live.bot import Bot
from live.binance_client import BinanceError

PASS = 0
FAIL = 0

OUR_PREFIX = config.ORDER_PREFIX


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


class FakeClient:
    def __init__(self, positions, orders, mark_price, fail_new_sl=False):
        self._positions = {p["symbol"]: p for p in positions}
        self._orders = {s: list(lst) for s, lst in (orders or {}).items()}
        self._mark_price = mark_price
        self.fail_new_sl = fail_new_sl
        self.placed = []      # (kind, symbol, side, price, client_id)
        self.cancelled = []   # (symbol, client_id)
        self.market_closes = []  # (symbol, side, qty)
        self._order_counter = 0

    def _order_id(self):
        self._order_counter += 1
        return self._order_counter

    def position_risk(self):
        return list(self._positions.values())

    def mark_price(self, symbol):
        return self._mark_price

    def klines(self, symbol, interval, limit=3):
        # Return a bar with high/low that triggers BE/trail for SHORT
        # bar format: open, high, low, close, volume, quote_volume
        mp = self._mark_price
        return [[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                [0, mp * 1.02, mp * 0.95, 0, 0, 0, 0, 0, 0, 0, 0, 0]]

    def open_algo_orders(self, symbol=None):
        if symbol is None:
            out = []
            for lst in self._orders.values():
                out.extend(lst)
            return out
        return list(self._orders.get(symbol, []))

    def open_orders(self, symbol=None):
        return self.open_algo_orders(symbol)

    def new_stop_market(self, symbol, side, stop_price, client_id=None, close_position=True, qty=None):
        if self.fail_new_sl and client_id and client_id != f"{OUR_PREFIX}_{symbol}_sl_old":
            raise BinanceError(-4130, "fake: closePosition SL already exists")
        oid = self._order_id()
        self.placed.append(("SL", symbol, side, stop_price, client_id))
        self._orders.setdefault(symbol, []).append({
            "symbol": symbol, "type": "STOP_MARKET", "orderId": oid,
            "clientOrderId": client_id or "", "clientAlgoId": client_id or "",
            "algoId": oid, "triggerPrice": stop_price, "side": side,
        })
        return {"orderId": oid, "clientOrderId": client_id, "clientAlgoId": client_id}

    def new_take_profit_market(self, symbol, side, stop_price, client_id=None, close_position=True, qty=None):
        oid = self._order_id()
        self.placed.append(("TP", symbol, side, stop_price, client_id))
        self._orders.setdefault(symbol, []).append({
            "symbol": symbol, "type": "TAKE_PROFIT_MARKET", "orderId": oid,
            "clientOrderId": client_id or "", "clientAlgoId": client_id or "",
            "algoId": oid, "triggerPrice": stop_price, "side": side,
        })
        return {"orderId": oid, "clientOrderId": client_id, "clientAlgoId": client_id}

    def new_market_order(self, symbol, side, qty, client_id=None, reduce_only=False):
        self.market_closes.append((symbol, side, qty))
        return {"orderId": 999, "avgPrice": str(self._mark_price)}

    def cancel_algo_order(self, symbol=None, algo_id=None, client_id=None):
        target = algo_id or client_id
        self.cancelled.append((symbol, target))
        if symbol and target:
            lst = self._orders.get(symbol, [])
            self._orders[symbol] = [o for o in lst
                                    if o.get("clientOrderId") != target and o.get("clientAlgoId") != target]
        return None

    def cancel_order(self, symbol, order_id=None, client_id=None):
        return self.cancel_algo_order(symbol, algo_id=order_id, client_id=client_id)


class FakeFilters:
    def has(self, symbol): return True
    def round_price(self, symbol, price): return round(float(price), 4)
    def round_qty(self, symbol, qty): return round(float(qty), 3)
    def valid_order(self, symbol, qty, price): return True, ""


def make_bot(client, filters, db):
    bot = Bot.__new__(Bot)
    bot.client = client
    bot.db = db
    bot.filters = filters
    bot.btc_regime = "neutral"
    bot.last_decision_bar = None
    bot._startup_notified = True
    bot._last_time_sync = time.time()
    bot._lock_fd = None
    return bot


def fresh_db():
    path = os.path.join(tempfile.gettempdir(), f"sl_move_test_{int(time.time()*1000)}.db")
    if os.path.exists(path):
        os.remove(path)
    return StateDB(path), path


def run_test():
    global PASS, FAIL
    mark_price = 98.5  # below 0.99*entry so BE SL (99) is above mark
    entry = 100.0
    sl_price = 101.0   # SHORT SL above entry
    tp_price = 97.0

    # Scenario 1: successful BE move (cancel old, place new)
    print("\n=== Scenario 1: valid BE move -> cancel old SL, place new SL ===")
    db, path = fresh_db()
    db.upsert_position({
        "symbol": "BTCUSDT", "direction": "SHORT", "entry_price": entry, "qty": 1.0,
        "leverage": 10, "orig_sl_pct": 1.0, "sl_price": sl_price, "tp_price": tp_price,
        "be_moved": 0, "trail_moved": 0, "entry_time": int(time.time()*1000) - 3600*1000,
        "score": 7, "margin": 10, "sl_client_id": f"{OUR_PREFIX}_BTCUSDT_sl_old",
        "tp_client_id": f"{OUR_PREFIX}_BTCUSDT_tp_1", "entry_client_id": None, "adopted": 0,
    })
    orders = {"BTCUSDT": [
        {"symbol": "BTCUSDT", "type": "STOP_MARKET", "orderId": 1,
         "clientOrderId": f"{OUR_PREFIX}_BTCUSDT_sl_old", "clientAlgoId": f"{OUR_PREFIX}_BTCUSDT_sl_old",
         "algoId": 1, "triggerPrice": sl_price, "side": "BUY"},
    ]}
    fc = FakeClient([{"symbol": "BTCUSDT", "amt": -1.0, "dir": "SHORT", "entry": entry,
                      "mark": mark_price, "upnl": 0, "leverage": 10, "liq": 110}],
                    orders, mark_price)
    bot = make_bot(fc, FakeFilters(), db)
    bot._update_stops("BTCUSDT", db.get_position("BTCUSDT"))

    # After BE move, old SL should be cancelled, new SL placed
    check("old SL cancelled", any(t[1] == f"{OUR_PREFIX}_BTCUSDT_sl_old" for t in fc.cancelled),
          f"cancelled={fc.cancelled}")
    new_sl = [p for p in fc.placed if p[0] == "SL" and p[4] != f"{OUR_PREFIX}_BTCUSDT_sl_old"]
    check("new SL placed", len(new_sl) >= 1, f"placed={fc.placed}")
    dbp = db.get_position("BTCUSDT")
    check("DB be_moved flag set", dbp and dbp["be_moved"] == 1, f"be_moved={dbp['be_moved'] if dbp else None}")
    db.close(); os.remove(path)

    # Scenario 2: new SL placement fails -> old SL restored
    print("\n=== Scenario 2: new SL placement fails -> restore old SL ===")
    db, path = fresh_db()
    db.upsert_position({
        "symbol": "ETHUSDT", "direction": "SHORT", "entry_price": entry, "qty": 1.0,
        "leverage": 10, "orig_sl_pct": 1.0, "sl_price": sl_price, "tp_price": tp_price,
        "be_moved": 0, "trail_moved": 0, "entry_time": int(time.time()*1000) - 3600*1000,
        "score": 7, "margin": 10, "sl_client_id": f"{OUR_PREFIX}_ETHUSDT_sl_old",
        "tp_client_id": f"{OUR_PREFIX}_ETHUSDT_tp_1", "entry_client_id": None, "adopted": 0,
    })
    orders = {"ETHUSDT": [
        {"symbol": "ETHUSDT", "type": "STOP_MARKET", "orderId": 1,
         "clientOrderId": f"{OUR_PREFIX}_ETHUSDT_sl_old", "clientAlgoId": f"{OUR_PREFIX}_ETHUSDT_sl_old",
         "algoId": 1, "triggerPrice": sl_price, "side": "BUY"},
    ]}
    fc = FakeClient([{"symbol": "ETHUSDT", "amt": -1.0, "dir": "SHORT", "entry": entry,
                      "mark": mark_price, "upnl": 0, "leverage": 10, "liq": 110}],
                    orders, mark_price, fail_new_sl=True)
    bot = make_bot(fc, FakeFilters(), db)
    bot._update_stops("ETHUSDT", db.get_position("ETHUSDT"))

    # Old SL should be cancelled, then restored
    check("old SL was cancelled then restored",
          fc.cancelled.count(("ETHUSDT", f"{OUR_PREFIX}_ETHUSDT_sl_old")) >= 1,
          f"cancelled={fc.cancelled}")
    restored = [p for p in fc.placed if p[0] == "SL" and p[4] == f"{OUR_PREFIX}_ETHUSDT_sl_old"]
    check("old SL restored after failed new SL", len(restored) >= 1,
          f"placed={fc.placed}")
    check("market close NOT triggered", len(fc.market_closes) == 0,
          f"market_closes={fc.market_closes}")
    db.close(); os.remove(path)

    print(f"\nRESULT: {PASS} passed, {FAIL} failed")


if __name__ == "__main__":
    run_test()
