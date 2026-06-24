"""Stop all 3 bots + close all positions + cancel all orders on testnet."""
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

# 1. Stop all 3 bots
print("\n=== Stopping all 3 bots ===")
run(ssh, "systemctl stop trading-bot-lv4 trading-bot-lv5 trading-bot-lv6 2>&1")
run(ssh, "systemctl status trading-bot-lv4 trading-bot-lv5 trading-bot-lv6 --no-pager 2>&1 | grep -E 'Active:|●'")

# 2. Close all positions + cancel all orders via cleanup script
print("\n=== Closing all positions + orders ===")
CLOSE_SCRIPT = '''
import os, sys, time, json
sys.path.insert(0, "/opt/trading/production")
sys.path.insert(0, "/opt/trading/production/live")
from pathlib import Path
for line in Path("/opt/trading/production/live/.env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from live.binance_client import BinanceClient, BinanceError

for level in ["lv4", "lv5", "lv6"]:
    print(f"\\n{'='*60}")
    print(f"=== {level.upper()} ===")
    os.environ["BOT_STRATEGY"] = level
    os.environ["BOT_MODE"] = "testnet"
    # Re-import config to pick up new env
    import importlib
    from live import config
    importlib.reload(config)
    try:
        client = BinanceClient()
    except Exception as e:
        print(f"  Client init failed: {e}")
        continue

    # Get positions
    positions = client.position_risk()
    active = [p for p in positions if abs(float(p.get("positionAmt", 0))) > 0]
    print(f"  Active positions: {len(active)}")
    for p in active:
        sym = p["symbol"]
        amt = float(p["positionAmt"])
        direction = "LONG" if amt > 0 else "SHORT"
        qty = abs(amt)
        print(f"  {sym} {direction} qty={qty}")

        # Cancel all algo orders (SL/TP) first
        try:
            algo_orders = client.open_algo_orders(sym)
            for o in algo_orders:
                try:
                    client.cancel_algo_order(sym, algo_id=o.get("algoId"))
                    print(f"    cancelled algo {o.get('orderType')} {o.get('algoId')}")
                except Exception as e:
                    print(f"    cancel algo failed: {e}")
        except Exception as e:
            print(f"    list algo failed: {e}")

        # Cancel regular orders
        try:
            reg_orders = client.open_orders(sym)
            for o in reg_orders:
                try:
                    client.cancel_order(sym, order_id=o.get("orderId"))
                    print(f"    cancelled order {o.get('orderId')}")
                except Exception as e:
                    print(f"    cancel order failed: {e}")
        except Exception as e:
            print(f"    list orders failed: {e}")

        # Market close
        close_side = "SELL" if direction == "LONG" else "BUY"
        try:
            resp = client.new_market_order(sym, close_side, qty, reduce_only=True)
            print(f"    CLOSED: {resp.get('status')} avgPrice={resp.get('avgPrice')}")
        except BinanceError as e:
            print(f"    close FAILED: {e}")
        time.sleep(0.3)

    # Verify
    time.sleep(1)
    positions2 = client.position_risk()
    active2 = [p for p in positions2 if abs(float(p.get("positionAmt", 0))) > 0]
    print(f"  After cleanup: {len(active2)} active positions")

    # Check equity
    try:
        equity, avail = client.equity_usdt()
        print(f"  Equity: ${equity:.2f}  Available: ${avail:.2f}")
    except Exception as e:
        print(f"  Equity check failed: {e}")

print("\\n=== DONE ===")
'''

sftp = ssh.open_sftp()
with sftp.open("/tmp/close_all.py", "w") as f:
    f.write(CLOSE_SCRIPT)
sftp.close()

run(ssh, "cd /opt/trading/production && /opt/trading/venv/bin/python3 /tmp/close_all.py 2>&1", timeout=120)

ssh.close()
print("\n=== ALL DONE ===")
