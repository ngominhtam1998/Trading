from .sma_crossover import SmaCrossoverStrategy
from .bollinger_rsi import BollingerRsiStrategy
from .rsi_reversal import RsiReversalStrategy
from .breakout_momentum import BreakoutMomentumStrategy
from .trend_pullback import TrendPullbackStrategy
from .volatility_breakout import VolatilityBreakoutStrategy
from .volatility_breakout_hf import VolatilityBreakoutHFStrategy
from .scalp_momentum import ScalpMomentumStrategy
from .ml_momentum import MLMomentumStrategy
from .llm_mock_strategy import LLMMockStrategy
from .llm_agent_strategy import LLMAgentStrategy

STRATEGY_REGISTRY = {
    "sma_crossover": SmaCrossoverStrategy,
    "bollinger_rsi": BollingerRsiStrategy,
    "rsi_reversal": RsiReversalStrategy,
    "breakout_momentum": BreakoutMomentumStrategy,
    "trend_pullback": TrendPullbackStrategy,
    "volatility_breakout": VolatilityBreakoutStrategy,
    "volatility_breakout_hf": VolatilityBreakoutHFStrategy,
    "scalp_momentum": ScalpMomentumStrategy,
    "ml_momentum": MLMomentumStrategy,
    "llm_mock": LLMMockStrategy,
    "llm_agent": LLMAgentStrategy,
}


def get_strategy(name: str, params: dict = None):
    cls = STRATEGY_REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"Unknown strategy: {name}")
    return cls(params)
