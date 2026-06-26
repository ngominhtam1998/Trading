"""SSH helper using paramiko — run commands on VPS without password prompt.
Usage: python ssh_vps.py "command1" "command2" ...
"""
import paramiko, sys

def run(cmds):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    # Try key auth first, fall back to password
    try:
        client.connect("74.113.235.40", username="root",
                       key_filename=__import__("os").path.expanduser("~/.ssh/id_rsa"),
                       timeout=15, allow_agent=False, look_for_keys=True)
    except Exception:
        client.connect("74.113.235.40", username="root", password="Vintasenko01@@",
                       timeout=15, allow_agent=False, look_for_keys=False)
    for cmd in cmds:
        print(f">>> {cmd}")
        stdin, stdout, stderr = client.exec_command(cmd, timeout=120)
        out = stdout.read().decode()
        err = stderr.read().decode()
        if out: sys.stdout.buffer.write(out.encode("utf-8", errors="replace"))
        if err: sys.stdout.buffer.write(b"[stderr] " + err.encode("utf-8", errors="replace"))
        print()
    client.close()

if __name__ == "__main__":
    cmds = sys.argv[1:] or ["echo 'no commands given'"]
    run(cmds)
