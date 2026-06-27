"""Auto-tune v7_1m: push risk/reward higher. Lab only, NOT deployed.
Usage: python auto_tune_v7_1m.py
"""
import sys, os, json, time, gc, pickle, statistics, subprocess

_real_args = sys.argv[:]
sys.argv = ["auto_tune_v7", "12", "777", "v6_1m", "1"]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')

import multi_month_test as mmt
mmt.STRAT_NAME = "v7_1m"
mmt.COINS = 20

TEST_MONTHS = [
    (2024, 8, 777),
    (2024, 12, 777),
    (2025, 3, 777),
    (2025, 6, 777),
    (2025, 8, 777),
]

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_cache_months")

def cache_path(y, m, seed):
    return os.path.join(CACHE_DIR, f"m_{y}_{m:02d}_s{seed}_1m.pkl")

# v7_1m round 2: BE0.3 baseline, push position size + combos
COMBOS = [
    # Baseline (v7_1m with BE0.3)
    {"name": "BE0.3_BASE", "params": {}},
    # 1. Bigger position
    {"name": "BE0.3_POS35", "params": {"POSITION_PCT": 35.0}},
    {"name": "BE0.3_POS40", "params": {"POSITION_PCT": 40.0}},
    {"name": "BE0.3_POS45", "params": {"POSITION_PCT": 45.0}},
    # 2. More concurrent
    {"name": "BE0.3_MC20", "params": {"MAX_CONCURRENT": 20}},
    # 3. Higher DLL
    {"name": "BE0.3_DLL15", "params": {"DAILY_LOSS_LIMIT": 15.0}},
    {"name": "BE0.3_DLL18", "params": {"DAILY_LOSS_LIMIT": 18.0}},
    # 4. Earlier trail
    {"name": "BE0.3_TR1.5", "params": {"TRAIL_R": 1.5}},
    {"name": "BE0.3_TR1.0", "params": {"TRAIL_R": 1.0}},
    # 5. Combos: BE0.3 + big pos
    {"name": "BE0.3_POS35_TR1.5", "params": {"POSITION_PCT": 35.0, "TRAIL_R": 1.5}},
    {"name": "BE0.3_POS40_TR1.5", "params": {"POSITION_PCT": 40.0, "TRAIL_R": 1.5}},
    {"name": "BE0.3_POS40_DLL18", "params": {"POSITION_PCT": 40.0, "DAILY_LOSS_LIMIT": 18.0}},
    {"name": "BE0.3_POS40_MC20", "params": {"POSITION_PCT": 40.0, "MAX_CONCURRENT": 20}},
    # 6. Max aggression with BE0.3
    {"name": "BE0.3_POS40_TR1.5_DLL18", "params": {"POSITION_PCT": 40.0, "TRAIL_R": 1.5, "DAILY_LOSS_LIMIT": 18.0}},
    {"name": "BE0.3_POS45_TR1.5", "params": {"POSITION_PCT": 45.0, "TRAIL_R": 1.5}},
    {"name": "BE0.3_POS45_DLL18", "params": {"POSITION_PCT": 45.0, "DAILY_LOSS_LIMIT": 18.0}},
    # 7. BE even earlier
    {"name": "BE0.2", "params": {"BE_R": 0.2}},
    {"name": "BE0.2_POS40", "params": {"BE_R": 0.2, "POSITION_PCT": 40.0}},
    {"name": "BE0.1", "params": {"BE_R": 0.1}},
    # 8. SL tighter (smaller R = BE triggers faster relative to SL)
    {"name": "BE0.3_SL0.5", "params": {"SL_MULT": 0.5}},
    {"name": "BE0.3_SL0.45", "params": {"SL_MULT": 0.45}},
    {"name": "BE0.3_SL0.5_POS40", "params": {"SL_MULT": 0.5, "POSITION_PCT": 40.0}},
]

def run_combo_worker():
    import strategy_v7_1m as strat
    
    combo_idx = int(os.environ.get("TUNE_COMBO_IDX", "0"))
    combo = COMBOS[combo_idx]
    
    for k, v in combo["params"].items():
        setattr(strat, k, v)
        if k == "MAX_HOLD_BARS":
            strat.MAX_HOLD_1M = v * strat.BARS1_PER_15
    
    results = []
    for y, m, seed in TEST_MONTHS:
        cp = cache_path(y, m, seed)
        if not os.path.exists(cp):
            results.append({"month": f"{y}-{m:02d}", "ret": None})
            continue
        with open(cp, "rb") as f:
            payload = pickle.load(f)
        try:
            trades, cash, maxc, vol, liq, peak, trough = strat.backtest_portfolio(
                payload["coin_data"], payload["btc_daily"],
                start_bar=payload["start_bar"])
            ret = (cash / strat.TOTAL_CAPITAL - 1) * 100
            wins = [t for t in trades if t["net_pnl"] > 0]
            wr = len(wins) / len(trades) * 100 if trades else 0
            min_vs_init = (trough / strat.TOTAL_CAPITAL - 1) * 100
            gp = sum(t["net_pnl"] for t in wins)
            gl = abs(sum(t["net_pnl"] for t in trades if t["net_pnl"] <= 0))
            pf = gp / gl if gl > 0 else 0
            reasons = {}
            for t in trades:
                r = t["reason"].split("_")[0]
                reasons[r] = reasons.get(r, 0) + 1
            results.append({
                "month": f"{y}-{m:02d}", "ret": ret, "wr": wr,
                "min_vs_init": min_vs_init, "liq": liq, "pf": pf,
                "trades": len(trades), "reasons": reasons, "maxc": maxc,
            })
            del trades
        except Exception as e:
            results.append({"month": f"{y}-{m:02d}", "ret": None, "err": str(e)})
        gc.collect()
    
    valid = [r for r in results if r.get("ret") is not None]
    if valid:
        rets = [r["ret"] for r in valid]
        dips = [r["min_vs_init"] for r in valid]
        wrs = [r["wr"] for r in valid]
        avg = statistics.mean(rets)
        med = statistics.median(rets)
        std = statistics.stdev(rets) if len(rets) > 1 else 0
        prof = sum(1 for r in rets if r > 0)
        wr_avg = statistics.mean(wrs)
        worst_dip = min(dips)
        liq_total = sum(r["liq"] for r in valid)
        sharpe = avg / std if std > 0 else 0
        print(f"COMBO={combo['name']}|avg={avg:+.0f}|med={med:+.0f}|std={std:.0f}|"
              f"prof={prof}/{len(valid)}|WR={wr_avg:.1f}|dip={worst_dip:+.0f}|"
              f"liq={liq_total}|sharpe={sharpe:.2f}")
        for r in valid:
            print(f"  {r['month']}: ret={r['ret']:+.0f} WR={r['wr']:.0f}% "
                  f"dip={r['min_vs_init']:+.0f} liq={r['liq']} pf={r['pf']:.1f} "
                  f"tr={r['trades']} mc={r['maxc']} {r['reasons']}")
    else:
        print(f"COMBO={combo['name']}|NO_VALID_RESULTS")

