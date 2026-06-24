"""Fix systemd services: use journal instead of append (avoid duplicate logs).
Then restart bots and push code update."""
import paramiko
import sys
import io
import time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HOST = "74.113.235.40"
USER = "root"
PWD = "Vintasenko01@@"

def run(ssh, cmd, timeout=120):
    print(f"\n$ {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    exit_code = stdout.channel.recv_exit_status()
    print(out, end="")
    if err.strip():
        print(f"[stderr] {err}", end="")
    print(f"[exit={exit_code}]")
    return exit_code, out

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PWD, timeout=15)
print("Connected!")

# Update services: use journal instead of append file
print("\n=== Updating systemd services (remove duplicate log) ===")
for level in ["lv4", "lv5", "lv6"]:
    service = f"""[Unit]
Description=Trading Bot {level.upper()}
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/trading/production
Environment=BOT_MODE=testnet
Environment=BOT_STRATEGY={level}
Environment=PYTHONIOENCODING=utf-8
ExecStart=/opt/trading/venv/bin/python3 -u -m live.bot
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
"""
    sftp = ssh.open_sftp()
    with sftp.file(f"/etc/systemd/system/trading-bot-{level}.service", "w") as f:
        f.write(service)
    sftp.close()
    print(f"  Updated trading-bot-{level}.service (journal only, no append)")

# Pull latest code (has -4028, -2027 in PERMANENT_CODES)
print("\n=== Pulling latest code ===")
run(ssh, "cd /opt/trading && git pull origin main 2>&1")

# Restart bots
print("\n=== Restarting bots ===")
run(ssh, "systemctl daemon-reload")
run(ssh, "systemctl restart trading-bot-lv4 trading-bot-lv5 trading-bot-lv6 2>&1")

# Wait
print("\nWaiting 20s...")
time.sleep(20)

# Check
run(ssh, "systemctl is-active trading-bot-lv4 trading-bot-lv5 trading-bot-lv6")
print("\n=== LV4 log (should be no duplicates) ===")
run(ssh, "tail -10 /opt/trading/production/live/bot_testnet_lv4.log 2>&1")
print("\n=== journalctl LV4 ===")
run(ssh, "journalctl -u trading-bot-lv4 -n 10 --no-pager 2>&1")

ssh.close()
print("\n=== DONE ===")
