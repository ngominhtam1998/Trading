import pandas as pd
from .base import Strategy


class SmaCrossoverStrategy(Strategy):
    """Simple SMA crossover strategy."""

    def __init__(self, params: dict = None):
        super().__init__(params)
        self.fast = self.params.get("fast", 9)
        self.slow = self.params.get("slow", 21)
        self.trend_filter = self.params.get("trend_filter", 200)

    @property
    def name(self):
        return f"sma_crossover_{self.fast}_{self.slow}"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        df = df.copy()
        df["fast"] = df["close"].rolling(self.fast).mean()
        df["slow"] = df["close"].rolling(self.slow).mean()
        df["trend"] = df["close"].rolling(self.trend_filter).mean()

        # Long when fast > slow and price > trend
        long_cond = (df["fast"] > df["slow"]) & (df["close"] > df["trend"])
        short_cond = (df["fast"] < df["slow"]) & (df["close"] < df["trend"])

        signal = pd.Series(0, index=df.index)
        signal[long_cond] = 1
        signal[short_cond] = -1
        return signal
