import pandas as pd
from .base import Strategy


class BollingerRsiStrategy(Strategy):
    """Bollinger Bands + RSI mean reversion strategy."""

    def __init__(self, params: dict = None):
        super().__init__(params)
        self.bb_window = self.params.get("bb_window", 20)
        self.bb_std = self.params.get("bb_std", 2.0)
        self.rsi_window = self.params.get("rsi_window", 14)
        self.rsi_oversold = self.params.get("rsi_oversold", 30)
        self.rsi_overbought = self.params.get("rsi_overbought", 70)

    @property
    def name(self):
        return f"bollinger_rsi_{self.bb_window}_{self.rsi_window}"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        df = df.copy()
        df["ma"] = df["close"].rolling(self.bb_window).mean()
        df["std"] = df["close"].rolling(self.bb_window).std()
        df["upper"] = df["ma"] + self.bb_std * df["std"]
        df["lower"] = df["ma"] - self.bb_std * df["std"]

        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0).rolling(self.rsi_window).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(self.rsi_window).mean()
        rs = gain / loss
        df["rsi"] = 100 - (100 / (1 + rs))

        long_cond = (df["close"] < df["lower"]) & (df["rsi"] < self.rsi_oversold)
        short_cond = (df["close"] > df["upper"]) & (df["rsi"] > self.rsi_overbought)

        signal = pd.Series(0, index=df.index)
        signal[long_cond] = 1
        signal[short_cond] = -1
        return signal
