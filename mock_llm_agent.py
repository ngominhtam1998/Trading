import pandas as pd
import numpy as np


def mock_llm_agent_decision(context_df: pd.DataFrame, position_state: dict) -> str:
    """
    Mock LLM agent that decides: 'open_long', 'open_short', 'close', or 'hold'.
    It sees the full market context up to the current candle and its current position.
    No future data is used.
    """
    if context_df is None or len(context_df) < 40:
        return "hold"

    df = context_df.copy()
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if df[["open", "high", "low", "close", "volume"]].isnull().any().any():
        return "hold"

    c = df["close"].values
    o = df["open"].values
    h = df["high"].values
    l = df["low"].values
    v = df["volume"].values

    def ema(series, span):
        return pd.Series(series).ewm(span=span, adjust=False).mean().values

    def rsi(series, period=14):
        delta = np.diff(series)
        gain = np.where(delta > 0, delta, 0)
        loss = np.where(delta < 0, -delta, 0)
        avg_gain = pd.Series(gain).rolling(window=period).mean().iloc[-1]
        avg_loss = pd.Series(loss).rolling(window=period).mean().iloc[-1]
        if avg_loss == 0 or pd.isna(avg_loss):
            return 50.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def adx(high, low, close, period=14):
        tr1 = high - low
        tr2 = np.abs(high - np.roll(close, 1))
        tr3 = np.abs(low - np.roll(close, 1))
        tr = np.maximum(np.maximum(tr1, tr2), tr3)
        tr[0] = tr[1]
        atr = pd.Series(tr).ewm(span=period, adjust=False).mean().values
        plus_dm = np.where((high - np.roll(high, 1)) > (np.roll(low, 1) - low),
                          np.maximum(high - np.roll(high, 1), 0), 0)
        minus_dm = np.where((np.roll(low, 1) - low) > (high - np.roll(high, 1)),
                           np.maximum(np.roll(low, 1) - low, 0), 0)
        plus_dm[0] = 0
        minus_dm[0] = 0
        plus_di = 100 * pd.Series(plus_dm).ewm(span=period, adjust=False).mean().values / (atr + 1e-9)
        minus_di = 100 * pd.Series(minus_dm).ewm(span=period, adjust=False).mean().values / (atr + 1e-9)
        dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-9)
        return pd.Series(dx).ewm(span=period, adjust=False).mean().iloc[-1]

    # Indicators
    ema5 = ema(c, 5)
    ema12 = ema(c, 12)
    ema26 = ema(c, 26)
    rsi14 = rsi(c, 14)
    adx_val = adx(h, l, c)

    # Recent data
    last_close = c[-1]
    last5 = c[-5:]
    last_high_20 = np.max(h[-20:])
    last_low_20 = np.min(l[-20:])
    vol_spike = v[-1] > 1.3 * np.mean(v[-20:])

    trend_up = ema5[-1] > ema12[-1] > ema26[-1]
    trend_down = ema5[-1] < ema12[-1] < ema26[-1]
    ema_cross_bull = ema5[-1] > ema12[-1] and ema5[-2] <= ema12[-2]
    ema_cross_bear = ema5[-1] < ema12[-1] and ema5[-2] >= ema12[-2]

    # If in a position, decide whether to close
    if position_state["in_trade"]:
        side = position_state["side"]
        unrealized = position_state["unrealized_pnl_pct"]
        bars = position_state["bars_in_trade"]

        # Take profit when momentum fades
        if side == 1:
            if unrealized > 0.04:
                if ema_cross_bear or rsi14 > 75 or last_close < ema5[-1]:
                    return "close"
            if unrealized < -0.03:
                if ema_cross_bear or trend_down:
                    return "close"
            if bars > 20 and (last_close < ema12[-1] or rsi14 < 45):
                return "close"
        elif side == -1:
            if unrealized > 0.04:
                if ema_cross_bull or rsi14 < 25 or last_close > ema5[-1]:
                    return "close"
            if unrealized < -0.03:
                if ema_cross_bull or trend_up:
                    return "close"
            if bars > 20 and (last_close > ema12[-1] or rsi14 > 55):
                return "close"
        return "hold"

    # If not in a position, decide entry
    if trend_up and (ema_cross_bull or last_close > last_high_20 * 0.995) and rsi14 < 70 and adx_val > 15:
        if vol_spike or last_close > last_high_20:
            return "open_long"
    if trend_down and (ema_cross_bear or last_close < last_low_20 * 1.005) and rsi14 > 30 and adx_val > 15:
        if vol_spike or last_close < last_low_20:
            return "open_short"
    return "hold"
