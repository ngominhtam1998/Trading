"""Comprehensive data verification: compare live API data with script expectations."""
import json, sys, os, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from live import config
from live.binance_client import BinanceClient
from live.exchange_filters import ExchangeFilters
from live import strategy_adapter as sa
import pandas as pd

c = BinanceClient()
f = ExchangeFilters(c)
SYM = "BTCUSDT"
errors = []
passes = []

def check(name, condition, detail=""):
    if condition:
        passes.append(f"  PASS: {name}")
    else:
        errors.append(f"  FAIL: {name} — {detail}")

def section(title):
    print(f"\n[{title}]")
    sys.stdout.flush()

print(f"=== DATA VERIFY: Mode={config.MODE} Strategy={config.STRATEGY_LEVEL} ===")

# 1. KLINES 15m
section("1] KLINES 15m")
try:
    raw = c.klines(SYM, "15m", limit=5)
    check("klines returns list", isinstance(raw, list), f"got {type(raw)}")
    check("klines non-empty", len(raw) > 0, "empty")
    if raw:
        k = raw[0]
        check("kline has 12 fields", len(k) == 12, f"got {len(k)}")
        df = sa.klines_to_df(raw, drop_forming=False)
        check("klines_to_df works", df is not None and len(df) > 0, "")
        check("df has OHLCV", all(col in df.columns for col in ["open","high","low","close","volume"]), "")
        check("df open is float", str(df["open"].dtype).startswith("float"), f"dtype={df['open'].dtype}")
        df2 = sa.klines_to_df(raw, drop_forming=True)
        check("drop_forming drops last", df2 is not None and len(df2) == len(raw)-1, f"len={len(df2) if df2 is not None else 0}")
        print(f"  Sample kline: O={df.iloc[0]['open']} H={df.iloc[0]['high']} L={df.iloc[0]['low']} C={df.iloc[0]['close']} V={df.iloc[0]['volume']}")
except Exception as e:
    errors.append(f"  ERROR section 1: {e}")
    traceback.print_exc()

# 2. BTC regime
section("2] BTC regime (1d)")
try:
    regime = sa.get_btc_regime_live(c)
    check("regime is valid", regime in ("bull","bear","neutral"), f"got '{regime}'")
    print(f"  regime={regime}")
except Exception as e:
    errors.append(f"  ERROR section 2: {e}")
    traceback.print_exc()

# 3. HTF trend
section("3] HTF trend (1h)")
try:
    htf = sa.get_htf_trend(c, SYM)
    check("htf is up/down/None", htf in ("up","down",None), f"got '{htf}'")
    print(f"  htf={htf}")
except Exception as e:
    errors.append(f"  ERROR section 3: {e}")
    traceback.print_exc()

# 4. Position risk
section("4] Position risk")
try:
    positions = c.position_risk()
    check("position_risk returns list", isinstance(positions, list), f"got {type(positions)}")
    if positions:
        p = positions[0]
        check("has symbol", "symbol" in p, f"keys={list(p.keys())}")
        check("has amt (float)", "amt" in p and isinstance(p["amt"], float), "")
        check("has dir (LONG/SHORT)", "dir" in p and p["dir"] in ("LONG","SHORT"), "")
        check("has entry (float)", "entry" in p and isinstance(p["entry"], float), "")
        print(f"  Sample: {p}")
    else:
        print("  (no open positions)")
except Exception as e:
    errors.append(f"  ERROR section 4: {e}")
    traceback.print_exc()

# 5. Equity
section("5] Equity")
try:
    eq, avail = c.equity_usdt()
    check("equity is float > 0", isinstance(eq, float) and eq > 0, f"eq={eq} type={type(eq)}")
    check("avail is float >= 0", isinstance(avail, float) and avail >= 0, f"avail={avail}")
    print(f"  equity={eq:.2f} avail={avail:.2f}")
except Exception as e:
    errors.append(f"  ERROR section 5: {e}")
    traceback.print_exc()

# 6. Algo orders
section("6] Algo orders")
try:
    algo = c.open_algo_orders(SYM)
    check("open_algo_orders returns list", isinstance(algo, list), "")
    if algo:
        o = algo[0]
        check("has type", "type" in o, f"keys={list(o.keys())}")
        check("has algoId", "algoId" in o, "")
        check("has clientOrderId", "clientOrderId" in o, "")
        print(f"  Sample: {o}")
    else:
        print("  (no open algo orders)")
except Exception as e:
    errors.append(f"  ERROR section 6: {e}")
    traceback.print_exc()

# 7. Ticker
section("7] Ticker 24h")
try:
    tickers = c.ticker_24h()
    check("ticker_24h returns list", isinstance(tickers, list), "")
    check("non-empty", len(tickers) > 0, "")
    usdt = [t for t in tickers if t["symbol"].endswith("USDT")]
    check("has USDT pairs", len(usdt) > 100, f"only {len(usdt)}")
    check("ticker has quoteVolume", "quoteVolume" in tickers[0], f"keys={list(tickers[0].keys())[:5]}")
    print(f"  total={len(tickers)} usdt={len(usdt)}")
except Exception as e:
    errors.append(f"  ERROR section 7: {e}")
    traceback.print_exc()

