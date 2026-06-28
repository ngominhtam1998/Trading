"""OPUS_TRADING — multi-timeframe, BTC-aware, realistic high-frequency scalper.

WHY THIS EXISTS
---------------
v7/v8 looked great in backtest but bled on testnet. Root causes we are fixing:

1. Backtest evaluated SL on the 1m CLOSE, but a live STOP_MARKET triggers on the
   wick (mark price). So live got stopped on wicks the backtest "survived".
   -> opus is designed to be tested with INTRABAR (wick) fills (see
      test_opus_replay.py). SLs are placed wide enough (structure + ATR buffer)
      that normal noise wicks do NOT hit them.

2. Backtest managed positions every 1m, live only every 15m.
   -> opus runs the live loop every LOOP_SECONDS (60s) so BE/trail actually work.

3. Entries used only the last closed 15m bar + a slow daily BTC regime, so the
   bot kept shorting into 1m/5m bounces ("BTC hồi nhịp nhẹ mà cứ short rồi SL").
   -> opus requires MULTI-TIMEFRAME alignment (1m trigger, 5m + 15m trend, 1h
      context) AND a BTC short-term context check AND an explicit BOUNCE GUARD
      that refuses to short into a recovering low (and refuses to long into a
      failing high).

DESIGN
------
Direction is decided by the 15m trend, then it must be CONFIRMED by 5m and 1h,
TRIGGERED by 1m momentum, ALIGNED with BTC short-term direction, and must pass
the bounce/exhaustion guard. Only then do we size by confluence score.

SL is structure-based (recent swing) padded by ATR, clamped to a sane band, so
wicks don't knife us out. TP = RR * SL. Leverage is reduced until ROE-at-SL is
safe.

This module exposes BOTH:
- analyze_live(client, symbol, btc_regime, btc_ctx)  -> live entry decision
- get_btc_context_live(client)                        -> BTC short-term context
- compute_trail_sl(...)                               -> 1m BE/ATR-trail for live
- backtest_portfolio(...)                             -> a CLOSE-based backtest
  kept ONLY for parity tooling; the REAL evaluation is test_opus_replay.py which
  uses intrabar fills. DO NOT trust backtest_portfolio numbers for go/no-go.
"""
import requests, pandas as pd, time, urllib3, os, random
from datetime import datetime, timedelta
from collections import Counter
urllib3.disable_warnings()

random.seed(777)

# === Shared economics ===
FEE_PCT = 0.04                # taker round-trip-ish per side budget (0.04% market taker)
FUNDING_RATE = 0.0005
FUNDING_INTERVAL_BARS = 16
TOTAL_CAPITAL = 1000.0
MIN_NOTIONAL = 5.0
MAX_VOL_PCT = 10.0
LIQ_SAFETY_ROE = 60.0         # tighter than v7/v8 (was 70) — keep liq far away

# === OPUS risk / sizing params ===
MIN_SCORE = 6                 # high bar: only confluent setups (scale 0..10)
# Risk bumped a notch since the universe is now liquid majors only (safer fills):
POSITION_PCT = 6.0            # base per-trade margin (% of equity); compounding
POS_SCORE_HIGH = 9.0          # score >= 9
POS_SCORE_MID = 6.5           # score 7..8
POS_SCORE_LOW = 4.5           # score == MIN_SCORE..6
MAX_CONCURRENT = 10           # a few more concurrent positions
MAX_LEVERAGE = 12             # slightly higher leverage on liquid coins
DAILY_LOSS_LIMIT = 8.0        # stop the day after -8%

# === Stop / target geometry ===
# Tightened after live testnet showed avg-loss ~3x avg-win: cap loss size and
# keep winners by trailing tighter so payoff (avg win / avg loss) >= ~1.
SL_MIN_PCT = 0.40             # never tighter than this (avoid wick stop-outs)
SL_MAX_PCT = 1.3              # cap loss size (was 2.0 -> losses too big live)
SL_ATR_MULT = 1.4             # SL = max(structure, SL_ATR_MULT * atr15_pct)
SWING_LOOKBACK_5M = 20        # bars on 5m to find protective swing
RR = 1.8                      # TP = RR * SL  (a bit more reward per trade)

