import os
import time
import requests
import urllib3
import pandas as pd
from datetime import datetime, timezone, timedelta
from typing import Optional
from tqdm import tqdm

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://api.bybit.com"

COLUMNS = [
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "turnover",
]


def fetch_klines(
    symbol: str,
    interval: int,
    start_ms: int,
    end_ms: int,
    limit: int = 1000,
    category: str = "spot",
    sleep_ms: int = 100,
    retries: int = 3,
) -> pd.DataFrame:
    """Fetch one batch of klines from Bybit V5 API."""
    url = f"{BASE_URL}/v5/market/kline"
    params = {
        "category": category,
        "symbol": symbol,
        "interval": str(interval),
        "start": start_ms,
        "end": end_ms,
        "limit": limit,
    }

    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=30, verify=False)
            resp.raise_for_status()
            data = resp.json()
            if data.get("retCode") == 10001:
                # Symbol not supported
                return pd.DataFrame(columns=COLUMNS)
            if data.get("retCode") != 0:
                raise RuntimeError(f"Bybit API error: {data}")
            rows = data["result"]["list"]
            if not rows:
                return pd.DataFrame(columns=COLUMNS)
            df = pd.DataFrame(rows, columns=COLUMNS)
            df["timestamp"] = pd.to_datetime(df["timestamp"].astype(int), unit="ms", utc=True)
            for col in ["open", "high", "low", "close", "volume", "turnover"]:
                df[col] = df[col].astype(float)
            df = df.sort_values("timestamp").reset_index(drop=True)
            if sleep_ms:
                time.sleep(sleep_ms / 1000.0)
            return df
        except Exception as e:
            if attempt == retries - 1:
                raise
            print(f"Retry {attempt + 1} for {symbol} {interval}: {e}")
            time.sleep(2 ** attempt)


def fetch_all(
    symbol: str,
    interval: int,
    days: int = 30,
    limit: int = 1000,
    category: str = "spot",
    sleep_ms: int = 100,
    data_dir: str = "data",
) -> pd.DataFrame:
    """Fetch all klines for a symbol/interval going back N days."""
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)

    os.makedirs(data_dir, exist_ok=True)
    cache_path = os.path.join(data_dir, f"{symbol}_{interval}m_{category}.csv")

    if os.path.exists(cache_path):
        cached = pd.read_csv(cache_path, parse_dates=["timestamp"])
        if not cached.empty:
            cached_start = cached["timestamp"].min().value // 10**6
            if cached_start <= start_ms:
                print(f"[Cache] Using {cache_path}")
                return cached

    all_dfs = []
    interval_ms = interval * 60 * 1000
    step_ms = limit * interval_ms
    current_start = start_ms
    pbar = tqdm(total=end_ms - start_ms, desc=f"Fetching {symbol} {interval}m")

    while current_start < end_ms:
        current_end = min(current_start + step_ms, end_ms)
        batch = fetch_klines(
            symbol=symbol,
            interval=interval,
            start_ms=current_start,
            end_ms=current_end,
            limit=limit,
            category=category,
            sleep_ms=sleep_ms,
        )
        if batch.empty:
            break
        all_dfs.append(batch)
        last_ts = int(batch["timestamp"].max().timestamp() * 1000)
        next_start = last_ts + interval_ms
        if next_start <= current_start:
            break
        pbar.update(min(next_start - current_start, current_end - current_start))
        current_start = next_start

    pbar.close()

    if not all_dfs:
        return pd.DataFrame(columns=COLUMNS)

    df = pd.concat(all_dfs, ignore_index=True)
    df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    df.to_csv(cache_path, index=False)
    print(f"[Saved] {cache_path} ({len(df)} rows)")
    return df


def fetch_multi(
    symbols: list[str],
    intervals: list[int],
    days: int = 30,
    data_dir: str = "data",
    **kwargs,
) -> dict:
    """Fetch data for multiple symbols and intervals."""
    data = {}
    for symbol in symbols:
        for interval in intervals:
            key = f"{symbol}_{interval}m"
            data[key] = fetch_all(
                symbol=symbol,
                interval=interval,
                days=days,
                data_dir=data_dir,
                **kwargs,
            )
    return data


if __name__ == "__main__":
    df = fetch_all("BTCUSDT", 1, days=7)
    print(df.head())
    print(df.tail())
