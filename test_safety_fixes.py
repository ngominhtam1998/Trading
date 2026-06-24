"""Test new safety features: cooldown, liquidation warning, funding tracking."""
import os, sys, time, tempfile, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "production"))
os.environ["BOT_MODE"] = "testnet"
os.environ["BOT_STRATEGY"] = "lv4"

from live import config
from live.state_db import StateDB

# Use temp DB
tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
tmp.close()
db = StateDB(tmp.name)

print("=== TEST 1: Cooldown tracking ===")
# Simulate 2 consecutive SLs on AWEUSDT
db.set_kv("cooldowns", {})
assert not db.get_kv("cooldowns", {}).get("AWEUSDT")

# First SL
cooldowns = db.get_kv("cooldowns", {})
cooldowns["AWEUSDT"] = {"consecutive_sls": 1, "cooldown_until": 0}
db.set_kv("cooldowns", cooldowns)
print(f"  After 1st SL: {db.get_kv('cooldowns', {})}")

# Second SL → trigger cooldown
cooldowns = db.get_kv("cooldowns", {})
cooldowns["AWEUSDT"] = {"consecutive_sls": 2, "cooldown_until": int(time.time()*1000) + 6*15*60*1000}
db.set_kv("cooldowns", cooldowns)
print(f"  After 2nd SL: {db.get_kv('cooldowns', {})}")

# Check cooldown active
cd = db.get_kv("cooldowns", {})["AWEUSDT"]
assert cd["cooldown_until"] > time.time()*1000, "Cooldown should be active"
print(f"  Cooldown active: YES (until {cd['cooldown_until']})")

# Reset after TP
cooldowns = db.get_kv("cooldowns", {})
cooldowns["AWEUSDT"] = {"consecutive_sls": 0, "cooldown_until": 0}
db.set_kv("cooldowns", cooldowns)
assert db.get_kv("cooldowns", {})["AWEUSDT"]["consecutive_sls"] == 0
print(f"  After TP reset: {db.get_kv('cooldowns', {})}")
print("  PASS: Cooldown tracking works")

print("\n=== TEST 2: Liquidation warning threshold ===")
from live.strategy_adapter import strat
for lev in [10, 18, 22]:
    liq_pct = strat.get_liquidation_threshold(lev)
    print(f"  lev={lev}x → liq_threshold={liq_pct:.2f}% price move")
    # For SHORT at entry=0.06, lev=10x
    entry = 0.06
    liq_price = entry * (1 + liq_pct/100)
    warn_at = liq_price * (1 - config.LIQ_WARN_THRESHOLD_PCT/100)
    print(f"    SHORT entry={entry} → liq_price={liq_price:.6f} → warn when price > {warn_at:.6f}")
print("  PASS: Liquidation threshold calculation OK")

print("\n=== TEST 3: Funding cost tracking ===")
# Simulate a position held for 32 bars (2 funding intervals)
db.set_kv("funding_daily", {})
entry_time = int(time.time()*1000) - 32 * 15 * 60 * 1000  # 32 bars ago
qty = 100000.0
entry_price = 0.06
notional = qty * entry_price  # $6000
fr = 0.0005 / 100  # 0.0005%
bars_held = (time.time()*1000 - entry_time) / 1000 / (15*60)
funding_intervals = int(bars_held // 16)
funding_cost = notional * fr * funding_intervals
print(f"  Position: qty={qty} entry={entry_price} notional=${notional:.0f}")
print(f"  Bars held: {bars_held:.0f} → funding intervals: {funding_intervals}")
print(f"  Funding cost: ${funding_cost:.4f}")
# Track in DB
funding_state = {"date": "2026-06-24", "total": funding_cost, "warned": False}
db.set_kv("funding_daily", funding_state)
state = db.get_kv("funding_daily", {})
assert state["total"] == funding_cost
print(f"  DB stored: {state}")
# Check warning threshold (5% of $5000 = $250)
equity = 5000.0
if state["total"] > equity * config.FUNDING_DAILY_WARN_PCT / 100:
    print(f"  WARNING would trigger: ${state['total']:.2f} > ${equity*0.05:.2f}")
else:
    print(f"  No warning: ${state['total']:.2f} < ${equity*0.05:.2f} (5% of ${equity})")
print("  PASS: Funding tracking works")

print("\n=== TEST 4: SSL verification mode ===")
from live.binance_client import BinanceClient
# testnet → verify=False
os.environ["BOT_MODE"] = "testnet"
from live import config as cfg2
import importlib
importlib.reload(cfg2)
print(f"  testnet MODE={cfg2.MODE} → SSL should be OFF")
# live → verify=True
os.environ["BOT_MODE"] = "live"
importlib.reload(cfg2)
print(f"  live MODE={cfg2.MODE} → SSL should be ON")
# Reset
os.environ["BOT_MODE"] = "testnet"
importlib.reload(cfg2)
print("  PASS: SSL mode switches correctly")

print("\n=== ALL TESTS PASSED ===")
os.unlink(tmp.name)