# === Breakeven / trailing (managed on 1m CLOSE, live) ===
# BE_LOCK_PCT MUST exceed round-trip costs (taker fee both sides ~0.08% +
# slippage ~0.06% ≈ 0.14%) or "breakeven" exits silently lose money and crush
# the win-rate. We lock +0.25% so a BE exit is a small NET win.
BE_R = 0.5                    # at +0.5R, lock breakeven (+BE_LOCK_PCT)
BE_LOCK_PCT = 0.25            # lock real profit at BE (covers fees+slippage)
TRAIL_START_R = 0.7           # start ATR trailing earlier (+0.7R) to bank winners
TRAIL_ATR_MULT = 1.2          # trail tighter (was 2.0 -> gave back too much)
TRAIL_R = TRAIL_START_R       # legacy alias read by live/config.py

# === Cadence ===
MAX_HOLD_BARS = 48            # 48 x 15m = 12h max hold
LOOP_SECONDS = 60             # live: manage positions every 60s
ENTRY_EVERY_LOOPS = 3         # live: scan for entries every 3 loops (~3 min)
DECISION_EVERY_BARS = 2       # backtest-tool cadence (15m units)

# === UNIVERSE (liquid majors only) ===
# Live on testnet ranked junk/illiquid coins to the top by (fake) volume, which
# gave catastrophic SL slippage. Restrict to a curated set of liquid USDT perps
# that have real depth on BOTH testnet and mainnet. scan_entries uses this list
# (intersected with what the exchange currently lists) instead of top-volume.
UNIVERSE = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT",
    "AVAXUSDT", "LINKUSDT", "TRXUSDT", "LTCUSDT", "BCHUSDT", "DOTUSDT", "MATICUSDT",
    "NEARUSDT", "APTUSDT", "ARBUSDT", "OPUSDT", "INJUSDT", "SUIUSDT", "TONUSDT",
    "ATOMUSDT", "FILUSDT", "AAVEUSDT", "UNIUSDT", "ETCUSDT", "ICPUSDT", "HBARUSDT",
    "SEIUSDT", "RUNEUSDT",
]
MAX_LEVERAGE_CAP_NOTE = "MAX_LEVERAGE reduced to 10 so a full SL is not catastrophic"

# === Multi-timeframe gate thresholds ===
ADX_MIN_15M = 22              # require a real trend on 15m
ADX_MIN_5M = 18
SLOPE_MIN_15M = 0.05          # |ema50 slope| min on 15m
RSI_SHORT_FLOOR = 38          # do NOT short if 1m RSI below this (oversold -> bounce risk)
RSI_LONG_CEIL = 62            # do NOT long if 1m RSI above this (overbought -> reversal risk)
BOUNCE_ATR_MULT = 1.0         # if price already moved this many ATRs off the recent extreme -> skip (chasing/bounce)
BOUNCE_LOOKBACK_1M = 12       # bars on 1m to measure the recent extreme
EXHAUSTION_GREEN_RED = 2      # if >= N of last 3 1m candles oppose our direction -> skip

# === BTC alignment ===
BTC_BOUNCE_ATR_MULT = 0.8     # BTC considered "bouncing" if it moved this many 1m ATRs off its recent extreme
BTC_SYMBOLS_STRICT = {"ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
                      "ADAUSDT", "AVAXUSDT", "LINKUSDT", "TRXUSDT", "BCHUSDT",
                      "LTCUSDT", "DOTUSDT", "MATICUSDT", "TONUSDT"}  # high-cap: stricter BTC gate