# 8. Funding rate
section("8] Funding rate")
try:
    pi = c._request("GET", "/fapi/v1/premiumIndex", {"symbol": SYM})
    check("has markPrice", "markPrice" in pi, f"keys={list(pi.keys())}")
    check("has lastFundingRate", "lastFundingRate" in pi, "")
    fr = c.funding_rate(SYM)
    check("funding_rate returns float", isinstance(fr, float), f"got {type(fr)}")
    print(f"  markPrice={pi.get('markPrice')} funding={fr*100:.4f}%")
except Exception as e:
    errors.append(f"  ERROR section 8: {e}")
    traceback.print_exc()

# 9. Exchange filters
section("9] Exchange filters")
try:
    check("filters loaded", len(f.symbols) > 0, f"loaded {len(f.symbols)}")
    if SYM in f.symbols:
        filt = f.symbols[SYM]
        check("has step", "step" in filt, "")
        check("has tick", "tick" in filt, "")
        check("has min_notional", "min_notional" in filt, "")
        check("has qty_prec", "qty_prec" in filt, "")
        check("has price_prec", "price_prec" in filt, "")
        p = f.round_price(SYM, 62757.78231884)
        q = f.round_qty(SYM, 0.00194)
        check("round_price works", isinstance(p, float), f"got {type(p)}")
        check("round_qty works", isinstance(q, float), f"got {type(q)}")
        ok, reason = f.valid_order(SYM, 0.002, 62757.0)
        check("valid_order returns tuple", isinstance(ok, bool), "")
        print(f"  {SYM}: prec_p={filt['price_prec']} prec_q={filt['qty_prec']} minNotional={filt['min_notional']}")
        print(f"  round_price(62757.78)={p} round_qty(0.00194)={q} valid_order={ok} ({reason})")
except Exception as e:
    errors.append(f"  ERROR section 9: {e}")
    traceback.print_exc()

# 10. End-to-end analyze_symbol
section("10] End-to-end analyze_symbol")
try:
    raw_full = c.klines(SYM, config.BAR_INTERVAL, limit=config.KLINES_LOOKBACK)
    check(f"klines {config.KLINES_LOOKBACK} bars", len(raw_full) >= 200, f"got {len(raw_full)}")
    df_full = sa.klines_to_df(raw_full, drop_forming=True)
    check("klines_to_df works", df_full is not None and len(df_full) >= 200, f"len={len(df_full) if df_full is not None else 0}")
    if df_full is not None:
        df_ind = sa.strat.add_indicators(df_full)
        check("add_indicators works", df_ind is not None and len(df_ind) > 0, "")
        if df_ind is not None:
            check("has ema9", "ema9" in df_ind.columns, "")
            check("has rsi14", "rsi14" in df_ind.columns, "")
            check("has atr14", "atr14" in df_ind.columns, "")
            check("has adx14", "adx14" in df_ind.columns, "")
            last = df_ind.iloc[-1]
            check("ema9 not NaN", pd.notna(last.get("ema9")), f"ema9={last.get('ema9')}")
            check("rsi14 not NaN", pd.notna(last.get("rsi14")), f"rsi14={last.get('rsi14')}")
            check("atr14 not NaN", pd.notna(last.get("atr14")), f"atr14={last.get('atr14')}")
            print(f"  last bar: ema9={last.get('ema9'):.2f} rsi14={last.get('rsi14'):.1f} atr14={last.get('atr14'):.4f} adx14={last.get('adx14'):.1f}")
    opp = sa.analyze_symbol(c, SYM, sa.get_btc_regime_live(c))
    check("analyze_symbol returns dict/None", opp is None or isinstance(opp, dict), f"got {type(opp)}")
    if opp:
        check("has dir", "dir" in opp, f"keys={list(opp.keys())}")
        check("has lev", "lev" in opp, "")
        check("has sl", "sl" in opp, "")
        check("has tp", "tp" in opp, "")
        check("has score", "score" in opp, "")
        check("dir is LONG/SHORT", opp["dir"] in ("LONG","SHORT"), f"dir={opp['dir']}")
        check("lev > 0", isinstance(opp["lev"], int) and opp["lev"] > 0, f"lev={opp['lev']}")
        check("sl > 0", isinstance(opp["sl"], (int,float)) and opp["sl"] > 0, f"sl={opp['sl']}")
        check("tp > 0", isinstance(opp["tp"], (int,float)) and opp["tp"] > 0, f"tp={opp['tp']}")
        check("score 0-10", isinstance(opp["score"], int) and 0 <= opp["score"] <= 10, f"score={opp['score']}")
        print(f"  Opportunity: {opp}")
    else:
        print(f"  (no opportunity for {SYM} — may not meet criteria)")
except Exception as e:
    errors.append(f"  ERROR section 10: {e}")
    traceback.print_exc()

# SUMMARY
print(f"\n{'='*60}")
print(f"RESULTS: {len(passes)} PASS, {len(errors)} FAIL")
print(f"{'='*60}")
for p in passes:
    print(p)
if errors:
    print("\nERRORS:")
    for e in errors:
        print(e)
else:
    print("\nAll checks passed!")
sys.stdout.flush()
