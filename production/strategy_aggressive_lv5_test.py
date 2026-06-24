"""AGGRESSIVE LV5 Extended Test - 31 months (same months as aggressive/LV2 for comparison)."""
import requests, pandas as pd, time, urllib3, os, random, sys
from datetime import datetime, timedelta
from collections import Counter
urllib3.disable_warnings()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import strategy_aggressive_lv5 as strat

test_months = [(2022, 12), (2023, 1), (2024, 8), (2025, 5), (2026, 2),
               (2024, 5), (2025, 10), (2026, 3), (2022, 6), (2023, 9), (2025, 2),
               (2022, 1), (2022, 2), (2022, 3), (2022, 7), (2022, 8), (2022, 9),
               (2023, 3), (2023, 6), (2023, 7), (2023, 12),
               (2024, 1), (2024, 3), (2024, 7), (2024, 9), (2024, 11),
               (2025, 4), (2025, 6), (2025, 11), (2026, 1), (2026, 4)]

COINS_PER_MONTH = 30

print(f"AGGRESSIVE LV5 EXTENDED TEST - {len(test_months)} months")
print(f"Params: pos={strat.POSITION_PCT}% of equity, daily_limit={strat.DAILY_LOSS_LIMIT}%, "
      f"min_score={strat.MIN_SCORE}, max_lev={strat.MAX_LEVERAGE}x, max_conc={strat.MAX_CONCURRENT}")
print(f"Min notional: ${strat.MIN_NOTIONAL} | Max vol pct: {strat.MAX_VOL_PCT}%")
print(f"LV5: RR=7.5, SL=0.7xATR, BE=1.3R, Trail=3.0R, scan_every=4 bars, LIQ_SAFETY_ROE={strat.LIQ_SAFETY_ROE}%")
print(f"Lev thresholds: 25x->{strat.get_liquidation_threshold(25):.1f}%, 20x->{strat.get_liquidation_threshold(20):.1f}%, "
      f"15x->{strat.get_liquidation_threshold(15):.1f}%, 10x->{strat.get_liquidation_threshold(10):.1f}%, "
      f"5x->{strat.get_liquidation_threshold(5):.1f}%")

all_symbols = strat.get_all_symbols()
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
    btc_daily = strat.fetch_btc_daily(start_dt, end_dt)
    if btc_daily is None:
        print(f"  No BTC daily data, skipping"); continue
    print(f"  BTC daily: {len(btc_daily)} bars")
    candidates = month_coin_map[(year, month)]
    coin_data = {}
    for coin in candidates:
        try:
            df15 = strat.fetch_klines_range(coin, "15m", start_dt, end_dt)
            df1h = strat.fetch_klines_range(coin, "1h", start_dt, end_dt)
            if df15 is not None and len(df15) > 200 and df1h is not None and len(df1h) > 50:
                coin_data[coin] = {"15m": df15, "1h": df1h}
                if len(coin_data) >= COINS_PER_MONTH: break
        except: pass
    print(f"  Got {len(coin_data)} valid coins")
    if len(coin_data) < 10:
        print("  Skip (too few coins)"); continue
    trades, final_cap, max_conc, total_vol, liq_count, peak_eq, trough_eq = strat.backtest_portfolio(coin_data, btc_daily)
    r = strat.report(trades, final_cap, max_conc, total_vol, liq_count, label, show_coins=False)
    if r:
        r['peak'] = peak_eq; r['trough'] = trough_eq; r['final'] = final_cap
        results.append(r)

# === Final Summary ===
print(f"\n\n{'='*110}")
print(f"  AGGRESSIVE LV5 SUMMARY ({len(results)} months)")
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
buckets = [(-100,-50),(-50,-20),(-20,-10),(-10,0),(0,10),(10,30),(30,50),(50,100),(100,200),(200,500),(500,1000)]
for lo, hi in buckets:
    cnt = sum(1 for r in results if lo <= r['ret'] < hi)
    if cnt > 0:
        bar = '#' * cnt
        print(f"  {lo:>+5d}% to {hi:>+5d}%: {cnt:2d} {bar}")

# Compare with aggressive (V15r2) AND LV2
aggressive_results = {"Dec 2022": 26.49, "Jan 2023": 33.23, "Aug 2024": 30.37, "May 2025": 86.32, "Feb 2026": 60.21,
                      "May 2024": 21.02, "Oct 2025": 29.84, "Mar 2026": 53.40, "Jun 2022": 32.46, "Sep 2023": 37.81, "Feb 2025": 25.15,
                      "Jan 2022": 61.25, "Feb 2022": 30.92, "Mar 2022": 27.67, "Jul 2022": 2.44, "Aug 2022": 92.42,
                      "Sep 2022": 28.41, "Mar 2023": 34.30, "Jun 2023": 56.35, "Jul 2023": 33.35, "Dec 2023": 97.43,
                      "Jan 2024": 23.03, "Mar 2024": 6.72, "Jul 2024": 20.05, "Sep 2024": 21.82, "Nov 2024": 15.65,
                      "Apr 2025": 55.76, "Jun 2025": 35.44, "Nov 2025": 22.17, "Jan 2026": 61.35, "Apr 2026": 43.12}
# LV2 results (from PROJECT_HISTORY.md / Phase 8 backtest) — fill from prior run if available
lv2_results = {}  # populated below if lv2 module importable
try:
    import strategy_aggressive_lv2 as lv2_mod
    # Re-run is expensive; instead use hardcoded known LV2 results from PROJECT_HISTORY if present
    # We leave empty and only compare LV5 vs Aggressive here; LV2 comparison done separately
except Exception:
    pass

print(f"\nAGGRESSIVE (V15r2) vs AGGRESSIVE LV5 comparison:")
print(f"{'Month':>12} {'Aggressive':>12} {'LV3':>10} {'Diff':>10}")
print(f"{'-'*48}")
for r in results:
    agg = aggressive_results.get(r['label'], 0)
    diff = r['ret'] - agg
    marker = " <<<" if abs(diff) > 20 else ""
    print(f"{r['label']:>12} {agg:>+11.2f}% {r['ret']:>+9.2f}% {diff:>+9.2f}%{marker}")

agg_vals = list(aggressive_results.values())
agg_avg = sum(agg_vals)/len(agg_vals)
agg_wins = sum(1 for v in agg_vals if v > 0)
print(f"\nAggressive: {agg_wins}/{len(agg_vals)} profitable, avg {agg_avg:+.2f}%")
print(f"LV5:        {wins}/{len(results)} profitable, avg {avg_ret:+.2f}%")
print(f"Improvement: {avg_ret - agg_avg:+.2f}% avg return")
