"""Debug: directly call Telegram API to check HTTP response for entry notification."""
import os, sys, requests, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from live import config  # loads .env

token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
chat_id = os.environ.get("TELEGRAM_CHAT_LV4", "")
print(f"token={'set' if token else 'empty'}, chat_id={chat_id}")

# Test 1: simple text
print("\n[1] Simple text...")
r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                  json={"chat_id": chat_id, "text": "Test simple", "parse_mode": "HTML"},
                  timeout=10)
print(f"    status={r.status_code}, ok={r.json().get('ok')}")
if r.status_code != 200:
    print(f"    response: {r.text[:300]}")

# Test 2: entry notification (same format as notify_entry)
print("\n[2] Entry notification format...")
msg = "\n".join([
    "\U0001f534 <b>MỞ LỆNH</b> — BTCUSDT",
    "├ Hướng: <b>SHORT</b>  |  Đòn bẩy: <b>18x</b>",
    "├ Giá vào: <b>62757.8</b>",
    "├ Khối lượng: <b>0.0019</b>  (~$119.24)",
    "├ Ký quỹ: <b>$675.22</b>",
    "├ SL: <b>63385.4</b> (0.80%)",
    "├ TP: <b>60875.0</b> (5.20%)",
    "├ RR: <b>6.5</b>  |  Score: <b>9/10</b>",
    "└ Thời gian: 2026-06-24 08:00:00",
])
print(f"    message length: {len(msg)} chars")
r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                  json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML",
                        "disable_web_page_preview": True},
                  timeout=10)
print(f"    status={r.status_code}, ok={r.json().get('ok')}")
if r.status_code != 200:
    print(f"    response: {r.text[:500]}")
else:
    print(f"    message_id={r.json()['result']['message_id']}")

# Test 3: entry with float qty (like bot sends)
print("\n[3] Entry with float qty (111549.0)...")
msg2 = "\n".join([
    "\U0001f534 <b>MỞ LỆNH</b> — DOGEUSDT",
    "├ Hướng: <b>SHORT</b>  |  Đòn bẩy: <b>13x</b>",
    "├ Giá vào: <b>0.07869</b>",
    "├ Khối lượng: <b>111549.0</b>  (~$8,777.0)",
    "├ Ký quỹ: <b>$675.22</b>",
    "├ SL: <b>0.0790834</b> (0.50%)",
    "├ TP: <b>0.0761326</b> (3.25%)",
    "├ RR: <b>6.5</b>  |  Score: <b>9/10</b>",
    "└ Thời gian: 2026-06-24 08:00:00",
])
r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                  json={"chat_id": chat_id, "text": msg2, "parse_mode": "HTML",
                        "disable_web_page_preview": True},
                  timeout=10)
print(f"    status={r.status_code}, ok={r.json().get('ok')}")
if r.status_code != 200:
    print(f"    response: {r.text[:500]}")
else:
    print(f"    message_id={r.json()['result']['message_id']}")

print("\nDone. Check @trading_v4 for 3 messages.")
