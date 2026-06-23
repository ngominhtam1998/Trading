import pandas as pd
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mock_llm import mock_llm_decision
from .base import Strategy


class LLMMockStrategy(Strategy):
    """
    Mock LLM-based strategy.
    At each candle, sends the last N candles to a mock LLM analyst and trades the signal.
    No future data is used: the context only contains candles up to the current one.
    """

    def __init__(self, params: dict = None):
        super().__init__(params)
        self.context_window = self.params.get("context_window", 50)

    @property
    def name(self):
        return f"llm_mock_{self.context_window}"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        signal = pd.Series(0, index=df.index)
        for i in range(self.context_window, len(df)):
            context = df.iloc[: i + 1].copy()
            decision = mock_llm_decision(context)
            signal.iloc[i] = decision.get("signal", 0)
        return signal
