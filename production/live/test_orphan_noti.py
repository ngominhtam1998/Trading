"""Test orphan adopted notification."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from live import config
from live import telegram as tg

print(f"Telegram enabled: {tg.is_enabled()}")
print(f"Chat ID LV4: {tg._CHAT_IDS.get('lv4')}")

# Send test orphan notification
print("\nSending test orphan adopted notification...")
tg.notify_orphan_adopted(
    symbol="VELVETUSDT",
    direction="SHORT",
    qty=23227.0,
    entry=0.459010,
    lev=10,
    sl_price=0.463600,
    tp_price=0.442860,
    sl_pct=1.0,
)
import time
time.sleep(5)
tg.flush(5)
print("Done. Check @trading_v4 channel for 'ADOPT ORPHAN — VELVETUSDT'")