# 1m equivalents (for backtest tool)
BARS1_PER_15 = 15
FUNDING_INTERVAL_1M = FUNDING_INTERVAL_BARS * BARS1_PER_15
DAILY_HALT_BARS_1M = 96 * BARS1_PER_15
MAX_HOLD_1M = MAX_HOLD_BARS * BARS1_PER_15
COOLDOWN_1M = 6 * BARS1_PER_15


# ==========================================================================
# Data / indicators
# ==========================================================================
def get_all_symbols():
    r = requests.get("https://fapi.binance.com/fapi/v1/exchangeInfo", timeout=30, verify=False)
    data = r.json()
    return [s["symbol"] for s in data["symbols"]
            if s["quoteAsset"] == "USDT" and s["contractType"] == "PERPETUAL" and s["status"] == "TRADING"]


def fetch_klines_range(symbol, interval, start_dt, end_dt):
    start_ms = int(start_dt.timestamp() * 1000); end_ms = int(end_dt.timestamp() * 1000)
    url = "https://fapi.binance.com/fapi/v1/klines"
    all_data = []; cur = start_ms; ban_until = 0
    while cur < end_ms:
        # honor an IP ban window reported by -1003
        if ban_until > time.time():
            time.sleep(min(ban_until - time.time() + 1, 60))
        try:
            r = requests.get(url, params={"symbol": symbol, "interval": interval,
                "startTime": cur, "endTime": end_ms, "limit": 1000}, timeout=15, verify=False)
            if r.status_code in (418, 429):
                try:
                    ban_until = (r.json().get("code") == -1003 and
                                 int(r.json().get("msg", "").split("banned until ")[1].split(".")[0]) / 1000) or (time.time() + 30)
                except Exception:
                    ban_until = time.time() + 30
                continue
            r.raise_for_status(); data = r.json()
            if not data: break
            all_data.extend(data)
            ms_map = {"1m":60*1000, "3m":3*60*1000, "5m":5*60*1000, "15m":15*60*1000,
                  "1h":60*60*1000, "4h":4*60*60*1000, "1d":24*60*60*1000}[interval]
            cur = data[-1][0] + ms_map; time.sleep(0.12)
        except Exception:
            time.sleep(0.5); continue
    if not all_data: return None
    df = pd.DataFrame(all_data, columns=["open_time","open","high","low","close","volume",
        "close_time","quote_volume","trades","tbb","tbq","ignore"])
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    for c in ["open","high","low","close","volume","quote_volume"]:
        df[c] = df[c].astype(float)
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
    """Slow daily regime — used only as a soft bias, not a hard gate in opus."""
    if btc_daily is None: return "neutral"
    closed = btc_daily[btc_daily["open_time"] < current_time]
    if len(closed) < 5: return "neutral"
    last = closed.iloc[-1]
    e50 = last["ema50"]; e200 = last["ema200"]; price = last["close"]
    if pd.isna(e200): return "neutral"
    if price > e50 and e50 > e200: return "bull"
    if price < e50 and e50 < e200: return "bear"
    return "neutral"


def get_liquidation_threshold(leverage):
    """Max adverse price-move % before liquidation (approx, isolated)."""
    liq_roe = 55 + 30 * (25 - leverage) / 15
    liq_roe = max(50, min(95, liq_roe))
    return liq_roe / leverage


def get_roe_at_sl(sl_pct, leverage):
    return sl_pct * leverage


def adjust_leverage_for_liq(sl_pct, lev):
    """Reduce leverage until ROE-at-SL is safe and liq is far from SL."""
    while lev >= 3:
        roe = get_roe_at_sl(sl_pct, lev)
        liq_threshold = get_liquidation_threshold(lev)
        if roe < LIQ_SAFETY_ROE and sl_pct < liq_threshold * 0.7:
            return lev
        lev -= 1
    return None


def _ema(s, p): return s.ewm(span=p, adjust=False).mean()


