"""FINAL strategy — higher-timeframe trend-following, let-winners-run, regime-gated.

WHY THIS EXISTS (root-cause fix for opus/glm)
---------------------------------------------
Realistic intrabar backtests (test_*_replay.py) showed BOTH opus and glm bleed
~95% over 60 days. The killer was NOT the entry edge — it was the PAYOFF math:
    AvgWin ($8) < AvgLoss ($9)  ->  W/L ~ 0.9
With WR ~42% and W/L < 1, fees+slippage+funding guarantee a slow death no matter
how the entry is tuned. Two design errors caused W/L < 1:
  1. Early breakeven (+1.0R) + tight trail (+1.3R) CUT winners short, while losers
     always took the full -1R. Classic "cut profits early, let losses run".
  2. Trading on 1m triggers in a choppy 15m regime = constant whipsaw, 10 SL/day.

FINAL flips every one of these:
  * HIGHER TIMEFRAME signal: 1h primary trend (EMA stack + ADX) + 15m pullback
    entry. Far fewer, far cleaner setups; 1m noise no longer triggers entries.
  * REGIME HARD GATE: only LONG when BTC daily regime is bull, only SHORT when
    bear. Sit in cash during neutral/chop (where the bleed happened).
  * LET WINNERS RUN: NO fixed TP, NO early breakeven. Tight structural initial SL
    (the only place we cap risk), then a WIDE 15m-ATR trail that only engages
    after +1.5R. Winners can run to 3-6R; losers are capped at 1R. Target W/L > 2.
  * RISK-BASED SIZING (anti-blowup): each trade risks a fixed RISK_PCT% of capital
    (size the margin so a full SL = RISK_PCT% of capital). 10 losses in a row =
    -10%, mathematically cannot blow up. Winners running 3-6R compound the upside.

This module exposes the same interface as glm/opus so the replay harness and the
live bot can call it unchanged:
- decide_mtf(...)            -> pure entry decision
- analyze_live(...)          -> live wrapper
- compute_trail_sl(...)      -> let-winners-run trail
- btc_context_from_frames(...), add_indicators(...), fetch_klines_range(...)
The REAL evaluation is test_final_replay.py (intrabar fills). DO NOT trust any
close-based backtest for go/no-go.
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

# === RISK-BASED sizing (anti-blowup) ===
# The single most important change: we no longer size off a fixed % of capital
# as MARGIN. Instead, each trade RISKS a fixed % of capital — the margin is
# computed so that a full stop-out loses exactly RISK_PCT% of TOTAL_CAPITAL.
# This makes drawdown bounded and predictable: N consecutive full-SL losses lose
# N * RISK_PCT %. Winners (which run far past 1R) are pure upside on top.
MIN_SCORE = 6                 # high bar: only confluent setups (scale 0..10)
RISK_PCT = 1.0                # risk 1.0% of capital per trade (full SL = -1% of cap)
RISK_PCT_HIGH = 2.5           # score >= 9 + regime aligned -> press the edge (sweet spot)
RISK_PCT_MID = 1.5            # score 7..8
RISK_PCT_LOW = 1.0            # score == MIN_SCORE..6
RISK_PCT_NEUTRAL = 0.5        # neutral regime: minimal risk (chop is dangerous)
# Legacy compounding knobs (kept so live/config and old code don't break). The
# replay sizer uses RISK_PCT, not these.
POSITION_PCT = 3.0
POS_SCORE_HIGH = 4.0
POS_SCORE_MID = 3.0
POS_SCORE_LOW = 2.0
MAX_CONCURRENT = 5            # fewer concurrent: higher-TF setups are rarer + bigger
MAX_LEVERAGE = 10             # cap leverage so a full SL is never catastrophic
DAILY_LOSS_LIMIT = 6.0        # stop the day after -6% (6 full-risk losses)

# === Stop / target geometry (higher TF -> wider SL, NO fixed TP) ===
# Initial SL is the ONLY place we cap risk. It is structural (15m swing) padded by
# 15m ATR, clamped to a sane band. Because the signal is on 1h, the SL is wider
# than glm's 1m-noise SL — this gives the trade room to breathe instead of being
# wicked out. There is NO fixed take-profit: TP is a far safety cap (TP_CAP_R)
# that almost never triggers; winners are harvested by the wide trail instead.
SL_MIN_PCT = 1.2              # never tighter than this (higher TF -> wider noise band)
SL_MAX_PCT = 4.0              # cap loss size per trade (risk-sizing keeps $ loss fixed)
SL_ATR_MULT = 2.0             # SL = max(structure, SL_ATR_MULT * atr15_pct)
SWING_LOOKBACK_5M = 24        # bars on 15m to find protective swing
TP_CAP_R = 8.0                # far safety TP at +8R (effectively "no TP"; trail harvests)
RR = TP_CAP_R                 # alias kept for code that reads RR

# === LET-WINNERS-RUN trailing (managed on 1m CLOSE, live) ===
# This is the core payoff fix. The old glm/opus trail killed W/L by moving to
# breakeven at +1.0R and trailing tight at +1.3R, so winners were chopped to
# ~1R while losers ran the full -1R. FINAL does the opposite:
#   * NO early breakeven. We do NOT touch the SL until the trade is firmly in
#     profit (TRAIL_START_R). Giving the trade room is what lets it reach 3-6R.
#   * Trail only ENGAGES at +TRAIL_START_R (default +1.5R). Until then the
#     original structural SL stands (max risk = 1R, sized to RISK_PCT% of cap).
#   * Once engaged, the trail is WIDE — TRAIL_ATR_MULT * 15m ATR (a slow, smooth
#     TF) with a floor. A wide trail rides the trend through normal pullbacks
#     instead of being shaken out, so a runner can reach 5R+.
#   * When the trail first engages we lock a guaranteed profit floor at
#     +LOCK_PROFIT_R (so a runner can never come back to a loss).
BE_R = 999                    # disabled: NO early breakeven move (let it breathe)
BE_LOCK_PCT = 0.30            # unused now (kept for live/config compatibility)
BE_LOCK_CAP_FRAC = 0.6        # unused now
TRAIL_START_R = 1.5           # trail engages only at +1.5R (winners get room first)
LOCK_PROFIT_R = 0.6           # when trail engages, guarantee at least +0.6R locked
TRAIL_ATR_MULT = 3.0          # WIDE trail = 3.0x 15m ATR (rides the trend)
TRAIL_MIN_PCT = 0.80          # floor trail distance % (covers fees+slippage+noise)
TRAIL_R = TRAIL_START_R       # legacy alias read by live/config.py

# === Cadence (higher TF -> slower scan, longer hold) ===
MAX_HOLD_BARS = 72            # 72 x 15m = 18h max hold (balance: let winners run vs cut dead)
LOOP_SECONDS = 60             # live: manage positions every 60s
ENTRY_EVERY_LOOPS = 5         # live: scan for entries every 5 loops (~5 min)
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

# === DYNAMIC UNIVERSE (the second change vs opus) ===
# Opus pins UNIVERSE to 30 majors. GLM can either use that same list OR scan the
# top-N USDT perps by 24h quote volume (with a min-volume floor to keep illiquid
# junk out). When USE_DYNAMIC_UNIVERSE is True, scan_entries fetches the top-N
# dynamically; the static UNIVERSE above is only used as a fallback / override.
USE_DYNAMIC_UNIVERSE = True
DYNAMIC_UNIVERSE_SIZE = 50    # scan top 50 coins by 24h quote volume
MIN_24H_QUOTE_VOLUME_M = 50.0 # skip coins with < $50M 24h quote volume
EXCLUDE_STABLECOINS = {"USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "BUSDUSDT", "EURUSDT",
                       "GBPUSDT", "AEVOUSDT", "IOUSDT", "BTTCUSDT", "USDPUSDT"}

# === Multi-timeframe gate thresholds (higher-TF: 1h primary, 15m entry) ===
# In FINAL, decide_mtf is called with (d1h, d15, d5) mapped onto the (d15,d5,d1)
# slots of the shared signature — i.e. the "primary" frame is 1h, "confirm" is
# 15m, and the pullback/entry frame is 5m. The threshold names keep their slot
# meaning: *_15M now gates the PRIMARY (1h) frame.
ADX_MIN_15M = 25              # require a trend on the 15m primary frame
ADX_MIN_5M = 18
SLOPE_MIN_15M = 0.04          # |ema50 slope| min on the 1h primary frame
RSI_SHORT_FLOOR = 35          # do NOT short if entry-frame RSI below this (oversold)
RSI_LONG_CEIL = 65            # do NOT long if entry-frame RSI above this (overbought)
BOUNCE_ATR_MULT = 1.2         # skip if price already ran this many ATRs off recent extreme
BOUNCE_LOOKBACK_1M = 12       # bars to measure the recent extreme (entry frame)
EXHAUSTION_GREEN_RED = 2      # if >= N of last 3 entry candles oppose direction -> skip

# === PULLBACK ENTRY (on the 5m entry frame, within a 1h trend) ===
# Wait for a pullback off the recent swing extreme, then a reversal candle
# resuming the 1h trend. Wider band than glm because the entry frame is 5m (not
# 1m) — a 5m pullback within a 1h trend is a real, tradeable dip/rally.
PULLBACK_MIN_ATR = 0.2        # price MUST have pulled back at least this many ATRs off swing extreme
PULLBACK_MAX_ATR = 3.5        # ...but not more than this (too far = missed the move)
PULLBACK_LOOKBACK_1M = 18     # bars on the entry frame to find the swing extreme
PULLBACK_RSI_MIN = 25         # entry-frame RSI floor for SHORT (not too oversold after pullback)
PULLBACK_RSI_MAX = 75         # entry-frame RSI ceiling for LONG
REVERSAL_BODY_PCT = 0.03      # reversal candle must have body >= this % of price
USE_PULLBACK_GATE = True      # master switch (False = behave like opus breakout)
# === REGIME GATE (the chop filter) ===
# The 60-day bleed happened by trading through neutral/choppy regime. FINAL only
# takes trades that ALIGN with the BTC daily regime: LONG only in bull, SHORT
# only in bear. In neutral regime we allow trades at REDUCED risk (0.5%) — this
# prevents multi-week zero-trade droughts while still being conservative in chop.
REGIME_HARD_GATE = True        # hard gate: neutral blocked entirely (no chop trades)
REGIME_NEUTRAL_RISK = 0.3      # risk % when BTC regime is neutral (minimal in chop)

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


def get_dynamic_universe(n=DYNAMIC_UNIVERSE_SIZE, min_vol_m=MIN_24H_QUOTE_VOLUME_M):
    """Top-N USDT perpetuals by 24h quote volume, filtered to liquid non-stablecoins.

    Used by scan_entries when USE_DYNAMIC_UNIVERSE is True. Falls back to the
    static UNIVERSE list on any error.
    """
    try:
        r = requests.get("https://fapi.binance.com/fapi/v1/ticker/24hr", timeout=30, verify=False)
        data = r.json()
        perps = get_all_symbols()
        rows = []
        for t in data:
            sym = t.get("symbol", "")
            if sym not in perps:
                continue
            if sym in EXCLUDE_STABLECOINS:
                continue
            qv = float(t.get("quoteVolume", 0) or 0)
            if qv < min_vol_m * 1_000_000:
                continue
            rows.append((sym, qv))
        rows.sort(key=lambda x: -x[1])
        out = [s for s, _ in rows[:n]]
        # Always keep the curated majors from the static UNIVERSE as a floor, so
        # a thin 24h ticker (e.g. early UTC) does not drop BTC/ETH from the scan.
        for s in UNIVERSE:
            if s not in out:
                out.append(s)
        return out
    except Exception:
        return list(UNIVERSE)


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
    df["ema9"] = ema(df["close"], 9)
    df["ema21"] = ema(df["close"], 21)
    df["ema50"] = ema(df["close"], 50)
    df["ema200"] = ema(df["close"], 200)
    return df


def get_btc_regime(btc_daily, current_time):
    """BTC regime — fast detection using daily EMA9/21.
    EMA50/200 and EMA20/50 were both too slow for choppy crypto markets: BTC
    hovers around the EMAs and returns 'neutral' for weeks, blocking all trades.
    EMA9/21 on daily reacts in ~2 weeks and catches real trends while filtering
    flat chop (price below both = bear, above both = bull, between = neutral)."""
    if btc_daily is None: return "neutral"
    closed = btc_daily[btc_daily["open_time"] < current_time]
    if len(closed) < 5: return "neutral"
    last = closed.iloc[-1]
    e9 = last.get("ema9", last.get("ema50"))
    e21 = last.get("ema21", last.get("ema50"))
    price = last["close"]
    if pd.isna(e21): return "neutral"
    if pd.isna(e9): e9 = e21
    if price > e9 and e9 > e21: return "bull"
    if price < e9 and e9 < e21: return "bear"
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
    """Compute BTC short-term context once per scan cycle (live wrapper).
    Regime uses 4h EMA9/21 (faster than daily — catches real trends within
    a week instead of 2+ weeks for daily EMAs)."""
    try:
        df5 = _fetch_df(client, "BTCUSDT", "5m", 120)
        df15 = _fetch_df(client, "BTCUSDT", "15m", 120)
        df1 = _fetch_df(client, "BTCUSDT", "1m", 60)
        d5 = add_indicators(df5) if df5 is not None and len(df5) > 25 else None
        d15 = add_indicators(df15) if df15 is not None and len(df15) > 25 else None
        d1 = add_indicators(df1) if df1 is not None and len(df1) > 20 else None
        regime = "neutral"
        # 4h EMA9/21 for regime (matches the backtest/replay test exactly)
        df4h = _fetch_df(client, "BTCUSDT", "4h", 120)
        if df4h is not None and len(df4h) > 30:
            df4h = df4h.copy()
            df4h["ema9"] = _ema(df4h["close"], 9)
            df4h["ema21"] = _ema(df4h["close"], 21)
            last = df4h.iloc[-1]
            if not pd.isna(last["ema21"]):
                e9 = last["ema9"] if not pd.isna(last["ema9"]) else last["ema21"]
                if last["close"] > e9 > last["ema21"]:
                    regime = "bull"
                elif last["close"] < e9 < last["ema21"]:
                    regime = "bear"
        return btc_context_from_frames(d1, d5, d15, regime)
    except Exception:
        return {"dir_5m": "flat", "dir_15m": "flat", "bounce_up": False,
                "bounce_down": False, "regime": "neutral"}


def _btc_blocks(direction, symbol, btc_ctx):
    """Return a reason string if BTC context blocks this trade, else None.
    Only uses 15m direction (not 5m) — the 5m BTC direction flips too often
    and blocks too many valid setups in choppy markets."""
    if not btc_ctx:
        return None
    strict = symbol.upper() in BTC_SYMBOLS_STRICT or symbol.upper() == "BTCUSDT"
    if direction == "SHORT":
        if btc_ctx.get("dir_15m") == "up":
            return "btc 15m up"
    else:  # LONG
        if btc_ctx.get("dir_15m") == "down":
            return "btc 15m down"
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
      15m trend+strength -> 5m confirm -> 1h not opposing -> PULLBACK gate
      (replaces opus 1m trigger + bounce guard) -> BTC alignment -> funding -> score.
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

    # ---- 3.5) REGIME GATE (soft — checked early before expensive pullback calc) ----
    # BTC daily regime: bull/bear/neutral. In HARD mode, neutral blocks entirely.
    # In SOFT mode (default), neutral is allowed at reduced risk, and opposing
    # regime always blocks. This prevents multi-week droughts while still being
    # conservative in chop.
    regime = btc_ctx.get("regime", "neutral") if btc_ctx else "neutral"
    regime_oppose = (direction == "LONG" and regime == "bear") or \
                    (direction == "SHORT" and regime == "bull")
    if regime_oppose:
        return _rej(stats, "regime_oppose")
    if REGIME_HARD_GATE and regime == "neutral":
        return _rej(stats, "regime_neutral")

    # ---- 4) PULLBACK GATE (replaces opus 1m trigger + bounce guard) ----
    # The core change vs opus: instead of entering on the breakout candle, we
    # require price to have ALREADY pulled back off the recent swing extreme by
    # [PULLBACK_MIN_ATR, PULLBACK_MAX_ATR] ATRs, AND the latest 1m candle to be
    # a reversal candle (red for short, green for long) resuming the trend.
    # This is "sell the rally / buy the dip" instead of "sell the breakdown".
    if USE_PULLBACK_GATE:
        pb_atr = _recent_extreme_move_atr(d1, direction)
        if pb_atr < PULLBACK_MIN_ATR:
            return _rej(stats, "no_pullback")        # price still at the extreme -> wait
        if pb_atr > PULLBACK_MAX_ATR:
            return _rej(stats, "pullback_too_far")   # missed the move -> skip
        # RSI band on 5m (entry frame): after pullback, RSI should be in mid-band
        rsi5 = r5["rsi14"]
        if direction == "SHORT" and (pd.isna(rsi5) or rsi5 < PULLBACK_RSI_MIN):
            return _rej(stats, "pullback_rsi_low")
        if direction == "LONG" and (pd.isna(rsi5) or rsi5 > PULLBACK_RSI_MAX):
            return _rej(stats, "pullback_rsi_high")
        # Momentum resume: 5m EMA9 must be aligned with trend direction (not the
        # noisy reversal-candle check). For LONG: EMA9 > EMA21 and latest 5m close
        # above EMA9. For SHORT: EMA9 < EMA21 and latest 5m close below EMA9.
        # This confirms the pullback is ending and momentum is resuming.
        if direction == "LONG":
            if not (r5["ema9"] > r5["ema21"] and r5["close"] > r5["ema9"]):
                return _rej(stats, "no_momentum_resume")
        else:
            if not (r5["ema9"] < r5["ema21"] and r5["close"] < r5["ema9"]):
                return _rej(stats, "no_momentum_resume")
        # Exhaustion guard on 5m: 2/3 of last 3 5m candles opposing the trend
        # means the pullback is too strong, not a fade-able bounce.
        if _opposing_candles(d5, direction, 3) >= EXHAUSTION_GREEN_RED:
            return _rej(stats, "exhaustion")
    else:
        # Legacy opus path (when USE_PULLBACK_GATE is False) — kept for A/B testing.
        e9_1, e21_1 = r1["ema9"], r1["ema21"]
        prev_e9_1 = d1.iloc[-2]["ema9"]
        if direction == "LONG":
            trigger = (r1["close"] > e9_1 and e9_1 > prev_e9_1 and r1["body"] > 0)
        else:
            trigger = (r1["close"] < e9_1 and e9_1 < prev_e9_1 and r1["body"] < 0)
        if not trigger:
            return _rej(stats, "1m_trigger")
        rsi1 = r1["rsi14"]
        if direction == "SHORT" and (pd.isna(rsi1) or rsi1 < RSI_SHORT_FLOOR):
            return _rej(stats, "rsi_extreme")
        if direction == "LONG" and (pd.isna(rsi1) or rsi1 > RSI_LONG_CEIL):
            return _rej(stats, "rsi_extreme")
        if _recent_extreme_move_atr(d1, direction) >= BOUNCE_ATR_MULT:
            return _rej(stats, "bounce_chase")
        if _opposing_candles(d1, direction, 3) >= EXHAUSTION_GREEN_RED:
            return _rej(stats, "exhaustion")

    # ---- 5.5) REGIME GATE (soft — moved earlier, see section 3.5) ----
    # Regime is now checked at section 3.5 (before pullback) for efficiency.
    # Here we just read the regime for scoring/sizing decisions.

    # ---- 6) BTC alignment ----
    if _btc_blocks(direction, symbol, btc_ctx):
        return _rej(stats, "btc_align")

    # ---- 7) funding filter (don't sit on the paying side) ----
    FUNDING_THRESHOLD = 0.001
    if direction == "SHORT" and funding_rate <= -FUNDING_THRESHOLD:
        return _rej(stats, "funding")
    if direction == "LONG" and funding_rate >= FUNDING_THRESHOLD:
        return _rej(stats, "funding")

    # ---- 8) geometry: structure SL + ATR, FAR safety TP (no real TP) ----
    entry_price = float(r1["close"])
    sl_pct = _swing_sl_pct(d5, direction, entry_price)
    tp_pct = TP_CAP_R * sl_pct   # far cap; winners harvested by the wide trail

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
    # In neutral regime, require higher score (filter low-quality chop trades)
    min_score_eff = MIN_SCORE + 1 if regime == "neutral" else MIN_SCORE
    if score < min_score_eff:
        return _rej(stats, "low_score")

    if stats is not None:
        stats["PASS"] = stats.get("PASS", 0) + 1
    # Risk-based sizing: trend-following only profits in trends, so PRESS the
    # edge when regime is aligned (bull+LONG / bear+SHORT) and score is high.
    # In neutral regime, risk is minimal — chop bleeds slowly.
    regime_aligned = (direction == "LONG" and regime == "bull") or \
                     (direction == "SHORT" and regime == "bear")
    if score >= 9: risk_pct = RISK_PCT_HIGH if regime_aligned else RISK_PCT_MID
    elif score >= 7: risk_pct = RISK_PCT_MID if regime_aligned else RISK_PCT_LOW
    else: risk_pct = RISK_PCT_LOW
    # In neutral regime, cap risk at RISK_PCT_NEUTRAL (chop is dangerous)
    if regime == "neutral":
        risk_pct = min(risk_pct, RISK_PCT_NEUTRAL)
    # legacy pos_pct kept for the live bot's compounding sizer
    if score >= 9: pos_pct = POS_SCORE_HIGH
    elif score >= 7: pos_pct = POS_SCORE_MID
    else: pos_pct = POS_SCORE_LOW

    return {"dir": direction, "lev": lev, "sl": round(sl_pct, 3),
            "tp": round(tp_pct, 3), "score": score, "pos_pct": pos_pct,
            "risk_pct": risk_pct,
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
def _atr_5m_pct_from_1m(df1):
    """Estimate 5m ATR (%) from a slice of 1m bars by resampling into 5m bars.

    Returns None if not enough data. The 5m ATR is smoother than the 1m ATR and
    reflects the coin's REAL noise band over a 5-minute window — this is what
    the adaptive trail distance should be sized against (a major like BTC has a
    tiny 5m ATR ~0.15%, an altcoin can be 0.5%+).
    """
    if df1 is None or len(df1) < 30 or "open_time" not in df1.columns:
        return None
    try:
        df = df1.copy()
        df["5m_bucket"] = df["open_time"].dt.floor("5min")
        bars5 = df.groupby("5m_bucket").agg(
            high=("high", "max"), low=("low", "min"),
            close=("close", "last"), open=("open", "first")
        ).reset_index()
        if len(bars5) < 14:
            return None
        hl = bars5["high"] - bars5["low"]
        hc = (bars5["high"] - bars5["close"].shift()).abs()
        lc = (bars5["low"] - bars5["close"].shift()).abs()
        atr5 = pd.concat([hl, hc, lc], axis=1).max(axis=1).rolling(14).mean()
        last_atr5 = atr5.iloc[-1]
        last_close = float(bars5["close"].iloc[-1])
        if pd.isna(last_atr5) or last_close <= 0:
            return None
        return float(last_atr5 / last_close * 100)
    except Exception:
        return None


def compute_trail_sl(direction, entry, orig_sl_pct, be_moved, trail_moved, df1):
    """LET-WINNERS-RUN trail. Returns (new_sl, be_moved, trail_moved).

    Philosophy (the payoff fix):
      * NO early breakeven. The original structural SL stands until the trade is
        firmly in profit. Giving the trade room is what lets it reach 3-6R.
      * The trail ENGAGES only at +TRAIL_START_R (1.5R). At that moment we lock a
        guaranteed profit floor at +LOCK_PROFIT_R so a runner can never round-trip
        back to a loss.
      * Once engaged, the trail is WIDE: TRAIL_ATR_MULT * 5m ATR (floored). A wide
        trail rides the trend through normal pullbacks instead of being shaken out.
      * SL only ever moves favorably.
    The live bot still validates the new SL against current price before applying.
    """
    if df1 is None or len(df1) == 0:
        return None, be_moved, trail_moved
    last = df1.iloc[-1]
    cur_close = float(last["close"])
    atr_1m_pct = last.get("atr_pct", None)
    if atr_1m_pct is None or pd.isna(atr_1m_pct) or atr_1m_pct <= 0:
        atr_1m_pct = orig_sl_pct
    atr_5m_pct = _atr_5m_pct_from_1m(df1)
    if atr_5m_pct is None or pd.isna(atr_5m_pct) or atr_5m_pct <= 0:
        atr_5m_pct = atr_1m_pct * 2.24

    # WIDE trail distance: 5m ATR * mult, floored to cover costs + noise.
    trail_distance_pct = max(TRAIL_MIN_PCT, TRAIL_ATR_MULT * atr_5m_pct)
    # Guaranteed locked profit when the trail first engages.
    lock_pct = LOCK_PROFIT_R * orig_sl_pct

    new_sl = None
    if direction == "LONG":
        peak = float(df1["close"].max())
        profit_pct = (cur_close - entry) / entry * 100
        if profit_pct >= TRAIL_START_R * orig_sl_pct:
            trail = peak * (1 - trail_distance_pct / 100)
            lock_floor = entry * (1 + lock_pct / 100)
            new_sl = max(trail, lock_floor)
            trail_moved = True; be_moved = True
        # NO early-BE branch: before +1.5R the original SL stands.
    else:
        trough = float(df1["close"].min())
        profit_pct = (entry - cur_close) / entry * 100
        if profit_pct >= TRAIL_START_R * orig_sl_pct:
            trail = trough * (1 + trail_distance_pct / 100)
            lock_floor = entry * (1 - lock_pct / 100)
            new_sl = min(trail, lock_floor)
            trail_moved = True; be_moved = True
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
