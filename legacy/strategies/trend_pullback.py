import pandas as pd
from .base import Strategy


class TrendPullbackStrategy(Strategy):
    """
    Trend pullback scalping.
    Long when price is above EMA trend and pulls back to EMA, then bounces.
    Short when price is below EMA trend and rallies to EMA, then rejects.
    No future data used.
    """

    def __init__(self, params: dict = None):
        super().__init__(params)
        self.trend_ema = self.params.get("trend_ema", 50)
        self.pullback_ema = self.params.get("pullback_ema", 10)

    @property
    def name(self):
        return f"trend_pullback_{self.trend_ema}_{self.pullback_ema}"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        df = df.copy()
        df["ema_trend"] = df["close"].ewm(span=self.trend_ema, adjust=False).mean()
        df["ema_fast"] = df["close"].ewm(span=self.pullback_ema, adjust=False).mean()

        # Long: trend up, fast EMA pulls back near trend EMA, then close above fast EMA
        long_cond = (
            (df["close"].shift(1) > df["ema_trend"].shift(1))
            & (df["ema_fast"].shift(1) <= df["ema_trend"].shift(1) * 1.005)
            & (df["close"] > df["ema_fast"])
        )

        # Short: trend down, fast EMA rallies near trend EMA, then close below fast EMA
        short_cond = (
            (df["close"].shift(1) < df["ema_trend"].shift(1))
            & (df["ema_fast"].shift(1) >= df["ema_trend"].shift(1) * 0.995)
            & (df["close"] < df["ema_fast"])
        )

        signal = pd.Series(0, index=df.index)
        signal[long_cond] = 1
        signal[short_cond] = -1
        return signal
