import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime


@dataclass
class Trade:
    entry_time: datetime
    exit_time: datetime
    side: int  # 1 long, -1 short
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


def _calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period, min_periods=period).mean()
    return atr


def run_backtest(
    df: pd.DataFrame,
    signal: pd.Series,
    config: Dict[str, Any],
    symbol: str = "",
    timeframe: int = 1,
    strategy_name: str = "",
) -> BacktestResult:
    """
    Vectorized backtest with leverage, ATR SL/TP, liquidation, and time exit.
    df: DataFrame with columns open, high, low, close, volume, timestamp
    signal: Series of -1, 0, 1 aligned with df index
    """
    initial_capital = config["backtest"]["initial_capital"]
    position_size_pct = config["backtest"]["position_size_pct"]
    fee_rate = config["backtest"]["fee_rate"]
    slippage = config["backtest"]["slippage"]
    leverage = config["backtest"].get("leverage", 1)

    stop_loss = config["risk"]["stop_loss"]
    take_profit = config["risk"]["take_profit"]
    use_atr_sl_tp = config["risk"].get("use_atr_sl_tp", False)
    atr_sl_mult = config["risk"].get("atr_multiplier_sl", 1.0)
    atr_tp_mult = config["risk"].get("atr_multiplier_tp", 2.0)
    max_hold_bars = config["risk"].get("max_hold_bars", 0)

    df = df.copy()
    df["signal"] = signal.reindex(df.index).fillna(0).astype(int)
    df["position"] = df["signal"].shift(1).fillna(0).astype(int)
    df["atr"] = _calculate_atr(df, period=14)

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
    sl_price = None
    tp_price = None
    liq_price = None

    for i in range(1, len(df)):
        row = df.iloc[i]
        prev_row = df.iloc[i - 1]
        timestamp = row["timestamp"]

        stopped_out = False

        # Check open position: SL / TP / liquidation / time exit
        if in_trade:
            bars_in_trade += 1

            # Liquidation check
            if side == 1 and row["low"] <= liq_price:
                exit_price = liq_price * (1 - slippage)
                pnl = -margin  # lose all margin
                capital += pnl
                trades.append(Trade(entry_time, timestamp, side, entry_price, exit_price, position_value, pnl, -1.0, "liquidation"))
                in_trade = False
                stopped_out = True
            elif side == -1 and row["high"] >= liq_price:
                exit_price = liq_price * (1 + slippage)
                pnl = -margin
                capital += pnl
                trades.append(Trade(entry_time, timestamp, side, entry_price, exit_price, position_value, pnl, -1.0, "liquidation"))
                in_trade = False
                stopped_out = True

            # SL / TP check
            if in_trade:
                if side == 1:
                    if row["low"] <= sl_price:
                        exit_price = sl_price * (1 - slippage)
                        pnl = (exit_price - entry_price) / entry_price * position_value * side * leverage - fee_rate * position_value
                        capital += pnl
                        trades.append(Trade(entry_time, timestamp, side, entry_price, exit_price, position_value, pnl, pnl / margin if margin else 0, "stop_loss"))
                        in_trade = False
                        stopped_out = True
                    elif row["high"] >= tp_price:
                        exit_price = tp_price * (1 - slippage)
                        pnl = (exit_price - entry_price) / entry_price * position_value * side * leverage - fee_rate * position_value
                        capital += pnl
                        trades.append(Trade(entry_time, timestamp, side, entry_price, exit_price, position_value, pnl, pnl / margin if margin else 0, "take_profit"))
                        in_trade = False
                        stopped_out = True
                elif side == -1:
                    if row["high"] >= sl_price:
                        exit_price = sl_price * (1 + slippage)
                        pnl = (exit_price - entry_price) / entry_price * position_value * side * leverage - fee_rate * position_value
                        capital += pnl
                        trades.append(Trade(entry_time, timestamp, side, entry_price, exit_price, position_value, pnl, pnl / margin if margin else 0, "stop_loss"))
                        in_trade = False
                        stopped_out = True
                    elif row["low"] <= tp_price:
                        exit_price = tp_price * (1 + slippage)
                        pnl = (exit_price - entry_price) / entry_price * position_value * side * leverage - fee_rate * position_value
                        capital += pnl
                        trades.append(Trade(entry_time, timestamp, side, entry_price, exit_price, position_value, pnl, pnl / margin if margin else 0, "take_profit"))
                        in_trade = False
                        stopped_out = True

            # Time exit
            if in_trade and max_hold_bars > 0 and bars_in_trade >= max_hold_bars:
                exit_price = row["open"] * (1 - slippage * side) if side == 1 else row["open"] * (1 + slippage * abs(side))
                pnl = (exit_price - entry_price) / entry_price * position_value * side * leverage - fee_rate * position_value
                capital += pnl
                trades.append(Trade(entry_time, timestamp, side, entry_price, exit_price, position_value, pnl, pnl / margin if margin else 0, "time_exit"))
                in_trade = False
                stopped_out = True

        # Entry / exit based on signal change
        if not in_trade and not stopped_out and row["position"] != 0:
            side = int(row["position"])
            entry_price = row["open"] * (1 + slippage * side) if side == 1 else row["open"] * (1 - slippage * abs(side))
            position_value = capital * position_size_pct
            margin = position_value / leverage
            entry_cost = fee_rate * position_value
            capital -= entry_cost
            entry_time = timestamp
            bars_in_trade = 0
            in_trade = True

            atr = row["atr"]
            if use_atr_sl_tp and pd.notna(atr) and atr > 0:
                sl_price = entry_price - atr * atr_sl_mult * side
                tp_price = entry_price + atr * atr_tp_mult * side
            else:
                sl_price = entry_price * (1 - stop_loss * side) if side == 1 else entry_price * (1 + stop_loss * abs(side))
                tp_price = entry_price * (1 + take_profit * side) if side == 1 else entry_price * (1 - take_profit * abs(side))

            liq_price = entry_price * (1 - 1 / leverage * side) if side == 1 else entry_price * (1 + 1 / leverage * abs(side))

        elif in_trade and row["position"] == 0:
            exit_price = row["open"] * (1 - slippage * side) if side == 1 else row["open"] * (1 + slippage * abs(side))
            pnl = (exit_price - entry_price) / entry_price * position_value * side * leverage - fee_rate * position_value
            capital += pnl
            trades.append(Trade(entry_time, timestamp, side, entry_price, exit_price, position_value, pnl, pnl / margin if margin else 0, "signal"))
            in_trade = False
            side = 0

        equity.append(capital)

    df["equity"] = equity
    return BacktestResult(
        symbol=symbol,
        timeframe=timeframe,
        strategy=strategy_name,
        equity=df.set_index("timestamp")["equity"],
        trades=trades,
    )
