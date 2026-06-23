"""Strategy AGGRESSIVE - 6-month continuous compounding test (3 windows)."""
import requests, pandas as pd, time, urllib3, os, random, sys
from datetime import datetime, timedelta
from collections import Counter
urllib3.disable_warnings()

sys.path.insert(0, 'D:/Temp/Trading')
import strategy_aggressive as v15

windows = [
    ("H1-2025", datetime(2025, 1, 1), datetime(2025, 7, 1)),
    ("H2-2025", datetime(2025, 7, 1), datetime(2026, 1, 1)),
    ("H2-2022", datetime(2022, 7, 1), datetime(2023, 1, 1)),
]

COINS_PER_WINDOW = 30
SEED = 777

print(f"STRATEGY AGGRESSIVE - 6-MONTH CONTINUOUS COMPOUNDING TEST (3 windows)")
print(f"Starting capital: ${v15.TOTAL_CAPITAL} | Position: {v15.POSITION_PCT}% of equity | Max lev: {v15.MAX_LEVERAGE}x")
print(f"Min notional: ${v15.MIN_NOTIONAL} | Max vol pct: {v15.MAX_VOL_PCT}%")
print(f"RR=3.5, SL=1.3xATR, BE=0.5R, Trail=1.2R\n")

all_symbols = v15.get_all_symbols()
print(f"Total USDT perpetuals: {len(all_symbols)}\n")

random.seed(SEED)
results = []

for label, start_dt, end_dt in windows:
    print(f"\n{'='*80}")
    print(f">>> {label}: {start_dt.strftime('%b %Y')} -> {end_dt.strftime('%b %Y')}")
    print(f"{'='*80}")

    btc_daily = v15.fetch_btc_daily(start_dt, end_dt)
    if btc_daily is None:
        print(f"  No BTC daily data, skipping"); continue
    print(f"  BTC daily: {len(btc_daily)} bars")

    candidates = random.sample(all_symbols, min(COINS_PER_WINDOW * 2, len(all_symbols)))
    coin_data = {}
    for coin in candidates:
        try:
            df15 = v15.fetch_klines_range(coin, "15m", start_dt, end_dt)
            df1h = v15.fetch_klines_range(coin, "1h", start_dt, end_dt)
            if df15 is not None and len(df15) > 1000 and df1h is not None and len(df1h) > 200:
                coin_data[coin] = {"15m": df15, "1h": df1h}
                if len(coin_data) >= COINS_PER_WINDOW: break
        except: pass
    print(f"  Got {len(coin_data)} valid coins (with full 6-month data)")
    if len(coin_data) < 10:
        print("  Skip (too few coins)"); continue

    trades, final_cap, max_conc, total_vol, liq_count, peak_eq, trough_eq = v15.backtest_portfolio(coin_data, btc_daily)
    r = v15.report(trades, final_cap, max_conc, total_vol, liq_count, label, show_coins=False)
    if r:
        r['peak'] = peak_eq; r['trough'] = trough_eq; r['final'] = final_cap
        results.append(r)

    print(f"\n  === EQUITY STATS ===")
    print(f"  Peak equity:   ${peak_eq:.2f} ({(peak_eq/v15.TOTAL_CAPITAL-1)*100:+.2f}%)")
    print(f"  Trough equity: ${trough_eq:.2f} ({(trough_eq/v15.TOTAL_CAPITAL-1)*100:+.2f}%)")
    print(f"  Final equity:  ${final_cap:.2f} ({(final_cap/v15.TOTAL_CAPITAL-1)*100:+.2f}%)")
    print(f"  Max drawdown from peak: {(peak_eq-trough_eq)/peak_eq*100:.1f}%")
    cagr = ((final_cap/v15.TOTAL_CAPITAL) ** (1/6) - 1) * 100 if final_cap > 0 else -99
    print(f"  CAGR/month: {cagr:+.2f}%")
    print(f"  6-month multiplier: {final_cap/v15.TOTAL_CAPITAL:.2f}x")

# === Final Summary ===
print(f"\n\n{'='*110}")
print(f"  AGGRESSIVE 6-MONTH CONTINUOUS SUMMARY ({len(results)} windows)")
print(f"{'='*110}")
print(f"{'Window':>12} {'Return':>10} {'End Cap':>10} {'Peak':>10} {'Trough':>10} {'Trades':>8} {'WR':>7} {'PF':>6} {'MaxDD':>7} {'LIQ':>5} {'CAGR/mo':>9}")
print(f"{'-'*105}")
for r in results:
    cagr = ((r['final']/v15.TOTAL_CAPITAL) ** (1/6) - 1) * 100 if r['final'] > 0 else -99
    print(f"{r['label']:>12} {r['ret']:>+9.2f}% ${r['final']:>9.2f} ${r['peak']:>9.2f} ${r['trough']:>9.2f} {r['trades']:>8} {r['wr']:>6.1f}% {r['pf']:>5.2f} {r['mdd']:>6.1f}% {r['liq']:>5} {cagr:>+8.2f}%")

wins = sum(1 for r in results if r['ret'] > 0)
avg_ret = sum(r['ret'] for r in results) / len(results)
avg_pf = sum(r['pf'] for r in results) / len(results)
avg_mdd = sum(r['mdd'] for r in results) / len(results)
total_liq = sum(r['liq'] for r in results)
avg_cagr = sum(((r['final']/v15.TOTAL_CAPITAL) ** (1/6) - 1) * 100 for r in results if r['final'] > 0) / len(results)

print(f"\nProfitable windows: {wins}/{len(results)} ({wins/len(results)*100:.0f}%)")
print(f"Avg 6-month return: {avg_ret:+.2f}%")
print(f"Avg CAGR/month: {avg_cagr:+.2f}%")
print(f"Avg PF: {avg_pf:.2f} | Avg MaxDD: {avg_mdd:.1f}% | Total LIQ: {total_liq}")
worst = min(results, key=lambda x: x['ret'])
best = max(results, key=lambda x: x['ret'])
print(f"Worst: {worst['label']} ({worst['ret']:+.2f}% -> ${worst['final']:.0f})")
print(f"Best: {best['label']} ({best['ret']:+.2f}% -> ${best['final']:.0f})")

print(f"\n{'='*100}")
print(f"  COMPOUNDING SHOWCASE: $1000 starting capital")
print(f"{'='*100}")
for r in sorted(results, key=lambda x: -x['ret']):
    cagr = ((r['final']/v15.TOTAL_CAPITAL) ** (1/6) - 1) * 100 if r['final'] > 0 else -99
    print(f"  {r['label']:>12}: $1000 -> ${r['final']:>10.2f} ({r['ret']:>+7.2f}%) | CAGR {cagr:>+6.2f}%/mo | Peak ${r['peak']:.0f} | Trough ${r['trough']:.0f}")
