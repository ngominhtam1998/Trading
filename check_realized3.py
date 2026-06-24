"""Check DB schema + closed positions on VPS."""
import paramiko
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HOST = "74.113.235.40"
USER = "root"
PWD = "Vintasenko01@@"

SCRIPT = '''
import sqlite3, json
for level in ["lv4", "lv5", "lv6"]:
    print(f"\\n{'='*70}")
    print(f"=== {level.upper()} ===")
    conn = sqlite3.connect(f"live/state_testnet_{level}.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    tables = cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    table_names = [t[0] for t in tables]
    print(f"Tables: {table_names}")
    for name in table_names:
        count = cur.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        print(f"  {name}: {count} rows")
    # exit events
    try:
        rows = cur.execute("SELECT ts, kind, symbol, detail FROM events WHERE kind IN ('exit','market_close','recover_closed') ORDER BY ts DESC LIMIT 30").fetchall()
        print(f"\\nExit/close events ({len(rows)}):")
        total_realized = 0
        for r in rows:
            d = dict(r)
            try:
                detail = json.loads(d.get("detail","{}")) if d.get("detail") else {}
            except:
                detail = {}
            pnl = detail.get("pnl")
            if pnl is not None:
                total_realized += pnl
            print(f"  {d['kind']:20s} {d['symbol']:16s} pnl={pnl} detail={d.get('detail','')[:80]}")
        print(f"\\nSum realized (from events): {total_realized:.2f}")
    except Exception as e:
        print(f"events query error: {e}")
    conn.close()
'''

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PWD, timeout=15)

# Write script to VPS
sftp = ssh.open_sftp()
with sftp.open("/tmp/check_db.py", "w") as f:
    f.write(SCRIPT)
sftp.close()

stdin, stdout, stderr = ssh.exec_command("cd /opt/trading/production && /opt/trading/venv/bin/python3 /tmp/check_db.py 2>&1", timeout=60)
print(stdout.read().decode("utf-8", errors="replace"))
err = stderr.read().decode("utf-8", errors="replace")
if err:
    print("STDERR:", err)

ssh.close()
