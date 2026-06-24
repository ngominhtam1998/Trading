"""Upload .env to VPS and start bots."""
import paramiko
import sys

HOST = "74.113.235.40"
USER = "root"
PWD = "Vintasenko01@@"

# Read local .env
with open(r"D:\Tam\trading\production\live\.env", "r", encoding="utf-8") as f:
    env_content = f.read()

print(f"Local .env: {len(env_content)} bytes")

def run(ssh, cmd, timeout=120):
    print(f"\n$ {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout, get_pty=True)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    exit_code = stdout.channel.recv_exit_status()
    print(out, end="")
    if err.strip():
        print(f"[stderr] {err}", end="")
    print(f"[exit={exit_code}]")
    return exit_code, out, err

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
print(f"Connecting to {USER}@{HOST}...")
ssh.connect(HOST, username=USER, password=PWD, timeout=15)
print("Connected!")

# Upload .env via SFTP
print("\n=== Uploading .env ===")
sftp = ssh.open_sftp()
with sftp.file("/opt/trading/production/live/.env", "w") as f:
    f.write(env_content)
sftp.chmod("/opt/trading/production/live/.env", 0o600)
sftp.close()
print(".env uploaded (600 perms)")

# Verify
run(ssh, "head -5 /opt/trading/production/live/.env")
run(ssh, "grep -c 'BINANCE_TESTNET_KEY_LV' /opt/trading/production/live/.env")
run(ssh, "grep 'TELEGRAM_CHAT_LV' /opt/trading/production/live/.env")

# Stop bots on local laptop first (avoid duplicate bots)
print("\n=== Note: Stop local bots before starting on VPS! ===")

# Create systemd services
print("\n=== Creating systemd services ===")

services = {
    "lv4": "trading-bot-lv4",
    "lv5": "trading-bot-lv5",
    "lv6": "trading-bot-lv6",
}

for level, name in services.items():
    service = f"""[Unit]
Description=Trading Bot {level.upper()}
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/trading/production
Environment=BOT_MODE=testnet
Environment=BOT_STRATEGY={level}
Environment=PYTHONIOENCODING=utf-8
ExecStart=/opt/trading/venv/bin/python3 -u -m live.bot
Restart=always
RestartSec=30
StandardOutput=append:/opt/trading/production/live/bot_testnet_{level}.log
StandardError=append:/opt/trading/production/live/bot_testnet_{level}.log

[Install]
WantedBy=multi-user.target
"""
    sftp = ssh.open_sftp()
    with sftp.file(f"/etc/systemd/system/{name}.service", "w") as f:
        f.write(service)
    sftp.close()
    print(f"  Created {name}.service")

# Enable + start
run(ssh, "systemctl daemon-reload")
run(ssh, "systemctl enable trading-bot-lv4 trading-bot-lv5 trading-bot-lv6")

# DON'T start yet - need to stop local bots first
print("\n=== Services created but NOT started yet ===")
print("=== Stop local bots on laptop first, then start on VPS ===")

# Check status
run(ssh, "systemctl is-enabled trading-bot-lv4 trading-bot-lv5 trading-bot-lv6")

ssh.close()
print("\n=== DONE: VPS ready, services created, waiting for local bot stop ===")
