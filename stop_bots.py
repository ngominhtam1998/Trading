"""Stop all 3 trading bots on VPS without closing positions.

Positions remain on the exchange protected by their existing SL/TP orders.
Use this only when you want to pause the bot logic (no new entries, no SL moves)
while keeping current trades alive.

Usage:
  python stop_bots.py
"""
import paramiko
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HOST = "74.113.235.40"
USER = "root"
PWD = "Vintasenko01@@"


def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PWD, timeout=15)
    print("Connected.")

    print("\nStopping bots (positions stay open with SL/TP on exchange)...")
    stdin, stdout, stderr = ssh.exec_command(
        "systemctl stop trading-bot-lv4 trading-bot-lv5 trading-bot-lv6 2>&1")
    print(stdout.read().decode("utf-8", errors="replace"), end="")
    err = stderr.read().decode("utf-8", errors="replace")
    if err:
        print("STDERR:", err, end="")

    stdin, stdout, stderr = ssh.exec_command(
        "systemctl is-active trading-bot-lv4 trading-bot-lv5 trading-bot-lv6 2>&1")
    print("\nStatus:")
    print(stdout.read().decode("utf-8", errors="replace"), end="")

    ssh.close()
    print("\nBots stopped. Positions remain open on exchange.")


if __name__ == "__main__":
    main()
