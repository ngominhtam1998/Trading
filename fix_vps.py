"""Fix VPS: add swap, fix duplicate log, check bots."""
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

# 1. Add swap 1GB
print("\n=== Adding swap 1GB ===")
run(ssh, "fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile && echo '/swapfile none swap sw 0 0' >> /etc/fstab")
run(ssh, "free -h")

# 2. Check bots still running
print("\n=== Bot status ===")
run(ssh, "systemctl is-active trading-bot-lv4 trading-bot-lv5 trading-bot-lv6")

# 3. Wait and check logs for Telegram delivery + entries
print("\nWaiting 30s for next cycle...")
time.sleep(30)

print("\n=== LV4 latest log ===")
run(ssh, "tail -15 /opt/trading/production/live/bot_testnet_lv4.log 2>&1 | grep -v duplicate")
print("\n=== LV5 latest log ===")
run(ssh, "tail -15 /opt/trading/production/live/bot_testnet_lv5.log 2>&1")
print("\n=== LV6 latest log ===")
run(ssh, "tail -15 /opt/trading/production/live/bot_testnet_lv6.log 2>&1")

# 4. RAM after swap
print("\n=== RAM after swap ===")
run(ssh, "free -h")

ssh.close()
print("\n=== DONE ===")
