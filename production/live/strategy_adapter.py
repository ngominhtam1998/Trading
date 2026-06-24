"""Adapter between live Binance klines and the backtest strategy logic.

Reuses decide_v15 / add_indicators / get_btc_regime from the selected strategy
module (v15/lv2/lv3/lv4/lv5/lv6) WITHOUT modifying any trading logic.
This module only:
- converts raw klines -> DataFrame in the shape add_indicators expects
- selects the correct "signal bar" (last CLOSED bar, no look-ahead)
- returns the decision dict for a symbol
"""
import os
import sys
import logging
import importlib
import pandas as pd
from datetime import datetime, timezone

# import the production strategy module (one dir up) based on config.STRATEGY_LEVEL
_THIS = os.path.dirname(__file__)
_PARENT = os.path.dirname(_THIS)
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)

from . import config  # noqa: E402

# Dynamically import the selected strategy module
strat = importlib.import_module(config.STRATEGY_MODULE)

log = logging.getLogger("strategy")

# column layout returned by /fapi/v1/klines
_KLINE_COLS = ["open_time", "open", "high", "low", "close", "volume",
               "close_time", "quote_volume", "trades", "tbb", "tbq", "ignore"]


def klines_to_df(raw, drop_forming=True):
    """Convert raw kline list to a DataFrame matching add_indicators() input.
    drop_forming: drop the last (currently-forming, incomplete) bar.
    """
    if not raw:
        return None
    df = pd.DataFrame(raw, columns=_KLINE_COLS)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    for c in ["open", "high", "low", "close", "volume", "quote_volume"]:
        df[c] = df[c].astype(float)
    if drop_forming and len(df) > 1:
        df = df.iloc[:-1]  # last bar is still forming
    return df.reset_index(drop=True) if len(df) > 0 else None


def get_btc_regime_live(client):
    """Fetch BTC daily, compute regime (bull/bear/neutral)."""
    try:
        raw = client.klines("BTCUSDT", "1d", limit=260)
        df = klines_to_df(raw, drop_forming=True)
        if df is None or len(df) < 50:
            log.warning("BTC daily insufficient -> neutral")
            return "neutral"
        df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
        df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
        # current_time = now; get_btc_regime uses bars strictly before it
        now = pd.Timestamp(datetime.now(timezone.utc).replace(tzinfo=None))
        return strat.get_btc_regime(df, now)
    except Exception as e:
        log.warning(f"BTC regime fetch failed: {e} -> neutral")
        return "neutral"


def get_htf_trend(client, symbol):
    """1h trend from last CLOSED 1h bar (ema9 vs ema21). No look-ahead."""
    try:
        raw = client.klines(symbol, config.HTF_INTERVAL, limit=60)
        df = klines_to_df(raw, drop_forming=True)
        if df is None or len(df) < 25:
            return None
        df = strat.add_indicators(df)
        last = df.iloc[-1]
        return "up" if last["ema9"] > last["ema21"] else "down"
    except Exception as e:
        log.warning(f"HTF trend {symbol} failed: {e}")
        return None


def analyze_symbol(client, symbol, btc_regime):
    """Return decision dict {dir, lev, sl, tp, score, neutral} or None.
    Mirrors backtest: signal bar = last closed 15m bar; window = 50 bars to it.
    Also applies funding rate filter:
      - SHORT + funding <= -0.1% → skip (shorts pay longs when funding negative)
      - LONG  + funding >= +0.1% → skip (longs pay shorts when funding positive)
    """
    try:
        raw = client.klines(symbol, config.BAR_INTERVAL, limit=config.KLINES_LOOKBACK)
        df = klines_to_df(raw, drop_forming=True)
        if df is None or len(df) < 220:  # need >200 for EMA200
            return None
        df = strat.add_indicators(df)
        if len(df) < 51:
            return None
        row = df.iloc[-1]                 # last closed bar = signal bar
        wd = df.iloc[-50:]                # 50-bar window ending at signal bar
        htf = get_htf_trend(client, symbol)
        opp = strat.decide_v15(row, wd, htf, btc_regime)
        if opp is None:
            return None
        # Funding rate filter (live-only, not in backtest)
        # Positive funding = longs pay shorts; Negative = shorts pay longs
        # Skip if we'd be on the paying side with funding >= 0.1% magnitude
        fr = client.funding_rate(symbol)
        FUNDING_THRESHOLD = 0.001  # 0.1% = 0.001 in API format
        if opp["dir"] == "SHORT" and fr <= -FUNDING_THRESHOLD:
            log.info(f"{symbol}: skip SHORT (funding={fr*100:.4f}% <= -0.1%, shorts pay)")
            return None
        if opp["dir"] == "LONG" and fr >= FUNDING_THRESHOLD:
            log.info(f"{symbol}: skip LONG (funding={fr*100:.4f}% >= +0.1%, longs pay)")
            return None
        return opp
    except Exception as e:
        log.warning(f"analyze {symbol} failed: {e}")
        return None
