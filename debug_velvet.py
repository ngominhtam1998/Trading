"""Check VPS logs for VELVETUSDT — why no new notifications after initial 3?"""
import paramiko
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HOST = "74.113.235.40"
USER = "root"
PWD = "Vintasenko01@@"

def run(ssh, cmd, timeout=60):
    print(f"\n$ {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    print(out, end="")
    return out

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PWD, timeout=15)
print("Connected!")

# 1. Full log LV4 — search for VELVET
print("\n=== LV4: All VELVET mentions ===")
run(ssh, "grep -i velvet /opt/trading/production/live/bot_testnet_lv4.log 2>&1 | tail -30")

print("\n=== LV4: All AWE mentions ===")
run(ssh, "grep -i aweusdt /opt/trading/production/live/bot_testnet_lv4.log 2>&1 | tail -20")

print("\n=== LV4: All AGT mentions ===")
run(ssh, "grep -i agtusdt /opt/trading/production/live/bot_testnet_lv4.log 2>&1 | tail -20")

# 2. Full log LV5
print("\n=== LV5: All VELVET mentions ===")
run(ssh, "grep -i velvet /opt/trading/production/live/bot_testnet_lv5.log 2>&1 | tail -30")

# 3. Full log LV6
print("\n=== LV6: All VELVET mentions ===")
run(ssh, "grep -i velvet /opt/trading/production/live/bot_testnet_lv6.log 2>&1 | tail -30")

# 4. All ENTER lines (entries)
print("\n=== LV4: All ENTER lines ===")
run(ssh, "grep 'ENTER' /opt/trading/production/live/bot_testnet_lv4.log 2>&1")
print("\n=== LV5: All ENTER lines ===")
run(ssh, "grep 'ENTER' /opt/trading/production/live/bot_testnet_lv5.log 2>&1")
print("\n=== LV6: All ENTER lines ===")
run(ssh, "grep 'ENTER' /opt/trading/production/live/bot_testnet_lv6.log 2>&1")

# 5. All EXIT/close lines
print("\n=== LV4: All exit/close lines ===")
run(ssh, "grep -iE 'close|exit|TP hit|SL hit|closed' /opt/trading/production/live/bot_testnet_lv4.log 2>&1 | tail -20")

# 6. Cycle summaries
print("\n=== LV4: All Cycle done lines ===")
run(ssh, "grep 'Cycle done' /opt/trading/production/live/bot_testnet_lv4.log 2>&1 | tail -10")

# 7. Check current positions on exchange
print("\n=== Current positions (via bot API) ===")
run(ssh, "cd /opt/trading/production && /opt/trading/venv/bin/python -c \""
      "import os; "
      "from pathlib import Path; "
      "[os.environ.__setitem__(k.strip(), v.strip()) for line in Path('live/.env').read_text().splitlines() if '=' in line and not line.startswith('#') for k, v in [line.split('=', 1)]]; "
      "os.environ['BOT_MODE']='testnet'; os.environ['BOT_STRATEGY']='lv4'; "
      "from live.binance_client import BinanceClient; "
      "c = BinanceClient(); "
      "eq, avail = c.equity_usdt(); "
      "print(f'LV4 equity={eq} avail={avail}'); "
      "for p in c.position_risk(): "
      "    if p['amt'] != 0: print(f'  {p[\"symbol\"]} {p[\"dir\"]} amt={p[\"amt\"]} entry={p[\"entry\"]}'); "
      "algo = c.open_algo_orders(''); "
      "print(f'  algo orders: {len(algo)}') "
      "\" 2>&1")

ssh.close()
