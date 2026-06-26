"""Backtest runner for strategy_reversal_scalp (1m mean-reversion scalper).

Selects the top-N most ACTIVE coins (volume x daily range), fetches real 1m
klines for a recent window, and runs the backtest.

Usage:
    python backtest_reversal_scalp.py [MONTHS] [TOP_N]
    e.g. python backtest_reversal_scalp.py 1 8
"""
import sys, os, time, requests, urllib3
from datetime import datetime, timedelta, timezone
urllib3.disable_warnings()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import strategy_reversal_scalp as strat

MONTHS = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0
TOP_N = int(sys.argv[2]) if len(sys.argv) > 2 else 8

END_DT = datetime.now(timezone.utc).replace(tzinfo=None).replace(second=0, microsecond=0)
START_DT = END_DT - timedelta(days=int(MONTHS * 30))

print(f"REVERSAL SCALP BACKTEST — {START_DT:%Y-%m-%d} -> {END_DT:%Y-%m-%d} ({MONTHS} months)")
print(f"Selecting top {TOP_N} active coins (24h quoteVolume x daily range%)")
print(f"Params: spike>={strat.SPIKE_PCT}%/{strat.SPIKE_LOOKBACK}m, RSI{strat.RSI_PERIOD} "
      f"OB/OS={strat.RSI_OB}/{strat.RSI_OS}, BB({strat.BB_PERIOD},{strat.BB_STD})")
print(f"TP~{strat.TP_RETRACE}xspike[{strat.TP_MIN_PCT}-{strat.TP_MAX_PCT}%], "
      f"SL extreme+buf[{strat.SL_MIN_PCT}-{strat.SL_MAX_PCT}%], lev<={strat.MAX_LEVERAGE}x, "
      f"pos={strat.POSITION_PCT}%, conc={strat.MAX_CONCURRENT}, timestop={strat.MAX_HOLD_MIN}m\n")


# Coin-selection filters: keep liquid, sanely-volatile coins (no new-listing
# pump/dump rockets that liquidate a mean-reversion scalper).
MIN_QUOTE_VOLUME = 200_000_000   # >= $200M 24h volume (established, liquid)
MIN_DAY_RANGE = 3.0              # >= 3% daily range (must actually move)
MAX_DAY_RANGE = 25.0            # <= 25% daily range (exclude insane pump coins)


def select_active_coins(top_n):
    """Rank liquid USDT perpetuals by quoteVolume * (capped) daily-range%."""
    perps = set(strat.get_all_symbols())
    r = requests.get("https://fapi.binance.com/fapi/v1/ticker/24hr", timeout=30, verify=False)
    data = r.json()
    scored = []
    for t in data:
        sym = t.get("symbol")
        if sym not in perps:
            continue
        try:
            qv = float(t.get("quoteVolume", 0) or 0)
            hi = float(t.get("highPrice", 0) or 0)
            lo = float(t.get("lowPrice", 0) or 0)
            if lo <= 0 or qv < MIN_QUOTE_VOLUME:
                continue
            day_range = (hi - lo) / lo * 100
            if day_range < MIN_DAY_RANGE or day_range > MAX_DAY_RANGE:
                continue
            score = qv * min(day_range, MAX_DAY_RANGE)
            scored.append((sym, score, qv, day_range))
        except Exception:
            continue
    scored.sort(key=lambda x: -x[1])
    return scored[:top_n]


top = select_active_coins(TOP_N)
print("Selected coins (by activity score):")
for sym, score, qv, dr in top:
    print(f"  {sym:14s} score={score:>14,.0f}  vol=${qv:>14,.0f}  range={dr:>5.1f}%")
print()

coin_data = {}
for sym, *_ in top:
    print(f"  Fetching 1m {sym} ...")
    df = strat.fetch_klines_range(sym, "1m", START_DT, END_DT)
    if df is not None and len(df) > 500:
        coin_data[sym] = df
        print(f"    -> {len(df)} bars")
    else:
        print("    -> insufficient, skip")

if len(coin_data) < 2:
    print("\nToo few coins with data, aborting.")
    sys.exit(1)

print(f"\nRunning backtest on {len(coin_data)} coins ...")
trades, final_cap, max_conc, total_vol, liq_count, peak_eq, trough_eq = strat.backtest_portfolio(coin_data)
r = strat.report(trades, final_cap, max_conc, total_vol, liq_count,
                 f"REVERSAL SCALP {START_DT:%Y-%m-%d}->{END_DT:%Y-%m-%d}", show_coins=True)

if r:
    days = (END_DT - START_DT).days or 1
    print(f"\n  === EXTRA ===")
    print(f"  Period: {days} days | Trades/day: {r['trades']/days:.1f}")
    print(f"  Peak: ${peak_eq:.2f} | Trough: ${trough_eq:.2f}")
    mult = final_cap / strat.TOTAL_CAPITAL
    monthly = (mult ** (1 / MONTHS) - 1) * 100 if mult > 0 and MONTHS > 0 else -99
    print(f"  Approx monthly return: {monthly:+.2f}%")
