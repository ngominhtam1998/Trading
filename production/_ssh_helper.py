"""SSH helper using paramiko — run commands on VPS with password auth."""
import sys, paramiko

HOST = "74.113.235.40"
USER = "root"
PASS = "Vintasenko01@@"

def run(cmd, timeout=30):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(HOST, username=USER, password=PASS, timeout=15)
        stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        if out: print(out, end="")
        if err: print(err, end="", file=sys.stderr)
        return code
    finally:
        client.close()

def put(local_path, remote_path):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(HOST, username=USER, password=PASS, timeout=15)
        sftp = client.open_sftp()
        sftp.put(local_path, remote_path)
        sftp.close()
        print(f"Uploaded {local_path} -> {remote_path}")
    finally:
        client.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python _ssh_helper.py 'command'  |  python _ssh_helper.py PUT local remote")
        sys.exit(1)
    if sys.argv[1] == "PUT":
        put(sys.argv[2], sys.argv[3])
    else:
        sys.exit(run(sys.argv[1]))
