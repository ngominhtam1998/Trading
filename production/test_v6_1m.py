"""Test v6_1m single month — 1m monitoring, realistic data.
Usage: python test_v6_1m.py [YYYY] [MM] [SEED]
Default: random month, seed=777
Only 1 month at a time (1m data is huge ~40k bars/coin).
"""
import sys, os, json, random, statistics, time, pickle, gc

# Parse REAL args first (before setting dummy argv for multi_month_test import)
_real_args = sys.argv[:]
if len(_real_args) >= 3:
    _y, _m = int(_real_args[1]), int(_real_args[2])
    _seed = int(_real_args[3]) if len(_real_args) > 3 else 777
else:
    _y = _m = _seed = None

# Set dummy argv BEFORE importing multi_month_test (it reads sys.argv on import)
sys.argv = ["test_v6_1m", "12", "777", "v6_1m", "1"]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')

import strategy_v6_1m as strat
import multi_month_test as mmt
mmt.STRAT_NAME = "v6_1m"
mmt.COINS = 20  # more coins = more opportunities
mmt.strat = strat

# Patch cache_path to use _1m suffix
orig_cache_path = mmt.cache_path
def cache_path_1m(y, m, seed):
    return os.path.join(mmt.CACHE_DIR, f"m_{y}_{m:02d}_s{seed}_1m.pkl")
mmt.cache_path = cache_path_1m

