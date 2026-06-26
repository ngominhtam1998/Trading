"""Auto-tune v6_3m: find highest stable return with worst_dip <= 10%.

Usage: python auto_tune_v6_3m.py
Each combo runs in separate subprocess (RAM-safe).
"""
import sys, os, json, statistics, subprocess, time

N_SEEDS = 2
N_MONTHS = 4      # 4 months per seed = 8 total per combo
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_cache_months")
RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tune_results")
os.makedirs(RESULTS_DIR, exist_ok=True)

MAX_WORST_DIP = 10.0  # accept if worst_dip >= -10%

# === ALL COMBOS FROM PREVIOUS ROUNDS + NEW ONES ===
COMBOS = [
    # Remaining from round 5 (combo 6-10)
    {"name": "MC10_B0.5_DLL8_TR2", "params": {"MAX_CONCURRENT": 10, "BE_R": 0.5, "DAILY_LOSS_LIMIT": 8.0, "TRAIL_R": 2.0}},
    {"name": "MC8_P15_DLL5_RR6", "params": {"MAX_CONCURRENT": 8, "POSITION_PCT": 15.0, "BE_R": 0.5, "DAILY_LOSS_LIMIT": 5.0, "RR": 6.0}},
    {"name": "MC8_P15_DLL5_TR2", "params": {"MAX_CONCURRENT": 8, "POSITION_PCT": 15.0, "BE_R": 0.5, "DAILY_LOSS_LIMIT": 5.0, "TRAIL_R": 2.0}},
    {"name": "MC10_P10_B0.5_DLL8", "params": {"MAX_CONCURRENT": 10, "POSITION_PCT": 10.0, "BE_R": 0.5, "DAILY_LOSS_LIMIT": 8.0}},
    {"name": "MC10_P10_B0.5_DLL5", "params": {"MAX_CONCURRENT": 10, "POSITION_PCT": 10.0, "BE_R": 0.5, "DAILY_LOSS_LIMIT": 5.0}},
]

SEEDS = [777, 123]

WORKER_SCRIPT = r'''
import sys, os, json, statistics, gc
sys.argv = ["worker", "12", "777", "v6_3m", "1"]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import strategy_v6_3m as strat
import multi_month_test as mmt
mmt.STRAT_NAME = "v6_3m"
mmt.COINS = 20
mmt.strat = strat

params = json.loads(os.environ["TUNE_PARAMS"])
seeds = json.loads(os.environ["TUNE_SEEDS"])
n_months = int(os.environ["TUNE_N_MONTHS"])

for k, v in params.items():
    setattr(strat, k, v)

all_results = []
for seed in seeds:
    import random
    random.seed(seed)
    all_months = mmt.build_month_list()
    chosen = random.sample(all_months, min(n_months, len(all_months)))
    chosen.sort()
    for y, m in chosen:
        payload = mmt.fetch_month_data(y, m, seed)
        if payload is None: continue
        trades, cash, maxc, vol, liq, peak, trough = strat.backtest_portfolio(
            payload["coin_data"], payload["btc_daily"], start_bar=payload["start_bar"])
        ret = (cash / strat.TOTAL_CAPITAL - 1) * 100
        wins = [t for t in trades if t["net_pnl"] > 0]
        wr = len(wins) / len(trades) * 100 if trades else 0
        min_vs_init = (trough / strat.TOTAL_CAPITAL - 1) * 100
        all_results.append({"seed": seed, "month": f"{y}-{m:02d}",
            "ret": ret, "wr": wr, "trades": len(trades), "liq": liq,
            "min_vs_init": min_vs_init})
        del payload, trades
        gc.collect()

rets = [r["ret"] for r in all_results]
wrs = [r["wr"] for r in all_results]
min_inits = [r["min_vs_init"] for r in all_results]
result = {
    "n_months": len(all_results),
    "avg_ret": statistics.mean(rets) if rets else 0,
    "med_ret": statistics.median(rets) if rets else 0,
    "std_ret": statistics.stdev(rets) if len(rets) > 1 else 0,
    "avg_wr": statistics.mean(wrs) if wrs else 0,
    "profitable": sum(1 for r in rets if r > 0),
    "total_months": len(all_results),
    "worst_dip": min(min_inits) if min_inits else 0,
    "results": all_results
}
print(json.dumps(result))
'''

