"""Setup trading bot on Kamatera VPS via SSH."""
import paramiko
import sys

HOST = "74.113.235.40"
USER = "root"
PWD = "Vintasenko01@@"

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
try:
    ssh.connect(HOST, username=USER, password=PWD, timeout=15)
    print("Connected!")
except Exception as e:
    print(f"Connect failed: {e}")
    sys.exit(1)

# Step 1: System info
run(ssh, "uname -a")
run(ssh, "cat /etc/os-release | head -3")
run(ssh, "python3 --version 2>/dev/null || echo 'no python3'")

# Step 2: Install packages
print("\n=== Installing packages ===")
run(ssh, "export DEBIAN_FRONTEND=noninteractive; apt update -y 2>&1 | tail -3", timeout=180)
run(ssh, "export DEBIAN_FRONTEND=noninteractive; apt install -y python3 python3-pip python3-venv git tmux nano curl 2>&1 | tail -5", timeout=300)
run(ssh, "python3 --version")

# Step 3: Clone repo
print("\n=== Cloning repo ===")
run(ssh, "mkdir -p /opt/trading")
run(ssh, "rm -rf /opt/trading/* /opt/trading/.git 2>/dev/null")
run(ssh, "cd /opt/trading && git clone https://github.com/ngominhtam1998/Trading.git . 2>&1 | tail -5", timeout=120)
run(ssh, "ls /opt/trading/production/live/ | head -20")

# Step 4: venv + packages
print("\n=== Setting up venv ===")
run(ssh, "python3 -m venv /opt/trading/venv", timeout=60)
run(ssh, "/opt/trading/venv/bin/pip install --quiet pandas requests 2>&1 | tail -3", timeout=300)
run(ssh, "/opt/trading/venv/bin/python -c 'import pandas, requests; print(\"deps OK\")'")

# Step 5: Check .env exists
run(ssh, "ls -la /opt/trading/production/live/.env* 2>/dev/null || echo 'no .env files'")

ssh.close()
print("\n=== DONE: VPS ready for .env + bot start ===")
