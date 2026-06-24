"""EMERGENCY STOP — stop all 3 bots + close all positions + cancel all orders.

Usage:
  python emergency_stop.py

This script:
  1. Stops systemd services trading-bot-lv4/5/6
  2. Cancels all open orders (algo + regular) for all symbols
  3. Market-closes all open positions
  4. Prints final equity for each account

Use when market crashes, bot misbehaves, or you need instant risk-off.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "production"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "production", "live"))


def _run_for_level(level):
    print(f"\n{'='*70}")
    print(f"=== {level.upper()} EMERGENCY CLOSE ===")
    os.environ["BOT_STRATEGY"] = level
    os.environ["BOT_MODE"] = "testnet"

    # Force reload config for each level
    import importlib
    from live import config
    importlib.reload(config)

    from live.binance_client import BinanceClient, BinanceError

    try:
        client = BinanceClient()
    except Exception as e:
        print(f"  Client init failed: {e}")
        return

    # 1. Cancel ALL open orders for ALL symbols
    try:
        all_algo = client.open_algo_orders()
        for o in all_algo:
            try:
                client.cancel_algo_order(o.get("symbol"), algo_id=o.get("algoId"))
                print(f"  cancelled algo {o.get('symbol')} {o.get('orderType')}")
            except Exception as e:
                print(f"  cancel algo err {o.get('symbol')}: {e}")
    except Exception as e:
        print(f"  list algo orders failed: {e}")

    try:
        all_reg = client.open_orders()
        for o in all_reg:
            try:
                client.cancel_order(o.get("symbol"), order_id=o.get("orderId"))
                print(f"  cancelled order {o.get('symbol')} {o.get('orderId')}")
            except Exception as e:
                print(f"  cancel order err {o.get('symbol')}: {e}")
    except Exception as e:
        print(f"  list regular orders failed: {e}")

    # 2. Market-close all positions
    positions = client.position_risk()
    active = [p for p in positions if abs(p["amt"]) > 0]
    if not active:
        print("  No active positions.")
    for p in active:
        sym = p["symbol"]
        amt = p["amt"]
        direction = "LONG" if amt > 0 else "SHORT"
        close_side = "SELL" if direction == "LONG" else "BUY"
        qty = abs(amt)
        try:
            resp = client.new_market_order(sym, close_side, qty, reduce_only=True)
            print(f"  CLOSED {sym} {direction} qty={qty} avg={resp.get('avgPrice')}")
        except BinanceError as e:
            print(f"  CLOSE FAILED {sym}: {e}")
        time.sleep(0.2)

    # 3. Print equity
    time.sleep(1)
    try:
        equity, avail = client.equity_usdt()
        print(f"  Final equity: ${equity:.2f}  available: ${avail:.2f}")
    except Exception as e:
        print(f"  Equity check failed: {e}")


def main():
    import paramiko
    HOST = "74.113.235.40"
    USER = "root"
    PWD = "Vintasenko01@@"

    print("Connecting to VPS...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PWD, timeout=15)

    print("\nSTOPPING bots...")
    ssh.exec_command("systemctl stop trading-bot-lv4 trading-bot-lv5 trading-bot-lv6")
    time.sleep(2)
    stdin, stdout, stderr = ssh.exec_command(
        "systemctl is-active trading-bot-lv4 trading-bot-lv5 trading-bot-lv6")
    print("Bot status:", stdout.read().decode().strip())

    print("\nCLOSING all positions/orders...")
    script = open(__file__, "r", encoding="utf-8").read()
    sftp = ssh.open_sftp()
    with sftp.open("/tmp/emergency_stop.py", "w") as f:
        f.write(script)
    sftp.close()

    stdin, stdout, stderr = ssh.exec_command(
        "cd /opt/trading/production && /opt/trading/venv/bin/python3 /tmp/emergency_stop.py --local 2>&1",
        timeout=300)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    print(out)
    if err:
        print("STDERR:", err)

    ssh.close()
    print("\nEMERGENCY STOP COMPLETE")


def local_run():
    """Run directly on the VPS (invoked via --local flag)."""
    for level in ["lv4", "lv5", "lv6"]:
        _run_for_level(level)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--local":
        local_run()
    else:
        main()
