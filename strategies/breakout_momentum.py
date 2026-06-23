import pandas as pd
from .base import Strategy


class BreakoutMomentumStrategy(Strategy):
    """
    Breakout momentum scalping.
    Long when close breaks above highest high of last N bars with volume spike.
    Short when close breaks below lowest low of last N bars with volume spike.
    No future data used.
    """

    def __init__(self, params: dict = None):
        super().__init__(params)
        self.lookback = self.params.get("lookback", 10)
        self.volume_mult = self.params.get("volume_mult", 1.2)

    @property
    def name(self):
        return f"breakout_momentum_{self.lookback}_{self.volume_mult}"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        df = df.copy()
        df["highest_high"] = df["high"].rolling(self.lookback).max().shift(1)
        df["lowest_low"] = df["low"].rolling(self.lookback).min().shift(1)
        df["volume_ma"] = df["volume"].rolling(self.lookback).mean().shift(1)

        long_cond = (df["close"] > df["highest_high"]) & (df["volume"] > self.volume_mult * df["volume_ma"])
        short_cond = (df["close"] < df["lowest_low"]) & (df["volume"] > self.volume_mult * df["volume_ma"])

        signal = pd.Series(0, index=df.index)
        signal[long_cond] = 1
        signal[short_cond] = -1
        return signal
