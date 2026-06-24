"""Deploy: pull latest code on VPS + restart bots."""
import paramiko
import sys, io, time
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

# 1. Pull latest code
print("\n=== Pull latest code ===")
run(ssh, "cd /opt/trading && git pull origin main 2>&1")

# 2. Verify the fix is there
print("\n=== Verify notify_orphan_adopted exists ===")
run(ssh, "grep -n 'notify_orphan_adopted' /opt/trading/production/live/telegram.py")
run(ssh, "grep -n 'notify_orphan_adopted' /opt/trading/production/live/bot.py")

# 3. Restart bots
print("\n=== Restarting 3 bots ===")
run(ssh, "systemctl restart trading-bot-lv4 trading-bot-lv5 trading-bot-lv6 2>&1")

# 4. Wait for boot
print("\nWaiting 20s for bots to boot...")
time.sleep(20)

# 5. Check status
print("\n=== Status ===")
run(ssh, "systemctl is-active trading-bot-lv4 trading-bot-lv5 trading-bot-lv6")

# 6. Check logs for orphan notifications
print("\n=== LV4 log (last 15 lines) ===")
run(ssh, "tail -15 /opt/trading/production/live/bot_testnet_lv4.log 2>&1")
print("\n=== LV5 log (last 15 lines) ===")
run(ssh, "tail -15 /opt/trading/production/live/bot_testnet_lv5.log 2>&1")
print("\n=== LV6 log (last 15 lines) ===")
run(ssh, "tail -15 /opt/trading/production/live/bot_testnet_lv6.log 2>&1")

# 7. Check Telegram delivered
print("\n=== Telegram delivered (all 3) ===")
for level in ["lv4", "lv5", "lv6"]:
    run(ssh, f"grep 'Telegram delivered' /opt/trading/production/live/bot_testnet_{level}.log 2>&1 | tail -5")

ssh.close()
print("\n=== DONE ===")
