# HANDOFF — Repo cleanup & opus-only (2026-06-28)

> Ghi chú bàn giao cho agent tiếp theo (Devin). Đọc file này trước khi làm gì.
> File liên quan cũng nên đọc: `production/OPUS_TRADING.md` (design opus),
> `DEPLOYMENT_STATUS.md` (trạng thái deploy), `AGENTS.md` (rules + lệnh).

## TL;DR — Trạng thái hiện tại
- **Chỉ còn 1 strategy: `opus`** (`production/strategy_opus.py`). Toàn bộ v6/v7/v8 đã **xóa** (chạy testnet toàn thua dù backtest lãi).
- **1 bot đang chạy**: `trading-bot-opus-v4` trên account **lv4 testnet**, active + healthy, equity ~4982, đang giữ 1 vị thế SOLUSDT, regime=bear, 9 slot trống.
- **v5/v6 đã retired** (stop + disable). User tự đóng vị thế leftover + reset tiền lv5/lv6 (KHÔNG cần lo, đừng động vào).
- Repo đã dọn, commit, push, pull VPS, restart opus-v4, verify sạch.

## Đã làm trong session này (cleanup)

### 1. Retire v5/v6 trên VPS
- `trading-bot-v7-1m-v5.service` + `trading-bot-v7-1m-be02-v6.service`: `systemctl stop` + `disable` (inactive, khỏi autostart).
- Lúc retire, lv5 còn 3 vị thế SHORT lãi ~+747 USDT (ETH/BCH/DOGE), lv6 còn 2 vị thế SHORT lãi ~+661 USDT (ETH/DOGE), đều có SL/TP trên sàn. **User bảo tự đóng tay + reset tiền → không can thiệp.**

### 2. Xóa 27 file rác (local + VPS)
- **Strategy cũ**: `strategy_v6_1m.py`, `strategy_v6_1m_plus.py`, `strategy_v6_3m.py`, `strategy_v7_1m.py`, `strategy_v7_1m_be02.py`, `strategy_v8_1m.py`
- **Runners/backtest**: `continuous_2024_lv{2,3,4,5,6,v15}.py`, `auto_tune_v6_1m_plus.py`, `auto_tune_v6_3m.py`, `auto_tune_v7_1m.py`, `backtest_reversal_scalp.py`, `multi_month_test.py`
- **Test cũ**: `test_v6_1m.py`, `test_v6_1m_plus.py`, `test_lv6_daily_limit_mock.py`, `test_opus_replay_fixed.py` (bản trùng opus test)
- **Debug**: `_tmp_debug_2025_04.py`, `_tmp_debug_may_jun.py`

### 3. Chuyển opus-only
- `production/live/config.py`: validation chỉ còn `opus`; `STRATEGY_MODULE={"opus":"strategy_opus"}`; `get_api_keys()` → account LV4 (override bằng `BOT_ACCOUNT`). Giá trị default `BOT_STRATEGY` đổi từ `v7_1m` → `opus`. Bất kỳ strategy cũ nào đều raise `ValueError`.
- `production/live/telegram.py`: `_CHAT_IDS` chỉ còn `opus` (TELEGRAM_CHAT_LV4 → @trading_v4) + cơ chế override bằng `BOT_ACCOUNT`. (File này có thay đổi từ session trước chưa commit, giờ gộp vào commit cleanup.)
- `production/live/bot.py` + `strategy_adapter.py`: chỉ sửa comment/docstring sang opus (logic không đổi).
- **5 live test + cleanup.py + test_algo.py**: đổi default `BOT_STRATEGY` từ `v6_3m`/`lv4` → `opus` (v6_3m/lv4 đã xóa, không đổi thì test fail khi import config).
- `production/live/test_sl_move.py`: `FakeClient.klines` cũ trả bar toàn 0 → opus `compute_trail_sl` ra `new_sl=0` → bot skip. Đã craft 40 bar 1m tại ~99.4 (SHORT entry 100, +0.6R) để trigger BE move tới 99.75 (trên mark 98.5, dưới SL cũ 101). Test lại 6/6 PASS.
- `check_bots_status.py` (root): service list → chỉ `trading-bot-opus-v4`; label lv5/lv6 = "retired, leftover".
- `DEPLOYMENT_STATUS.md` (root): opus-v4 là bot duy nhất active, v5/v6 retired, bảng params opus, kết quả replay.
- `production/live/README_LIVE.md`: mô tả opus (loop 60s, MTF, params), thay flow 15m cũ.
- `AGENTS.md`: "3 bots" → "1 bot active opus-v4"; lệnh restart; `BOT_STRATEGY=opus`; realized_pnl 5/5.
- `.gitignore`: thêm `production/_cache_opus/` + `production/_cache_months/` (giữ local, không lên git).

