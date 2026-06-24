"""Debug: test if notify_entry actually sends to Telegram.
Calls notify_startup then notify_entry with real params, checks queue."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Force load .env
from live import config  # this loads .env
print(f"STRATEGY={config.STRATEGY_LEVEL}")
print(f"TELEGRAM_BOT_TOKEN={'set' if os.environ.get('TELEGRAM_BOT_TOKEN') else 'EMPTY'}")
print(f"TELEGRAM_CHAT_LV4={os.environ.get('TELEGRAM_CHAT_LV4', 'EMPTY')}")
print(f"TELEGRAM_CHAT_LV5={os.environ.get('TELEGRAM_CHAT_LV5', 'EMPTY')}")
print(f"TELEGRAM_CHAT_LV6={os.environ.get('TELEGRAM_CHAT_LV6', 'EMPTY')}")

from live import telegram as tg

print(f"\ntg.is_enabled() = {tg.is_enabled()}")
print(f"tg._BOT_TOKEN = {'set' if tg._BOT_TOKEN else 'empty'}")
print(f"tg._CHAT_IDS = {tg._CHAT_IDS}")

# Test 1: startup
print("\n[1] Sending startup...")
r1 = tg.notify_startup("lv4", "testnet", 4500.0)
print(f"    queued: {r1}")
time.sleep(3)

# Test 2: entry with EXACT same params as bot
print("\n[2] Sending entry notification...")
r2 = tg.notify_entry(
    symbol="BTCUSDT",
    direction="SHORT",
    qty=0.0019,
    price=62757.78,
    lev=18,
    sl_pct=0.8,
    tp_pct=5.2,
    score=9,
    margin=675.22,
    notional=119.24,
    sl_price=63385.4,
    tp_price=60875.0,
    entry_time=int(time.time() * 1000),
)
print(f"    queued: {r2}")

# Test 3: simple text (no HTML)
print("\n[3] Sending simple text...")
r3 = tg.send("Simple test: entry BTCUSDT SHORT", level="lv4")
print(f"    queued: {r3}")

# Wait for delivery
print("\nWaiting 10s for delivery...")
time.sleep(10)
tg.flush(5)
print("Done. Check Telegram channel @trading_v4 for 3 messages.")
