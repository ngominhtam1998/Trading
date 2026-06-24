"""Investigate AWEUSDT: was it orphan or new entry? Check Telegram delivery."""
import paramiko
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HOST = "74.113.235.40"
USER = "root"
PWD = "Vintasenko01@@"

def run(ssh, cmd, timeout=60):
    print(f"\n$ {cmd[:150]}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    print(out, end="")
    return out

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PWD, timeout=15)
print("Connected!")

# 1. Timeline: what happened with AWEUSDT on LV4
print("\n" + "="*80)
print("=== LV4: Complete AWEUSDT timeline ===")
run(ssh, "grep -i aweusdt /opt/trading/production/live/bot_testnet_lv4.log 2>&1")

# 2. What positions were on exchange at startup?
print("\n" + "="*80)
print("=== LV4: All 'Exchange positions' lines ===")
run(ssh, "grep 'Exchange positions' /opt/trading/production/live/bot_testnet_lv4.log 2>&1")

# 3. What was the 303 chars message? Check around 04:15
print("\n" + "="*80)
print("=== LV4: Full log around 04:15 (AWE entry) ===")
run(ssh, "grep -A2 -B2 '04:15' /opt/trading/production/live/bot_testnet_lv4.log 2>&1 | head -30")

# 4. Check: was AWEUSDT on exchange BEFORE VPS bot started?
# (i.e. was it from laptop?)
print("\n" + "="*80)
print("=== Check: AWEUSDT position history ===")
run(ssh, """cd /opt/trading/production && /opt/trading/venv/bin/python3 << 'PYEOF'
import os, sqlite3
from pathlib import Path
for line in Path('live/.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())

# Check DB for AWEUSDT
db_path = 'live/state_testnet_lv4.db'
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    # Position
    rows = cur.execute("SELECT * FROM positions WHERE symbol='AWEUSDT'").fetchall()
    print("DB positions for AWEUSDT:")
    for r in rows:
        d = dict(r)
        print(f"  dir={d['direction']} entry={d['entry_price']} qty={d['qty']} "
              f"adopted={d.get('adopted',0)} entry_time={d['entry_time']} "
              f"sl={d['sl_price']} tp={d['tp_price']}")
    # Events
    events = cur.execute("SELECT * FROM events WHERE symbol='AWEUSDT' ORDER BY ts DESC LIMIT 10").fetchall()
    print(f"\nDB events for AWEUSDT ({len(events)}):")
    for e in events:
        print(f"  {dict(e)}")
    conn.close()
else:
    print(f"DB not found: {db_path}")
PYEOF
""")

# 5. Check Telegram: get recent messages from @trading_v4 channel
print("\n" + "="*80)
print("=== Telegram: get recent messages from @trading_v4 ===")
run(ssh, """cd /opt/trading/production && /opt/trading/venv/bin/python3 << 'PYEOF'
import os, requests, json
from pathlib import Path
for line in Path('live/.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())

token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
chat_id = '@trading_v4'

# getUpdates doesn't work for channels. Try sendMessage with disable_notification to check
# Instead, let's check the bot's sent messages via getUpdates (might not work for channels)
# Better: just send a test message and verify

# Actually, let's use getChat to verify the channel exists
r = requests.get(f"https://api.telegram.org/bot{token}/getChat", 
                 params={"chat_id": chat_id}, verify=False, timeout=10)
print(f"getChat @trading_v4: {r.status_code}")
if r.status_code == 200:
    data = r.json()
    print(f"  ok={data.get('ok')} title={data.get('result',{}).get('title')}")

# Try to get recent messages via forwardMessage trick (won't work)
# Instead, let's just verify the AWE notification was sent by checking the log timestamp

# Send a test message to verify bot can send
r2 = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                   data={"chat_id": chat_id, "text": "TEST: verifying AWEUSDT notification delivery",
                         "parse_mode": "HTML"},
                   verify=False, timeout=10)
print(f"\nTest send: {r2.status_code}")
if r2.status_code == 200:
    print(f"  ok={r2.json().get('ok')} message_id={r2.json().get('result',{}).get('message_id')}")
else:
    print(f"  error: {r2.text[:200]}")
PYEOF
""")

ssh.close()
print("\n=== DONE ===")
