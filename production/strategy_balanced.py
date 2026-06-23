"""V14 COMPOUND - Fixed % of current equity (lãi kép).
Same as V14 production but position size = current_equity * 7% instead of fixed $70.
- Win → equity up → position size up (compound)
- Lose → equity down → position size down (de-risk)
- Risk per trade stays constant at 7% of equity
- Max 10 concurrent = max 70% deployed, 30% buffer for floating PnL
"""
import requests, pandas as pd, time, urllib3, os, random
from datetime import datetime, timedelta
from collections import Counter
urllib3.disable_warnings()

random.seed(777)

FEE_PCT = 0.01; FUNDING_RATE = 0.0005; FUNDING_INTERVAL_BARS = 16
TOTAL_CAPITAL = 1000.0; MAX_CONCURRENT = 10
POSITION_PCT = 7.0        # was 10
DAILY_LOSS_LIMIT = 5.0    # was 8
MIN_SCORE = 6             # was 5
MAX_LEVERAGE = 10         # was 20
COINS_PER_MONTH = 50
# === REALISTIC EXECUTION CONSTRAINTS ===
MIN_NOTIONAL = 5.0        # Binance Futures min notional per order ($5 for most pairs)
MAX_VOL_PCT = 10.0        # Max % of bar quote volume our order can use (liquidity check)
# If our order > 10% of bar volume → partial fill or skip on entry
# Real liquidation thresholds (from user's experience with low-cap coins):
# 25x -> ROE -55% = liq (price move 2.2%)
# 10x -> ROE -85% = liq (price move 8.5%)
# 5x  -> ROE -95% = liq (price move 19%)
# Formula: liq_roe = 55 + 30*(25-lev)/15, clamped [50, 95]
LIQ_SAFETY_ROE = 45.0      # max ROE loss at SL before reducing leverage (% of margin)

def get_all_symbols():
    r = requests.get("https://fapi.binance.com/fapi/v1/exchangeInfo", timeout=30, verify=False)
    data = r.json()
    return [s["symbol"] for s in data["symbols"]
            if s["quoteAsset"] == "USDT" and s["contractType"] == "PERPETUAL" and s["status"] == "TRADING"]

def fetch_klines_range(symbol, interval, start_dt, end_dt):
    start_ms = int(start_dt.timestamp() * 1000); end_ms = int(end_dt.timestamp() * 1000)
    url = "https://api.binance.com/api/v3/klines"
    all_data = []; cur = start_ms
    while cur < end_ms:
        try:
            r = requests.get(url, params={"symbol": symbol, "interval": interval,
                "startTime": cur, "endTime": end_ms, "limit": 1000}, timeout=15, verify=False)
            r.raise_for_status(); data = r.json()
            if not data: break
            all_data.extend(data)
            ms = {"15m":15*60*1000, "1h":60*60*1000, "1d":24*60*60*1000}[interval]
            cur = data[-1][0] + ms; time.sleep(0.06)
        except: break
    if not all_data: return None
    df = pd.DataFrame(all_data, columns=["open_time","open","high","low","close","volume",
        "close_time","quote_volume","trades","tbb","tbq","ignore"])
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    for c in ["open","high","low","close","volume","quote_volume"]: df[c] = df[c].astype(float)
    df = df[(df["open_time"] >= start_dt) & (df["open_time"] < end_dt)]
    return df if len(df) > 0 else None

def fetch_btc_daily(start_dt, end_dt):
    fetch_start = start_dt - timedelta(days=250)
    df = fetch_klines_range("BTCUSDT", "1d", fetch_start, end_dt)
    if df is None or len(df) < 50: return None
    def ema(s, p): return s.ewm(span=p, adjust=False).mean()
    df["ema50"] = ema(df["close"], 50)
    df["ema200"] = ema(df["close"], 200)
    return df

def get_btc_regime(btc_daily, current_time):
    if btc_daily is None: return "neutral"
    mask = btc_daily["open_time"] < current_time
    closed = btc_daily[mask]
    if len(closed) < 5: return "neutral"
    last = closed.iloc[-1]
    e50 = last["ema50"]; e200 = last["ema200"]; price = last["close"]
    if pd.isna(e200): return "neutral"
    if price > e50 and e50 > e200: return "bull"
    if price < e50 and e50 < e200: return "bear"
    return "neutral"

