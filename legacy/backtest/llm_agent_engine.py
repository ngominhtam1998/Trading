import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Any, Callable
from datetime import datetime


@dataclass
class Trade:
    entry_time: datetime
    exit_time: datetime
    side: int
    entry_price: float
    exit_price: float
    size: float
    pnl: float
    pnl_pct: float
    reason: str


@dataclass
class BacktestResult:
    symbol: str
    timeframe: int
    strategy: str
    equity: pd.Series
    trades: List[Trade]
    metrics: Dict[str, Any] = field(default_factory=dict)


def run_llm_agent_backtest(
    df: pd.DataFrame,
    decision_fn: Callable,
    config: Dict[str, Any],
    symbol: str = "",
    timeframe: int = 1,
    strategy_name: str = "",
) -> BacktestResult:
    """
    LLM agent backtest. The decision_fn receives market context + position state
    and returns one of: 'open_long', 'open_short', 'close', 'hold'.
    No fixed SL/TP. The agent decides when to exit.
    """
    initial_capital = config["backtest"]["initial_capital"]
    position_size_pct = config["backtest"]["position_size_pct"]
    fee_rate = config["backtest"]["fee_rate"]
    slippage = config["backtest"]["slippage"]
    leverage = config["backtest"].get("leverage", 1)

    capital = initial_capital
    equity = [capital]
    trades = []
    in_trade = False
    entry_time = None
    entry_price = None
    side = 0
    position_value = 0.0
    margin = 0.0
    bars_in_trade = 0
    max_bars = config["risk"].get("max_hold_bars", 0)

    for i in range(50, len(df)):
        row = df.iloc[i]
        prev_row = df.iloc[i - 1]
        timestamp = row["timestamp"]

        context = df.iloc[: i + 1].copy()
        position_state = {
            "in_trade": in_trade,
            "side": side,
            "entry_price": entry_price,
            "bars_in_trade": bars_in_trade,
            "unrealized_pnl_pct": ((row["close"] - entry_price) / entry_price * side * leverage) if in_trade else 0.0,
        }
        action = decision_fn(context, position_state)

        # Force close if max hold bars exceeded
        if max_bars > 0 and in_trade and bars_in_trade >= max_bars:
            action = "close"
            reason = "max_hold_bars"
        else:
            reason = action

        if not in_trade and action == "open_long":
            side = 1
            entry_price = row["open"] * (1 + slippage)
            position_value = capital * position_size_pct
            margin = position_value / leverage
            capital -= fee_rate * position_value
            entry_time = timestamp
            bars_in_trade = 0
            in_trade = True

        elif not in_trade and action == "open_short":
            side = -1
            entry_price = row["open"] * (1 - slippage)
            position_value = capital * position_size_pct
            margin = position_value / leverage
            capital -= fee_rate * position_value
            entry_time = timestamp
            bars_in_trade = 0
            in_trade = True

        elif in_trade and action == "close":
            exit_price = row["open"] * (1 - slippage * side)
            pnl = (exit_price - entry_price) / entry_price * position_value * side * leverage - fee_rate * position_value
            capital += pnl
            trades.append(Trade(entry_time, timestamp, side, entry_price, exit_price, position_value, pnl, pnl / margin if margin else 0, reason))
            in_trade = False
            side = 0
            bars_in_trade = 0

        if in_trade:
            bars_in_trade += 1

        equity.append(capital)

    df = df.iloc[50:].copy()
    df["equity"] = equity[1:]
    return BacktestResult(
        symbol=symbol,
        timeframe=timeframe,
        strategy=strategy_name,
        equity=df.set_index("timestamp")["equity"],
        trades=trades,
    )
