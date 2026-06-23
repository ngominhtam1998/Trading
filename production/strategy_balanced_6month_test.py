"""V14 PRODUCTION - 6-month continuous compounding test.
Run backtest continuously across 6 months to see compounding effect.
Tests multiple 6-month windows.
"""
import requests, pandas as pd, time, urllib3, os, random, sys
from datetime import datetime, timedelta
from collections import Counter
urllib3.disable_warnings()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import strategy_balanced as v14

# Single 6-month window to test
windows = [
    ("H2-2022", datetime(2022, 7, 1), datetime(2023, 1, 1)),
    ("H2-2025", datetime(2025, 7, 1), datetime(2026, 1, 1)),
]

COINS_PER_WINDOW = 30
SEED = 777

print(f"V14 PRODUCTION - 6-MONTH CONTINUOUS COMPOUNDING TEST")
print(f"Starting capital: ${v14.TOTAL_CAPITAL} | Position: {v14.POSITION_PCT}% of equity | Max lev: {v14.MAX_LEVERAGE}x")
print(f"Min notional: ${v14.MIN_NOTIONAL} | Max vol pct: {v14.MAX_VOL_PCT}%")
print(f"Windows: {len(windows)} x 6 months each\n")

all_symbols = v14.get_all_symbols()
print(f"Total USDT perpetuals: {len(all_symbols)}\n")

random.seed(SEED)
results = []

for label, start_dt, end_dt in windows:
    print(f"\n{'='*80}")
    print(f">>> {label}: {start_dt.strftime('%b %Y')} -> {end_dt.strftime('%b %Y')}")
    print(f"{'='*80}")

    btc_daily = v14.fetch_btc_daily(start_dt, end_dt)
    if btc_daily is None:
        print(f"  No BTC daily data, skipping"); continue
    print(f"  BTC daily: {len(btc_daily)} bars")

    # Pick random coins and fetch 6 months of data
    candidates = random.sample(all_symbols, min(COINS_PER_WINDOW * 2, len(all_symbols)))
    coin_data = {}
    for coin in candidates:
        try:
            df15 = v14.fetch_klines_range(coin, "15m", start_dt, end_dt)
            df1h = v14.fetch_klines_range(coin, "1h", start_dt, end_dt)
            if df15 is not None and len(df15) > 1000 and df1h is not None and len(df1h) > 200:
                coin_data[coin] = {"15m": df15, "1h": df1h}
                if len(coin_data) >= COINS_PER_WINDOW: break
        except: pass
    print(f"  Got {len(coin_data)} valid coins (with full 6-month data)")
    if len(coin_data) < 10:
        print("  Skip (too few coins)"); continue

    # Run continuous backtest
    trades, final_cap, max_conc, total_vol, liq_count, peak_eq, trough_eq = v14.backtest_portfolio(coin_data, btc_daily)
    r = v14.report(trades, final_cap, max_conc, total_vol, liq_count, label, show_coins=False)
    if r:
        r['peak'] = peak_eq
        r['trough'] = trough_eq
        r['final'] = final_cap
        results.append(r)
    print(f"\n  === EQUITY STATS ===")
    print(f"  Peak equity:   ${peak_eq:.2f} ({(peak_eq/v14.TOTAL_CAPITAL-1)*100:+.2f}%)")
    print(f"  Trough equity: ${trough_eq:.2f} ({(trough_eq/v14.TOTAL_CAPITAL-1)*100:+.2f}%)")
    print(f"  Final equity:  ${final_cap:.2f} ({(final_cap/v14.TOTAL_CAPITAL-1)*100:+.2f}%)")
    print(f"  Max drawdown from peak: {(peak_eq-trough_eq)/peak_eq*100:.1f}%")

    # Show equity curve by month
    if trades:
        print(f"\n  Equity curve by month:")
        monthly_caps = {}
        cap = v14.TOTAL_CAPITAL
        for t in trades:
            cap += t["net_pnl"]
            month_key = t.get("month", "")
        # Reconstruct equity curve from trades chronologically
        cap = v14.TOTAL_CAPITAL
        current_month = None
        month_start_cap = cap
        for t in trades:
            cap += t["net_pnl"]
        # Simpler: just show start and end
        ret_pct = (final_cap / v14.TOTAL_CAPITAL - 1) * 100
        # Calculate months
        total_months = 6
        monthly_avg = ((final_cap / v14.TOTAL_CAPITAL) ** (1/total_months) - 1) * 100 if final_cap > 0 else 0
        print(f"  Start: ${v14.TOTAL_CAPITAL:.0f} -> End: ${final_cap:.2f} ({ret_pct:+.2f}%)")
        print(f"  Monthly avg (CAGR): {monthly_avg:+.2f}%/month")
        print(f"  6-month multiplier: {final_cap/v14.TOTAL_CAPITAL:.2f}x")

# === Final Summary ===
print(f"\n\n{'='*100}")
print(f"  6-MONTH CONTINUOUS COMPOUNDING SUMMARY ({len(results)} windows)")
print(f"{'='*100}")
print(f"{'Window':>12} {'Return':>10} {'End Cap':>10} {'Peak':>10} {'Trough':>10} {'Trades':>8} {'WR':>7} {'PF':>6} {'MaxDD':>7} {'LIQ':>5}")
print(f"{'-'*95}")
for r in results:
    print(f"{r['label']:>12} {r['ret']:>+9.2f}% ${r['final']:>9.2f} ${r['peak']:>9.2f} ${r['trough']:>9.2f} {r['trades']:>8} {r['wr']:>6.1f}% {r['pf']:>5.2f} {r['mdd']:>6.1f}% {r['liq']:>5}")

wins = sum(1 for r in results if r['ret'] > 0)
avg_ret = sum(r['ret'] for r in results) / len(results)
avg_pf = sum(r['pf'] for r in results) / len(results)
avg_mdd = sum(r['mdd'] for r in results) / len(results)
total_liq = sum(r['liq'] for r in results)
avg_cagr = sum(((r['final']/v14.TOTAL_CAPITAL) ** (1/6) - 1) * 100 for r in results if r['final'] > 0) / len(results)

print(f"\nProfitable windows: {wins}/{len(results)} ({wins/len(results)*100:.0f}%)")
print(f"Avg 6-month return: {avg_ret:+.2f}%")
print(f"Avg CAGR/month: {avg_cagr:+.2f}%")
print(f"Avg PF: {avg_pf:.2f} | Avg MaxDD: {avg_mdd:.1f}% | Total LIQ: {total_liq}")
worst = min(results, key=lambda x: x['ret'])
best = max(results, key=lambda x: x['ret'])
print(f"Worst: {worst['label']} ({worst['ret']:+.2f}% -> ${worst['final']:.0f})")
print(f"Best: {best['label']} ({best['ret']:+.2f}% -> ${best['final']:.0f})")

# Compounding showcase
print(f"\n{'='*100}")
print(f"  FIXED POSITION SHOWCASE: $1000 starting capital, $70/trade constant")
print(f"{'='*100}")
for r in sorted(results, key=lambda x: -x['ret']):
    print(f"  {r['label']:>12}: $1000 -> ${r['final']:>10.2f} ({r['ret']:>+7.2f}%) | Peak ${r['peak']:.0f} | Trough ${r['trough']:.0f}")