def get_liquidation_threshold(leverage):
    """Returns max adverse price move % before liquidation.
    Based on real exchange data for low-cap coins:
      25x -> ROE -55% -> price 2.2%
      10x -> ROE -85% -> price 8.5%
      5x  -> ROE -95% -> price 19%
    Formula: liq_roe = 55 + 30*(25-lev)/15, clamped [50, 95]
    """
    liq_roe = 55 + 30 * (25 - leverage) / 15
    liq_roe = max(50, min(95, liq_roe))
    return liq_roe / leverage  # convert ROE% to price move %

def get_roe_at_sl(sl_pct, leverage):
    """Returns ROE loss % at given SL and leverage."""
    return sl_pct * leverage

def adjust_leverage_for_liq(sl_pct, lev):
    """Reduce leverage if ROE at SL exceeds safety threshold."""
    while lev > 3:
        roe = get_roe_at_sl(sl_pct, lev)
        liq_threshold = get_liquidation_threshold(lev)
        if roe < LIQ_SAFETY_ROE and sl_pct < liq_threshold * 0.8:
            return lev
        lev -= 1
    # Final check at lev=3
    roe = get_roe_at_sl(sl_pct, lev)
    liq_threshold = get_liquidation_threshold(lev)
    if roe < LIQ_SAFETY_ROE and sl_pct < liq_threshold * 0.8:
        return lev
    return None  # can't safely trade

def add_indicators(df):
    def rsi(s, p=14):
        d = s.diff(); g = d.clip(lower=0).rolling(p).mean(); l = (-d.clip(upper=0)).rolling(p).mean()
        return 100 - 100/(1+g/l)
    def ema(s, p): return s.ewm(span=p, adjust=False).mean()
    def atr(df, p=14):
        hl = df["high"]-df["low"]; hc=(df["high"]-df["close"].shift()).abs(); lc=(df["low"]-df["close"].shift()).abs()
        return pd.concat([hl,hc,lc],axis=1).max(axis=1).rolling(p).mean()
    def adx(df, p=14):
        hl = df["high"] - df["low"]
        hc = (df["high"] - df["close"].shift()).abs()
        lc = (df["low"] - df["close"].shift()).abs()
        tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        up = df["high"].diff().clip(lower=0)
        dn = (-df["low"].diff()).clip(lower=0)
        up_dm = pd.Series(0.0, index=df.index)
        dn_dm = pd.Series(0.0, index=df.index)
        for i in range(1, len(df)):
            if up.iloc[i] > dn.iloc[i] and up.iloc[i] > 0: up_dm.iloc[i] = up.iloc[i]
            if dn.iloc[i] > up.iloc[i] and dn.iloc[i] > 0: dn_dm.iloc[i] = dn.iloc[i]
        atr_s = tr.ewm(alpha=1/p, adjust=False).mean()
        plus_di = 100 * up_dm.ewm(alpha=1/p, adjust=False).mean() / atr_s
        minus_di = 100 * dn_dm.ewm(alpha=1/p, adjust=False).mean() / atr_s
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-10)
        return dx.ewm(alpha=1/p, adjust=False).mean()
    df["rsi14"] = rsi(df["close"]); df["ema9"] = ema(df["close"], 9)
    df["ema21"] = ema(df["close"], 21); df["ema50"] = ema(df["close"], 50)
    df["atr14"] = atr(df); df["atr_pct"] = df["atr14"]/df["close"]*100
    df["body"] = df["close"] - df["open"]
    df["ema50_slope"] = (df["ema50"] - df["ema50"].shift(5)) / df["close"] * 100
    df["adx14"] = adx(df)
    return df