### 4. Verify local
- `import live.bot` / `live.config` / `strategy_opus` OK.
- Config VPS: `LEVEL=opus MODULE=strategy_opus LOOP=60 ENTRY=3`.
- Mock test pass: `test_recovery` 17/17, `test_decision_bars` 6/6, `test_sl_move` 6/6, `test_realized_pnl` 5/5.
- `py_compile test_opus_replay.py test_opus_regimes.py strategy_opus.py` OK.
- Grep: không còn tham chiếu strategy cũ trong file giữ lại.

### 5. Commit + push + deploy
- Commit `80ef3ef` — "Retire legacy v6/v7/v8 strategies; opus-only" (18 file xóa, -3949 dòng).
- Commit `33f9a84` — "Apply opus-only config/docs/tests after legacy strategy removal" (18 file sửa/thêm, +307/-89).
- Đã `git push origin main` (HEAD = origin/main).
- VPS `git pull` fast-forward `462d9ee..33f9a84`, 36 file, toàn file cũ mất khỏi VPS, `git ls-files` sạch.
- `systemctl restart trading-bot-opus-v4` → **active**, log: `STRATEGY=opus`, reconcile OK, Telegram @trading_v4, loop 60s chạy đều.
- v5/v6: `enabled=disabled active=inactive`.

## Opus strategy — tham số hiện tại (strategy_opus.py)
| Param | Giá trị |
|---|---|
| `POSITION_PCT` | 6.0 (scale theo confluence score) |
| `POS_SCORE_HIGH/MID/LOW` | 9.0 / 6.5 / 4.5 |
| `MAX_CONCURRENT` | 10 |
| `MAX_LEVERAGE` | 12 |
| `DAILY_LOSS_LIMIT` | 8.0 |
| `MIN_SCORE` | 6 |
| `SL_MIN_PCT` / `SL_MAX_PCT` | 0.40 / 1.3 |
| `SL_ATR_MULT` | 1.4 |
| `RR` | 1.8 |
| `BE_R` / `BE_LOCK_PCT` | 0.5 / 0.25 |
| `TRAIL_START_R` / `TRAIL_ATR_MULT` | 0.7 / 1.2 |
| `LOOP_SECONDS` | 60 |
| `ENTRY_EVERY_LOOPS` | 3 (entry scan mỗi 3 phút) |
| `UNIVERSE` | 30 coin liquid major (BTC/ETH/BNB/SOL/.../RUNE) |

**Design pillars** (chi tiết trong `production/OPUS_TRADING.md`):
- MTF: 15m trend + 5m momentum + 1h context + 1m trigger.
- BTC short-term context (1m/5m/15m + bounce/exhaustion guard) — fetch 1 lần/scan.
- Quản lý trên 1m CLOSE (60s loop): BE@0.5R lock 0.25%, ATR-trail@0.7R×1.2ATR.
- Replay sát thực tế: **wick fills** (không close-based), slippage 0.06%, fee taker, funding.
- `UNIVERSE` cố định 30 coin → tránh coin illiquid trên testnet làm hỏng SL fill.
- `fetch_klines_range` có retry + `ban_until` chống IP ban Binance (-1003).

