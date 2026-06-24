# Live Trading Bot — Binance USDT-M Futures

Execution + safety layer around the `strategy_aggressive_lv1` (LV1) strategy.
**Trading logic is unchanged** — this only adds order execution, error handling,
and crash recovery.

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
(run from `D:/Temp/Trading`)

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
├── strategy_adapter.py  # live klines -> decide_v15 (shared function name, no logic change)
├── bot.py               # reconciliation + main loop (entry/manage)
└── test_recovery.py     # offline crash-recovery self-test (no keys needed)
```

## Key config (live/config.py)

| Setting | Default | Meaning |
|---|---|---|
| `POSITION_PCT` | 7.0 | % of equity per trade (compounding) |
| `MAX_CONCURRENT` | 10 | max open positions (5 in neutral regime) |
| `MAX_LEVERAGE` | 10 | cap leverage (5 in neutral regime) |
| `DAILY_LOSS_LIMIT` | 5.0 | halt new entries if down 5% on the day |
| `MIN_SCORE` | 6 | minimum signal score |
| `COINS_UNIVERSE_SIZE` | 60 | top-volume symbols scanned per cycle |
| `DECISION_EVERY_BARS` | 16 | entry scan cadence (matches backtest) |
| `MAX_HOLD_BARS` | 48 | force-close after 12h |
| `ORPHAN_ACTION` | adopt | what to do with orphan positions |

## How the loop works

Every 15-minute bar close:
1. Refresh BTC regime (bull/bear/neutral) from BTC daily EMA50/EMA200.
2. Fetch current positions + equity.
3. **Manage** open positions: move SL to breakeven at 0.5R, trail at 1.2R
   (cancels old SL order, places new one), force-close at max hold.
4. **Scan entries** (if not daily-halted): rank top-volume symbols by signal
   score, open positions in free slots.
5. Sleep to next bar.

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
