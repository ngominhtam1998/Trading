import pandas as pd
import numpy as np


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute technical features from OHLCV data for ML.
    No future data is used (all features are shifted or lagged).
    """
    df = df.copy()

    # Returns
    df["ret_1"] = df["close"].pct_change()
    for window in [3, 5, 10, 20]:
        df[f"ret_{window}"] = df["close"].pct_change(window)

    # Log returns
    df["log_ret_1"] = np.log(df["close"] / df["close"].shift(1))

    # Volatility
    for window in [5, 10, 20]:
        df[f"volatility_{window}"] = df["log_ret_1"].rolling(window).std()

    # RSI
    def rsi(close, window=14):
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(window).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    for window in [7, 14, 21]:
        df[f"rsi_{window}"] = rsi(df["close"], window)

    # MACD
    ema_12 = df["close"].ewm(span=12, adjust=False).mean()
    ema_26 = df["close"].ewm(span=26, adjust=False).mean()
    df["macd"] = ema_12 - ema_26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    # Bollinger Bands position
    for window in [20]:
        ma = df["close"].rolling(window).mean()
        std = df["close"].rolling(window).std()
        df[f"bb_position_{window}"] = (df["close"] - ma) / (2 * std)
        df[f"bb_width_{window}"] = (ma + 2 * std - (ma - 2 * std)) / ma

    # ATR
    prev_close = df["close"].shift(1)
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - prev_close).abs()
    tr3 = (df["low"] - prev_close).abs()
    df["tr"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    for window in [7, 14, 21]:
        df[f"atr_{window}"] = df["tr"].rolling(window).mean()
        df[f"atr_pct_{window}"] = df[f"atr_{window}"] / df["close"]

    # Volume features
    df["volume_change_1"] = df["volume"].pct_change()
    for window in [5, 10, 20]:
        df[f"volume_ma_{window}"] = df["volume"].rolling(window).mean()
        df[f"volume_ratio_{window}"] = df["volume"] / df[f"volume_ma_{window}"]

    # Price position within candle
    df["candle_position"] = (df["close"] - df["low"]) / (df["high"] - df["low"] + 1e-9)

    # Trend: EMA cross
    for fast, slow in [(5, 12), (8, 21), (12, 50)]:
        ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
        ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
        df[f"ema_ratio_{fast}_{slow}"] = ema_fast / ema_slow

    # Lag features (shift 1 to avoid look-ahead)
    feature_cols = [c for c in df.columns if c not in ["timestamp", "open", "high", "low", "close", "volume", "turnover"]]
    for col in feature_cols:
        df[col] = df[col].shift(1)

    # Replace NaN/Inf with 0 for ML safety
    df[feature_cols] = df[feature_cols].replace([np.inf, -np.inf], 0).fillna(0)

    return df
