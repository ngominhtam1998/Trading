"""Check total traded volume across all 3 bots via Binance testnet API.

Uses /fapi/v1/userTrades to fetch all historical trades per symbol per bot,
sums up quoteQty (USDT value) of each fill.
"""
import paramiko
import os

HOST = "74.113.235.40"
USER = "root"
PWD = "Vintasenko01@@"

REMOTE_SCRIPT = "/tmp/_check_total_volume.py"
REMOTE_OUT = "/tmp/_check_total_volume.out"

REMOTE_SCRIPT_CONTENT = '''"""Fetch all user trades and sum total volume per bot."""
import os, urllib.parse, hmac, hashlib, time
import requests
from datetime import datetime, timezone

BASE = 'https://testnet.binancefuture.com'
OUT_PATH = '/tmp/_check_total_volume.out'

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
    r = requests.request(method, url, headers=headers, timeout=20)
    r.raise_for_status()
    return r.json()

with open(OUT_PATH, 'w', encoding='utf-8') as f:
    f.write('')

now = datetime.now(timezone.utc)
log(f"Total volume report: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}\\n")

grand_total_volume = 0.0
grand_total_trades = 0
grand_total_commission = 0.0
grand_total_realized = 0.0

for level in ['lv4', 'lv5', 'lv6']:
    suffix = level.upper()
    k = env.get(f'BINANCE_TESTNET_KEY_{suffix}', '') or env.get('BINANCE_TESTNET_KEY', '')
    s = env.get(f'BINANCE_TESTNET_SECRET_{suffix}', '') or env.get('BINANCE_TESTNET_SECRET', '')
    if not k or not s:
        log(f"[{level.upper()}] MISSING KEYS")
        continue

    log(f"{'='*70}")
    log(f"[{level.upper()}]")
    try:
        # Get all symbols that have had activity via positionRisk
        pos = api_call(k, s, 'GET', '/fapi/v3/positionRisk')
        symbols = set()
        for p in pos:
            if p.get('symbol'):
                symbols.add(p['symbol'])

        # Also fetch income to find symbols with realized PnL (might have closed positions)
        # income API doesn't return symbol for all types, but REALIZED_PNL does
        # We need to fetch trades per symbol — but we need the list of symbols.
        # Use a wide approach: query userTrades for each symbol we know about.
        # If we miss some, that's ok for an estimate.

        # Better: query all order history to find all symbols traded
        # /fapi/v1/allOrders with no symbol returns all orders? No, symbol is required.
        # Use /fapi/v1/income with REALIZED_PNL to get symbols
        income = api_call(k, s, 'GET', '/fapi/v1/income', {
            'startTime': 0,
            'limit': 1000,
        })
        for item in income:
            if item.get('symbol'):
                symbols.add(item['symbol'])

        log(f"  Symbols with activity: {len(symbols)}")

        bot_volume = 0.0
        bot_trades = 0
        bot_commission = 0.0
        bot_realized = 0.0
        per_symbol = {}

        for sym in sorted(symbols):
            try:
                # userTrades returns up to 1000 last trades; paginate via startTime
                start_ms = 0
                sym_vol = 0.0
                sym_count = 0
                while True:
                    params = {'symbol': sym, 'limit': 1000}
                    if start_ms > 0:
                        params['startTime'] = start_ms
                    trades = api_call(k, s, 'GET', '/fapi/v1/userTrades', params)
                    if not trades:
                        break
                    for t in trades:
                        sym_vol += float(t.get('quoteQty', 0) or 0)
                        sym_count += 1
                        bot_commission += abs(float(t.get('commission', 0) or 0))
                    if len(trades) < 1000:
                        break
                    # next page
                    last_id = int(trades[-1].get('id', 0))
                    if last_id == 0:
                        break
                    # use fromId to paginate
                    params2 = {'symbol': sym, 'limit': 1000, 'fromId': last_id + 1}
                    next_trades = api_call(k, s, 'GET', '/fapi/v1/userTrades', params2)
                    if not next_trades or next_trades == trades:
                        break
                    trades = next_trades
                    for t in trades:
                        sym_vol += float(t.get('quoteQty', 0) or 0)
                        sym_count += 1
                        bot_commission += abs(float(t.get('commission', 0) or 0))
                    if len(trades) < 1000:
                        break
                if sym_vol > 0:
                    per_symbol[sym] = (sym_vol, sym_count)
                    bot_volume += sym_vol
                    bot_trades += sym_count
            except Exception as e:
                pass

        # Realized PnL from income
        for item in income:
            if item.get('incomeType') == 'REALIZED_PNL':
                bot_realized += float(item.get('income', 0))

        log(f"  Total volume:    ${bot_volume:,.2f}")
        log(f"  Total fills:     {bot_trades}")
        log(f"  Total commission: ${bot_commission:,.2f}")
        log(f"  Total realized:  ${bot_realized:+,.2f}")
        log(f"  Top symbols by volume:")
        top = sorted(per_symbol.items(), key=lambda x: -x[1][0])[:5]
        for sym, (vol, cnt) in top:
            log(f"    {sym:14s} ${vol:>14,.2f}  ({cnt} fills)")

        grand_total_volume += bot_volume
        grand_total_trades += bot_trades
        grand_total_commission += bot_commission
        grand_total_realized += bot_realized
    except Exception as e:
        log(f"  ERROR: {e}")
        import traceback
        log(traceback.format_exc())

log(f"\\n{'='*70}")
log(f"GRAND TOTAL (3 BOTS)")
log(f"  Total volume:     ${grand_total_volume:,.2f}")
log(f"  Total fills:      {grand_total_trades}")
log(f"  Total commission: ${grand_total_commission:,.2f}")
log(f"  Total realized:   ${grand_total_realized:+,.2f}")
log(f"\\nDone.")
'''

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PWD, timeout=15)
sftp = ssh.open_sftp()
with open("__remote_vol.py", "w", encoding="utf-8") as f:
    f.write(REMOTE_SCRIPT_CONTENT)
sftp.put("__remote_vol.py", REMOTE_SCRIPT)
sftp.close()
ssh.exec_command(f"rm -f {REMOTE_OUT}")
stdin, stdout, stderr = ssh.exec_command(f"cd /opt/trading && /opt/trading/venv/bin/python3 {REMOTE_SCRIPT}", timeout=300)
code = stdout.channel.recv_exit_status()
stdin, stdout, stderr = ssh.exec_command(f"cat {REMOTE_OUT}")
out = stdout.read().decode("utf-8", errors="replace")
ssh.exec_command(f"rm -f {REMOTE_SCRIPT} {REMOTE_OUT}")
ssh.close()

os.remove("__remote_vol.py")
print(out)
if code != 0:
    err = stderr.read().decode("utf-8", errors="replace") if stderr else ""
    print(f"Exit code: {code}")
    if err:
        print(f"stderr: {err}")
