"""Check realized PnL history from DB on VPS."""
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
    print(f"=== {level.upper()}: Closed positions history ===")
    run(ssh, f"""cd /opt/trading/production && /opt/trading/venv/bin/python3 -c "
import sqlite3
conn = sqlite3.connect('live/state_testnet_{level}.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()
rows = cur.execute('SELECT * FROM closed_positions ORDER BY exit_time DESC').fetchall()
print(f'Closed positions: {{len(rows)}}')
total_pnl = 0
for r in rows:
    d = dict(r)
    total_pnl += d.get('pnl', 0) or 0
    print(f'  {{d.get(\\"symbol\\",\\\"?\\\")}} {{d.get(\\"direction\\",\\\"?\\\")}} entry={{d.get(\\"entry_price\\",0)}} exit={{d.get(\\"exit_price\\",0)}} pnl={{d.get(\\"pnl\\",0):.2f}} reason={{d.get(\\"reason\\",\\\"?\\\")}}')
print(f'Total realized PnL: {{total_pnl:.2f}}')
conn.close()
" 2>&1""")

ssh.close()
