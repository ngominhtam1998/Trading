"""Compare LV6 with vs without daily loss limit on mock data 2024-2026.

Generates synthetic OHLCV data for 30 coins + BTC daily, then runs the LV6
backtest twice: once with DAILY_LOSS_LIMIT=18 (default) and once with
DAILY_LOSS_LIMIT=1000 (effectively disabled).
"""
import sys, os, random, numpy as np, pandas as pd
from datetime import datetime, timedelta
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import strategy_aggressive_lv6 as strat

random.seed(777)
np.random.seed(777)

START_DT = datetime(2026, 3, 1)
END_DT = datetime(2026, 6, 1)
COINS = 10
BAR_HOURS = 0.25


def generate_btc_daily(start, end):
    days = int((end - start).total_seconds() / 86400) + 250
    dates = [start - timedelta(days=250) + timedelta(days=i) for i in range(days)]
    price = 42000.0
    prices = []
    for i in range(days):
        # random walk with bull/bear/neutral regimes
        regime = (i // 60) % 3  # 0=bull, 1=bear, 2=neutral
        drift = [0.08, -0.06, 0.0][regime] / 100
        ret = np.random.normal(drift, 0.025)
        price *= (1 + ret)
        prices.append(price)
    df = pd.DataFrame({
        "open_time": dates,
        "open": prices,
        "high": [p * (1 + abs(np.random.normal(0, 0.01))) for p in prices],
        "low": [p * (1 - abs(np.random.normal(0, 0.01))) for p in prices],
        "close": prices,
        "volume": [abs(np.random.normal(1e9, 2e8)) for _ in prices],
        "quote_volume": [abs(np.random.normal(3e10, 5e9)) for _ in prices],
        "trades": [abs(np.random.normal(2e6, 3e5)) for _ in prices],
        "tbb": [0] * len(prices),
        "tbq": [0] * len(prices),
        "ignore": [0] * len(prices),
    })
    df["close_time"] = df["open_time"] + timedelta(days=1)
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
    df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
    mask = df["open_time"] >= start
    return df[mask].reset_index(drop=True)


def generate_coin_data(start, end, base_price):
    """Generate 1h and 15m OHLCV for one coin."""
    total_hours = int((end - start).total_seconds() / 3600) + 1
    hours_1h = [start + timedelta(hours=i) for i in range(total_hours)]
    price = base_price
    opens = []
    highs = []
    lows = []
    closes = []
    volumes = []
    quote_volumes = []
    trades = []
    for i in range(total_hours):
        regime = (i // 200) % 3
        drift = [0.05, -0.04, 0.0][regime] / 100
        vol = 0.008 + 0.004 * (i % 50 < 10)  # higher vol 20% of time
        ret = np.random.normal(drift, vol)
        o = price
        c = price * (1 + ret)
        h = max(o, c) * (1 + abs(np.random.normal(0, vol * 0.5)))
        l = min(o, c) * (1 - abs(np.random.normal(0, vol * 0.5)))
        v = abs(np.random.normal(1e6, 2e5)) * (1.5 if i % 50 < 10 else 1)
        qv = v * c
        opens.append(o); highs.append(h); lows.append(l); closes.append(c)
        volumes.append(v); quote_volumes.append(qv); trades.append(abs(np.random.normal(5e3, 1e3)))
        price = c
    df1h = pd.DataFrame({
        "open_time": hours_1h, "open": opens, "high": highs, "low": lows, "close": closes,
        "volume": volumes, "close_time": [t + timedelta(hours=1) for t in hours_1h],
        "quote_volume": quote_volumes, "trades": trades, "tbb": 0, "tbq": 0, "ignore": 0,
    })
    # build 15m from 1h using interpolation
    rows15 = []
    for i in range(len(df1h) - 1):
        o = df1h.iloc[i]["open"]
        c = df1h.iloc[i]["close"]
        h = df1h.iloc[i]["high"]
        l = df1h.iloc[i]["low"]
        for j in range(4):
            t = df1h.iloc[i]["open_time"] + timedelta(minutes=15 * j)
            if j == 0:
                oc = o
            elif j == 3:
                oc = c
            else:
                # interpolate
                alpha = j / 3
                oc = o * (1 - alpha) + c * alpha
            # add noise
            oc *= (1 + np.random.normal(0, 0.001))
            oh = max(oc, oc * (1 + abs(np.random.normal(0, 0.003))))
            ol = min(oc, oc * (1 - abs(np.random.normal(0, 0.003))))
            v = volumes[i] / 4
            qv = quote_volumes[i] / 4
            rows15.append([t, oc, oh, ol, oc, v, t + timedelta(minutes=15), qv, trades[i] / 4, 0, 0, 0])
    df15 = pd.DataFrame(rows15, columns=["open_time", "open", "high", "low", "close", "volume",
                                          "close_time", "quote_volume", "trades", "tbb", "tbq", "ignore"])
    return {"15m": df15, "1h": df1h}


def run_backtest(daily_limit):
    log(f"  Setting DAILY_LOSS_LIMIT={daily_limit}%...")
    strat.DAILY_LOSS_LIMIT = daily_limit
    log(f"  Generating BTC daily...")
    btc_daily = generate_btc_daily(START_DT, END_DT)
    all_symbols = [f"COIN{i}USDT" for i in range(COINS)]
    coin_data = {}
    for i, sym in enumerate(all_symbols):
        log(f"  Generating {sym}...")
        base = 0.01 + (i * 0.5)  # mix of low and higher prices
        coin_data[sym] = generate_coin_data(START_DT, END_DT, base)
    log(f"  Running backtest with DAILY_LOSS_LIMIT={daily_limit}%...")
    trades, final_cap, max_conc, total_vol, liq_count, peak_eq, trough_eq = strat.backtest_portfolio(coin_data, btc_daily)
    log(f"  Backtest done: {len(trades)} trades, final=${final_cap:.2f}")
    return trades, final_cap, max_conc, total_vol, liq_count, peak_eq, trough_eq


def summarize(label, trades, final_cap, max_conc, total_vol, liq_count, peak_eq, trough_eq):
    total_ret = (final_cap / strat.TOTAL_CAPITAL - 1) * 100
    max_dd = (peak_eq - trough_eq) / peak_eq * 100 if peak_eq > 0 else 0
    wins = sum(1 for t in trades if t["net_pnl"] > 0)
    losses = sum(1 for t in trades if t["net_pnl"] <= 0)
    wr = wins / len(trades) * 100 if trades else 0
    avg_win = np.mean([t["net_pnl"] for t in trades if t["net_pnl"] > 0]) if wins else 0
    avg_loss = np.mean([t["net_pnl"] for t in trades if t["net_pnl"] <= 0]) if losses else 0
    pf = sum(t["net_pnl"] for t in trades if t["net_pnl"] > 0) / abs(sum(t["net_pnl"] for t in trades if t["net_pnl"] < 0)) if losses else 0
    log(f"\n{'='*70}")
    log(f"  {label}")
    log(f"{'='*70}")
    log(f"  Final capital: ${final_cap:.2f} | Total return: {total_ret:+.2f}%")
    log(f"  Peak: ${peak_eq:.2f} | Trough: ${trough_eq:.2f} | MaxDD: {max_dd:.1f}%")
    log(f"  Trades: {len(trades)} | Wins: {wins} | Losses: {losses} | WR: {wr:.1f}%")
    log(f"  Avg win: ${avg_win:.2f} | Avg loss: ${avg_loss:.2f} | PF: {pf:.2f}")
    log(f"  Liquidations: {liq_count} | Max concurrent: {max_conc}")
    log(f"  Total volume: ${total_vol:,.2f}")
    return {
        "label": label, "final_cap": final_cap, "total_ret": total_ret, "max_dd": max_dd,
        "trades": len(trades), "wins": wins, "losses": losses, "wr": wr, "pf": pf,
        "liq": liq_count, "peak": peak_eq, "trough": trough_eq,
    }


import sys
out_path = os.path.join(os.path.dirname(__file__), "test_lv6_daily_limit_mock_output.txt")
fout = open(out_path, "w", encoding="utf-8")

def log(*args):
    line = " ".join(str(a) for a in args)
    fout.write(line + "\n")
    fout.flush()

log(f"LV6 DAILY LOSS LIMIT COMPARISON — Mock data {START_DT.strftime('%b %Y')} -> {END_DT.strftime('%b %Y')}")
log(f"Base capital: ${strat.TOTAL_CAPITAL} | Coins: {COINS}")
log(f"Generating mock data...")

res_daily = summarize("LV6 DAILY_LIMIT=18%", *run_backtest(18.0))
res_nodaily = summarize("LV6 DAILY_LIMIT=1000% (disabled)", *run_backtest(1000.0))

log(f"\n{'='*70}")
log(f"  COMPARISON")
log(f"{'='*70}")
log(f"  Return:        {res_daily['total_ret']:+.2f}% vs {res_nodaily['total_ret']:+.2f}%  (diff: {res_nodaily['total_ret'] - res_daily['total_ret']:+.2f}%)")
log(f"  MaxDD:         {res_daily['max_dd']:.1f}% vs {res_nodaily['max_dd']:.1f}%  (diff: {res_nodaily['max_dd'] - res_daily['max_dd']:+.1f}%)")
log(f"  Trades:        {res_daily['trades']} vs {res_nodaily['trades']}")
log(f"  Liquidations:  {res_daily['liq']} vs {res_nodaily['liq']}")
log(f"  Profit factor: {res_daily['pf']:.2f} vs {res_nodaily['pf']:.2f}")

if res_nodaily['max_dd'] > res_daily['max_dd'] * 1.2 and res_nodaily['total_ret'] < res_daily['total_ret'] * 1.05:
    log("\n  => Daily loss limit IMPROVES risk-adjusted return (lower MaxDD, similar return)")
elif res_nodaily['total_ret'] > res_daily['total_ret'] * 1.2 and res_nodaily['max_dd'] <= res_daily['max_dd'] * 1.2:
    log("\n  => Disabling daily loss limit improves return without much extra drawdown")
else:
    log("\n  => Trade-off: daily limit reduces drawdown but may also reduce final return")

fout.close()