## Cấu trúc repo sau cleanup
```
production/
├── strategy_opus.py            # strategy duy nhất
├── test_opus_replay.py         # replay sát thực tế (intrabar wick fills)
├── test_opus_regimes.py        # chạy replay qua nhiều regime (max_workers=2)
├── close_all_positions.py      # utility đóng hết position (lv4/5/6)
├── close_lv4.py                # utility đóng lv4
├── OPUS_TRADING.md             # doc design opus
├── _cache_opus/                # 32 file replay_*.pkl (gitignored, giữ local)
├── _cache_months/              # 65 m_*.pkl + 23 results_*.json (gitignored, DATA CŨ cho v6/v7 — orphan)
└── live/
    ├── bot.py                  # execution + safety layer, loop 60s
    ├── config.py               # opus-only
    ├── strategy_adapter.py     # delegate sang strat.analyze_live + get_btc_context
    ├── binance_client.py
    ├── exchange_filters.py
    ├── state_db.py
    ├── telegram.py             # opus channel + BOT_ACCOUNT override
    ├── cleanup.py
    ├── test_*.py               # mock + real-API tests (mặc định BOT_STRATEGY=opus)
    └── __init__.py
check_bots_status.py            # status + PnL qua VPS API
DEPLOYMENT_STATUS.md            # trạng thái deploy
AGENTS.md                       # rules + lệnh
```

## Lệnh thường dùng
```powershell
# Mock test (local, không cần key)
cd D:\Tam\trading\production
$env:BOT_MODE="dry"; $env:BOT_STRATEGY="opus"
python -m live.test_recovery          # 17/17
python -m live.test_decision_bars     # 6/6
python -m live.test_sl_move           # 6/6
python -m live.test_realized_pnl      # 5/5

# Replay opus (cần data; dùng cache _cache_opus, fetch nếu thiếu)
python test_opus_replay.py [START_DAYS_AGO] [WINDOW_DAYS]
python test_opus_regimes.py           # sweep nhiều regime (max 2 worker)

# Status bot + PnL
python check_bots_status.py
```
```bash
# VPS
ssh root@74.113.235.40
systemctl status trading-bot-opus-v4
systemctl restart trading-bot-opus-v4
cd /opt/trading && git pull origin main && systemctl restart trading-bot-opus-v4
tail -f /opt/trading/production/live/bot_testnet_opus.log
```

## Lưu ý quan trọng / gotchas
1. **`config.py` chỉ chấp nhận `opus`**. Đặt `BOT_STRATEGY=v6_3m`/`v7_1m`/... sẽ raise. Nếu cần chạy strategy khác → phải viết lại + thêm vào validation/module map.
2. **Vị thế lv5/lv6**: user tự đóng + reset. Bot v5/v6 đã tắt, SL/TP trên sàn vẫn còn. **Đừng khởi động lại v5/v6** (file strategy đã xóa, sẽ crash).
3. **Cache**: `_cache_opus/` (32 pkl) là data replay opus — giữ dùng lại. `_cache_months/` (65 pkl + 23 json) là **data cũ cho v6/v7 đã orphan** (multi_month_test đã xóa); giữ tạm để tránh fetch lại, nhưng không còn script nào đọc nó cả.
4. **Opus manage trên 1m (60s loop)**, entry scan mỗi 3 loop (3 phút) — khác hẳn flow 15m cũ. Bot._update_stops có nhánh `compute_trail_sl` (opus) + nhánh legacy (chỉ chạy nếu strategy không có `compute_trail_sl`).
5. **Testnet liquidity**: opus dùng `UNIVERSE` 30 coin cố định (bot.scan_entries ưu tiên `sa.strat.UNIVERSE`) để tránh SL fill tệ trên coin exotic testnet — đây là fix quan trọng sau lần deploy opus đầu tiên thua.
6. **IP ban Binance**: đừng chạy nhiều instance `test_opus_replay`/`test_opus_regimes` song song (>2 worker) → -1003. `fetch_klines_range` đã có retry + ban_until.
7. **Trial VPS hết hạn ~2026-07-24** (30 ngày từ 2026-06-24).
8. **Telegram**: `verify=False` trên testnet, `verify=True` trên live.

## Open / việc còn lại
- User đang tự đóng vị thế lv5/lv6 + reset tiền → khi xong, 2 account đó trống.
- opus-v4 chạy testnet lv4, ~4982 equity (lúc 13:37 ICT), 1 vị thế SOLUSDT. Theo dõi WR/PF sau vài ngày.
- Chưa lên live (mainnet). Khi lên: `nano .env` → `BOT_MODE=live` + live keys → `systemctl restart trading-bot-opus-v4` → monitor sát ngày đầu.

## Git
- Remote: `origin` (github.com/ngominhtam1998/Trading), branch `main`.
- 2 commit session này: `80ef3ef`, `33f9a84` (đã push).
- Rule: **KHÔNG tự push** trừ khi user nói rõ. Commit local OK.
