import pandas as pd
import numpy as np


def mock_llm_decision(context_df: pd.DataFrame) -> dict:
    """
    Advanced mock LLM analyst for OHLCV candle data.
    Simulates how a technical analyst / LLM would reason about a market snapshot.

    Input: DataFrame with columns timestamp, open, high, low, close, volume.
    Uses only rows up to the last row (no future data).
    Output: {"signal": 1/-1/0, "reason": str}
    """
    if context_df is None or len(context_df) < 40:
        return {"signal": 0, "reason": "Not enough data."}

    df = context_df.copy()
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if df[["open", "high", "low", "close", "volume"]].isnull().any().any():
        return {"signal": 0, "reason": "Missing values."}

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

    def stochastic(high, low, close, k=14, d=3):
        lowest = pd.Series(low).rolling(k).min().iloc[-1]
        highest = pd.Series(high).rolling(k).max().iloc[-1]
        if highest == lowest:
            return 50.0, 50.0
        k_val = 100 * (close[-1] - lowest) / (highest - lowest)
        return k_val, k_val

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
        plus_di = 100 * pd.Series(plus_dm).ewm(span=period, adjust=False).mean().values / atr
        minus_di = 100 * pd.Series(minus_dm).ewm(span=period, adjust=False).mean().values / atr
        dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-9)
        adx_val = pd.Series(dx).ewm(span=period, adjust=False).mean().iloc[-1]
        return plus_di[-1], minus_di[-1], adx_val

    def macd(close, fast=12, slow=26, signal=9):
        ema_fast = pd.Series(close).ewm(span=fast, adjust=False).mean()
        ema_slow = pd.Series(close).ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        hist = macd_line - signal_line
        return macd_line, signal_line, hist

    # Compute indicators
    ema12 = ema(c, 12)
    ema26 = ema(c, 26)
    ema50 = ema(c, 50)
    rsi14 = rsi(c, 14)
    rsi7 = rsi(c, 7)
    stoch_k, _ = stochastic(h, l, c)
    plus_di, minus_di, adx_val = adx(h, l, c)
    macd_line, signal_line, macd_hist = macd(c)
    current_macd = macd_line.iloc[-1]
    current_signal = signal_line.iloc[-1]
    current_hist = macd_hist.iloc[-1]
    prev_hist = macd_hist.iloc[-2] if len(macd_hist) > 1 else current_hist

    vol_mean20 = np.mean(v[-20:])
    vol_mean5 = np.mean(v[-5:])
    vol_spike = v[-1] > 1.2 * vol_mean20
    vol_trend = vol_mean5 > vol_mean20

    recent_high = np.max(c[-20:])
    recent_low = np.min(c[-20:])
    position_in_range = (c[-1] - recent_low) / (recent_high - recent_low + 1e-9)

    # Market structure
    hh = c[-1] > np.max(c[-10:-1]) if len(c) > 10 else False
    hl = c[-1] > np.min(c[-10:-1]) and c[-1] < np.max(c[-10:-1])
    ll = c[-1] < np.min(c[-10:-1]) if len(c) > 10 else False
    lh = c[-1] < np.max(c[-10:-1]) and c[-1] > np.min(c[-10:-1])

    # Candlestick
    body = c[-1] - o[-1]
    range_ = h[-1] - l[-1]
    upper_shadow = (h[-1] - max(c[-1], o[-1])) / (range_ + 1e-9)
    lower_shadow = (min(c[-1], o[-1]) - l[-1]) / (range_ + 1e-9)
    bullish_candle = body > 0
    bearish_candle = body < 0
    big_candle = abs(body) > 0.3 * range_
    doji = abs(body) < 0.1 * range_

    # Trend and regime
    trend_up = ema12[-1] > ema26[-1] > ema50[-1]
    trend_down = ema12[-1] < ema26[-1] < ema50[-1]
    ema_cross_bull = ema12[-1] > ema26[-1] and ema12[-2] <= ema26[-2]
    ema_cross_bear = ema12[-1] < ema26[-1] and ema12[-2] >= ema26[-2]
    ranging = adx_val < 20
    trending = adx_val > 25

    # Ensemble score (weighted)
    bullish_score = 0.0
    bearish_score = 0.0
    reasons = []

    # Trend weight
    if trend_up:
        bullish_score += 1.5
        reasons.append("uptrend EMA12>26>50")
    if trend_down:
        bearish_score += 1.5
        reasons.append("downtrend EMA12<26<50")
    if ema_cross_bull:
        bullish_score += 1.0
        reasons.append("EMA12 crossed above EMA26")
    if ema_cross_bear:
        bearish_score += 1.0
        reasons.append("EMA12 crossed below EMA26")

    # Momentum
    if rsi14 < 35:
        bullish_score += 1.0
        reasons.append(f"RSI14 oversold {rsi14:.1f}")
    if rsi14 > 65:
        bearish_score += 1.0
        reasons.append(f"RSI14 overbought {rsi14:.1f}")
    if rsi7 < 25:
        bullish_score += 0.5
    if rsi7 > 75:
        bearish_score += 0.5
    if stoch_k < 20:
        bullish_score += 0.7
        reasons.append(f"Stoch oversold {stoch_k:.1f}")
    if stoch_k > 80:
        bearish_score += 0.7
        reasons.append(f"Stoch overbought {stoch_k:.1f}")

    # MACD
    if current_hist > 0 and current_hist > prev_hist:
        bullish_score += 0.8
        reasons.append("MACD histogram rising")
    if current_hist < 0 and current_hist < prev_hist:
        bearish_score += 0.8
        reasons.append("MACD histogram falling")

    # Volume
    if vol_spike and bullish_candle:
        bullish_score += 1.0
        reasons.append("volume spike on bullish candle")
    if vol_spike and bearish_candle:
        bearish_score += 1.0
        reasons.append("volume spike on bearish candle")
    if vol_trend and trend_up:
        bullish_score += 0.5
    if vol_trend and trend_down:
        bearish_score += 0.5

    # Market structure
    if hh:
        bullish_score += 1.0
        reasons.append("new 10-candle high")
    if ll:
        bearish_score += 1.0
        reasons.append("new 10-candle low")
    if position_in_range < 0.25:
        bullish_score += 0.5
        reasons.append("price near 20-period support")
    if position_in_range > 0.75:
        bearish_score += 0.5
        reasons.append("price near 20-period resistance")

    # ADX regime
    if trending and trend_up:
        bullish_score += 0.5
    if trending and trend_down:
        bearish_score += 0.5
    if ranging:
        # Reduce trend-following scores in ranging market
        bullish_score *= 0.7
        bearish_score *= 0.7

    # Candlestick patterns
    if bullish_candle and lower_shadow > 0.5 and not doji:
        bullish_score += 0.5
        reasons.append("bullish rejection lower shadow")
    if bearish_candle and upper_shadow > 0.5 and not doji:
        bearish_score += 0.5
        reasons.append("bearish rejection upper shadow")
    if bullish_candle and big_candle and trend_up:
        bullish_score += 0.5
    if bearish_candle and big_candle and trend_down:
        bearish_score += 0.5

    # Decision thresholds: balance frequency and quality
    diff = bullish_score - bearish_score
    if bullish_score >= 3.0 and diff >= 1.5:
        reason = "Bullish: " + ", ".join(reasons[:5]) + f" (score +{diff:.1f})."
        return {"signal": 1, "reason": reason}
    elif bearish_score >= 3.0 and diff <= -1.5:
        reason = "Bearish: " + ", ".join(reasons[:5]) + f" (score {diff:.1f})."
        return {"signal": -1, "reason": reason}
    else:
        return {"signal": 0, "reason": f"Neutral (bull {bullish_score:.1f}, bear {bearish_score:.1f}, RSI {rsi14:.1f}, ADX {adx_val:.1f})."}
