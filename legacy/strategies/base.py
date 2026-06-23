import pandas as pd
from abc import ABC, abstractmethod
from typing import Dict, Any


class Strategy(ABC):
    """Base class for strategies."""

    def __init__(self, params: Dict[str, Any] = None):
        self.params = params or {}

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        """
        Return a pandas Series of signals aligned with df index:
        -1 = short, 0 = flat, 1 = long
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        pass
