# Deployment Status — VPS Trading Bots

Last updated: 2026-06-28

Only one bot is actively managed. Legacy v5/v6 bots (v7_1m, v7_1m_be02) have
been **retired** (stopped + disabled) because they lost money on testnet
despite profitable backtests. Their strategy files were removed from the repo.
Any leftover positions on lv5/lv6 are still protected by exchange SL/TP orders
but are no longer actively managed.

| Channel | Account | Strategy | Service File | Status | Notes |
|---|---|---|---|---|---|
| @trading_v4 | lv4 | **opus** | `trading-bot-opus-v4.service` | active | MTF scalp, loop 60s, entry/3min, UNIVERSE 30 |
| @trading_v5 | lv5 | (retired) | `trading-bot-v7-1m-v5.service` | disabled | leftover positions only |
| @trading_v6 | lv6 | (retired) | `trading-bot-v7-1m-be02-v6.service` | disabled | leftover positions only |

## Opus strategy params (strategy_opus.py)
| Param | Value |
|---|---|
| POSITION_PCT | 6.0 (scaled by confluence score) |
| MAX_LEVERAGE | 12x |
| MAX_CONCURRENT | 10 |
| DAILY_LOSS_LIMIT | 8% |
| RR | 1.8 |
| SL_MAX_PCT / SL_ATR_MULT | 1.3 / 1.4 |
| BE_R / BE_LOCK_PCT | 0.5 / 0.25 |
| TRAIL_START_R / TRAIL_ATR_MULT | 0.7 / 1.2 |
| LOOP_SECONDS / ENTRY_EVERY_LOOPS | 60 / 3 |
| UNIVERSE | 30 curated liquid majors |

## Opus test results (intrabar, realistic — see test_opus_replay.py / test_opus_regimes.py)
| Window | Return | WR | PF | MaxDD | Liq |
|---|---|---|---|---|---|
| 5d / 20 symbols | +16.4% | 59% | 1.18 | 14.0% | 0 |
| 7d / 20 symbols | +116.8% | 58.7% | 1.90 | 13.9% | 0 |
| 14d / 20 symbols | +601% | 57% | 2.08 | 15.9% | 0 |
| 21d / 20 symbols | +11877% | 52.4% | 3.23 | 24.7% | 0 |

## Quick commands
```bash
ssh root@74.113.235.40
systemctl status trading-bot-opus-v4
systemctl restart trading-bot-opus-v4
tail -f /opt/trading/production/live/bot_testnet_opus.log
```

## Emergency close all positions
```bash
cd /opt/trading/production
python close_all_positions.py    # all accounts (lv4/lv5/lv6)
python close_lv4.py              # lv4 only
```
