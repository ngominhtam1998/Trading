import pandas as pd
import numpy as np
from typing import Dict, List
from .engine import BacktestResult, Trade


def calculate_metrics(result: BacktestResult) -> Dict[str, float]:
    equity = result.equity
    trades = result.trades

    if equity.empty:
        return {}

    initial = equity.iloc[0]
    final = equity.iloc[-1]
    total_return = (final - initial) / initial

    # Daily returns
    daily_equity = equity.resample("D").last().dropna()
    daily_returns = daily_equity.pct_change().dropna()

    # Sharpe (annualized, 252 trading days, risk-free = 0)
    sharpe = 0.0
    if len(daily_returns) > 1 and daily_returns.std() > 0:
        sharpe = (daily_returns.mean() / daily_returns.std()) * np.sqrt(252)

    # Sortino
    downside = daily_returns[daily_returns < 0]
    sortino = 0.0
    if len(downside) > 0 and downside.std() > 0:
        sortino = (daily_returns.mean() / downside.std()) * np.sqrt(252)

    # Max drawdown
    rolling_max = equity.cummax()
    drawdown = (equity - rolling_max) / rolling_max
    max_drawdown = drawdown.min()

    # Calmar
    years = max((equity.index[-1] - equity.index[0]).days / 365.25, 0.01)
    cagr = (final / initial) ** (1 / years) - 1 if initial > 0 else 0.0
    calmar = cagr / abs(max_drawdown) if max_drawdown != 0 else 0.0

    # Trade metrics
    if trades:
        pnls = [t.pnl for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        win_rate = len(wins) / len(pnls) if pnls else 0.0
        gross_profit = sum(wins) if wins else 0.0
        gross_loss = abs(sum(losses)) if losses else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
        avg_trade = np.mean(pnls)
        num_trades = len(trades)
        liquidation_count = sum(1 for t in trades if t.reason == "liquidation")
        time_exit_count = sum(1 for t in trades if t.reason == "time_exit")
        sl_count = sum(1 for t in trades if t.reason == "stop_loss")
        tp_count = sum(1 for t in trades if t.reason == "take_profit")
    else:
        win_rate = 0.0
        profit_factor = 0.0
        avg_trade = 0.0
        num_trades = 0
        liquidation_count = 0
        time_exit_count = 0
        sl_count = 0
        tp_count = 0

    return {
        "symbol": result.symbol,
        "timeframe": result.timeframe,
        "strategy": result.strategy,
        "initial_capital": initial,
        "final_capital": final,
        "total_return": total_return,
        "profit_loss": final - initial,
        "cagr": cagr,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_drawdown,
        "calmar": calmar,
        "num_trades": num_trades,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "avg_trade": avg_trade,
        "liquidation_count": liquidation_count,
        "time_exit_count": time_exit_count,
        "sl_count": sl_count,
        "tp_count": tp_count,
    }


def print_metrics(metrics: Dict[str, float]):
    print(f"\n=== Backtest Result: {metrics.get('symbol')} | {metrics.get('timeframe')}m | {metrics.get('strategy')} ===")
    print(f"Initial capital:    ${metrics['initial_capital']:,.2f}")
    print(f"Final capital:      ${metrics['final_capital']:,.2f}")
    print(f"Profit/Loss:        ${metrics['profit_loss']:,.2f}")
    print(f"Total return:       {metrics['total_return']*100:.2f}%")
    print(f"CAGR:               {metrics['cagr']*100:.2f}%")
    print(f"Sharpe:             {metrics['sharpe']:.2f}")
    print(f"Sortino:            {metrics['sortino']:.2f}")
    print(f"Max drawdown:       {metrics['max_drawdown']*100:.2f}%")
    print(f"Calmar:             {metrics['calmar']:.2f}")
    print(f"Trades:             {metrics['num_trades']}")
    print(f"Win rate:           {metrics['win_rate']*100:.2f}%")
    print(f"Profit factor:      {metrics['profit_factor']:.2f}")
    print(f"Avg trade:          ${metrics['avg_trade']:.2f}")
    print(f"SL / TP / Liquidation / Time exit: {metrics['sl_count']} / {metrics['tp_count']} / {metrics['liquidation_count']} / {metrics['time_exit_count']}")