def _rsi(s, p=14):
    d = s.diff(); g = d.clip(lower=0).rolling(p).mean(); l = (-d.clip(upper=0)).rolling(p).mean()
    return 100 - 100 / (1 + g / l)


def _atr(df, p=14):
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift()).abs()
    lc = (df["low"] - df["close"].shift()).abs()
    return pd.concat([hl, hc, lc], axis=1).max(axis=1).rolling(p).mean()


def _adx(df, p=14):
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift()).abs()
    lc = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    up = df["high"].diff().clip(lower=0)
    dn = (-df["low"].diff()).clip(lower=0)
    up_dm = up.where((up > dn) & (up > 0), 0.0)
    dn_dm = dn.where((dn > up) & (dn > 0), 0.0)
    atr_s = tr.ewm(alpha=1/p, adjust=False).mean()
    plus_di = 100 * up_dm.ewm(alpha=1/p, adjust=False).mean() / atr_s
    minus_di = 100 * dn_dm.ewm(alpha=1/p, adjust=False).mean() / atr_s
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-10)
    return dx.ewm(alpha=1/p, adjust=False).mean()


def add_indicators(df):
    df = df.copy()
    df["rsi14"] = _rsi(df["close"])
    df["ema9"] = _ema(df["close"], 9)
    df["ema21"] = _ema(df["close"], 21)
    df["ema50"] = _ema(df["close"], 50)
    df["ema200"] = _ema(df["close"], 200)
    df["atr14"] = _atr(df)
    df["atr_pct"] = df["atr14"] / df["close"] * 100
    df["body"] = df["close"] - df["open"]
    df["body_pct"] = df["body"].abs() / df["close"] * 100
    df["ema50_slope"] = (df["ema50"] - df["ema50"].shift(5)) / df["close"] * 100
    df["adx14"] = _adx(df)
    return df


# ==========================================================================
# Live data helper
# ==========================================================================
def _fetch_df(client, symbol, interval, limit):
    """Fetch klines via the live client, drop the forming bar, return DataFrame."""
    try:
        raw = client.klines(symbol, interval, limit=limit)
    except Exception:
        return None
    if not raw:
        return None
    df = pd.DataFrame(raw, columns=["open_time","open","high","low","close","volume",
        "close_time","quote_volume","trades","tbb","tbq","ignore"])
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    for c in ["open","high","low","close","volume","quote_volume"]:
        df[c] = df[c].astype(float)
    if len(df) > 1:
        df = df.iloc[:-1]  # drop forming bar (no look-ahead)
    return df.reset_index(drop=True) if len(df) > 0 else None


def _trend_dir(row):
    """EMA-stack trend on a single closed bar: 'up' / 'down' / 'flat'."""
    e9, e21, e50 = row["ema9"], row["ema21"], row["ema50"]
    if e9 > e21 > e50:
        return "up"
    if e9 < e21 < e50:
        return "down"
    return "flat"


def _recent_extreme_move_atr(df1, direction):
    """How many ATRs has price moved off its recent extreme (against a fresh entry)?

    For a SHORT we care about the recent LOW: if price already bounced
    BOUNCE_ATR_MULT ATRs above the recent low, the down-leg is exhausted / bouncing.
    For a LONG we care about the recent HIGH.
    Returns the move in ATR units (>=0).
    """
    look = min(BOUNCE_LOOKBACK_1M, len(df1))
    seg = df1.iloc[-look:]
    atr = df1.iloc[-1].get("atr14", None)
    cur = df1.iloc[-1]["close"]
    if atr is None or pd.isna(atr) or atr <= 0:
        return 0.0
    if direction == "SHORT":
        ext = seg["low"].min()
        return max(0.0, (cur - ext) / atr)
    else:
        ext = seg["high"].max()
        return max(0.0, (ext - cur) / atr)


def _opposing_candles(df1, direction, n=3):
    """Count of the last n 1m candles whose body opposes our direction."""
    seg = df1.iloc[-n:]
    if direction == "SHORT":
        return int((seg["close"] > seg["open"]).sum())   # green candles oppose a short
    else:
        return int((seg["close"] < seg["open"]).sum())   # red candles oppose a long


