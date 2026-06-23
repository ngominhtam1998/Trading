import pandas as pd
from .base import Strategy


class RsiReversalStrategy(Strategy):
    """High-frequency RSI mean reversion for scalping."""

    def __init__(self, params: dict = None):
        super().__init__(params)
        self.rsi_window = self.params.get("rsi_window", 7)
        self.oversold = self.params.get("oversold", 25)
        self.overbought = self.params.get("overbought", 75)

    @property
    def name(self):
        return f"rsi_reversal_{self.rsi_window}_{self.oversold}_{self.overbought}"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        df = df.copy()
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0).rolling(self.rsi_window).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(self.rsi_window).mean()
        rs = gain / loss
        df["rsi"] = 100 - (100 / (1 + rs))

        long_cond = df["rsi"] < self.oversold
        short_cond = df["rsi"] > self.overbought

        signal = pd.Series(0, index=df.index)
        signal[long_cond] = 1
        signal[short_cond] = -1
        return signal
