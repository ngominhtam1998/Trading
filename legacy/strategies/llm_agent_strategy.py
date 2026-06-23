import pandas as pd
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mock_llm_agent import mock_llm_agent_decision
from backtest.llm_agent_engine import run_llm_agent_backtest
from .base import Strategy


class LLMAgentStrategy(Strategy):
    """
    LLM agent strategy. The LLM decides entry, exit, and direction.
    No fixed SL/TP. Uses llm_agent_engine.
    """

    def __init__(self, params: dict = None):
        super().__init__(params)

    @property
    def name(self):
        return "llm_agent"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        # Not used; engine directly calls decision_fn.
        return pd.Series(0, index=df.index)

    def run_backtest(self, df, config, symbol, timeframe):
        return run_llm_agent_backtest(
            df=df,
            decision_fn=mock_llm_agent_decision,
            config=config,
            symbol=symbol,
            timeframe=timeframe,
            strategy_name=self.name,
        )
