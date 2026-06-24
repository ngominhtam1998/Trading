"""Check DB for AWEUSDT + verify Telegram delivery."""
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

# DB check
print("=== DB: AWEUSDT in LV4 ===")
run(ssh, """cd /opt/trading/production && /opt/trading/venv/bin/python3 -c "
import os, sqlite3
from pathlib import Path
for line in Path('live/.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())
conn = sqlite3.connect('live/state_testnet_lv4.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()
rows = cur.execute('SELECT * FROM positions WHERE symbol=\\"AWEUSDT\\"').fetchall()
for r in rows:
    d = dict(r)
    print(f'adopted={d.get(\\"adopted\\",0)} dir={d[\\"direction\\"]} entry={d[\\"entry_price\\"]} entry_time={d[\\"entry_time\\"]}')
events = cur.execute('SELECT * FROM events WHERE symbol=\\"AWEUSDT\\" ORDER BY ts DESC').fetchall()
print(f'Events ({len(events)}):')
for e in events:
    print(f'  {dict(e)}')
conn.close()
" 2>&1""")

# Telegram: send test message to verify bot works
print("\n=== Telegram: verify bot can send to @trading_v4 ===")
run(ssh, """cd /opt/trading/production && /opt/trading/venv/bin/python3 -c "
import os, requests
from pathlib import Path
for line in Path('live/.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())
token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
# Send test
r = requests.post(f'https://api.telegram.org/bot{token}/sendMessage',
    data={'chat_id': '@trading_v4', 'text': 'TEST: AWEUSDT notification verification', 'parse_mode': 'HTML'},
    verify=False, timeout=10)
print(f'Send status: {r.status_code}')
print(f'Response: {r.json()}')
" 2>&1""")

ssh.close()
