# HANDOFF — Trading Bot (2026-06-24)

> File này để AI/máy khác tiếp tục công việc. Đọc kỹ trước khi làm gì.

## Dự án là gì

Bot scalping crypto trên Binance Futures (USDT perpetuals). 6 chiến lược từ conservative → ultra high risk. Live bot đã verify trên testnet.

## Trạng thái HIỆN TẠI (2026-06-24 07:23)

**3 bot đang chạy trên testnet (PowerShell background):**
- LV4: equity $4573, 6 positions SHORT, channel @trading_v4
- LV5: equity $4644, 5 positions SHORT, channel @trading_v5
- LV6: equity $4609, 4 positions SHORT, channel @trading_v6

Bot chạy overnight ~8.6 giờ, ổn định. Không vào lệnh mới vì hết margin (đúng logic — margin đã dùng cho positions đang mở).

## Cấu trúc thư mục chính

```
D:\Tam\trading\
├── HANDOFF.md                          # ← FILE NÀY
├── PROJECT_HISTORY.md                  # Lịch sử đầy đủ 11 phases (đọc để hiểu context)
├── README.md                           # Tổng quan + so sánh strategies
├── production/
│   ├── strategy_aggressive.py          # V15r2 (conservative, +39%/mo, 0 LIQ)
│   ├── strategy_aggressive_lv{2..6}.py # LV2-LV6 (risk tăng dần)
│   ├── strategy_aggressive_lv{2..6}_test.py  # 31 tháng backtest
│   ├── continuous_2024_*.py            # Continuous backtest Jan2024–Jun2026
│   └── live/                           # ← LIVE BOT (production)
│       ├── config.py                   # Mode/strategy/keys/params
│       ├── binance_client.py           # REST client + Algo Order API
│       ├── bot.py                      # Main loop + recovery + Telegram
│       ├── telegram.py                 # Async notifications
│       ├── strategy_adapter.py         # Live klines → strategy module
│       ├── exchange_filters.py         # Precision/min-notional
│       ├── state_db.py                 # SQLite state persistence
│       ├── cleanup.py                  # Close all + cancel all (one-shot)
│       ├── test_recovery.py            # 17/17 PASS
│       ├── test_algo.py                # Algo Order API PASS
│       ├── test_noti.py                # Telegram test
│       ├── .env                        # API keys + Telegram (GITIGNORED)
│       └── .env.example                # Template
```

## Cách chạy 3 bot trên testnet

```powershell
# Mỗi bot 1 shell riêng (PowerShell)
cd D:\Tam\trading\production
$env:BOT_MODE="testnet"; $env:BOT_STRATEGY="lv4"; python -m live.bot
$env:BOT_MODE="testnet"; $env:BOT_STRATEGY="lv5"; python -m live.bot
$env:BOT_MODE="testnet"; $env:BOT_STRATEGY="lv6"; python -m live.bot
```

`.env` đã có sẵn API keys + Telegram token. Không cần set thêm gì.

## Cách cleanup (close all + cancel all)

```powershell
cd D:\Tam\trading\production
$env:BOT_MODE="testnet"; $env:BOT_STRATEGY="lv4"; python -m live.cleanup
$env:BOT_STRATEGY="lv5"; python -m live.cleanup
$env:BOT_STRATEGY="lv6"; python -m live.cleanup
```

## Những việc ĐÃ XONG (10/10)

1. ✅ Recovery test 17/17 PASS (6 scenario: crash, orphan, stale, rác, disconnect)
2. ✅ 3 testnet API key riêng trong `.env` (mỗi strategy 1 account)
3. ✅ Verify 3 account kết nối ($5000 mỗi acc)
4. ✅ Telegram async (queue + worker, không block trading loop)
5. ✅ Noti chi tiết: entry/exit/SL-move/halt/startup/shutdown/error
6. ✅ Algo Order API migration (Binance breaking change Dec 9, 2025)
7. ✅ Test Algo Order PASS (SL/TP đặt + hiển thị + cleanup)
8. ✅ Fix `-4046` retry (margin type already set → permanent, không retry)
9. ✅ Fix margin auto-scale (bot check avail >= margin/pos, $100 cũng chạy được)
10. ✅ 3 bot chạy song song testnet verified (overnight 8.6 giờ ổn định)

