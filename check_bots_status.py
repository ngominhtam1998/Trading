"""Check trading bot status + PnL via VPS API.

Usage:
    python check_bots_status.py
"""
import paramiko
import os
import sys

HOST = "74.113.235.40"
USER = "root"
PWD = "Vintasenko01@@"

REMOTE_SCRIPT = "/tmp/_check_bots_status.py"
REMOTE_OUT = "/tmp/_check_bots_status.out"

REMOTE_SCRIPT_CONTENT = '''"""Remote API checker for trading bots."""
import os, urllib.parse, hmac, hashlib, time
import requests
from datetime import datetime, timezone

BASE = 'https://testnet.binancefuture.com'
OUT_PATH = '/tmp/_check_bots_status.out'

def log(s):
    with open(OUT_PATH, 'a', encoding='utf-8') as f:
        f.write(s + '\\n')

def load_env(path='/opt/trading/production/live/.env'):
    env = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            env[k] = v.strip().strip('"').strip("'")
    return env

env = load_env()

def api_call(key, sec, method, endpoint, params=None):
    params = params or {}
    params['timestamp'] = int(time.time() * 1000)
    params['recvWindow'] = 10000
    qs = urllib.parse.urlencode(params)
    sig = hmac.new(sec.encode(), qs.encode(), hashlib.sha256).hexdigest()
    headers = {'X-MBX-APIKEY': key}
    url = f"{BASE}{endpoint}?{qs}&signature={sig}"
    r = requests.request(method, url, headers=headers, timeout=15)
    r.raise_for_status()
    return r.json()

with open(OUT_PATH, 'w', encoding='utf-8') as f:
    f.write('')

now = datetime.now(timezone.utc)
today_start_ms = int(datetime(now.year, now.month, now.day, 0, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
now_ms = int(now.timestamp() * 1000)

total_wallet = 0.0
total_upnl = 0.0
total_equity = 0.0
total_realized_today = 0.0
total_commission_today = 0.0
total_funding_today = 0.0
total_closed_today = 0

total_initial = 5000 * 3  # 3 testnet accounts; only opus-v4 is actively managed

log(f"Check time: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}")

# Systemd status (only opus-v4 is an active bot; lv5/lv6 services are retired)
import subprocess
for svc in ['trading-bot-opus-v4']:
    try:
        res = subprocess.run(['systemctl', 'is-active', svc], capture_output=True, text=True, timeout=5)
        status = res.stdout.strip() or 'unknown'
    except Exception as e:
        status = f'error: {e}'
    log(f"  {svc}: {status}")

BOT_LABELS = {'lv4': 'opus', 'lv5': 'lv5 (retired, leftover)', 'lv6': 'lv6 (retired, leftover)'}
for level in ['lv4', 'lv5', 'lv6']:
    suffix = level.upper()
    label = BOT_LABELS[level]
    k = env.get(f'BINANCE_TESTNET_KEY_{suffix}', '') or env.get('BINANCE_TESTNET_KEY', '')
    s = env.get(f'BINANCE_TESTNET_SECRET_{suffix}', '') or env.get('BINANCE_TESTNET_SECRET', '')
    if not k or not s:
        log(f"\\n[{label}] MISSING KEYS")
        continue

    log(f"\\n{'='*70}")
    log(f"[{label}]")
    try:
        bal = api_call(k, s, 'GET', '/fapi/v3/balance')
        usdt = next((x for x in bal if x['asset'] == 'USDT'), {})
        wallet = float(usdt.get('balance', 0) or 0)
        available = float(usdt.get('availableBalance', 0) or 0)

        pos = api_call(k, s, 'GET', '/fapi/v3/positionRisk')
        active = [p for p in pos if abs(float(p.get('positionAmt', 0))) > 0]
        bot_upnl = 0.0
        if not active:
            log(f"  Positions: none")
        else:
            log(f"  Positions ({len(active)}):")
            for p in active:
                amt = float(p['positionAmt'])
                upnl = float(p['unRealizedProfit'])
                bot_upnl += upnl
                log(f"    {p['symbol']:12s} {'SHORT' if amt < 0 else 'LONG':5s} amt={abs(amt):.2f} entry={p['entryPrice']} mark={p['markPrice']} upnl={upnl:+.2f} liq={p['liquidationPrice']}")
        bot_equity = wallet + bot_upnl
        bot_pnl = bot_equity - 5000
        total_wallet += wallet
        total_upnl += bot_upnl
        total_equity += bot_equity
        log(f"  Wallet balance: {wallet:.2f} USDT")
        log(f"  Available:      {available:.2f} USDT")
        log(f"  Unrealized PnL: {bot_upnl:+.2f} USDT")
        log(f"  Total equity:   {bot_equity:.2f} USDT")
        log(f"  PnL vs 5k init: {bot_pnl:+.2f} USDT")

        orders = api_call(k, s, 'GET', '/fapi/v1/openAlgoOrders')
        if not orders:
            log(f"  Open orders: none")
        else:
            log(f"  Open orders ({len(orders)}):")
            for o in orders:
                log(f"    {o['symbol']:12s} {o.get('orderType') or o.get('type')} side={o.get('side')} trigger={o.get('triggerPrice')}")

        income = api_call(k, s, 'GET', '/fapi/v1/income', {
            'startTime': now_ms - 30 * 24 * 3600 * 1000,
            'endTime': now_ms,
            'limit': 1000,
        })
        today_income = [x for x in income if int(x.get('time', 0)) >= today_start_ms]
        by_type = {}
        for item in today_income:
            t = item.get('incomeType', 'UNKNOWN')
            by_type[t] = by_type.get(t, 0) + float(item.get('income', 0))
        realized = by_type.get('REALIZED_PNL', 0)
        commission = by_type.get('COMMISSION', 0)
        funding = by_type.get('FUNDING_FEE', 0)
        total_realized_today += realized
        total_commission_today += commission
        total_funding_today += funding
        log(f"\\n  Today:")
        log(f"    Realized PnL: {realized:+.2f} USDT")
        log(f"    Commission:   {commission:+.2f} USDT")
        log(f"    Funding:      {funding:+.2f} USDT")
        closed = [x for x in today_income if x.get('incomeType') == 'REALIZED_PNL']
        sl = sum(1 for c in closed if float(c['income']) < 0)
        tp = sum(1 for c in closed if float(c['income']) > 0)
        total_closed_today += len(closed)
        log(f"    Closed trades: {len(closed)} (SL={sl}, TP={tp})")

    except Exception as e:
        log(f"  ERROR: {e}")
        import traceback
        log(traceback.format_exc())

log("\\n" + "="*70)
log("TOTAL (3 accounts; only opus-v4 actively managed)")
log(f"  Wallet balance:  {total_wallet:.2f} USDT")
log(f"  Unrealized PnL:  {total_upnl:+.2f} USDT")
log(f"  Total equity:    {total_equity:.2f} USDT")
log(f"  PnL vs 15k init: {total_equity - total_initial:+.2f} USDT")
log(f"\\n  Today realized:  {total_realized_today:+.2f} USDT")
log(f"  Today commission: {total_commission_today:+.2f} USDT")
log(f"  Today funding:    {total_funding_today:+.2f} USDT")
log(f"  Today closed trades: {total_closed_today}")
log("\\nDone.")
'''

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PWD, timeout=15)
sftp = ssh.open_sftp()
with open("__remote_check.py", "w", encoding="utf-8") as f:
    f.write(REMOTE_SCRIPT_CONTENT)
sftp.put("__remote_check.py", REMOTE_SCRIPT)
sftp.close()
ssh.exec_command(f"rm -f {REMOTE_OUT}")
stdin, stdout, stderr = ssh.exec_command(f"cd /opt/trading && /opt/trading/venv/bin/python3 {REMOTE_SCRIPT}", timeout=180)
code = stdout.channel.recv_exit_status()
stdin, stdout, stderr = ssh.exec_command(f"cat {REMOTE_OUT}")
out = stdout.read().decode("utf-8", errors="replace")
ssh.exec_command(f"rm -f {REMOTE_SCRIPT} {REMOTE_OUT}")
ssh.close()

os.remove("__remote_check.py")
print(out)
if code != 0:
    print(f"Exit code: {code}")
