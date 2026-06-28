"""Run opus replay across MANY distinct market regimes and summarise.

Picks 7-day windows in the past, each tagged with the BTC regime at the time, so
we can see whether opus survives bear / choppy / high-volatility periods — not
just the recent friendly window. Runs the windows in PARALLEL (one process each)
to save wall-clock time.

Usage:
    python test_opus_regimes.py
"""
import subprocess, sys, os, re, shutil
from concurrent.futures import ThreadPoolExecutor

# (start_date, label, regime_description)
WINDOWS = [
    ("2024-03-04", "W1 bull-rally",   "Mar 2024: BTC 60k->70k strong uptrend"),
    ("2024-04-13", "W2 crash",        "Apr 2024: BTC 70k->60k sharp correction"),
    ("2024-08-04", "W3 choppy",       "Aug 2024: BTC sideways 60-65k, range-bound"),
    ("2024-09-08", "W4 sep dump",     "Sep 2024: BTC 56k choppy-down, weak"),
    ("2025-02-23", "W5 feb crash",    "Feb 2025: BTC 100k->80k high volatility drop"),
    ("2025-04-06", "W6 tariff-vol",   "Apr 2025: BTC 85k large swings, news-driven"),
    ("2025-08-01", "W7 aug grind",    "Aug 2025: BTC 105-113k slow grind up"),
]

DAYS = 7
NSYM = 30

def run_one(start, label, desc):
    cmd = [sys.executable, "test_opus_replay.py", str(DAYS), str(NSYM), "777", start]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=1200,
                           cwd=os.path.dirname(os.path.abspath(__file__)))
    except subprocess.TimeoutExpired:
        return label, desc, "TIMEOUT", {}
    out = p.stdout + p.stderr
    fields = {}
    m = re.search(r"PORTFOLIO: \$[\d.]+ -> \$([\d,.]+) \(([+\-][\d.]+)%\)", out)
    if m:
        fields["final"] = m.group(1); fields["ret%"] = m.group(2)
    m = re.search(r"HIGHEST \$([\d,.]+)\s+\|\s+LOWEST \$([\d,.]+)\s+\|\s+end", out)
    if m:
        fields["peak"] = m.group(1); fields["trough"] = m.group(2)
    m = re.search(r"Trades: (\d+) \| WR: ([\d.]+)% \| PF: ([\d.]+) \| MaxDD: ([\d.]+)%", out)
    if m:
        fields["trades"] = m.group(1); fields["wr"] = m.group(2)
        fields["pf"] = m.group(3); fields["mdd"] = m.group(4)
    m = re.search(r"Liquidations: (\d+)", out)
    if m:
        fields["liq"] = m.group(1)
    status = "OK" if fields.get("trades") else ("NO_TRADES" if "NO TRADES" in out else "PARSE_FAIL")
    return label, desc, status, fields

def main():
    print(f"OPUS REGIME SWEEP — {len(WINDOWS)} windows x {DAYS}d x {NSYM} symbols\n")
    results = []
    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = [ex.submit(run_one, s, lab, dsc) for s, lab, dsc in WINDOWS]
        for f in futs:
            results.append(f.result())

    # table
    print("\n" + "="*110)
    print(f"{'Window':<16}{'Status':<11}{'Start':<11}{'Trades':>7}{'WR':>7}{'PF':>7}{'MaxDD':>7}{'Liq':>5}  Equity: peak / trough / final")
    print("-"*110)
    n_ok = 0; rets = []
    for lab, desc, status, f in results:
        start = desc.split(":")[0]
        if status == "OK":
            n_ok += 1
            print(f"{lab:<16}{status:<11}{start:<11}{f.get('trades','?'):>7}{f.get('wr','?'):>6}%"
                  f"{f.get('pf','?'):>7}{f.get('mdd','?'):>6}%{f.get('liq','?'):>5}  "
                  f"${f.get('peak','?')} / ${f.get('trough','?')} / ${f.get('final','?')}  ({f.get('ret%','?')}%)")
            try: rets.append(float(f.get("ret%","0").replace(",","")))
            except: pass
        else:
            print(f"{lab:<16}{status:<11}{start:<11}{'-':>7}{'-':>7}{'-':>7}{'-':>7}{'-':>5}  {desc}")
    print("="*110)
    print(f"Profitable windows: {sum(1 for r in rets if r>0)}/{len(rets)}  | "
          f"avg ret {sum(rets)/len(rets):+.1f}%  | best {max(rets):+.1f}%  | worst {min(rets):+.1f}%\n")
    print("Reading guide:")
    print("  - Want MOST windows profitable with PF>1 and Liq=0 across bull/bear/choppy.")
    print("  - A loss in a crash window (W2/W5) is informative, not disqualifying, IF DD is bounded.")
    print("  - big Liq count in ANY window = reject for live.")

if __name__ == "__main__":
    main()
