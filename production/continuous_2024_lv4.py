"""LV4 — Single continuous compounding backtest Jan 2024 -> Jun 2026.
1 window, no breaks, capital compounds the entire 2.5 years.
Report includes avg hold time (hours) + total volume."""
import requests, pandas as pd, time, urllib3, os, random, sys
from datetime import datetime, timedelta
from collections import Counter
urllib3.disable_warnings()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import strategy_aggressive_lv4 as strat

START_DT = datetime(2024, 1, 1)
END_DT = datetime(2026, 7, 1)
COINS = 30
SEED = 777
BAR_HOURS = 0.25  # 15m chart = 0.25h per bar

print(f"LV4 AGGRESSIVE — CONTINUOUS COMPOUNDING {START_DT.strftime('%b %Y')} -> {END_DT.strftime('%b %Y')}")
print(f"Starting capital: ${strat.TOTAL_CAPITAL} | Position: {strat.POSITION_PCT}% of equity | Max lev: {strat.MAX_LEVERAGE}x")
print(f"RR=6.5, SL=0.8xATR, BE=1.1R, Trail=2.5R | Min notional: ${strat.MIN_NOTIONAL}\n")

all_symbols = strat.get_all_symbols()
print(f"Total USDT perpetuals: {len(all_symbols)}\n")

random.seed(SEED)
btc_daily = strat.fetch_btc_daily(START_DT, END_DT)
if btc_daily is None:
    print("No BTC daily data, aborting"); sys.exit(1)
print(f"BTC daily: {len(btc_daily)} bars")

candidates = random.sample(all_symbols, min(COINS * 2, len(all_symbols)))
coin_data = {}
for coin in candidates:
    try:
        df15 = strat.fetch_klines_range(coin, "15m", START_DT, END_DT)
        df1h = strat.fetch_klines_range(coin, "1h", START_DT, END_DT)
        if df15 is not None and len(df15) > 1000 and df1h is not None and len(df1h) > 200:
            coin_data[coin] = {"15m": df15, "1h": df1h}
            if len(coin_data) >= COINS: break
    except: pass
print(f"Got {len(coin_data)} valid coins with full 2.5-year data")
if len(coin_data) < 10:
    print("Too few coins, aborting"); sys.exit(1)

trades, final_cap, max_conc, total_vol, liq_count, peak_eq, trough_eq = strat.backtest_portfolio(coin_data, btc_daily)
r = strat.report(trades, final_cap, max_conc, total_vol, liq_count, "Jan 2024 -> Jun 2026", show_coins=False)

# === EXTRA METRICS: avg hold time (hours) + total volume ===
avg_hold_bars = sum(t["hold"] for t in trades) / len(trades) if trades else 0
avg_hold_hours = avg_hold_bars * BAR_HOURS
median_hold_bars = sorted([t["hold"] for t in trades])[len(trades)//2] if trades else 0
median_hold_hours = median_hold_bars * BAR_HOURS
max_hold_bars = max((t["hold"] for t in trades), default=0)
max_hold_hours = max_hold_bars * BAR_HOURS

months = 30
total_ret = (final_cap/strat.TOTAL_CAPITAL - 1) * 100
cagr = ((final_cap/strat.TOTAL_CAPITAL) ** (1/months) - 1) * 100 if final_cap > 0 else -99

print(f"\n{'='*80}")
print(f"  LV4 AGGRESSIVE — FINAL RESULT")
print(f"{'='*80}")
print(f"  $1000 -> ${final_cap:.2f} ({total_ret:+.2f}%) over {months} months")
print(f"  Multiplier: {final_cap/strat.TOTAL_CAPITAL:.2f}x")
print(f"  CAGR/month: {cagr:+.2f}%")
print(f"  Peak equity:   ${peak_eq:.2f} ({(peak_eq/strat.TOTAL_CAPITAL-1)*100:+.2f}%)")
print(f"  Trough equity: ${trough_eq:.2f} ({(trough_eq/strat.TOTAL_CAPITAL-1)*100:+.2f}%)")
print(f"  Max DD from peak: {(peak_eq-trough_eq)/peak_eq*100:.1f}%")
print(f"  Total trades: {len(trades)}")
print(f"  Total liquidations: {liq_count}")
print(f"\n  === HOLD TIME STATS ===")
print(f"  Avg hold time:    {avg_hold_hours:.2f}h ({avg_hold_bars:.1f} bars)")
print(f"  Median hold time: {median_hold_hours:.2f}h ({median_hold_bars:.0f} bars)")
print(f"  Max hold time:    {max_hold_hours:.2f}h ({max_hold_bars:.0f} bars)")
print(f"\n  === VOLUME STATS ===")
print(f"  Total volume: ${total_vol:,.2f}")
print(f"  Avg volume/trade: ${total_vol/len(trades):,.2f}" if trades else "")
