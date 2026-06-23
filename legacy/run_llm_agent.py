import os
import yaml
import argparse
import pandas as pd
from datetime import datetime

from data.bybit_fetcher import fetch_multi
from backtest.metrics import calculate_metrics, print_metrics
from strategies import get_strategy


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser(description="LLM agent backtest runner")
    parser.add_argument("--config", default="config.llm_agent.yaml", help="Path to config file")
    parser.add_argument("--fetch", action="store_true", help="Fetch fresh data")
    args = parser.parse_args()

    config = load_config(args.config)
    symbols = config["symbols"]
    timeframes = config["timeframes"]
    category = config["exchange"].get("category", "spot")
    days = config["fetch"].get("days", 28)

    print("=== LLM Agent Backtest Runner ===")
    print(f"Symbols: {symbols}")
    print(f"Timeframes: {timeframes}m")
    print(f"Data days: {days}")
    print(f"Category: {category}")

    if args.fetch or not os.listdir("data"):
        print("\n[1/3] Fetching data...")
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
        print("\n[1/3] Loading cached data...")
        data = {}
        for symbol in symbols:
            for tf in timeframes:
                key = f"{symbol}_{tf}m"
                path = f"data/{key}_{category}.csv"
                if os.path.exists(path):
                    data[key] = pd.read_csv(path, parse_dates=["timestamp"])

    print("\n[2/3] Running LLM agent backtest...")
    results = []
    for symbol in symbols:
        for tf in timeframes:
            key = f"{symbol}_{tf}m"
            df = data.get(key)
            if df is None or df.empty:
                print(f"[Skip] No data for {key}")
                continue

            strategy = get_strategy("llm_agent")
            result = strategy.run_backtest(df, config, symbol, tf)
            metrics = calculate_metrics(result)
            results.append(metrics)
            print(f"  {symbol} {tf}m {strategy.name}: return={metrics['total_return']*100:.2f}%, drawdown={metrics['max_drawdown']*100:.2f}%, trades={metrics['num_trades']}")

    print("\n[3/3] Results:")
    if not results:
        print("No results.")
        return

    report_df = pd.DataFrame(results)
    report_df = report_df.sort_values("total_return", ascending=False)
    os.makedirs(config["output"]["reports_dir"], exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(config["output"]["reports_dir"], f"llm_agent_report_{timestamp}.csv")
    report_df.to_csv(report_path, index=False)
    print(f"[Saved] {report_path}")
    print(report_df.to_string(index=False))

    print("\n=== Best result ===")
    print_metrics(report_df.iloc[0].to_dict())


if __name__ == "__main__":
    main()
