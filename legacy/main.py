import os
import yaml
import argparse
import pandas as pd
from datetime import datetime

from data.bybit_fetcher import fetch_multi
from backtest.engine import run_backtest
from backtest.metrics import calculate_metrics, print_metrics
from strategies import get_strategy


def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser(description="Scalping backtest runner")
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    parser.add_argument("--fetch", action="store_true", help="Fetch fresh data")
    parser.add_argument("--days", type=int, default=None, help="Override fetch days (default from config)")
    args = parser.parse_args()

    config = load_config(args.config)
    symbols = config["symbols"]
    timeframes = config["timeframes"]
    category = config["exchange"].get("category", "spot")
    # Support old 'months' key or new 'days' key
    config_days = config["fetch"].get("days", config["fetch"].get("months", 1) * 30)
    days = args.days if args.days is not None else config_days

    print("=== Scalping Backtest Runner ===")
    print(f"Symbols: {symbols}")
    print(f"Timeframes: {timeframes}m")
    print(f"Data days: {days}")
    print(f"Category: {category}")

    # Fetch data
    if args.fetch or not os.listdir("data"):
        print("\n[1/4] Fetching data from Bybit...")
        data = fetch_multi(
            symbols=symbols,
            intervals=timeframes,
            days=days,
            data_dir="data",
            category=category,
            limit=config["fetch"]["limit"],
            sleep_ms=config["fetch"]["sleep_ms"],
        )
    else:
        print("\n[1/4] Loading cached data...")
        data = {}
        for symbol in symbols:
            for tf in timeframes:
                key = f"{symbol}_{tf}m"
                path = f"data/{key}_{category}.csv"
                if os.path.exists(path):
                    data[key] = pd.read_csv(path, parse_dates=["timestamp"])

    print("\n[2/4] Running backtests...")
    results = []
    for symbol in symbols:
        for tf in timeframes:
            key = f"{symbol}_{tf}m"
            df = data.get(key)
            if df is None or df.empty:
                print(f"[Skip] No data for {key}")
                continue

            for strat_name in config["strategies"]:
                strategy = get_strategy(strat_name)
                signal = strategy.generate_signals(df)
                result = run_backtest(
                    df=df,
                    signal=signal,
                    config=config,
                    symbol=symbol,
                    timeframe=tf,
                    strategy_name=strategy.name,
                )
                metrics = calculate_metrics(result)
                results.append(metrics)
                print(f"  {symbol} {tf}m {strategy.name}: return={metrics['total_return']*100:.2f}%, drawdown={metrics['max_drawdown']*100:.2f}%, trades={metrics['num_trades']}")

    print("\n[3/4] Generating report...")
    if not results:
        print("No results.")
        return

    report_df = pd.DataFrame(results)
    report_df = report_df.sort_values("total_return", ascending=False)

    os.makedirs(config["output"]["reports_dir"], exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(config["output"]["reports_dir"], f"backtest_report_{timestamp}.csv")
    report_df.to_csv(report_path, index=False)
    print(f"[Saved] {report_path}")

    print("\n[4/4] Top 5 results by total return:")
    print(report_df.head(5).to_string(index=False))

    print("\n=== Best result ===")
    best = report_df.iloc[0]
    print_metrics(best.to_dict())


if __name__ == "__main__":
    main()