## Những việc CÒN LẠI (next steps)

1. **Monitor testnet thêm 3-7 ngày** — xem SL/TP có hit không, PnL ra sao, có lỗi gì không
2. **Check Telegram 3 channel** — xem user có nhận noti entry/exit không
3. **Khi đã ổn:** switch sang live
   - Fill `BINANCE_LIVE_KEY_LV4` / `_LV5` / `_LV6` + `BINANCE_LIVE_SECRET_*` trong `.env`
   - Đổi `BOT_MODE=live` trong `.env`
   - **BẮT BUỘC:** nạp tiền thật vào 3 account Binance, bắt đầu với số nhỏ ($100-500/account)
4. **VPS 24/7:** Bot cần chạy liên tục. Binance chỉ giữ SL/TP (tự đóng khi chạm giá), bot phải chạy để vào lệnh mới + trailing + BE. Nếu sập → SL/TP vẫn bảo vệ, khi lên lại bot tự reconcile.
5. **Monitor live sát:** ngày đầu check mỗi vài giờ, có lỗi gì → cleanup + dừng

## Lưu ý QUAN TRỌNG

### Binance Algo Order API (breaking change)
- Từ Dec 9, 2025: STOP_MARKET / TAKE_PROFIT_MARKET **phải** dùng `/fapi/v1/algoOrder`
- Endpoint cũ `/fapi/v1/order` trả error `-4120`
- `binance_client.py` đã migrate: `new_stop_market()`, `new_take_profit_market()`, `open_algo_orders()`, `cancel_algo_order()`
- Algo orders có `algoId` (không phải `orderId`), cancel bằng `algoId`

### Margin auto-scale
- `POSITION_PCT × MAX_CONCURRENT` = 270%-550% equity → KHÔNG thể mở đủ slots
- Bot check `avail >= margin_per_pos` trước mỗi entry, dừng khi hết margin
- **$100 cũng chạy được** — chỉ mở ít lệnh hơn (1-2 thay vì 6)
- Giống backtest logic `if cash < margin: continue`

### Backtest reality check
- Continuous compounding (Jan2024–Jun2026) cho kết quả "dream-like" (LV6 +7000%/năm)
- 31 monthly backtest riêng cho thấy thực tế: worst month -61%, 23-35 LIQ
- **Monthly backtest là con số thực tế hơn** — continuous che giấu rủi ro

### Telegram
- 1 bot token, 3 channel (`@trading_v4`, `@trading_v5`, `@trading_v6`)
- Async: queue + worker thread, fire-and-forget, KHÔNG block trading loop
- Queue full → drop oldest, never block
- Chat ID trong `.env`: `TELEGRAM_CHAT_LV4=@trading_v4` etc

### Error codes đã xử lý
- `-4046` margin type already set → permanent (không retry)
- `-4045` leverage not changed → permanent (không retry)
- `-4120` must use Algo Order API → permanent (đã migrate)
- `-2019` margin insufficient → permanent (bot check trước, không nên xảy ra)
- `-4005` qty greater than max → permanent (skip symbol)
- `-1021` timestamp error → resync + retry
- 429/418 rate limit → sleep Retry-After

### File `.env` (KHÔNG commit, đã trong .gitignore)
```
BOT_MODE=testnet
BOT_STRATEGY=v15  # override bằng env var khi chạy
BINANCE_TESTNET_KEY_LV4=...
BINANCE_TESTNET_SECRET_LV4=...
BINANCE_TESTNET_KEY_LV5=...
BINANCE_TESTNET_SECRET_LV5=...
BINANCE_TESTNET_KEY_LV6=...
BINANCE_TESTNET_SECRET_LV6=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_LV4=@trading_v4
TELEGRAM_CHAT_LV5=@trading_v5
TELEGRAM_CHAT_LV6=@trading_v6
```

## Tech stack
- Python 3.11+
- `requests` (REST API, không dùng websocket)
- SQLite (state persistence, `state_{mode}_{strategy}.db`)
- Telegram Bot API (HTTP, không cần library)
- Không có dependency nào khác → không cần requirements.txt phức tạp

## Git
- Remote: `origin` (GitHub)
- Branch: `main`
- `.env` + `state_*.db` + `bot_*.log` đã trong `.gitignore`
