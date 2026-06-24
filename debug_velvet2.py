"""Check all Telegram notifications sent from VPS."""
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

# All Telegram delivered lines
for level in ["lv4", "lv5", "lv6"]:
    print(f"\n{'='*80}")
    print(f"=== {level.upper()}: All Telegram delivered ===")
    run(ssh, f"grep 'Telegram delivered' /opt/trading/production/live/bot_testnet_{level}.log 2>&1")

# All notifications (notify_ calls)
for level in ["lv4", "lv5", "lv6"]:
    print(f"\n{'='*80}")
    print(f"=== {level.upper()}: All notify/send lines ===")
    run(ssh, f"grep -iE 'notify|send|ENTER|ORPHAN|adopt|exit|close|SL.*hit|TP.*hit' /opt/trading/production/live/bot_testnet_{level}.log 2>&1 | head -40")

# Full log LV4 (to see complete picture)
print(f"\n{'='*80}")
print(f"=== LV4: FULL LOG (last 80 lines) ===")
run(ssh, "tail -80 /opt/trading/production/live/bot_testnet_lv4.log 2>&1")

# Check if VELVET still has algo orders
print(f"\n{'='*80}")
print(f"=== Check VELVETUSDT algo orders on each account ===")
for level in ["lv4", "lv5", "lv6"]:
    print(f"\n--- {level.upper()} ---")
    run(ssh, f"cd /opt/trading/production && /opt/trading/venv/bin/python3 -c \""
          f"import os; "
          f"from pathlib import Path; "
          f"for line in Path('live/.env').read_text().splitlines():"
          f"    if '=' in line and not line.startswith('#'):"
          f"        k,v=line.split('=',1); os.environ.setdefault(k.strip(),v.strip()); "
          f"os.environ['BOT_MODE']='testnet'; os.environ['BOT_STRATEGY']='{level}'; "
          f"from live.binance_client import BinanceClient; "
          f"c = BinanceClient(); "
          f"algo = c.open_algo_orders('VELVETUSDT'); "
          f"print(f'VELVETUSDT algo orders: {{len(algo)}}'); "
          f"[print(f'  type={{o[\"type\"]}} trigger={{o.get(\"triggerPrice\")}} side={{o.get(\"side\")}}') for o in algo]; "
          f"pos = [p for p in c.position_risk() if p['symbol']=='VELVETUSDT' and p['amt']!=0]; "
          f"print(f'VELVETUSDT position: {{pos}}') "
          f"\" 2>&1")

ssh.close()
