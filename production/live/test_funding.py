"""Test funding rate API and filter logic."""
import json
from live import config
from live.binance_client import BinanceClient

c = BinanceClient()
print(f"Mode={config.MODE}")

# Raw API response
for sym in ["BTCUSDT", "ETHUSDT", "DOGEUSDT", "SOLUSDT"]:
    try:
        r = c._request("GET", "/fapi/v1/premiumIndex", {"symbol": sym})
        fr = float(r.get("lastFundingRate", 0))
        print(f"{sym}: markPrice={r.get('markPrice')} lastFundingRate={r.get('lastFundingRate')} "
              f"= {fr*100:.4f}% nextFundingTime={r.get('nextFundingTime')}")
    except Exception as e:
        print(f"{sym}: ERROR {e}")

# Test funding_rate method
print("\nfunding_rate() method:")
for sym in ["BTCUSDT", "ETHUSDT", "DOGEUSDT"]:
    fr = c.funding_rate(sym)
    print(f"  {sym}: {fr} ({fr*100:.4f}%)")

# Test filter logic
print("\nFilter logic test:")
FUNDING_THRESHOLD = 0.001
cases = [
    ("SHORT", -0.002, "should skip (shorts pay)"),
    ("SHORT", -0.001, "should skip (exactly -0.1%)"),
    ("SHORT", -0.0005, "should NOT skip (below threshold)"),
    ("SHORT", 0.001, "should NOT skip (shorts receive)"),
    ("SHORT", 0.002, "should NOT skip (shorts receive more)"),
    ("LONG", 0.002, "should skip (longs pay)"),
    ("LONG", 0.001, "should skip (exactly +0.1%)"),
    ("LONG", 0.0005, "should NOT skip (below threshold)"),
    ("LONG", -0.001, "should NOT skip (longs receive)"),
    ("LONG", -0.002, "should NOT skip (longs receive more)"),
]
for direction, fr, expected in cases:
    skip = (direction == "SHORT" and fr <= -FUNDING_THRESHOLD) or \
           (direction == "LONG" and fr >= FUNDING_THRESHOLD)
    action = "SKIP" if skip else "OK"
    print(f"  {direction} funding={fr*100:+.4f}% -> {action} ({expected})")