def decide_v14(row, wd, htf_trend, btc_regime):
    r = row["rsi14"]; e9 = row["ema9"]; e21 = row["ema21"]; e50 = row["ema50"]
    a = row["atr_pct"]; v = row["volume"]; av = wd["volume"].mean()
    b = row["body"]; vs = v > av * 1.5; slope50 = row["ema50_slope"]
    adx = row["adx14"]
    up = e9 > e21; dn = e9 < e21; sup = e9 > e21 > e50; sdn = e9 < e21 < e50
    if a > 1.5: return None
    if abs(slope50) < 0.05: return None
    if adx < 20: return None
    # BTC regime: bull/bear = directional filter, neutral = reduced exposure
    if btc_regime == "bull" and dn: return None
    if btc_regime == "bear" and up: return None
    is_neutral = (btc_regime == "neutral")
    if htf_trend == "up" and dn: return None
    if htf_trend == "down" and up: return None
    if a < 0.5: lev = 20
    elif a < 0.8: lev = 15
    elif a < 1.2: lev = 10
    else: lev = 5
    lev = min(lev, MAX_LEVERAGE)
    # In neutral regime, cap leverage at 5x
    if is_neutral:
        lev = min(lev, 5)
    sl_mult = 1.5; rr = 3.0; sl_pct = max(sl_mult * a, 0.3)
    direction = None
    if up and sup and slope50 > 0.05:
        if 40 <= r <= 65 and b > 0: direction = "LONG"
        elif r > 65 and vs and b > 0: direction = "LONG"
    if dn and sdn and slope50 < -0.05:
        if 35 <= r <= 60 and b < 0: direction = "SHORT"
        elif r < 50 and vs and b < 0: direction = "SHORT"
        elif r < 25 and a > 0.3:
            sl_pct = max(sl_mult * a, 0.5); lev = max(lev - 5, 3); direction = "SHORT"
    if direction is None: return None
    # --- LIQUIDATION SAFETY: adjust leverage so SL fits ---
    lev = adjust_leverage_for_liq(sl_pct, lev)
    if lev is None: return None  # can't safely trade
    score = 5
    if vs: score += 1
    if abs(slope50) > 0.15: score += 1
    if sup or sdn: score += 1
    if adx > 25: score += 1
    # Penalty for neutral regime (lower priority)
    if is_neutral: score -= 1
    score = min(score, 9)
    if score < MIN_SCORE: return None
    return {"dir": direction, "lev": lev, "sl": round(sl_pct, 2),
            "tp": round(rr * sl_pct, 2), "score": score, "neutral": is_neutral}

