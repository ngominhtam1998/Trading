# Crypto Scalping Bot - Binance Futures

Backtest framework + production strategies for crypto scalping on Binance Futures (USDT perpetuals).

## Strategy Versions

### strategy_aggressive.py (V15r2) — *** PRODUCTION (main) ***
**High return, higher risk tolerance, 0 liquidation — LOCKED as primary strategy**

- 31/31 months profitable (100%)
- Avg return: +38.90%/month
- Median return: +32.46%
- Avg PF: 1.89
- Avg MaxDD: 6.8%
- 0 liquidations in 31 months
- Worst month: +2.44% (Jul 2022)
- Best month: +97.43% (Dec 2023)

Key params vs balanced:
- RR = 3.5 (was 3.0) — bigger winners
- SL = 1.3x ATR (was 1.5) — tighter stop
- BE at 0.5R (was 0.7R) — protect capital earlier
- Trail from 1.2R (was 1.5R) — lock profit sooner
- EMA200 + body as SOFT score bonuses (not hard filters)

### strategy_balanced.py (V14) — CONSERVATIVE
**Lower return, proven robust, 0 liquidation**

- 26/31 months profitable (84%)
- Avg return: +24.84%/month
- Median return: +20.80%
- Avg PF: 1.44
- Avg MaxDD: 10.3%
- 0 liquidations in 31 months
- Worst month: -11.45% (Jul 2022)
- Best month: +85.57% (Aug 2022)

Key params:
- RR = 3.0
- SL = 1.5x ATR
- BE at 0.7R
- Trail from 1.5R
- Max concurrent: 10 (5 in neutral BTC regime)

## Common Parameters (both strategies)

- Starting capital: $1000
- Position size: 7% of current equity (compounding)
- Max leverage: 10x (5x in neutral BTC regime)
- Daily loss limit: 5%
- Min score: 6
- Max concurrent: 10 positions
- Min notional: $5 (Binance Futures minimum)
- Max vol pct: 10% (liquidity check per bar)
- Fee: 0.01% per side
- Funding: 0.0005% per 8h

## Filters (both strategies)

1. EMA9 > EMA21 > EMA50 (trend alignment)
2. EMA50 slope > 0.05% (momentum)
3. ADX > 20 (trending market)
4. ATR < 1.5% (avoid high volatility)
5. RSI 40-65 LONG, 35-60 SHORT
6. BTC daily regime: EMA50/EMA200
   - Bull: only LONG
   - Bear: only SHORT
   - Neutral: both, max 5x lev, max 5 concurrent
7. 1h trend filter (uses previous CLOSED 1h bar, no look-ahead)

## Liquidation Model

- 25x -> ROE -55% = liq (price 2.2%)
- 20x -> ROE -65% = liq (price 3.25%)
- 15x -> ROE -75% = liq (price 5.0%)
- 10x -> ROE -85% = liq (price 8.5%)
- 5x  -> ROE -95% = liq (price 19.0%)
- Auto-reduce leverage if ROE at SL > 45%

## Compounding Logic

- margin = current_equity * 7%
- Win → equity up → position size up (compound)
- Lose → equity down → position size down (de-risk)
- Risk per trade stays constant at 7% of equity
- 0 liquidations because position shrinks as equity drops

## Execution Constraints (realistic)

- MIN_NOTIONAL: $5 (Binance Futures minimum)
- MAX_VOL_PCT: 10% (max % of bar quote volume per order)
- Partial fills: if order > 10% of bar volume, only partial fills; remaining stays open
- If remaining position < $5 notional → force close
- All entry/exit wrapped in try/except → skip coin on error

## No Look-Ahead Verified

- Entry: uses bar bi-1 (closed) for signal, bar bi open for entry
- 1h trend: uses previous closed 1h bar
- Exit: SL/TP checked before SL update (SL update applies next bar)
- Liquidation: checked first (worst case wick)

## Files

```
strategy_aggressive.py          — V15r2 (BEST, high return)
strategy_aggressive_test.py     — 31-month test for aggressive
strategy_balanced.py            — V14 (conservative, proven)
strategy_balanced_test.py       — 31-month test for balanced
strategy_balanced_6month_test.py — 6-month continuous test for balanced
main.py                         — Entry point (legacy)
mock_llm.py                     — Mock LLM for testing
mock_llm_agent.py               — Mock LLM agent
run_llm_agent.py                — LLM agent runner
```

## How to Test

```bash
# Test aggressive strategy (31 months)
python strategy_aggressive_test.py

# Test balanced strategy (31 months)
python strategy_balanced_test.py

# Test balanced strategy (6 months continuous)
python strategy_balanced_6month_test.py
```

## Important Notes

- Backtest uses Binance public API (no API key needed for historical data)
- Results are historical, not guarantee of future performance
- Always test with small capital before going live
- Compounding means position size changes with equity — monitor in live trading
