"""One-shot cleanup: close all positions + cancel all orders on a testnet account.
Run:  BOT_STRATEGY=lv4 python -m live.cleanup
      BOT_STRATEGY=lv5 python -m live.cleanup
      BOT_STRATEGY=lv6 python -m live.cleanup
"""
import time
from . import config
from .binance_client import BinanceClient

print(f"Cleanup: MODE={config.MODE} STRATEGY={config.STRATEGY_LEVEL}")
c = BinanceClient()

# 1) cancel all open algo orders (SL/TP) on every symbol
algo_all = []
for sym in {o.get("symbol") for o in c.open_algo_orders()}:
    for o in c.open_algo_orders(sym):
        try:
            c.cancel_algo_order(sym, algo_id=o.get("algoId"))
            print(f"  cancelled algo {o.get('type')} on {sym} id={o.get('algoId')}")
        except Exception as e:
            print(f"  cancel algo {sym} failed: {e}")

# 2) close any open position via reduce-only MARKET
for p in c.position_risk():
    sym = p["symbol"]; amt = p["amt"]
    if amt == 0:
        continue
    side = "SELL" if amt > 0 else "BUY"
    try:
        c.new_market_order(sym, side, abs(amt), reduce_only=True,
                           client_id=f"scbot_cleanup_{sym}")
        print(f"  closed {sym} {side} qty={abs(amt)}")
    except Exception as e:
        print(f"  close {sym} failed: {e}")

time.sleep(2)
eq, avail = c.equity_usdt()
print(f"Done. equity={eq:.2f} avail={avail:.2f} open_positions="
      f"{[p['symbol'] for p in c.position_risk() if p['amt']!=0]}")
