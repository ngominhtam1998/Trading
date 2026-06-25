"""Multi-month random backtest framework for v6 / v6+ comparison.

Picks N random individual months from Jan 2024 -> Jun 2026, runs the given
strategy on each month INDEPENDENTLY (capital resets to $1000 each month),
and reports the distribution of monthly returns.

Usage:
    python multi_month_test.py [N_MONTHS=12] [SEED=777] [STRATEGY=lv6]

Strategies: lv6 (default), lv6plus

Data is cached to D:\\Tam\\trading\\production\\_cache_months/ so that
different strategies can be compared on identical data.
"""
import sys, os, time, json, pickle, random, requests, urllib3
from datetime import datetime, timedelta
from collections import Counter
urllib3.disable_warnings()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

N_MONTHS = int(sys.argv[1]) if len(sys.argv) > 1 else 12
SEED = int(sys.argv[2]) if len(sys.argv) > 2 else 777
STRAT_NAME = sys.argv[3] if len(sys.argv) > 3 else "lv6"
MONITOR_EVERY = int(sys.argv[4]) if len(sys.argv) > 4 else 1  # 1=15m, 2=30m

if STRAT_NAME == "lv6plus":
    import strategy_aggressive_lv6plus as strat
elif STRAT_NAME == "lv6":
    import strategy_aggressive_lv6 as strat
else:
    print(f"Unknown strategy: {STRAT_NAME}"); sys.exit(1)

COINS = 30  # back to 30 — no 3m data needed
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_cache_months")
os.makedirs(CACHE_DIR, exist_ok=True)

MON_LABEL = "30m" if MONITOR_EVERY == 2 else "15m"

# === Build list of candidate months: Jan 2024 -> Jun 2026 ===
def build_month_list():
    months = []
    y, m = 2024, 1
    while (y, m) <= (2026, 6):
        months.append((y, m))
        m += 1
        if m > 12: m = 1; y += 1
    return months

ALL_MONTHS = build_month_list()  # 30 months

def month_range(y, m):
    start = datetime(y, m, 1)
    if m == 12: end = datetime(y + 1, 1, 1)
    else: end = datetime(y, m + 1, 1)
    return start, end

# === Pick N random months (seeded) ===
random.seed(SEED)
chosen = random.sample(ALL_MONTHS, min(N_MONTHS, len(ALL_MONTHS)))
chosen.sort()
print(f"MULTI-MONTH TEST — strategy={STRAT_NAME} | {N_MONTHS} months | seed={SEED} | monitor={MON_LABEL}")
print(f"Months: {', '.join(f'{y}-{m:02d}' for y, m in chosen)}\n")

# === Cache key for a (month, coin_set) ===
def cache_path(y, m, seed):
    return os.path.join(CACHE_DIR, f"m_{y}_{m:02d}_s{seed}.pkl")

