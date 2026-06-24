"""Check VPS: recent entries, Telegram notifications, current positions."""
import paramiko
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HOST = "74.113.235.40"
USER = "root"
PWD = "Vintasenko01@@"

def run(ssh, cmd, timeout=60):
    print(f"\n$ {cmd[:120]}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    print(out, end="")
    return out

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PWD, timeout=15)
print("Connected!")

# 1. All ENTER lines (new entries)
for level in ["lv4", "lv5", "lv6"]:
    print(f"\n{'='*80}")
    print(f"=== {level.upper()}: ALL ENTER lines ===")
    run(ssh, f"grep 'ENTER' /opt/trading/production/live/bot_testnet_{level}.log 2>&1")

# 2. All Telegram delivered
for level in ["lv4", "lv5", "lv6"]:
    print(f"\n{'='*80}")
    print(f"=== {level.upper()}: ALL Telegram delivered ===")
    run(ssh, f"grep 'Telegram delivered' /opt/trading/production/live/bot_testnet_{level}.log 2>&1")

# 3. All ADOPT ORPHAN lines
for level in ["lv4", "lv5", "lv6"]:
    print(f"\n{'='*80}")
    print(f"=== {level.upper()}: ALL orphan/adopt lines ===")
    run(ssh, f"grep -i 'orphan\\|adopt\\|ADOPT' /opt/trading/production/live/bot_testnet_{level}.log 2>&1")

# 4. Current cycle status
for level in ["lv4", "lv5", "lv6"]:
    print(f"\n{'='*80}")
    print(f"=== {level.upper()}: Last 20 lines ===")
    run(ssh, f"tail -20 /opt/trading/production/live/bot_testnet_{level}.log 2>&1")

# 5. All Cycle done lines (to see opportunities count)
for level in ["lv4", "lv5", "lv6"]:
    print(f"\n{'='*80}")
    print(f"=== {level.upper()}: All Cycle done lines ===")
    run(ssh, f"grep 'Cycle done' /opt/trading/production/live/bot_testnet_{level}.log 2>&1")

ssh.close()
print("\n=== DONE ===")