def _swing_sl_pct(df5, direction, entry_price):
    """Protective SL distance % from the recent 5m swing, padded by 15m ATR.
    Returned value already clamped to [SL_MIN_PCT, SL_MAX_PCT]."""
    look = min(SWING_LOOKBACK_5M, len(df5))
    seg = df5.iloc[-look:]
    atr5 = df5.iloc[-1].get("atr_pct", None)
    if direction == "SHORT":
        swing = seg["high"].max()
        struct_pct = max(0.0, (swing - entry_price) / entry_price * 100)
    else:
        swing = seg["low"].min()
        struct_pct = max(0.0, (entry_price - swing) / entry_price * 100)
    atr_pct = atr5 if (atr5 is not None and not pd.isna(atr5)) else SL_MIN_PCT
    sl = max(struct_pct, SL_ATR_MULT * atr_pct)
    return max(SL_MIN_PCT, min(SL_MAX_PCT, sl))


# ==========================================================================
# BTC short-term context (live)
# ==========================================================================
def btc_context_from_frames(d1, d5, d15, regime="neutral"):
    """Pure BTC short-term context from already-indicatored frames (each ending
    at the current signal bar). Shared by live and the replay test so the two
    behave identically.

    Returns dict: dir_5m, dir_15m, bounce_up, bounce_down, regime.
    """
    ctx = {"dir_5m": "flat", "dir_15m": "flat", "bounce_up": False,
           "bounce_down": False, "regime": regime}
    if d5 is not None and len(d5) > 25:
        ctx["dir_5m"] = _trend_dir(d5.iloc[-1])
    if d15 is not None and len(d15) > 25:
        ctx["dir_15m"] = _trend_dir(d15.iloc[-1])
    if d1 is not None and len(d1) > 20:
        up_move = _recent_extreme_move_atr(d1, "SHORT")  # move up off recent low
        dn_move = _recent_extreme_move_atr(d1, "LONG")   # move down off recent high
        ctx["bounce_up"] = up_move >= BTC_BOUNCE_ATR_MULT
        ctx["bounce_down"] = dn_move >= BTC_BOUNCE_ATR_MULT
    return ctx


def get_btc_context_live(client):
    """Compute BTC short-term context once per scan cycle (live wrapper)."""
    try:
        df5 = _fetch_df(client, "BTCUSDT", "5m", 120)
        df15 = _fetch_df(client, "BTCUSDT", "15m", 120)
        df1 = _fetch_df(client, "BTCUSDT", "1m", 60)
        d5 = add_indicators(df5) if df5 is not None and len(df5) > 25 else None
        d15 = add_indicators(df15) if df15 is not None and len(df15) > 25 else None
        d1 = add_indicators(df1) if df1 is not None and len(df1) > 20 else None
        regime = "neutral"
        dfd = _fetch_df(client, "BTCUSDT", "1d", 260)
        if dfd is not None and len(dfd) > 50:
            dfd["ema50"] = _ema(dfd["close"], 50)
            dfd["ema200"] = _ema(dfd["close"], 200)
            last = dfd.iloc[-1]
            if not pd.isna(last["ema200"]):
                if last["close"] > last["ema50"] > last["ema200"]:
                    regime = "bull"
                elif last["close"] < last["ema50"] < last["ema200"]:
                    regime = "bear"
        return btc_context_from_frames(d1, d5, d15, regime)
    except Exception:
        return {"dir_5m": "flat", "dir_15m": "flat", "bounce_up": False,
                "bounce_down": False, "regime": "neutral"}


