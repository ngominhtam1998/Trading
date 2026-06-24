"""Deploy updated code to VPS + restart bots."""
import paramiko
import sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HOST = "74.113.235.40"
USER = "root"
PWD = "Vintasenko01@@"

def run(ssh, cmd, timeout=120):
    print(f"\n$ {cmd[:150]}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    if out: print(out, end="")
    if err: print("STDERR:", err, end="")
    return out

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PWD, timeout=15)
print("Connected!")

# 1. Pull latest code
print("\n=== Pull latest code ===")
run(ssh, "cd /opt/trading && git pull origin main 2>&1")

# 2. Verify new code has the fixes
print("\n=== Verify fixes present ===")
run(ssh, "grep -c '_is_in_cooldown' /opt/trading/production/live/bot.py")
run(ssh, "grep -c '_check_liquidation_warning' /opt/trading/production/live/bot.py")
run(ssh, "grep -c '_track_funding_cost' /opt/trading/production/live/bot.py")
run(ssh, "grep -c 'COOLDOWN_CONSEC_SL_THRESHOLD' /opt/trading/production/live/config.py")
run(ssh, "grep -c 'notify_cooldown' /opt/trading/production/live/telegram.py")
run(ssh, "grep -c 'notify_liq_warning' /opt/trading/production/live/telegram.py")
run(ssh, "grep -c '_verify_ssl' /opt/trading/production/live/binance_client.py")

# 3. Quick import test on VPS
print("\n=== Import test on VPS ===")
run(ssh, """cd /opt/trading/production && /opt/trading/venv/bin/python3 -c "
import os
os.environ['BOT_MODE']='testnet'
os.environ['BOT_STRATEGY']='lv4'
from live import config, bot, telegram, binance_client, strategy_adapter
print('All imports OK')
print(f'COOLDOWN_CONSEC_SL_THRESHOLD={config.COOLDOWN_CONSEC_SL_THRESHOLD}')
print(f'COOLDOWN_BARS={config.COOLDOWN_BARS}')
print(f'LIQ_WARN_THRESHOLD_PCT={config.LIQ_WARN_THRESHOLD_PCT}')
print(f'FUNDING_DAILY_WARN_PCT={config.FUNDING_DAILY_WARN_PCT}')
" 2>&1""")

# 4. Restart all 3 bots
print("\n=== Restart all 3 bots ===")
run(ssh, "systemctl restart trading-bot-lv4 trading-bot-lv5 trading-bot-lv6 2>&1")
time.sleep(3)
run(ssh, "systemctl status trading-bot-lv4 trading-bot-lv5 trading-bot-lv6 --no-pager 2>&1 | grep -E 'Active:|●'")

# 5. Check logs after 10 seconds
print("\n=== Wait 15s then check logs ===")
time.sleep(15)
for level in ["lv4", "lv5", "lv6"]:
    print(f"\n--- {level.upper()} last 15 lines ---")
    run(ssh, f"tail -15 /opt/trading/production/live/bot_testnet_{level}.log 2>&1")

ssh.close()
print("\n=== DEPLOY DONE ===")
