"""Check DB schema + closed positions."""
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

for level in ["lv4", "lv5", "lv6"]:
    print(f"\n{'='*80}")
    print(f"=== {level.upper()} ===")
    run(ssh, f"""cd /opt/trading/production && /opt/trading/venv/bin/python3 << 'PYEOF'
import sqlite3
conn = sqlite3.connect('live/state_testnet_{level}.db')
cur = conn.cursor()
# List all tables
tables = cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print(f"Tables: {[t[0] for t in tables]}")
# Check events table for exit/close events
for t in tables:
    name = t[0]
    cols = cur.execute(f"PRAGMA table_info({name})").fetchall()
    print(f"  {name}: {[c[1] for c in cols]}")
    count = cur.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
    print(f"    rows: {count}")
# Show exit events
try:
    rows = cur.execute("SELECT * FROM events WHERE kind IN ('exit','market_close','recover_closed') ORDER BY ts DESC LIMIT 20").fetchall()
    print(f"\nExit events ({len(rows)}):")
    for r in rows:
        print(f"  {r}")
except Exception as e:
    print(f"events query: {e}")
conn.close()
PYEOF
""")

ssh.close()