if __name__ == "__main__":
    if os.environ.get("TUNE_COMBO_IDX") is not None:
        run_combo_worker()
    else:
        print(f"AUTO-TUNE v7_1m | {len(COMBOS)} combos x {len(TEST_MONTHS)} months")
        print(f"Baseline: TR=2.0 BE=0.5 SL=0.6 RR=12 MC=15 POS=30% LEV=25 DLL=12%")
        print("=" * 90)
        
        all_results = []
        for i, combo in enumerate(COMBOS):
            print(f"\n[{i+1}/{len(COMBOS)}] {combo['name']} ...")
            sys.stdout.flush()
            env = os.environ.copy()
            env["TUNE_COMBO_IDX"] = str(i)
            try:
                r = subprocess.run(
                    [sys.executable, os.path.abspath(__file__)],
                    env=env, capture_output=True, text=True, timeout=600)
                out = r.stdout.strip()
                for line in out.split("\n"):
                    if line.startswith("COMBO=") or line.startswith("  "):
                        print(line)
                for line in out.split("\n"):
                    if line.startswith("COMBO="):
                        parts = line.split("|")
                        name = parts[0].split("=")[1]
                        avg = float(parts[1].split("=")[1])
                        med = float(parts[2].split("=")[1])
                        std = float(parts[3].split("=")[1])
                        prof = parts[4].split("=")[1]
                        wr = float(parts[5].split("=")[1])
                        dip = float(parts[6].split("=")[1])
                        liq = int(parts[7].split("=")[1])
                        sharpe = float(parts[8].split("=")[1])
                        all_results.append({
                            "name": name, "avg": avg, "med": med, "std": std,
                            "prof": prof, "wr": wr, "dip": dip, "liq": liq,
                            "sharpe": sharpe,
                        })
            except subprocess.TimeoutExpired:
                print(f"  TIMEOUT")
            except Exception as e:
                print(f"  ERROR: {e}")
        
        print(f"\n{'='*90}")
        print("ALL RESULTS (sorted by avg return):")
        print("-" * 90)
        all_results.sort(key=lambda x: x["avg"], reverse=True)
        for r in all_results:
            ok = "[OK]" if r["dip"] >= -15 and r["liq"] <= 3 else "[--]"
            print(f"  {r['name']:>25}  avg={r['avg']:+8.0f}  med={r['med']:+8.0f}  "
                  f"std={r['std']:>6.0f}  prof={r['prof']}  WR={r['wr']:>5.1f}%  "
                  f"dip={r['dip']:+4.0f}  liq={r['liq']}  Sharpe={r['sharpe']:.2f}  {ok}")
        
        print(f"\n{'='*90}")
        print("SAFE RESULTS (dip >= -15%, liq <= 3), sorted by Sharpe:")
        print("-" * 90)
        safe = [r for r in all_results if r["dip"] >= -15 and r["liq"] <= 3]
        safe.sort(key=lambda x: x["sharpe"], reverse=True)
        for i, r in enumerate(safe):
            print(f"  #{i+1} {r['name']:>25}  avg={r['avg']:+8.0f}  med={r['med']:+8.0f}  "
                  f"std={r['std']:>6.0f}  prof={r['prof']}  WR={r['wr']:>5.1f}%  "
                  f"dip={r['dip']:+4.0f}  liq={r['liq']}  Sharpe={r['sharpe']:.2f}")
        
        if safe:
            best = safe[0]
            print(f"\nBEST: {best['name']}")
            print(f"  avg={best['avg']:+.0f}  med={best['med']:+.0f}  "
                  f"Sharpe={best['sharpe']:.2f}  dip={best['dip']:+.0f}  liq={best['liq']}")
            combo = next(c for c in COMBOS if c["name"] == best["name"])
            print(f"  Params: {combo['params']}")
            
            out_path = os.path.join(CACHE_DIR, f"tune_v7_1m_{int(time.time())}.json")
            with open(out_path, "w") as f:
                json.dump({"results": all_results, "best": best,
                          "best_params": combo["params"]}, f, indent=2)
            print(f"\nResults saved to {out_path}")
