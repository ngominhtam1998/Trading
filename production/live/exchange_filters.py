"""Exchange filters: per-symbol precision, step size, min notional.

Orders are rejected by Binance if quantity/price don't match the symbol's
filters (errors -1111 precision, -4164/-4003 min notional, PRICE_FILTER).
This module loads exchangeInfo once and provides correct rounding.
"""
import math
import logging

log = logging.getLogger("filters")


def _round_step(value, step):
    """Round DOWN to the nearest multiple of step (for quantity)."""
    if step <= 0:
        return value
    return math.floor(value / step) * step


def _round_tick(value, tick):
    """Round to nearest tick (for price)."""
    if tick <= 0:
        return value
    return round(round(value / tick) * tick, 12)


class ExchangeFilters:
    def __init__(self, client):
        self.client = client
        self.symbols = {}  # symbol -> filter dict
        self.load()

    def load(self):
        info = self.client.exchange_info()
        for s in info["symbols"]:
            if s.get("quoteAsset") != "USDT" or s.get("contractType") != "PERPETUAL":
                continue
            if s.get("status") != "TRADING":
                continue
            step = min_qty = tick = min_notional = 0.0
            for f in s["filters"]:
                ft = f["filterType"]
                if ft == "LOT_SIZE":
                    step = float(f["stepSize"]); min_qty = float(f["minQty"])
                elif ft == "PRICE_FILTER":
                    tick = float(f["tickSize"])
                elif ft in ("MIN_NOTIONAL", "NOTIONAL"):
                    min_notional = float(f.get("notional", f.get("minNotional", 0)))
            self.symbols[s["symbol"]] = {
                "step": step, "min_qty": min_qty, "tick": tick,
                "min_notional": min_notional,
                "qty_prec": int(s.get("quantityPrecision", 8)),
                "price_prec": int(s.get("pricePrecision", 8)),
                "max_leverage": int(float(s.get("maxLeverage", 125) or 125)),
            }
        log.info(f"Loaded filters for {len(self.symbols)} symbols")

    def has(self, symbol):
        return symbol in self.symbols

    def round_qty(self, symbol, qty):
        qty = float(qty)
        f = self.symbols.get(symbol)
        if not f:
            return round(qty, 3)
        q = _round_step(qty, f["step"]) if f["step"] > 0 else qty
        return float(round(q, f["qty_prec"]))

    def round_price(self, symbol, price):
        price = float(price)
        f = self.symbols.get(symbol)
        if not f:
            return round(price, 4)
        p = _round_tick(price, f["tick"]) if f["tick"] > 0 else price
        return float(round(p, f["price_prec"]))

    def min_notional(self, symbol):
        f = self.symbols.get(symbol)
        return f["min_notional"] if f else 5.0

    def min_qty(self, symbol):
        f = self.symbols.get(symbol)
        return f["min_qty"] if f else 0.0

    def max_leverage(self, symbol):
        f = self.symbols.get(symbol)
        return f["max_leverage"] if f else 125

    def valid_order(self, symbol, qty, price):
        """Check qty/notional meet exchange minimums. Returns (ok, reason)."""
        f = self.symbols.get(symbol)
        if not f:
            return False, "unknown symbol"
        if qty < f["min_qty"]:
            return False, f"qty {qty} < minQty {f['min_qty']}"
        notional = qty * price
        if f["min_notional"] > 0 and notional < f["min_notional"]:
            return False, f"notional {notional:.2f} < min {f['min_notional']}"
        return True, ""
