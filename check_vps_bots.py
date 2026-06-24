"""Check VPS bots status."""
import paramiko
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HOST = "74.113.235.40"
USER = "root"
PWD = "Vintasenko01@@"

def run(ssh, cmd, timeout=60):
    print(f"\n$ {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout, get_pty=True)
    out = stdout.read().decode("utf-8", errors="replace")
    exit_code = stdout.channel.recv_exit_status()
    print(out, end="")
    print(f"[exit={exit_code}]")
    return exit_code, out

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PWD, timeout=15)
print("Connected!\n")

run(ssh, "systemctl is-active trading-bot-lv4 trading-bot-lv5 trading-bot-lv6")
print("\n=== LV4 log ===")
run(ssh, "tail -30 /opt/trading/production/live/bot_testnet_lv4.log 2>&1")
print("\n=== LV5 log ===")
run(ssh, "tail -30 /opt/trading/production/live/bot_testnet_lv5.log 2>&1")
print("\n=== LV6 log ===")
run(ssh, "tail -30 /opt/trading/production/live/bot_testnet_lv6.log 2>&1")
print("\n=== RAM ===")
run(ssh, "free -h")
run(ssh, "ps aux | grep live.bot | grep -v grep")

ssh.close()
