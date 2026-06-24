"""Verify VELVET is being managed correctly — check SL/TP + BE/trail status."""
import paramiko
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HOST = "74.113.235.40"
USER = "root"
PWD = "Vintasenko01@@"

def run(ssh, cmd, timeout=60):
    print(f"\n$ {cmd[:100]}...")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    print(out, end="")
    return out

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PWD, timeout=15)
print("Connected!")

# Check VELVET management in logs
print("\n=== LV4: VELVET management lines ===")
run(ssh, "grep -i velvet /opt/trading/production/live/bot_testnet_lv4.log 2>&1")

# Check all manage/update_stops lines
print("\n=== LV4: All _update_stops/manage lines ===")
run(ssh, "grep -iE 'manage|update_stops|BE|trail|breakeven|max.hold' /opt/trading/production/live/bot_testnet_lv4.log 2>&1 | head -20")

# Check VELVET algo orders via API
print("\n=== Check VELVETUSDT algo orders (LV4) ===")
run(ssh, """cd /opt/trading/production && /opt/trading/venv/bin/python3 << 'PYEOF'
import os
from pathlib import Path
for line in Path('live/.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())
os.environ['BOT_MODE'] = 'testnet'
os.environ['BOT_STRATEGY'] = 'lv4'
from live.binance_client import BinanceClient
c = BinanceClient()
# VELVET position
for p in c.position_risk():
    if p['symbol'] == 'VELVETUSDT' and p['amt'] != 0:
        print(f"Position: {p['dir']} amt={p['amt']} entry={p['entry']}")
# VELVET algo orders
algo = c.open_algo_orders('VELVETUSDT')
print(f"Algo orders: {len(algo)}")
for o in algo:
    print(f"  type={o['type']} trigger={o.get('triggerPrice')} side={o.get('side')} closePos={o.get('closePosition')}")
# Mark price
mp = c.mark_price('VELVETUSDT')
print(f"Mark price: {mp}")
PYEOF
""")

# Check DB state for VELVET
print("\n=== Check VELVET in DB (LV4) ===")
run(ssh, """cd /opt/trading/production && /opt/trading/venv/bin/python3 << 'PYEOF'
import os, sqlite3
from pathlib import Path
for line in Path('live/.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())
db_path = 'live/state_testnet_lv4.db'
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    # Check positions table
    rows = cur.execute("SELECT * FROM positions WHERE symbol='VELVETUSDT'").fetchall()
    for r in rows:
        print(f"DB position: {dict(r)}")
    # Check events
    events = cur.execute("SELECT * FROM events WHERE symbol='VELVETUSDT' ORDER BY ts DESC LIMIT 5").fetchall()
    for e in events:
        print(f"DB event: {dict(e)}")
    conn.close()
else:
    print(f"DB not found: {db_path}")
PYEOF
""")

ssh.close()