# Also patch fetch_month_data to fetch 1m instead of 3m
orig_fetch = mmt.fetch_month_data
def fetch_month_data_1m(y, m, seed):
    cp = cache_path_1m(y, m, seed)
    if os.path.exists(cp):
        with open(cp, "rb") as f: return pickle.load(f)
    from datetime import timedelta
    month_start, month_end = mmt.month_range(y, m)
    fetch_start = month_start - timedelta(days=20)
    btc_daily = strat.fetch_btc_daily(fetch_start, month_end)
    if btc_daily is None:
        print(f"  No BTC daily for {y}-{m:02d}, skip"); return None
    all_symbols = strat.get_all_symbols()
    rng = random.Random(seed + y * 100 + m)
    candidates = rng.sample(all_symbols, min(mmt.COINS * 2, len(all_symbols)))
    coin_data = {}
    for coin in candidates:
        try:
            df15 = strat.fetch_klines_range(coin, "15m", fetch_start, month_end)
            df1h = strat.fetch_klines_range(coin, "1h", fetch_start, month_end)
            df1m = strat.fetch_klines_range(coin, "1m", fetch_start, month_end)
            if (df15 is not None and len(df15) > 200 and df1h is not None
                    and df1m is not None and len(df1m) > 5000):
                coin_data[coin] = {"15m": df15, "1h": df1h, "1m": df1m}
        except: pass
    if len(coin_data) < 8:
        print(f"  Only {len(coin_data)} coins for {y}-{m:02d}, skip"); return None
    sample_df = list(coin_data.values())[0]["15m"]
    month_start_bars = (sample_df["open_time"] >= month_start).sum()
    start_bar = len(sample_df) - month_start_bars
    start_bar = max(start_bar, 50)
    filtered = {k: v for k, v in coin_data.items()
                if len(v["15m"]) >= start_bar + 100
                and len(v["1m"]) >= start_bar * 15 + 750
                and len(v["1h"]) >= start_bar // 4 + 50}
    if len(filtered) < 8:
        print(f"  Only {len(filtered)} coins with enough data, skip"); return None
    payload = {"coin_data": filtered, "btc_daily": btc_daily, "start_bar": start_bar}
    with open(cp, "wb") as f: pickle.dump(payload, f)
    print(f"  {len(filtered)} coins, warmup={start_bar} bars, cached")
    return payload
mmt.fetch_month_data = fetch_month_data_1m

if __name__ == "__main__":
    # Use real args parsed at top
    if _y is not None:
        y, m, seed = _y, _m, _seed
    else:
        all_months = mmt.build_month_list()
        y, m = random.choice(all_months)
        seed = 777
    
    print(f"V6-1M SINGLE MONTH TEST — {y}-{m:02d} seed={seed}")
    print(f"Params: MC={strat.MAX_CONCURRENT} BE={strat.BE_R} TR={strat.TRAIL_R} "
          f"DLL={strat.DAILY_LOSS_LIMIT} SL={strat.SL_MULT} RR={strat.RR}")
    print("=" * 80)
    
    t0 = time.time()
    payload = fetch_month_data_1m(y, m, seed)
    if payload is None:
        print("No data!"); sys.exit(1)
    
    fetch_time = time.time() - t0
    print(f"Data fetched in {fetch_time:.0f}s")
    n_bars_1m = min(len(v["1m"]) for v in payload["coin_data"].values())
    print(f"Min 1m bars: {n_bars_1m} (~{n_bars_1m/60:.0f} hours)")
    
    print(f"\nRunning backtest (1m monitoring, ~{n_bars_1m} bars)...")
    t1 = time.time()
    trades, cash, maxc, vol, liq, peak, trough = strat.backtest_portfolio(
        payload["coin_data"], payload["btc_daily"],
        start_bar=payload["start_bar"])
    bt_time = time.time() - t1
    print(f"Backtest done in {bt_time:.0f}s")
    
    final_cap = cash
    ret = (final_cap / strat.TOTAL_CAPITAL - 1) * 100
    wins = [t for t in trades if t["net_pnl"] > 0]
    losses = [t for t in trades if t["net_pnl"] <= 0]
    wr = len(wins) / len(trades) * 100 if trades else 0
    mdd = (1 - trough / peak) * 100 if peak > 0 else 0
    min_vs_init = (trough / strat.TOTAL_CAPITAL - 1) * 100
    peak_vs_init = (peak / strat.TOTAL_CAPITAL - 1) * 100
    
    # Exit reason breakdown
    reasons = {}
    for t in trades:
        r = t["reason"].split("_")[0]  # strip _p, _close
        reasons[r] = reasons.get(r, 0) + 1
    
    gp = sum(t["net_pnl"] for t in wins)
    gl = abs(sum(t["net_pnl"] for t in losses))
    pf = gp / gl if gl > 0 else 0
    
    print(f"\n{'='*80}")
    print(f"RESULT: {y}-{m:02d}")
    print(f"  Return:     {ret:+.0f}%")
    print(f"  Final cap:  {final_cap:.0f} (initial {strat.TOTAL_CAPITAL:.0f})")
    print(f"  Peak:       {peak:.0f} ({peak_vs_init:+.0f}% vs initial)")
    print(f"  Trough:     {trough:.0f} ({min_vs_init:+.0f}% vs initial)")
    print(f"  MDD (peak): {mdd:.1f}%")
    print(f"  worst_dip:  {min_vs_init:+.0f}% (vs initial capital)")
    print(f"  WR:         {wr:.1f}% ({len(wins)}/{len(trades)})")
    print(f"  PF:         {pf:.2f}")
    print(f"  MaxConc:    {maxc}")
    print(f"  Liq:        {liq}")
    print(f"  Trades:     {len(trades)}")
    print(f"  Exit reasons: {reasons}")
    
    # Save result
    result = {"month": f"{y}-{m:02d}", "seed": seed, "ret": ret, "wr": wr,
              "mdd": mdd, "min_vs_init": min_vs_init, "trades": len(trades),
              "liq": liq, "pf": pf, "reasons": reasons,
              "params": {"MC": strat.MAX_CONCURRENT, "BE_R": strat.BE_R,
                         "TRAIL_R": strat.TRAIL_R, "DLL": strat.DAILY_LOSS_LIMIT,
                         "SL_MULT": strat.SL_MULT, "RR": strat.RR}}
    out = os.path.join(mmt.CACHE_DIR, f"results_v6_1m_{y}_{m:02d}_s{seed}.json")
    with open(out, "w") as f: json.dump(result, f, indent=2)
    print(f"\nSaved to {out}")
    
    del payload, trades
    gc.collect()
