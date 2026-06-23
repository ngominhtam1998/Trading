import pandas as pd
from .base import Strategy


class VolatilityBreakoutHFStrategy(Strategy):
    """
    High-frequency volatility breakout scalping.
    Tighter Bollinger Bands + lower squeeze threshold to generate more signals.
    No future data used.
    """

    def __init__(self, params: dict = None):
        super().__init__(params)
        self.bb_window = self.params.get("bb_window", 10)
        self.bb_std = self.params.get("bb_std", 1.8)
        self.squeeze_lookback = self.params.get("squeeze_lookback", 15)
        self.squeeze_percentile = self.params.get("squeeze_percentile", 0.1)
        self.volume_mult = self.params.get("volume_mult", 1.0)
        self.atr_period = self.params.get("atr_period", 14)
        self.atr_filter_mult = self.params.get("atr_filter_mult", 0.5)

    @property
    def name(self):
        return f"volatility_breakout_hf_{self.bb_window}_{self.squeeze_lookback}"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        df = df.copy()
        df["ma"] = df["close"].rolling(self.bb_window).mean()
        df["std"] = df["close"].rolling(self.bb_window).std()
        df["upper"] = df["ma"] + self.bb_std * df["std"]
        df["lower"] = df["ma"] - self.bb_std * df["std"]
        df["bandwidth"] = (df["upper"] - df["lower"]) / df["ma"]
        df["bandwidth_low"] = df["bandwidth"].rolling(self.squeeze_lookback).quantile(self.squeeze_percentile).shift(1)
        df["was_squeeze"] = df["bandwidth"].shift(1) <= df["bandwidth_low"]

        df["volume_ma"] = df["volume"].rolling(self.bb_window).mean().shift(1)
        df["volume_ok"] = df["volume"] > self.volume_mult * df["volume_ma"]

        prev_close = df["close"].shift(1)
        tr1 = df["high"] - df["low"]
        tr2 = (df["high"] - prev_close).abs()
        tr3 = (df["low"] - prev_close).abs()
        df["tr"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df["atr"] = df["tr"].rolling(self.atr_period).mean()
        df["atr_ma"] = df["atr"].rolling(self.squeeze_lookback).mean().shift(1)
        df["atr_ok"] = df["atr"] > self.atr_filter_mult * df["atr_ma"]

        long_cond = df["was_squeeze"] & df["volume_ok"] & df["atr_ok"] & (df["close"] > df["upper"].shift(1))
        short_cond = df["was_squeeze"] & df["volume_ok"] & df["atr_ok"] & (df["close"] < df["lower"].shift(1))

        signal = pd.Series(0, index=df.index)
        signal[long_cond] = 1
        signal[short_cond] = -1
        return signal
