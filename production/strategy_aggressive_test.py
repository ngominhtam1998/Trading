"""V15 COMPOUND Extended Test - 31 months random test.
Same months as V14 for direct comparison.
"""
import requests, pandas as pd, time, urllib3, os, random, sys
from datetime import datetime, timedelta
from collections import Counter
urllib3.disable_warnings()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import strategy_aggressive as v15

test_months = [(2022, 12), (2023, 1), (2024, 8), (2025, 5), (2026, 2),
               (2024, 5), (2025, 10), (2026, 3), (2022, 6), (2023, 9), (2025, 2),
               (2022, 1), (2022, 2), (2022, 3), (2022, 7), (2022, 8), (2022, 9),
               (2023, 3), (2023, 6), (2023, 7), (2023, 12),
               (2024, 1), (2024, 3), (2024, 7), (2024, 9), (2024, 11),
               (2025, 4), (2025, 6), (2025, 11), (2026, 1), (2026, 4)]

COINS_PER_MONTH = 30

print(f"V15 COMPOUND EXTENDED TEST - {len(test_months)} months")
print(f"Params: pos={v15.POSITION_PCT}% of equity, daily_limit={v15.DAILY_LOSS_LIMIT}%, min_score={v15.MIN_SCORE}, max_lev={v15.MAX_LEVERAGE}x, max_conc={v15.MAX_CONCURRENT}")
print(f"Min notional: ${v15.MIN_NOTIONAL} | Max vol pct: {v15.MAX_VOL_PCT}%")
print(f"V15r2: RR=3.5, SL=1.3xATR, BE=0.5R, Trail=1.2R, EMA200+body SOFT bonus, V14 base params")
print(f"Lev thresholds: 25x->{v15.get_liquidation_threshold(25):.1f}%, 10x->{v15.get_liquidation_threshold(10):.1f}%, 5x->{v15.get_liquidation_threshold(5):.1f}%")

all_symbols = v15.get_all_symbols()
print(f"Total USDT perpetuals: {len(all_symbols)}\n")

random.seed(777)
month_coin_map = {}
for ym in test_months:
    candidates = random.sample(all_symbols, min(COINS_PER_MONTH * 2, len(all_symbols)))
    month_coin_map[ym] = candidates

results = []
for year, month in test_months:
    start_dt = datetime(year, month, 1)
    end_dt = datetime(year, month + 1, 1) if month < 12 else datetime(year + 1, 1, 1)
    label = start_dt.strftime('%b %Y')
    print(f"\n>>> {label}...")
    btc_daily = v15.fetch_btc_daily(start_dt, end_dt)
    if btc_daily is None:
        print(f"  No BTC daily data, skipping"); continue
    print(f"  BTC daily: {len(btc_daily)} bars")
    candidates = month_coin_map[(year, month)]
    coin_data = {}
    for coin in candidates:
        try:
            df15 = v15.fetch_klines_range(coin, "15m", start_dt, end_dt)
            df1h = v15.fetch_klines_range(coin, "1h", start_dt, end_dt)
            if df15 is not None and len(df15) > 200 and df1h is not None and len(df1h) > 50:
                coin_data[coin] = {"15m": df15, "1h": df1h}
                if len(coin_data) >= COINS_PER_MONTH: break
        except: pass
    print(f"  Got {len(coin_data)} valid coins")
    if len(coin_data) < 10:
        print("  Skip (too few coins)"); continue
    trades, final_cap, max_conc, total_vol, liq_count, peak_eq, trough_eq = v15.backtest_portfolio(coin_data, btc_daily)
    r = v15.report(trades, final_cap, max_conc, total_vol, liq_count, label, show_coins=False)
    if r:
        r['peak'] = peak_eq; r['trough'] = trough_eq; r['final'] = final_cap
        results.append(r)

