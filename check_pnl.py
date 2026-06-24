"""Check real positions + PnL + balance for 3 testnet accounts."""
import sys, io, os, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "production"))

# Load .env manually
from pathlib import Path
env_path = Path(__file__).parent / "production" / "live" / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from live.binance_client import BinanceClient

accounts = ["lv4", "lv5", "lv6"]

print("=" * 90)
print(f"{'BOT':<6} {'EQUITY':>12} {'AVAIL':>12} {'UNREALIZED':>12} {'POSITIONS':>10}")
print("=" * 90)

grand_eq = 0
grand_avail = 0
grand_upnl = 0

for strat in accounts:
    os.environ["BOT_STRATEGY"] = strat
    os.environ["BOT_MODE"] = "testnet"
    
    # Force reload config
    import importlib
    from live import config
    importlib.reload(config)
    
    try:
        c = BinanceClient()
    except Exception as e:
        print(f"{strat.upper()}: BinanceClient init failed: {e}")
        continue
    
    # Balance
    eq, avail = c.equity_usdt()
    
    # Positions
    positions = c.position_risk()
    open_pos = [p for p in positions if p["amt"] != 0]
    
    total_upnl = 0
    print(f"\n{'='*90}")
    print(f"{strat.upper()} — equity=${eq:.2f}  avail=${avail:.2f}  open={len(open_pos)}")
    print(f"{'-'*90}")
    
    if open_pos:
        print(f"  {'SYMBOL':<14} {'DIR':<6} {'QTY':>14} {'ENTRY':>12} {'MARK':>12} {'UPNL':>12} {'PnL%':>8}")
        print(f"  {'-'*14} {'-'*6} {'-'*14} {'-'*12} {'-'*12} {'-'*12} {'-'*8}")
        for p in open_pos:
            sym = p["symbol"]
            direction = p["dir"]
            amt = p["amt"]
            entry = p["entry"]
            try:
                mark = c.mark_price(sym)
            except:
                mark = entry
            if direction == "SHORT":
                upnl = (entry - mark) * abs(amt)
                pnl_pct = (entry - mark) / entry * 100
            else:
                upnl = (mark - entry) * abs(amt)
                pnl_pct = (mark - entry) / entry * 100
            total_upnl += upnl
            print(f"  {sym:<14} {direction:<6} {amt:>14.4f} {entry:>12.6f} {mark:>12.6f} {upnl:>12.4f} {pnl_pct:>7.2f}%")
        print(f"  {'-'*90}")
        print(f"  TOTAL UNREALIZED PnL: ${total_upnl:.4f}")
    else:
        print(f"  (no open positions)")
    
    print(f"  EQUITY: ${eq:.2f}  AVAILABLE: ${avail:.2f}  PnL: ${total_upnl:.4f}")
    grand_eq += eq
    grand_avail += avail
    grand_upnl += total_upnl
    
    time.sleep(0.5)  # rate limit

print(f"\n{'='*90}")
print(f"GRAND TOTAL (3 accounts)")
print(f"{'='*90}")
print(f"  Total Equity:     ${grand_eq:.2f}")
print(f"  Total Available:  ${grand_avail:.2f}")
print(f"  Total Unrealized: ${grand_upnl:.4f}")
print(f"  Start capital:    $15000.00 (3 x $5000)")
print(f"  Net PnL:          ${grand_eq - 15000:.4f} ({(grand_eq - 15000)/15000*100:.2f}%)")
