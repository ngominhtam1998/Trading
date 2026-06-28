"""Integration test: verify Algo Order API works on testnet for SL/TP.
Opens a tiny BTCUSDT position, places algo SL+TP, verifies they appear in
open_algo_orders, cancels them, then closes the position. Cleans up fully.

Run: python -m live.test_algo  (BOT_MODE=testnet BOT_STRATEGY=opus)
"""
import os, time
from . import config
from .binance_client import BinanceClient, BinanceError
from .exchange_filters import ExchangeFilters

SYM = "BTCUSDT"
c = BinanceClient()
f = ExchangeFilters(c)

print(f"Mode={config.MODE} Strategy={config.STRATEGY_LEVEL}")

# clean slate
for o in c.open_algo_orders(SYM):
    c.cancel_algo_order(SYM, algo_id=o.get("algoId"))
for p in c.position_risk():
    if p["symbol"] == SYM:
        side = "BUY" if p["amt"] < 0 else "SELL"
        c.new_market_order(SYM, side, abs(p["amt"]), reduce_only=True)

price = c.mark_price(SYM)
print(f"{SYM} mark price: {price}")

# open a tiny LONG (min notional ~ $100 to be safe)
notional = 120.0
qty = f.round_qty(SYM, notional / price)
print(f"Opening LONG qty={qty} (~${qty*price:.2f})")
c.set_margin_type(SYM, "ISOLATED")
c.set_leverage(SYM, 5)
resp = c.new_market_order(SYM, "BUY", qty, client_id="scbot_BTCUSDT_entry_test")
fill = float(resp.get("avgPrice") or price)
print(f"  filled @ {fill}, status={resp.get('status')}")

# place algo SL + TP
sl_price = f.round_price(SYM, fill * 0.99)
tp_price = f.round_price(SYM, fill * 1.05)
ok_sl = ok_tp = False
try:
    r = c.new_stop_market(SYM, "SELL", sl_price, client_id="scbot_BTCUSDT_sl_test", close_position=True)
    print(f"  SL placed: algoId={r.get('algoId')} clientAlgoId={r.get('clientAlgoId')}")
    ok_sl = True
except BinanceError as e:
    print(f"  SL FAILED: {e}")
try:
    r = c.new_take_profit_market(SYM, "SELL", tp_price, client_id="scbot_BTCUSDT_tp_test", close_position=True)
    print(f"  TP placed: algoId={r.get('algoId')} clientAlgoId={r.get('clientAlgoId')}")
    ok_tp = True
except BinanceError as e:
    print(f"  TP FAILED: {e}")

time.sleep(1)
algo = c.open_algo_orders(SYM)
print(f"  open_algo_orders: {[(o['type'], o['clientOrderId']) for o in algo]}")
has_sl = any(o["type"] == "STOP_MARKET" for o in algo)
has_tp = any(o["type"] == "TAKE_PROFIT_MARKET" for o in algo)

# cleanup
for o in algo:
    c.cancel_algo_order(SYM, algo_id=o.get("algoId"))
c.new_market_order(SYM, "SELL", qty, reduce_only=True)
time.sleep(1)
print(f"  after cleanup: positions={[(p['symbol'],p['amt']) for p in c.position_risk() if p['symbol']==SYM]}, "
      f"algo_orders={len(c.open_algo_orders(SYM))}")

print("\nRESULT:",
      "PASS" if (ok_sl and ok_tp and has_sl and has_tp) else "FAIL",
      f"(SL placed={ok_sl}, TP placed={ok_tp}, SL visible={has_sl}, TP visible={has_tp})")