def _btc_blocks(direction, symbol, btc_ctx):
    """Return a reason string if BTC context blocks this trade, else None."""
    if not btc_ctx:
        return None
    strict = symbol.upper() in BTC_SYMBOLS_STRICT or symbol.upper() == "BTCUSDT"
    if direction == "SHORT":
        if btc_ctx.get("bounce_up"):
            return "btc bouncing up"
        if btc_ctx.get("dir_5m") == "up":
            return "btc 5m up"
        if strict and btc_ctx.get("dir_15m") == "up":
            return "btc 15m up (high-cap)"
    else:  # LONG
        if btc_ctx.get("bounce_down"):
            return "btc rolling down"
        if btc_ctx.get("dir_5m") == "down":
            return "btc 5m down"
        if strict and btc_ctx.get("dir_15m") == "down":
            return "btc 15m down (high-cap)"
    return None


# ==========================================================================
# LIVE ENTRY DECISION (multi-timeframe)
# ==========================================================================
def _rej(stats, key):
    """Record a rejection reason (diagnostics) and return None."""
    if stats is not None:
        stats[key] = stats.get(key, 0) + 1
    return None


def decide_mtf(symbol, d15, d5, d1, d1h, btc_ctx=None, funding_rate=0.0, stats=None):
    """PURE multi-timeframe decision on already-indicatored frames.

    Each frame must END at the current signal bar (no look-ahead). This is the
    single source of truth for entry logic — both analyze_live (live) and
    test_opus_replay (offline) call it, so they cannot diverge.

    `stats` (optional Counter/dict) records WHY signals were rejected, so we can
    calibrate gate strictness instead of guessing.

    Gate order (each can reject):
      15m trend+strength -> 5m confirm -> 1h not opposing -> 1m trigger
      -> bounce/exhaustion guard -> BTC alignment -> funding -> score.
    Returns {dir, lev, sl, tp, score, pos_pct, neutral} or None.
    """
    if d15 is None or len(d15) < 60 or d5 is None or len(d5) < 60 or d1 is None or len(d1) < 30:
        return _rej(stats, "insufficient_data")
    r15 = d15.iloc[-1]; r5 = d5.iloc[-1]; r1 = d1.iloc[-1]

    # ---- 1) 15m primary trend + strength ----
    t15 = _trend_dir(r15)
    if t15 == "flat":
        return _rej(stats, "15m_flat")
    if pd.isna(r15["adx14"]) or r15["adx14"] < ADX_MIN_15M:
        return _rej(stats, "15m_adx")
    if abs(r15["ema50_slope"]) < SLOPE_MIN_15M:
        return _rej(stats, "15m_slope")
    if pd.isna(r15["atr_pct"]) or r15["atr_pct"] > 2.5:
        return _rej(stats, "15m_atr_high")
    direction = "LONG" if t15 == "up" else "SHORT"

    # ---- 2) 5m confirmation (not opposing; momentum aligned) ----
    t5 = _trend_dir(r5)
    if direction == "LONG" and t5 == "down":
        return _rej(stats, "5m_oppose")
    if direction == "SHORT" and t5 == "up":
        return _rej(stats, "5m_oppose")
    if direction == "LONG" and not (r5["ema9"] > r5["ema21"]):
        return _rej(stats, "5m_mom")
    if direction == "SHORT" and not (r5["ema9"] < r5["ema21"]):
        return _rej(stats, "5m_mom")

    # ---- 3) 1h must not oppose ----
    if d1h is not None and len(d1h) > 25:
        t1h = _trend_dir(d1h.iloc[-1])
        if direction == "LONG" and t1h == "down":
            return _rej(stats, "1h_oppose")
        if direction == "SHORT" and t1h == "up":
            return _rej(stats, "1h_oppose")
    else:
        t1h = "flat"

    # ---- 4) 1m trigger: momentum + closing candle in our direction ----
    e9_1, e21_1 = r1["ema9"], r1["ema21"]
    prev_e9_1 = d1.iloc[-2]["ema9"]
    if direction == "LONG":
        trigger = (r1["close"] > e9_1 and e9_1 > prev_e9_1 and r1["body"] > 0)
    else:
        trigger = (r1["close"] < e9_1 and e9_1 < prev_e9_1 and r1["body"] < 0)
    if not trigger:
        return _rej(stats, "1m_trigger")

    # ---- 5) bounce / exhaustion guard (THE fix for "short into a bounce") ----
    rsi1 = r1["rsi14"]
    if direction == "SHORT" and (pd.isna(rsi1) or rsi1 < RSI_SHORT_FLOOR):
        return _rej(stats, "rsi_extreme")
    if direction == "LONG" and (pd.isna(rsi1) or rsi1 > RSI_LONG_CEIL):
        return _rej(stats, "rsi_extreme")
    if _recent_extreme_move_atr(d1, direction) >= BOUNCE_ATR_MULT:
        return _rej(stats, "bounce_chase")
    if _opposing_candles(d1, direction, 3) >= EXHAUSTION_GREEN_RED:
        return _rej(stats, "exhaustion")

    # ---- 6) BTC alignment ----
    if _btc_blocks(direction, symbol, btc_ctx):
        return _rej(stats, "btc_align")

    # ---- 7) funding filter (don't sit on the paying side) ----
    FUNDING_THRESHOLD = 0.001
    if direction == "SHORT" and funding_rate <= -FUNDING_THRESHOLD:
        return _rej(stats, "funding")
    if direction == "LONG" and funding_rate >= FUNDING_THRESHOLD:
        return _rej(stats, "funding")

    # ---- 8) geometry: structure SL + ATR, RR target ----
    entry_price = float(r1["close"])
    sl_pct = _swing_sl_pct(d5, direction, entry_price)
    tp_pct = RR * sl_pct

    # ---- 9) leverage tier by 15m volatility, then liq-safety ----
    a15 = r15["atr_pct"]
    if a15 < 0.5: lev = MAX_LEVERAGE
    elif a15 < 0.9: lev = min(MAX_LEVERAGE, 12)
    elif a15 < 1.4: lev = min(MAX_LEVERAGE, 8)
    else: lev = min(MAX_LEVERAGE, 5)
    lev = adjust_leverage_for_liq(sl_pct, lev)
    if lev is None:
        return _rej(stats, "liq_unsafe")

    # ---- 10) confluence score -> position sizing ----
    score = 4
    if r15["adx14"] > 28: score += 1
    if r5["adx14"] > 25: score += 1
    if t1h == t15: score += 1
    if abs(r15["ema50_slope"]) > 0.12: score += 1
    if direction == "LONG" and r15["ema50"] > r15["ema200"]: score += 1
    if direction == "SHORT" and r15["ema50"] < r15["ema200"]: score += 1
    if r1["body_pct"] > 0.05: score += 1
    if btc_ctx:
        if direction == "LONG" and btc_ctx.get("dir_5m") == "up": score += 1
        if direction == "SHORT" and btc_ctx.get("dir_5m") == "down": score += 1
    score = min(score, 10)
    if score < MIN_SCORE:
        return _rej(stats, "low_score")

    if stats is not None:
        stats["PASS"] = stats.get("PASS", 0) + 1
    if score >= 9: pos_pct = POS_SCORE_HIGH
    elif score >= 7: pos_pct = POS_SCORE_MID
    else: pos_pct = POS_SCORE_LOW

    return {"dir": direction, "lev": lev, "sl": round(sl_pct, 3),
            "tp": round(tp_pct, 3), "score": score, "pos_pct": pos_pct,
            "neutral": (btc_ctx.get("regime", "neutral") == "neutral") if btc_ctx else False}


