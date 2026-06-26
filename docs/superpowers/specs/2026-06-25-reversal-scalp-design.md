# Design: `strategy_reversal_scalp` — Mean-Reversion Scalper (1m)

**Date:** 2026-06-25
**Status:** Approved (design), lab-only (no live deploy)

## 1. Purpose

A new **experimental** strategy that catches tops/bottoms via mean-reversion
scalping on the **1m** timeframe. When a coin is pushed too far too fast (a
spike), enter the opposite direction to capture the pullback ("con sóng hồi").

- **High leverage** inherited from v6 (up to ~22x).
- **Small, adaptive TP** (do NOT set deep targets — scalp the realistic
  pullback). Edge comes from high win-rate at statistical extremes, not big RR.
- **Lab only.** Does NOT touch the live bot (`bot.py`) or the existing
  trend-following strategies `strategy_aggressive_lv4/lv5/lv6`. Live integration
  is deferred.

## 2. Coin Selection (Top 5)

Every 15–30 min, re-rank all USDT perpetuals by an **activity score**:

```
activity_score = (24h quote volume) × (1m ATR% over last 60 minutes)
```

Pick the **top 5** — coins that are both liquid (volume) and volatile (moving).
Only these 5 are watched; in live mode they would be polled every ~20s. In
backtest the selection is computed per coin from the same metric on the loaded
window.

## 3. Entry Logic (Hybrid Mean-Reversion)

SHORT (catch top) requires ALL of the following on the 1m series. LONG (catch
bottom) is the exact mirror.

1. **Spike trigger:** price rose ≥ `SPIKE_PCT` within the last `SPIKE_LOOKBACK`
   minutes (e.g. +2.0% in 3–5 bars) — a rapid pump.
2. **Overextension confirm:** `RSI(7) ≥ 80` AND price above the upper Bollinger
   Band `BB(20, 2.5σ)` — a statistical extreme.
3. **Exhaustion candle:** the latest closed 1m candle shows reversal —
   upper wick ≥ `1.5 × body` OR a bearish close (`close < open`). This confirms
   price has started to turn before we enter (avoid the falling-knife of
   shorting mid-pump).
4. **Volume climax (bonus, scoring):** spike candle volume ≫ average → blow-off
   top adds confidence but is not mandatory.

Key principle: **wait for the first sign of reversal, do not blindly pick the
exact top.**

## 4. TP / SL — Adaptive

- Measure **spike size** `S` = the % magnitude of the move that triggered entry.
- **TP** = retrace ≈ 50% of `S` from entry (e.g. short at 100 after a 98→100
  spike → TP ≈ 99). Clamped to a sane band `[TP_MIN_PCT, TP_MAX_PCT]`
  (e.g. 0.4% – 1.5%). Target the realistic pullback, never a deep target.
- **SL** = just beyond the spike extreme + small buffer (a fraction of `S` or of
  1m ATR). If price prints a new high beyond the spike, the reversal thesis is
  invalidated → cut.
- **Time stop:** if neither TP nor SL hit within `MAX_HOLD_MIN` (~10–15 min),
  close at market. A scalp must resolve fast.
- Resulting RR ≈ 1:1 to 1.5:1; the win-rate at extremes carries the expectancy.

## 5. Risk Management

- Leverage tiers like v6 (up to `MAX_LEVERAGE = 22`), reused
  `adjust_leverage_for_liq()` logic so SL never sits too close to liquidation.
  Because SL is tight in %, ROE-at-SL stays controlled even at high leverage.
- `POSITION_PCT` inherited from v6 (22% of equity).
- `MAX_CONCURRENT` small (2–3) since only 5 coins are watched and scalps are
  quick.
- `DAILY_LOSS_LIMIT` circuit breaker retained.
- Cooldown after consecutive SLs on the same coin (reuse v6 pattern:
  2 consecutive SL → cooldown N bars).

## 6. Code Architecture

- **`production/strategy_reversal_scalp.py`** — self-contained module:
  - constants (SPIKE_PCT, BB params, RSI period, TP/SL bands, leverage, risk)
  - `get_all_symbols()`, `fetch_klines_range()` (reused pattern, 1m interval)
  - `add_indicators_1m(df)` — RSI(7), Bollinger(20, 2.5σ), ATR(14), spike metrics
  - `decide_reversal(row, window, ...)` → `{dir, lev, sl, tp, ...}` or `None`
  - `backtest_portfolio(coin_data)` operating bar-by-bar on 1m data, with the
    spike/TP/SL/time-stop logic and intrabar high/low fill checks
  - `report(...)` summary identical in spirit to the lv6 reports
- **`production/backtest_reversal_scalp.py`** — runner that fetches **real 1m**
  data for the top-N coins over a recent 2–3 month window, runs
  `backtest_portfolio`, prints return / WR / PF / MaxDD / trades / avg hold.
- **No changes** to `live/bot.py`, `live/config.py`, or `strategy_aggressive_*`.

## 7. Validation

- Backtest on **real 1m** Binance data, recent **2–3 month** window, top-N
  active coins (by the activity score). Report monthly/aggregate metrics.
- Success criteria for the lab: positive expectancy (PF > 1.1) with WR clearly
  above 50% (mean-reversion should be high WR), acceptable MaxDD, and enough
  trades to be statistically meaningful (not "1 trade/month").

## 8. Out of Scope (YAGNI)

- Live deployment / systemd service / new exchange account.
- WebSocket real-time feed (live polling design deferred).
- Multi-timeframe confluence beyond the 1m signal (no 1h/BTC-regime gate; this
  is a microstructure scalper, the macro regime filter from trend strategies is
  intentionally omitted).
