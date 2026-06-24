"""Start bots on VPS and verify."""
import paramiko
import sys

HOST = "74.113.235.40"
USER = "root"
PWD = "Vintasenko01@@"

def run(ssh, cmd, timeout=60):
    print(f"\n$ {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout, get_pty=True)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    exit_code = stdout.channel.recv_exit_status()
    # Replace problematic chars
    out = out.replace("\u2192", "->").replace("\u2026", "...")
    print(out, end="")
    if err.strip():
        err = err.replace("\u2192", "->").replace("\u2026", "...")
        print(f"[stderr] {err}", end="")
    print(f"[exit={exit_code}]")
    return exit_code, out, err

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
print(f"Connecting to {USER}@{HOST}...")
ssh.connect(HOST, username=USER, password=PWD, timeout=15)
print("Connected!")

# Enable
run(ssh, "systemctl enable trading-bot-lv4 trading-bot-lv5 trading-bot-lv6 2>&1")

# Start
print("\n=== Starting 3 bots ===")
run(ssh, "systemctl start trading-bot-lv4 trading-bot-lv5 trading-bot-lv6 2>&1")

# Wait 10s for boot
import time
print("\nWaiting 15s for bots to boot...")
time.sleep(15)

# Status
print("\n=== Status ===")
run(ssh, "systemctl is-active trading-bot-lv4 trading-bot-lv5 trading-bot-lv6")
run(ssh, "systemctl status trading-bot-lv4 --no-pager -l 2>&1 | head -15")
run(ssh, "systemctl status trading-bot-lv5 --no-pager -l 2>&1 | head -15")
run(ssh, "systemctl status trading-bot-lv6 --no-pager -l 2>&1 | head -15")

# Check logs
print("\n=== Logs (last 20 lines each) ===")
run(ssh, "tail -20 /opt/trading/production/live/bot_testnet_lv4.log 2>&1")
run(ssh, "tail -20 /opt/trading/production/live/bot_testnet_lv5.log 2>&1")
run(ssh, "tail -20 /opt/trading/production/live/bot_testnet_lv6.log 2>&1")

# RAM
print("\n=== RAM ===")
run(ssh, "free -h")
run(ssh, "ps aux | grep live.bot | grep -v grep")

ssh.close()
print("\n=== DONE ===")