def backtest_portfolio(coin_data, btc_daily, max_hold=48):
    min_bars = min(len(d["15m"]) for d in coin_data.values())
    WINDOW_SIZE = 50; DECISION_EVERY = 16
    htf_maps = {}
    for coin, data in coin_data.items():
        df1h = add_indicators(data["1h"].copy())
        htf_map = {}
        for _, row in df1h.iterrows():
            htf_map[row["open_time"]] = "up" if row["ema9"] > row["ema21"] else "down"
        htf_maps[coin] = htf_map
    dfs = {}
    for coin, data in coin_data.items():
        dfs[coin] = add_indicators(data["15m"].copy())
    capital = TOTAL_CAPITAL; cash = TOTAL_CAPITAL
    positions = {}; trades = []; cooldowns = {}; consec_sls = {}
    day_start_cap = capital; day_start_bar = 0
    daily_halt = False; daily_halt_until = 0
    max_concurrent_seen = 0; total_volume = 0.0
    liq_count = 0
    peak_equity = TOTAL_CAPITAL; trough_equity = TOTAL_CAPITAL

    for bi in range(WINDOW_SIZE, min_bars):
        if bi - day_start_bar >= 96:
            day_start_cap = capital; day_start_bar = bi; daily_halt = False
        if daily_halt and bi >= daily_halt_until: daily_halt = False
        if not daily_halt and capital < day_start_cap * (1 - DAILY_LOSS_LIMIT/100):
            daily_halt = True; daily_halt_until = bi + 96
            for coin in list(positions.keys()):
                try:
                    pos = positions[coin]; c = dfs[coin].iloc[bi]; ep = c["close"]
                    pp = (ep - pos["entry"]) if pos["dir"] == "LONG" else (pos["entry"] - ep)
                    ef = (pos["units"] * ep) * (FEE_PCT/100)
                    bars_held = bi - pos["entry_idx"]
                    funding = pos["units"] * pos["entry"] * FUNDING_RATE/100 * (bars_held // FUNDING_INTERVAL_BARS)
                    np_ = pos["units"] * pp - pos["entry_fee"] - ef - funding
                    cash += pos["margin"] + np_
                    trades.append({"coin": coin, "reason": "Halt", "net_pnl": np_, "hold": bars_held, "volume": pos["units"] * ep})
                    del positions[coin]
                except Exception:
                    positions.pop(coin, None)  # force close on error, safe if already deleted

        for coin in list(positions.keys()):
            pos = positions[coin]; c = dfs[coin].iloc[bi]
            entry = pos["entry"]; orig_sl = pos["orig_sl_pct"]
            sl_price = pos["sl_price"]; tp_price = pos["tp_price"]
            leverage = pos["leverage"]
            # --- LIQUIDATION PRICE ---
            liq_threshold_pct = get_liquidation_threshold(leverage)
            if pos["dir"] == "LONG":
                liq_price = entry * (1 - liq_threshold_pct/100)
            else:
                liq_price = entry * (1 + liq_threshold_pct/100)

            ep = None; er = None; is_liq = False
            if pos["dir"] == "LONG":
                profit_pct = (c["high"] - entry) / entry * 100
                # Check liquidation FIRST (worst case: wick through SL to liquidation)
                if c["low"] <= liq_price:
                    ep = liq_price; er = "LIQ"; is_liq = True
                elif c["low"] <= sl_price:
                    ep = sl_price; er = "Trail" if pos["trail_moved"] else ("BE" if pos["be_moved"] else "SL")
                elif c["high"] >= tp_price:
                    ep = tp_price; er = "TP"
                if ep is None:
                    if profit_pct >= 0.7 * orig_sl and not pos["be_moved"]:
                        pos["sl_price"] = entry * (1 + 0.01); pos["be_moved"] = True
                    if profit_pct >= 1.5 * orig_sl and not pos["trail_moved"]:
                        pos["sl_price"] = entry * (1 + orig_sl / 100); pos["trail_moved"] = True
            else:
                profit_pct = (entry - c["low"]) / entry * 100
                if c["high"] >= liq_price:
                    ep = liq_price; er = "LIQ"; is_liq = True
                elif c["high"] >= sl_price:
                    ep = sl_price; er = "Trail" if pos["trail_moved"] else ("BE" if pos["be_moved"] else "SL")
                elif c["low"] <= tp_price:
                    ep = tp_price; er = "TP"
                if ep is None:
                    if profit_pct >= 0.7 * orig_sl and not pos["be_moved"]:
                        pos["sl_price"] = entry * (1 - 0.01); pos["be_moved"] = True
                    if profit_pct >= 1.5 * orig_sl and not pos["trail_moved"]:
                        pos["sl_price"] = entry * (1 - orig_sl / 100); pos["trail_moved"] = True
            if ep is None and bi - pos["entry_idx"] >= max_hold:
                ep = c["close"]; er = "MaxH"
            if ep:
                if is_liq:
                    # Liquidated: lose entire margin (exchange force-closes 100%)
                    np_ = -pos["margin"]
                    liq_count += 1
                    exit_vol = pos["units"] * ep; total_volume += exit_vol
                    cash += pos["margin"] + np_
                    trades.append({"coin": coin, "reason": er, "net_pnl": np_, "hold": bi - pos["entry_idx"], "volume": exit_vol})
                    consec_sls[coin] = consec_sls.get(coin, 0) + 1
                    if consec_sls[coin] >= 2: cooldowns[coin] = 6; consec_sls[coin] = 0
                    del positions[coin]
                else:
                    # === PARTIAL FILL CHECK ===
                    bar_qvol = c.get("quote_volume", 0)
                    exit_notional = pos["units"] * ep
                    if bar_qvol > 0 and exit_notional > bar_qvol * MAX_VOL_PCT / 100 and er not in ("MaxH",):
                        # PARTIAL FILL: can only fill portion this bar
                        fillable_notional = bar_qvol * MAX_VOL_PCT / 100
                        fill_units = fillable_notional / ep
                        fill_ratio = fill_units / pos["units"]
                        # PnL for filled portion
                        pp = (ep - entry) if pos["dir"] == "LONG" else (entry - ep)
                        ef_fill = fill_units * ep * (FEE_PCT/100)
                        bars_held = bi - pos["entry_idx"]
                        funding_fill = fill_units * entry * FUNDING_RATE/100 * (bars_held // FUNDING_INTERVAL_BARS)
                        np_fill = fill_units * pp - pos["entry_fee"] * fill_ratio - ef_fill - funding_fill
                        margin_returned = pos["margin"] * fill_ratio
                        exit_vol = fill_units * ep; total_volume += exit_vol
                        cash += margin_returned + np_fill
                        trades.append({"coin": coin, "reason": er + "_p", "net_pnl": np_fill,
                            "hold": bars_held, "volume": exit_vol})
                        # Update remaining position
                        pos["units"] -= fill_units
                        pos["margin"] -= margin_returned
                        pos["entry_fee"] *= (1 - fill_ratio)
                        pos["partial_fills"] += 1
                        # If remaining too small, force-close next bar at market
                        remaining_notional = pos["units"] * ep
                        if remaining_notional < MIN_NOTIONAL:
                            # Force close remaining at current price
                            pp2 = (ep - entry) if pos["dir"] == "LONG" else (entry - ep)
                            ef2 = pos["units"] * ep * (FEE_PCT/100)
                            np2 = pos["units"] * pp2 - pos["entry_fee"] - ef2 - funding_fill
                            exit_vol2 = pos["units"] * ep; total_volume += exit_vol2
                            cash += pos["margin"] + np2
                            trades.append({"coin": coin, "reason": er + "_close", "net_pnl": np2,
                                "hold": bars_held, "volume": exit_vol2})
                            if er in ("SL",):
                                consec_sls[coin] = consec_sls.get(coin, 0) + 1
                                if consec_sls[coin] >= 2: cooldowns[coin] = 6; consec_sls[coin] = 0
                            else: consec_sls[coin] = 0
                            del positions[coin]
                        # else: remaining units stay open, SL/TP price unchanged
                        # Next bar will try to fill the rest
                    else:
                        # FULL FILL (or MaxH which is market order at close)
                        pp = (ep - entry) if pos["dir"] == "LONG" else (entry - ep)
                        ef = (pos["units"] * ep) * (FEE_PCT/100)
                        bars_held = bi - pos["entry_idx"]
                        funding = pos["units"] * entry * FUNDING_RATE/100 * (bars_held // FUNDING_INTERVAL_BARS)
                        np_ = pos["units"] * pp - pos["entry_fee"] - ef - funding
                        exit_vol = pos["units"] * ep; total_volume += exit_vol
                        cash += pos["margin"] + np_
                        trades.append({"coin": coin, "reason": er, "net_pnl": np_,
                            "hold": bi - pos["entry_idx"], "volume": exit_vol})
                        if er == "SL":
                            consec_sls[coin] = consec_sls.get(coin, 0) + 1
                            if consec_sls[coin] >= 2: cooldowns[coin] = 6; consec_sls[coin] = 0
                        else: consec_sls[coin] = 0
                        del positions[coin]

        capital = cash + sum(p["margin"] for p in positions.values())
        if capital > peak_equity: peak_equity = capital
        if capital < trough_equity: trough_equity = capital
        max_concurrent_seen = max(max_concurrent_seen, len(positions))
        if bi % DECISION_EVERY != 0 or daily_halt: continue
        current_time = dfs[list(dfs.keys())[0]].iloc[bi]["open_time"]
        btc_regime = get_btc_regime(btc_daily, current_time)
        # In neutral regime, cap concurrent at 5
        max_conc_now = 5 if btc_regime == "neutral" else MAX_CONCURRENT
        opportunities = []
        for coin, df in dfs.items():
            if coin in positions: continue
            if cooldowns.get(coin, 0) > 0: cooldowns[coin] -= 1; continue
            if bi >= len(df): continue
            row = df.iloc[bi - 1]; wd = df.iloc[max(0, bi-WINDOW_SIZE):bi]
            if len(wd) < 20: continue
            t = row["open_time"]
            htf_key = t.floor("1h") - timedelta(hours=1)
            htf = htf_maps[coin].get(htf_key, None)
            opp = decide_v14(row, wd, htf, btc_regime)
            if opp: opportunities.append({"coin": coin, **opp})
        opportunities.sort(key=lambda x: -x["score"])
        available_slots = max_conc_now - len(positions)
        for opp in opportunities[:available_slots]:
            coin = opp["coin"]
            if coin in positions: continue
            margin = capital * POSITION_PCT / 100  # COMPOUND: % of current equity
            if cash < margin: continue
            try:
                c = dfs[coin].iloc[bi]; ep = c["open"]
                notional = margin * opp["lev"]; units = notional / ep
                # === MIN NOTIONAL CHECK (Binance min order) ===
                if notional < MIN_NOTIONAL:
                    continue  # skip: order too small for exchange
                # === LIQUIDITY CHECK: our order vs bar volume ===
                bar_qvol = c.get("quote_volume", 0)
                if bar_qvol > 0 and notional > bar_qvol * MAX_VOL_PCT / 100:
                    # Order too big for this bar's liquidity → skip entry
                    continue
                entry_fee = notional * (FEE_PCT/100); total_volume += notional
                if opp["dir"] == "LONG":
                    sl = ep * (1 - opp["sl"]/100); tp = ep * (1 + opp["tp"]/100)
                else:
                    sl = ep * (1 + opp["sl"]/100); tp = ep * (1 - opp["tp"]/100)
                positions[coin] = {"dir": opp["dir"], "entry": ep, "sl_price": sl, "tp_price": tp,
                    "orig_sl_pct": opp["sl"], "units": units, "entry_fee": entry_fee,
                    "entry_idx": bi, "margin": margin, "be_moved": False, "trail_moved": False,
                    "leverage": opp["lev"], "partial_fills": 0}
                cash -= margin
            except Exception:
                continue  # skip coin on any error (data issue, API error, etc.)

    for coin in list(positions.keys()):
        try:
            pos = positions[coin]; last = dfs[coin].iloc[-1]; ep = last["close"]
            pp = (ep - pos["entry"]) if pos["dir"] == "LONG" else (pos["entry"] - ep)
            ef = (pos["units"] * ep) * (FEE_PCT/100)
            bars_held = len(dfs[coin]) - 1 - pos["entry_idx"]
            funding = pos["units"] * pos["entry"] * FUNDING_RATE/100 * (bars_held // FUNDING_INTERVAL_BARS)
            np_ = pos["units"] * pp - pos["entry_fee"] - ef - funding
            exit_vol = pos["units"] * ep; total_volume += exit_vol
            cash += pos["margin"] + np_
            trades.append({"coin": coin, "reason": "End", "net_pnl": np_, "hold": bars_held, "volume": exit_vol})
            del positions[coin]
        except Exception:
            positions.pop(coin, None)  # safe delete
    return trades, cash, max_concurrent_seen, total_volume, liq_count, peak_equity, trough_equity

def report(trades, final_cap, max_conc, total_vol, liq_count, label, show_coins=True):
    if not trades:
        print(f"\n{label}: No trades!"); return None
    wins = [t for t in trades if t["net_pnl"] > 0]; losses = [t for t in trades if t["net_pnl"] <= 0]
    gp = sum(t["net_pnl"] for t in wins) if wins else 0
    gl = abs(sum(t["net_pnl"] for t in losses)) if losses else 0
    peak = TOTAL_CAPITAL; mdd = 0; cap = TOTAL_CAPITAL
    for t in trades:
        cap += t["net_pnl"]
        if cap > peak: peak = cap
        dd = (peak - cap) / peak * 100
        if dd > mdd: mdd = dd
    reasons = Counter(t["reason"] for t in trades)
    avg_win = sum(t["net_pnl"] for t in wins)/len(wins) if wins else 0
    avg_loss = abs(sum(t["net_pnl"] for t in losses)/len(losses)) if losses else 0
    ret_pct = (final_cap / TOTAL_CAPITAL - 1) * 100
    coin_stats = {}
    for t in trades: coin_stats.setdefault(t["coin"], []).append(t)
    profitable = sum(1 for c in coin_stats if sum(t["net_pnl"] for t in coin_stats[c]) > 0)
    print(f"\n{'='*80}")
    print(f"  {label}")
    print(f"{'='*80}")
    print(f"PORTFOLIO: ${TOTAL_CAPITAL:.0f} -> ${final_cap:.2f} ({ret_pct:+.2f}%)")
    print(f"Trades: {len(trades)} | Coins: {len(coin_stats)} | WR: {len(wins)/len(trades)*100:.1f}%")
    print(f"PF: {gp/gl:.2f} | MaxDD: {mdd:.1f}% | MaxConc: {max_conc}/{MAX_CONCURRENT}")
    if avg_loss > 0: print(f"AvgWin: ${avg_win:+.2f} | AvgLoss: ${avg_loss:.2f} | W/L ratio: {avg_win/avg_loss:.2f}")
    print(f"Liquidations: {liq_count} | Volume: ${total_vol:,.0f}")
    print(f"Exits: {dict(reasons)}")
    partial_count = sum(1 for t in trades if "_p" in t["reason"])
    if partial_count > 0:
        print(f"Partial fills: {partial_count} trades")
    print(f"Profitable coins: {profitable}/{len(coin_stats)} ({profitable/len(coin_stats)*100:.0f}%)")
    if show_coins:
        print(f"\nPer-coin PnL:")
        print(f"{'Coin':>16} {'Tr':>4} {'WR':>6} {'NetPnL':>10} {'TP':>4} {'SL':>4} {'BE':>4} {'Trail':>6} {'LIQ':>4} {'MaxH':>5} {'Halt':>5}")
        print(f"{'-'*75}")
        for coin in sorted(coin_stats, key=lambda c: -sum(t["net_pnl"] for t in coin_stats[c])):
            ct = coin_stats[coin]; cr = Counter(t["reason"] for t in ct)
            net = sum(t["net_pnl"] for t in ct)
            wr = sum(1 for t in ct if t["net_pnl"]>0)/len(ct)*100
            print(f"{coin:>16} {len(ct):>4} {wr:>5.0f}% {net:>+9.2f} {cr.get('TP',0):>4} {cr.get('SL',0):>4} {cr.get('BE',0):>4} {cr.get('Trail',0):>6} {cr.get('LIQ',0):>4} {cr.get('MaxH',0):>5} {cr.get('Halt',0):>5}")
    print(f"\nSUMMARY: ${TOTAL_CAPITAL:.0f} -> ${final_cap:.2f} ({ret_pct:+.2f}%) | WR {len(wins)/len(trades)*100:.1f}% | PF {gp/gl:.2f} | MaxDD {mdd:.1f}% | {len(trades)} trades | LIQ {liq_count}")
    return {"label": label, "ret": ret_pct, "trades": len(trades), "wr": len(wins)/len(trades)*100,
            "pf": gp/gl if gl > 0 else 99, "mdd": mdd, "vol": total_vol, "final": final_cap,
            "profitable_pct": profitable/len(coin_stats)*100, "avg_win": avg_win, "avg_loss": avg_loss,
            "liq": liq_count}

# === MAIN (only runs when executed directly, not when imported) ===
if __name__ == '__main__':
    # Test months: 8 from V13 + 3 new random
    test_months = [(2022, 12), (2023, 1), (2024, 8), (2025, 5), (2026, 2),
                   (2024, 5), (2025, 10), (2026, 3),
                   (2022, 6), (2023, 9), (2025, 2)]  # 3 new random

    print(f"V14 COMPOUND: Fixed % of current equity (lãi kép)")
    print(f"Test months: {test_months}")
    print(f"Params: pos={POSITION_PCT}%, daily_limit={DAILY_LOSS_LIMIT}%, min_score={MIN_SCORE}, max_lev={MAX_LEVERAGE}x")
    print(f"Liquidation: max ROE at SL={LIQ_SAFETY_ROE}%")
    print(f"Lev thresholds: 25x->{get_liquidation_threshold(25):.1f}%, 20x->{get_liquidation_threshold(20):.1f}%, 15x->{get_liquidation_threshold(15):.1f}%, 10x->{get_liquidation_threshold(10):.1f}%, 5x->{get_liquidation_threshold(5):.1f}%")

    all_symbols = get_all_symbols()
    print(f"Total USDT perpetuals: {len(all_symbols)}")

    random.seed(777)
    month_coin_map = {}
    for year, month in test_months:
        candidates = random.sample(all_symbols, min(COINS_PER_MONTH * 2, len(all_symbols)))
        month_coin_map[(year, month)] = candidates

    results = []
    for year, month in test_months:
        start_dt = datetime(year, month, 1)
        end_dt = datetime(year, month + 1, 1) if month < 12 else datetime(year + 1, 1, 1)
        label = start_dt.strftime('%b %Y')
        print(f"\n\n>>> {label}...")
        btc_daily = fetch_btc_daily(start_dt, end_dt)
        if btc_daily is None:
            print(f"  No BTC daily data, skipping"); continue
        print(f"  BTC daily: {len(btc_daily)} bars")
        candidates = month_coin_map[(year, month)]
        coin_data = {}
        for coin in candidates:
            try:
                df15 = fetch_klines_range(coin, "15m", start_dt, end_dt)
                df1h = fetch_klines_range(coin, "1h", start_dt, end_dt)
                if df15 is not None and len(df15) > 200 and df1h is not None and len(df1h) > 50:
                    coin_data[coin] = {"15m": df15, "1h": df1h}
                    if len(coin_data) >= COINS_PER_MONTH: break
            except: pass
        print(f"  Got {len(coin_data)} valid coins")
        if len(coin_data) < 10: print("  Skip"); continue
        trades, final_cap, max_conc, total_vol, liq_count = backtest_portfolio(coin_data, btc_daily)
        r = report(trades, final_cap, max_conc, total_vol, liq_count, label, show_coins=True)
        if r: results.append(r)

    print(f"\n\n{'='*100}")
    print(f"  V14 COMPOUND SUMMARY (11 months)")
    print(f"{'='*100}")
    print(f"{'Month':>12} {'Return':>10} {'Trades':>8} {'WR':>7} {'PF':>6} {'MaxDD':>7} {'W/L':>6} {'LIQ':>5} {'Profit%':>9}")
    print(f"{'-'*80}")
    for r in results:
        wl = r['avg_win']/r['avg_loss'] if r['avg_loss'] > 0 else 0
        print(f"{r['label']:>12} {r['ret']:>+9.2f}% {r['trades']:>8} {r['wr']:>6.1f}% {r['pf']:>5.2f} {r['mdd']:>6.1f}% {wl:>5.2f} {r['liq']:>5} {r['profitable_pct']:>8.0f}%")
    wins = sum(1 for r in results if r['ret'] > 0)
    avg_ret = sum(r['ret'] for r in results) / len(results)
    avg_pf = sum(r['pf'] for r in results) / len(results)
    avg_mdd = sum(r['mdd'] for r in results) / len(results)
    total_liq = sum(r['liq'] for r in results)
    print(f"\nProfitable months: {wins}/{len(results)}")
    print(f"Avg return: {avg_ret:+.2f}% | Avg PF: {avg_pf:.2f} | Avg MaxDD: {avg_mdd:.1f}% | Total LIQ: {total_liq}")
    worst = min(results, key=lambda x: x['ret'])
    best = max(results, key=lambda x: x['ret'])
    print(f"Worst: {worst['label']} ({worst['ret']:+.2f}%) | Best: {best['label']} ({best['ret']:+.2f}%)")

    # V12 vs V13 comparison
    v12_baseline = {"Dec 2022": 94.23, "Jan 2023": 20.88, "Aug 2024": 190.69, "May 2025": 77.64, "Feb 2026": 152.20,
                    "May 2024": 27.55, "Oct 2025": -5.52, "Mar 2026": -64.82,
                    "Jun 2022": 0, "Sep 2023": 0, "Feb 2025": 0}
    print(f"\nV12 vs V13 comparison:")
    print(f"{'Month':>12} {'V12':>10} {'V13':>10} {'Diff':>10}")
    print(f"{'-'*45}")
    for r in results:
        v12 = v12_baseline.get(r['label'], 0)
        diff = r['ret'] - v12
        print(f"{r['label']:>12} {v12:>+9.2f}% {r['ret']:>+9.2f}% {diff:>+9.2f}%")