if __name__ == "__main__":
    worker_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp_worker.py")
    
    print(f"AUTO-TUNE v6_3m | {len(COMBOS)} combos x {len(SEEDS)} seeds x {N_MONTHS} months")
    print(f"Filter: worst_dip >= -{MAX_WORST_DIP}%")
    print("=" * 90)
    
    all_stats = []
    for i, combo in enumerate(COMBOS):
        name = combo["name"]
        params = combo["params"]
        with open(worker_path, "w", encoding="utf-8") as f:
            f.write(WORKER_SCRIPT)
        print(f"\n[{i+1}/{len(COMBOS)}] {name} ...", flush=True)
        try:
            env = os.environ.copy()
            env["TUNE_PARAMS"] = json.dumps(params)
            env["TUNE_SEEDS"] = json.dumps(SEEDS)
            env["TUNE_N_MONTHS"] = str(N_MONTHS)
            env["PYTHONIOENCODING"] = "utf-8"
            result = subprocess.run(
                [sys.executable, worker_path],
                capture_output=True, text=True, timeout=1200, encoding="utf-8",
                env=env
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split("\n")
                stats = json.loads(lines[-1])
                stats["name"] = name
                stats["params"] = params
                all_stats.append(stats)
                ok = "OK" if stats["worst_dip"] >= -MAX_WORST_DIP else "RISK"
                print(f"  avg={stats['avg_ret']:+.0f}%  med={stats['med_ret']:+.0f}%  "
                      f"std={stats['std_ret']:.0f}  "
                      f"prof={stats['profitable']}/{stats['total_months']}  "
                      f"WR={stats['avg_wr']:.1f}%  "
                      f"dip={stats['worst_dip']:+.0f}%  [{ok}]")
            else:
                print(f"  ERROR: {result.stderr[:300]}")
        except subprocess.TimeoutExpired:
            print(f"  TIMEOUT")
        except Exception as e:
            print(f"  EXCEPTION: {e}")
    
    try: os.remove(worker_path)
    except: pass
    
    if not all_stats:
        print("No results!"); sys.exit(1)
    
    # Filter: worst_dip <= MAX_WORST_DIP
    safe = [s for s in all_stats if s["worst_dip"] >= -MAX_WORST_DIP]
    
    print("\n" + "=" * 90)
    print(f"ALL RESULTS (sorted by avg return):")
    print("-" * 90)
    for s in sorted(all_stats, key=lambda x: -x["avg_ret"]):
        ok = "OK" if s["worst_dip"] >= -MAX_WORST_DIP else "RISK"
        print(f"  {s['name']:>22}  avg={s['avg_ret']:+8.0f}%  med={s['med_ret']:+8.0f}%  "
              f"std={s['std_ret']:>6.0f}  prof={s['profitable']}/{s['total_months']}  "
              f"WR={s['avg_wr']:>5.1f}%  dip={s['worst_dip']:+.0f}%  [{ok}]")
    
    if safe:
        print(f"\n{'=' * 90}")
        print(f"SAFE RESULTS (worst_dip >= -{MAX_WORST_DIP}%), sorted by Sharpe:")
        print("-" * 90)
        ranked = sorted(safe, key=lambda s: s["avg_ret"] / max(s["std_ret"], 1), reverse=True)
        for rank, s in enumerate(ranked, 1):
            sharpe = s["avg_ret"] / max(s["std_ret"], 1)
            print(f"  #{rank} {s['name']:>22}  avg={s['avg_ret']:+8.0f}%  med={s['med_ret']:+8.0f}%  "
                  f"std={s['std_ret']:>6.0f}  prof={s['profitable']}/{s['total_months']}  "
                  f"WR={s['avg_wr']:>5.1f}%  dip={s['worst_dip']:+.0f}%  Sharpe={sharpe:.2f}")
        
        out = os.path.join(RESULTS_DIR, f"tune_{int(time.time())}.json")
        with open(out, "w") as f:
            json.dump(ranked, f, indent=2)
        print(f"\nResults saved to {out}")
        
        best = ranked[0]
        print(f"\nBEST: {best['name']}")
        print(f"  avg={best['avg_ret']:+.0f}%  med={best['med_ret']:+.0f}%  "
              f"Sharpe={best['avg_ret']/max(best['std_ret'],1):.2f}  "
              f"dip={best['worst_dip']:+.0f}%")
        print(f"  Params: {best['params']}")
    else:
        print("\nNo safe results!")
