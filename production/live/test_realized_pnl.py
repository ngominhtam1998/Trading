"""Test realized_pnl_since uses income API for PnL and userTrades for exit price.

Run: python -m live.test_realized_pnl  (from D:/Tam/trading/production)
"""
import os

os.environ.setdefault("BOT_MODE", "dry")
os.environ.setdefault("BOT_STRATEGY", "opus")

from live.binance_client import BinanceClient

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


# Build a fake client bypassing __init__ network call
client = BinanceClient.__new__(BinanceClient)
client.base = ""
client.key = ""
client.secret = ""
client.session = None
client.time_offset = 0

income_data = [
    {"incomeType": "REALIZED_PNL", "income": "1.5", "symbol": "BTCUSDT", "time": 1000},
    {"incomeType": "COMMISSION", "income": "-0.02", "symbol": "BTCUSDT", "time": 1000},
    {"incomeType": "FUNDING_FEE", "income": "-0.01", "symbol": "BTCUSDT", "time": 1500},
    {"incomeType": "REALIZED_PNL", "income": "2.5", "symbol": "BTCUSDT", "time": 2000},
    {"incomeType": "TRANSFER", "income": "100.0", "symbol": "BTCUSDT", "time": 2500},
]
trades_data = [
    {"symbol": "BTCUSDT", "price": "100.0", "qty": "1", "realizedPnl": None, "commission": "0"},
    {"symbol": "BTCUSDT", "price": "101.0", "qty": "1", "realizedPnl": None, "commission": "0"},
]


def fake_request(method, path, params=None, signed=False, retries=None):
    if path == "/fapi/v1/income":
        return income_data
    raise RuntimeError(f"unexpected {path}")


client._request = fake_request
client.user_trades = lambda symbol, start_time=None, limit=50: trades_data

print("=== REALIZED_PNL INCOME API TEST ===")

pnl, exit_px, _ = client.realized_pnl_since("BTCUSDT", 0)
# net = 1.5 - 0.02 - 0.01 + 2.5 = 3.97 (TRANSFER excluded)
check("net PnL = realized+commission+funding", abs(pnl - 3.97) < 1e-9, f"pnl={pnl} (expected 3.97)")
check("TRANSFER excluded from PnL", pnl < 100, f"pnl={pnl} should not include transfer")
check("exit price from last user trade", exit_px == 101.0, f"exit_px={exit_px} (expected 101.0)")

# Test fallback when income API fails
client._request = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("network down"))
pnl2, exit_px2, _ = client.realized_pnl_since("BTCUSDT", 0)
check("PnL None when income fails", pnl2 is None, f"pnl2={pnl2}")
check("exit price still available from trades", exit_px2 == 101.0, f"exit_px2={exit_px2}")

print(f"\nRESULT: {PASS} passed, {FAIL} failed")