def fetch_month_data(y, m, seed):
    """Fetch 30 random coins (15m + 1h) + BTC daily for one month + 20-day warmup. Cached."""
    cp = cache_path(y, m, seed)
    if os.path.exists(cp):
        with open(cp, "rb") as f: return pickle.load(f)
    month_start, month_end = month_range(y, m)
    fetch_start = month_start - timedelta(days=20)
    btc_daily = strat.fetch_btc_daily(fetch_start, month_end)
    if btc_daily is None:
        print(f"  No BTC daily for {y}-{m:02d}, skip"); return None
    all_symbols = strat.get_all_symbols()
    rng = random.Random(seed + y * 100 + m)
    candidates = rng.sample(all_symbols, min(COINS * 2, len(all_symbols)))
    coin_data = {}
    for coin in candidates:
        try:
            df15 = strat.fetch_klines_range(coin, "15m", fetch_start, month_end)
            df1h = strat.fetch_klines_range(coin, "1h", fetch_start, month_end)
            if df15 is not None and len(df15) > 200 and df1h is not None and len(df1h) > 50:
                coin_data[coin] = {"15m": df15, "1h": df1h}
                if len(coin_data) >= COINS: break
        except: pass
    if len(coin_data) < 10:
        print(f"  Only {len(coin_data)} coins for {y}-{m:02d}, skip"); return None
    # Find the bar index where the actual month starts (for start_bar)
    sample_df = list(coin_data.values())[0]["15m"]
    month_start_bars = (sample_df["open_time"] >= month_start).sum()
    start_bar = len(sample_df) - month_start_bars  # bars before month_start = warmup (in 15m bars)
    start_bar = max(start_bar, 50)  # ensure at least WINDOW_SIZE
    # Filter coins: only keep those with enough bars
    filtered = {k: v for k, v in coin_data.items()
                if len(v["15m"]) >= start_bar + 100
                and len(v["1h"]) >= start_bar // 4 + 50}
    if len(filtered) < 10:
        print(f"  Only {len(filtered)} coins with enough data for {y}-{m:02d} "
              f"(start_bar={start_bar}), skip"); return None
    coin_data = filtered
    payload = {"coin_data": coin_data, "btc_daily": btc_daily,
               "start": fetch_start, "end": month_end,
               "month_start": month_start, "start_bar": start_bar}
    with open(cp, "wb") as f: pickle.dump(payload, f)
    return payload

# === Run backtest on each month ===
results = []
for y, m in chosen:
    print(f"  {y}-{m:02d}: fetching data ...")
    payload = fetch_month_data(y, m, SEED)
    if payload is None:
        results.append({"month": f"{y}-{m:02d}", "ret": None}); continue
    coin_data = payload["coin_data"]; btc_daily = payload["btc_daily"]
    start_bar = payload["start_bar"]
    print(f"    {len(coin_data)} coins, warmup={start_bar} bars, running backtest ...")
    trades, final_cap, max_conc, total_vol, liq_count, peak_eq, trough_eq = \
        strat.backtest_portfolio(coin_data, btc_daily, start_bar=start_bar,
                                 monitor_every=MONITOR_EVERY)
    ret = (final_cap / strat.TOTAL_CAPITAL - 1) * 100
    wins = sum(1 for t in trades if t["net_pnl"] > 0)
    wr = wins / len(trades) * 100 if trades else 0
    gp = sum(t["net_pnl"] for t in trades if t["net_pnl"] > 0)
    gl = abs(sum(t["net_pnl"] for t in trades if t["net_pnl"] <= 0))
    pf = gp / gl if gl > 0 else 99
    # max drawdown
    peak = strat.TOTAL_CAPITAL; cap = strat.TOTAL_CAPITAL; mdd = 0
    for t in trades:
        cap += t["net_pnl"]
        if cap > peak: peak = cap
        dd = (peak - cap) / peak * 100
        if dd > mdd: mdd = dd
    results.append({
        "month": f"{y}-{m:02d}", "ret": ret, "wr": wr, "pf": pf, "mdd": mdd,
        "trades": len(trades), "liq": liq_count, "final": final_cap,
        "peak": peak_eq, "trough": trough_eq,
    })
    print(f"    -> ret={ret:+.2f}% | WR={wr:.1f}% | PF={pf:.2f} | MDD={mdd:.1f}% | "
          f"trades={len(trades)} | liq={liq_count}")

# === Aggregate report ===
valid = [r for r in results if r["ret"] is not None]
rets = [r["ret"] for r in valid]
print(f"\n{'='*80}")
print(f"  AGGREGATE — {STRAT_NAME} | {len(valid)} months")
print(f"{'='*80}")
if not rets:
    print("  No valid results!"); sys.exit(0)
rets_sorted = sorted(rets)
avg = sum(rets) / len(rets)
median = rets_sorted[len(rets_sorted) // 2]
best = max(rets); worst = min(rets)
profitable = sum(1 for r in rets if r > 0)
std = (sum((r - avg) ** 2 for r in rets) / len(rets)) ** 0.5
avg_mdd = sum(r["mdd"] for r in valid) / len(valid)
max_mdd = max(r["mdd"] for r in valid)
total_liq = sum(r["liq"] for r in valid)
avg_trades = sum(r["trades"] for r in valid) / len(valid)
print(f"  Avg monthly return:   {avg:+.2f}%")
print(f"  Median monthly return:{median:+.2f}%")
print(f"  Std dev:              {std:.2f}%")
print(f"  Best month:           {best:+.2f}%")
print(f"  Worst month:          {worst:+.2f}%")
print(f"  Profitable months:    {profitable}/{len(rets)} ({profitable/len(rets)*100:.0f}%)")
print(f"  Avg MaxDD:            {avg_mdd:.1f}%")
print(f"  Max MaxDD:            {max_mdd:.1f}%")
print(f"  Total liquidations:   {total_liq}")
print(f"  Avg trades/month:     {avg_trades:.0f}")
print(f"\n  Per-month detail:")
print(f"  {'Month':>8} {'Ret':>8} {'WR':>6} {'PF':>5} {'MDD':>6} {'Tr':>5} {'LIQ':>4}")
print(f"  {'-'*50}")
for r in results:
    if r["ret"] is None:
        print(f"  {r['month']:>8}  NO DATA")
    else:
        print(f"  {r['month']:>8} {r['ret']:>+7.2f}% {r['wr']:>5.0f}% {r['pf']:>5.2f} "
              f"{r['mdd']:>5.1f}% {r['trades']:>5} {r['liq']:>4}")

# Save results to JSON for comparison
out_json = os.path.join(CACHE_DIR, f"results_{STRAT_NAME}_n{N_MONTHS}_s{SEED}_{MON_LABEL}.json")
with open(out_json, "w") as f: json.dump(results, f, indent=2)
print(f"\n  Results saved to: {out_json}")
