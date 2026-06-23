import pandas as pd
from .base import Strategy


class ScalpMomentumStrategy(Strategy):
    """
    Short-term momentum scalping for altcoins.
    Long when fast EMA crosses above slow EMA, RSI confirms momentum, and volume spikes.
    Short when fast EMA crosses below slow EMA, RSI confirms, and volume spikes.
    No future data used.
    """

    def __init__(self, params: dict = None):
        super().__init__(params)
        self.fast_ema = self.params.get("fast_ema", 5)
        self.slow_ema = self.params.get("slow_ema", 12)
        self.rsi_window = self.params.get("rsi_window", 7)
        self.rsi_long = self.params.get("rsi_long", 52)
        self.rsi_short = self.params.get("rsi_short", 48)
        self.volume_mult = self.params.get("volume_mult", 1.0)

    @property
    def name(self):
        return f"scalp_momentum_{self.fast_ema}_{self.slow_ema}_{self.rsi_window}"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        df = df.copy()
        df["ema_fast"] = df["close"].ewm(span=self.fast_ema, adjust=False).mean()
        df["ema_slow"] = df["close"].ewm(span=self.slow_ema, adjust=False).mean()
        df["cross_up"] = (df["ema_fast"] > df["ema_slow"]) & (df["ema_fast"].shift(1) <= df["ema_slow"].shift(1))
        df["cross_down"] = (df["ema_fast"] < df["ema_slow"]) & (df["ema_fast"].shift(1) >= df["ema_slow"].shift(1))

        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0).rolling(self.rsi_window).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(self.rsi_window).mean()
        rs = gain / loss
        df["rsi"] = 100 - (100 / (1 + rs))

        df["volume_ma"] = df["volume"].rolling(self.slow_ema).mean().shift(1)
        df["volume_ok"] = df["volume"] > self.volume_mult * df["volume_ma"]

        long_cond = df["cross_up"] & (df["rsi"] > self.rsi_long) & df["volume_ok"]
        short_cond = df["cross_down"] & (df["rsi"] < self.rsi_short) & df["volume_ok"]

        signal = pd.Series(0, index=df.index)
        signal[long_cond] = 1
        signal[short_cond] = -1
        return signal
