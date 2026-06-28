# Live Trading Bot — Binance USDT-M Futures

Execution + safety layer around the **opus** strategy (`strategy_opus.py`).
See `production/OPUS_TRADING.md` for the full strategy design; this file covers
the live execution/safety layer.

## Safety model (read this first)

The bot is built so that **a process crash never leaves you with an unprotected
position requiring manual intervention.**

1. **Real protective orders on the exchange.** Every position gets a
   `STOP_MARKET` (SL) and `TAKE_PROFIT_MARKET` (TP) order with
   `closePosition=true`, placed on Binance immediately after entry. If the bot
   process dies, **the exchange still closes your position at SL/TP automatically.**

2. **SQLite state + reconciliation on restart.** On every startup the bot calls
   `reconcile()` which makes the exchange and local DB consistent:

   | Scenario | Action |
   |---|---|
   | Position known + SL/TP intact | Resume managing |
   | Position known + SL/TP missing | Re-place SL/TP from saved prices |
   | Orphan position (not in DB) | **Adopt** + place emergency SL (your choice) |
   | In DB but gone from exchange | Record as closed, clean up |
   | Orders with no position | Cancel dangling orders |

3. **Entry crash window covered.** If entry fills but SL placement fails, the bot
   **immediately market-closes** the position rather than leave it unprotected.

4. **Every cycle is wrapped** — transient network/API errors are retried with
   backoff and never kill the loop.

So: if your VPS reboots, just start the bot again. It picks up exactly where it
left off. You do **not** need to manage open trades manually.

## Modes

Set with the `BOT_MODE` environment variable:

- `testnet` (default) — Binance Futures **Testnet**, fake money, full execution. **Start here.**
- `dry` — real market data, **no real orders** (logs intended trades only).
- `live` — **real money** on mainnet. Only after testnet is verified.

## Setup

### 1. Install deps
```bash
python -m pip install requests pandas urllib3
```

### 2. Get Testnet API keys
- Go to https://testnet.binancefuture.com → register → API Key
- Set environment variables (PowerShell):
```powershell
$env:BINANCE_TESTNET_KEY="your_testnet_key"
$env:BINANCE_TESTNET_SECRET="your_testnet_secret"
$env:BOT_MODE="testnet"
```

### 3. Run
```bash
python -m live.bot
```
(run from `D:/Tam/trading/production`)

### 4. Going live (after testnet works)
```powershell
$env:BINANCE_LIVE_KEY="your_live_key"
$env:BINANCE_LIVE_SECRET="your_live_secret"
$env:BOT_MODE="live"
python -m live.bot
```

## Files

```
live/
├── config.py            # mode, keys, strategy params, timing, recovery options
├── binance_client.py    # signed REST client: retries, backoff, error handling
├── exchange_filters.py  # per-symbol precision / min-notional rounding
├── state_db.py          # SQLite: positions, closed trades, events, kv
├── strategy_adapter.py  # live klines -> strategy.analyze_live (opus MTF decision)
├── bot.py               # reconciliation + main loop (entry/manage, 60s loop)
└── test_recovery.py     # offline crash-recovery self-test (no keys needed)
```

## Key config (strategy_opus.py + live/config.py)

The strategy params live in `production/strategy_opus.py`; `live/config.py`
handles mode/keys/timing. Key opus params:

| Setting | Value | Meaning |
|---|---|---|
| `POSITION_PCT` | 6.0 | % of equity per trade (scaled by confluence score) |
| `MAX_CONCURRENT` | 10 | max open positions |
| `MAX_LEVERAGE` | 12 | leverage cap |
| `DAILY_LOSS_LIMIT` | 8.0 | halt new entries if down 8% on the day |
| `MIN_SCORE` | 6 | minimum confluence score to enter |
| `UNIVERSE` | 30 | curated liquid major coins (no exotic testnet coins) |
| `SL_MAX_PCT` / `SL_ATR_MULT` | 1.3 / 1.4 | structure-based stop geometry |
| `RR` | 1.8 | reward:risk for TP |
| `BE_R` / `BE_LOCK_PCT` | 0.5 / 0.25 | breakeven trigger / locked profit |
| `TRAIL_START_R` / `TRAIL_ATR_MULT` | 0.7 / 1.2 | ATR trailing stop |
| `LOOP_SECONDS` | 60 | management loop cadence (1m) |
| `ENTRY_EVERY_LOOPS` | 3 | entry scan every 3 min |
| `ORPHAN_ACTION` | adopt | what to do with orphan positions |

## How the loop works

Every `LOOP_SECONDS` (60s):
1. Fetch current positions + equity.
2. **Manage** open positions on 1m close: move SL to breakeven at `BE_R`, then
   ATR-trail at `TRAIL_ATR_MULT` (cancel old SL, place new one).
3. Every `ENTRY_EVERY_LOOPS` (3 min): build short-term BTC context, scan the
   curated `UNIVERSE` with multi-timeframe alignment (15m trend, 5m momentum,
   1h context, 1m trigger), gate with bounce/exhaustion + funding filters,
   rank by confluence score, open positions in free slots.
4. Sleep to next loop.

SL/TP themselves trigger on the exchange intraday — more precise than the
bar-resolution backtest.

## Tests

```bash
# Mock tests (no API keys needed)
python -m live.test_recovery          # 17/17 crash-recovery scenarios
python -m live.test_decision_bars     # 6/6 DECISION_EVERY_BARS cadence
python -m live.test_sl_move           # 6/6 SL move (BE/trail) logic
python -m live.test_realized_pnl      # 4/4 income API PnL detection

# Real-API tests (need valid .env keys, run on VPS)
python -m live.test_data_verify       # 40/40 data sanity checks
python -m live.test_sl_fix             # 8/9 SL placement edge cases
python -m live.test_funding            # 10/10 funding rate checks
```

## Important notes

- **Always run testnet first.** Verify entries, SL/TP placement, and that
  restarting the bot recovers positions correctly.
- The bot uses ISOLATED margin per position.
- Position size compounds with equity (live equity fetched each cycle).
- Logs go to `live/bot_<mode>.log` and stdout.
- State DB is `live/state_<mode>.db` (separate per mode).
- Min notional per symbol is read from the exchange — some symbols may be
  skipped for small accounts (this is correct, prevents rejected orders).