# === Final Summary ===
print(f"\n\n{'='*110}")
print(f"  V15 COMPOUND SUMMARY ({len(results)} months)")
print(f"{'='*110}")
print(f"{'Month':>12} {'Return':>10} {'Trades':>8} {'WR':>7} {'PF':>6} {'MaxDD':>7} {'W/L':>6} {'LIQ':>5} {'Profit%':>9} {'Peak':>9} {'Trough':>9}")
print(f"{'-'*105}")
for r in results:
    wl = r['avg_win']/r['avg_loss'] if r['avg_loss'] > 0 else 0
    print(f"{r['label']:>12} {r['ret']:>+9.2f}% {r['trades']:>8} {r['wr']:>6.1f}% {r['pf']:>5.2f} {r['mdd']:>6.1f}% {wl:>5.2f} {r['liq']:>5} {r['profitable_pct']:>8.0f}% ${r['peak']:>8.0f} ${r['trough']:>8.0f}")

wins = sum(1 for r in results if r['ret'] > 0)
avg_ret = sum(r['ret'] for r in results) / len(results)
avg_pf = sum(r['pf'] for r in results) / len(results)
avg_mdd = sum(r['mdd'] for r in results) / len(results)
total_liq = sum(r['liq'] for r in results)
median_ret = sorted([r['ret'] for r in results])[len(results)//2]
total_trades = sum(r['trades'] for r in results)

print(f"\nProfitable months: {wins}/{len(results)} ({wins/len(results)*100:.0f}%)")
print(f"Avg return: {avg_ret:+.2f}% | Median return: {median_ret:+.2f}%")
print(f"Avg PF: {avg_pf:.2f} | Avg MaxDD: {avg_mdd:.1f}% | Total LIQ: {total_liq}")
print(f"Total trades: {total_trades} | Avg trades/month: {total_trades/len(results):.0f}")
worst = min(results, key=lambda x: x['ret'])
best = max(results, key=lambda x: x['ret'])
print(f"Worst: {worst['label']} ({worst['ret']:+.2f}%) | Best: {best['label']} ({best['ret']:+.2f}%)")

# Distribution
print(f"\nReturn distribution:")
buckets = [(-50,-20),(-20,-10),(-10,0),(0,10),(10,30),(30,50),(50,100),(100,200)]
for lo, hi in buckets:
    cnt = sum(1 for r in results if lo <= r['ret'] < hi)
    if cnt > 0:
        bar = '#' * cnt
        print(f"  {lo:>+4d}% to {hi:>+4d}%: {cnt:2d} {bar}")

# Compare with V14 compound
v14_results = {"Dec 2022": 7.04, "Jan 2023": 21.06, "Aug 2024": 17.38, "May 2025": 85.00, "Feb 2026": 54.27,
               "May 2024": 7.87, "Oct 2025": -5.51, "Mar 2026": 20.80, "Jun 2022": 22.93, "Sep 2023": 26.20, "Feb 2025": 9.02,
               "Jan 2022": 58.62, "Feb 2022": -1.33, "Mar 2022": 7.45, "Jul 2022": -11.45, "Aug 2022": 85.57,
               "Sep 2022": 28.61, "Mar 2023": 26.44, "Jun 2023": 43.49, "Jul 2023": 18.92, "Dec 2023": 58.46,
               "Jan 2024": -0.84, "Mar 2024": 11.58, "Jul 2024": 15.46, "Sep 2024": 8.29, "Nov 2024": 14.99,
               "Apr 2025": 29.43, "Jun 2025": 33.43, "Nov 2025": -10.55, "Jan 2026": 58.57, "Apr 2026": 28.76}
print(f"\nV14 COMPOUND vs V15 COMPOUND comparison:")
print(f"{'Month':>12} {'V14':>10} {'V15':>10} {'Diff':>10}")
print(f"{'-'*45}")
v14_wins = 0
for r in results:
    v14 = v14_results.get(r['label'], 0)
    diff = r['ret'] - v14
    if r['ret'] > 0: v14_wins += 0
    marker = " <<<" if abs(diff) > 15 else ""
    print(f"{r['label']:>12} {v14:>+9.2f}% {r['ret']:>+9.2f}% {diff:>+9.2f}%{marker}")

v14_vals = list(v14_results.values())
v14_avg = sum(v14_vals)/len(v14_vals)
v14_wins_cnt = sum(1 for v in v14_vals if v > 0)
print(f"\nV14: {v14_wins_cnt}/{len(v14_vals)} profitable, avg {v14_avg:+.2f}%")
print(f"V15: {wins}/{len(results)} profitable, avg {avg_ret:+.2f}%")
print(f"Improvement: {avg_ret - v14_avg:+.2f}% avg return")