def analyze_live(client, symbol, btc_regime="neutral", btc_ctx=None):
    """Live wrapper: fetch all timeframes, compute indicators, call decide_mtf."""
    try:
        df15 = _fetch_df(client, symbol, "15m", 260)
        df5 = _fetch_df(client, symbol, "5m", 200)
        df1 = _fetch_df(client, symbol, "1m", 120)
        df1h = _fetch_df(client, symbol, "1h", 60)
        if df15 is None or df5 is None or df1 is None:
            return None
        d15 = add_indicators(df15); d5 = add_indicators(df5); d1 = add_indicators(df1)
        d1h = add_indicators(df1h) if df1h is not None and len(df1h) > 25 else None
        try:
            fr = client.funding_rate(symbol)
        except Exception:
            fr = 0.0
        return decide_mtf(symbol, d15, d5, d1, d1h, btc_ctx, fr)
    except Exception:
        return None


# ==========================================================================
# LIVE POSITION MANAGEMENT (BE + ATR trail on 1m close)
# ==========================================================================
def compute_trail_sl(direction, entry, orig_sl_pct, be_moved, trail_moved, df1):
    """Given 1m bars SINCE entry (with atr14), return (new_sl, be_moved, trail_moved).

    new_sl is None if no change. SL only moves favorably. Uses 1m CLOSE for the
    profit trigger and the running peak/trough close for the ATR trail anchor.
    The live bot still validates the new SL against current price before applying.
    """
    if df1 is None or len(df1) == 0:
        return None, be_moved, trail_moved
    last = df1.iloc[-1]
    cur_close = float(last["close"])
    atr_pct = last.get("atr_pct", None)
    if atr_pct is None or pd.isna(atr_pct):
        atr_pct = orig_sl_pct
    new_sl = None
    if direction == "LONG":
        peak = float(df1["close"].max())
        profit_pct = (cur_close - entry) / entry * 100
        if profit_pct >= TRAIL_START_R * orig_sl_pct:
            trail = peak * (1 - TRAIL_ATR_MULT * atr_pct / 100)
            be_floor = entry * (1 + BE_LOCK_PCT / 100)
            new_sl = max(trail, be_floor)
            trail_moved = True; be_moved = True
        elif profit_pct >= BE_R * orig_sl_pct and not be_moved:
            new_sl = entry * (1 + BE_LOCK_PCT / 100)
            be_moved = True
    else:
        trough = float(df1["close"].min())
        profit_pct = (entry - cur_close) / entry * 100
        if profit_pct >= TRAIL_START_R * orig_sl_pct:
            trail = trough * (1 + TRAIL_ATR_MULT * atr_pct / 100)
            be_floor = entry * (1 - BE_LOCK_PCT / 100)
            new_sl = min(trail, be_floor)
            trail_moved = True; be_moved = True
        elif profit_pct >= BE_R * orig_sl_pct and not be_moved:
            new_sl = entry * (1 - BE_LOCK_PCT / 100)
            be_moved = True
    return new_sl, be_moved, trail_moved


# Backward-compat shim: live/strategy_adapter falls back to decide_v15 if a
# strategy has no analyze_live. opus HAS analyze_live, so decide_v15 is only a
# stub here to avoid import errors in tooling that probes the symbol.
def decide_v15(row, wd, htf_trend, btc_regime):
    return None


if __name__ == "__main__":
    print("strategy_opus — multi-timeframe BTC-aware scalper")
    print(f"  MIN_SCORE={MIN_SCORE} POSITION_PCT={POSITION_PCT}% MAX_CONC={MAX_CONCURRENT} "
          f"MAX_LEV={MAX_LEVERAGE}x DAILY_LIMIT={DAILY_LOSS_LIMIT}%")
    print(f"  SL band [{SL_MIN_PCT}%, {SL_MAX_PCT}%] x ATR{SL_ATR_MULT} | RR={RR} | "
          f"BE@{BE_R}R trail@{TRAIL_START_R}R x ATR{TRAIL_ATR_MULT}")
    print(f"  Live loop {LOOP_SECONDS}s, entry scan every {ENTRY_EVERY_LOOPS} loops")
    print("  REAL evaluation: python -m production.test_opus_replay  (intrabar wick fills)")
