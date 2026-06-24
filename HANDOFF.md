# HANDOFF — Trading Bot (2026-06-24 update 2)

> File này để AI/máy khác tiếp tục công việc. Đọc kỹ trước khi làm gì.

## Dự án là gì

Bot scalping crypto trên Binance Futures (USDT perpetuals). 6 chiến lược từ conservative → ultra high risk. Live bot đã verify trên testnet.

## Trạng thái HIỆN TẠI (2026-06-24 03:54 UTC)

**3 bot đang chạy 24/7 trên VPS Kamatera (KHÔNG còn chạy trên laptop):**

| Bot | Status | VPS | Channel | Positions |
|-----|--------|-----|---------|-----------|
| LV4 | active | Kamatera SG | @trading_v4 | 2 (AGTUSDT, VELVETUSDT) |
| LV5 | active | Kamatera SG | @trading_v5 | 2 (AGTUSDT, VELVETUSDT) |
| LV6 | active | Kamatera SG | @trading_v6 | 2 (AGTUSDT, VELVETUSDT) |

**VPS Kamatera:**
- IP: `74.113.235.40` (Singapore)
- OS: Ubuntu 26.04 LTS, Python 3.14.4
- RAM: 955MB + 1GB swap (3 bot tốn ~385MB)
- Trial 30 ngày ($100 credit), sau đó ~$4/tháng
- systemd: `trading-bot-lv4`, `trading-bot-lv5`, `trading-bot-lv6` (Restart=always)

**Laptop đã STOP 3 bot** (chuyển sang VPS, tránh chạy 2 nơi cùng lúc).

## Cấu trúc thư mục chính

```
D:\Tam\trading\
├── HANDOFF.md                          # ← FILE NÀY
├── PROJECT_HISTORY.md                  # Lịch sử đầy đủ 11 phases
├── README.md                           # Tổng quan + so sánh strategies
├── SETUP_VPS_FREE.md                   # Hướng dẫn setup Kamatera/Hetzner
├── SETUP_VPS_ORACLE.md                 # Hướng dẫn setup Oracle Cloud
├── setup_vps.py                        # Script SSH setup VPS (paramiko)
├── setup_vps_bots.py                   # Script upload .env + tạo systemd
├── start_vps_bots.py                   # Script start bots trên VPS
├── check_vps_bots.py                   # Script check status VPS
├── fix_vps.py                          # Script add swap VPS
├── fix_vps_logs.py                     # Script fix duplicate log + pull code
├── production/
│   ├── strategy_aggressive.py          # V15r2 (conservative, +39%/mo, 0 LIQ)
│   ├── strategy_aggressive_lv{2..6}.py # LV2-LV6 (risk tăng dần)
│   ├── strategy_aggressive_lv{2..6}_test.py  # 31 tháng backtest
│   ├── continuous_2024_*.py            # Continuous backtest Jan2024–Jun2026
│   └── live/                           # ← LIVE BOT (production)
│       ├── config.py                   # Mode/strategy/keys/params
│       ├── binance_client.py           # REST client + Algo Order API
│       ├── bot.py                      # Main loop + recovery + Telegram
│       ├── telegram.py                 # Async notifications (verify=False)
│       ├── strategy_adapter.py         # Live klines → strategy + funding filter
│       ├── exchange_filters.py         # Precision/min-notional
│       ├── state_db.py                 # SQLite state persistence
│       ├── cleanup.py                  # Close all + cancel all (one-shot)
│       ├── test_data_verify.py         # 40/40 PASS (verify API data)
│       ├── test_sl_fix.py              # 8/9 PASS (atomic SL swap)
│       ├── test_funding.py             # 10/10 PASS (funding rate filter)
│       ├── test_one_cycle.py           # End-to-end 1 cycle
│       ├── test_recovery.py            # 17/17 PASS
│       ├── test_algo.py                # Algo Order API PASS
│       ├── .env                        # API keys + Telegram (GITIGNORED)
│       └── .env.example                # Template
```

## Quản lý VPS (SSH)

```bash
# SSH vào VPS
ssh root@74.113.235.40
# Password: trong password manager (KHÔNG lưu trong file này)

# Status 3 bot
systemctl status trading-bot-lv4 trading-bot-lv5 trading-bot-lv6

# Restart
systemctl restart trading-bot-lv4 trading-bot-lv5 trading-bot-lv6

# Log realtime
tail -f /opt/trading/production/live/bot_testnet_lv4.log

# Update code từ git
cd /opt/trading && git pull origin main
systemctl restart trading-bot-lv4 trading-bot-lv5 trading-bot-lv6

# RAM
free -h
ps aux | grep live.bot
```

## Cách chạy 3 bot trên laptop (nếu cần fallback)

```powershell
cd D:\Tam\trading\production
$env:BOT_MODE="testnet"; $env:BOT_STRATEGY="lv4"; $env:PYTHONIOENCODING="utf-8"; python -u -m live.bot
# (mở 2 shell nữa cho lv5, lv6)
```

## Cách cleanup (close all + cancel all)

```bash
# Trên VPS
ssh root@74.113.235.40
cd /opt/trading/production
BOT_MODE=testnet BOT_STRATEGY=lv4 /opt/trading/venv/bin/python -m live.cleanup
BOT_MODE=testnet BOT_STRATEGY=lv5 /opt/trading/venv/bin/python -m live.cleanup
BOT_MODE=testnet BOT_STRATEGY=lv6 /opt/trading/venv/bin/python -m live.cleanup
```

## Những việc ĐÃ XONG (15/15)

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
11. ✅ Fix SL atomic swap (place new SL BEFORE cancel old, validate price side)
12. ✅ Fix Telegram SSL (verify=False + log warning, entry noti gửi OK)
13. ✅ Funding rate filter (skip SHORT+funding âm, LONG+funding dương >= 0.1%)
14. ✅ Data verification 40/40 PASS (API data khớp script 100%)
15. ✅ Deploy 3 bot lên VPS Kamatera 24/7 (systemd, auto-restart)

## Những việc CÒN LẠI (next steps)

1. **Monitor testnet trên VPS 3-7 ngày** — xem SL/TP có hit không, PnL ra sao
2. **Check Telegram 3 channel** — @trading_v4, @trading_v5, @trading_v6
3. **Reminder 25 ngày sau:** quyết định tiếp tục Kamatera ($4/tháng) hay migrate Hetzner
4. **Khi đã ổn:** switch sang live
   - Fill `BINANCE_LIVE_KEY_LV4` / `_LV5` / `_LV6` + secrets trong `.env` trên VPS
   - Đổi `BOT_MODE=live` trong `.env` trên VPS
   - `systemctl restart trading-bot-lv4 trading-bot-lv5 trading-bot-lv6`
   - **BẮT BUỘC:** nạp tiền thật vào 3 account Binance, bắt đầu nhỏ ($100-500/account)
5. **Monitor live sát:** ngày đầu check mỗi vài giờ, có lỗi → cleanup + dừng
6. **Backup state:** setup cron đẩy state DB lên GitHub mỗi 6 tiếng (chưa làm)

## Lưu ý QUAN TRỌNG

### Binance Algo Order API (breaking change)
- Từ Dec 9, 2025: STOP_MARKET / TAKE_PROFIT_MARKET **phải** dùng `/fapi/v1/algoOrder`
- Endpoint cũ `/fapi/v1/order` trả error `-4120`
- `binance_client.py` đã migrate: `new_stop_market()`, `new_take_profit_market()`, `open_algo_orders()`, `cancel_algo_order()`
- Algo orders có `algoId` (không phải `orderId`), cancel bằng `algoId`
- `open_algo_orders` trả thêm `triggerPrice`, `side`, `workingType`, `closePosition`

### SL atomic swap (fix quan trọng)
- **OLD (bug):** cancel old SL → place new SL. Nếu new SL fail → position không protection!
- **NEW (fix):** place new SL → nếu OK → cancel old SL. Nếu new fail → old SL vẫn còn.
- Price validation: check `new_sl > cur_mp` (SHORT) hoặc `new_sl < cur_mp` (LONG) trước khi move
- Nếu invalid → skip, giữ SL cũ

### Telegram fix
- `_session.verify = False` (match binance_client) — SSL error trước đây bị silent
- Log error ở warning level (trước đây debug level, không hiện)
- Log success: `"Telegram delivered to @trading_v4 (307 chars)"`

### Funding rate filter
- `funding_rate()` method trong binance_client (từ `premiumIndex.lastFundingRate`)
- SHORT + funding <= -0.1% → skip (shorts pay longs)
- LONG + funding >= +0.1% → skip (longs pay shorts)
- Threshold: 0.001 (API format)

### Margin auto-scale
- `POSITION_PCT × MAX_CONCURRENT` = 270%-550% equity → KHÔNG thể mở đủ slots
- Bot check `avail >= margin_per_pos` trước mỗi entry, dừng khi hết margin
- **$100 cũng chạy được** — chỉ mở ít lệnh hơn (1-2 thay vì 6)

### Error codes đã xử lý (PERMANENT_CODES)
- `-4046` margin type already set → permanent
- `-4045` leverage not changed → permanent
- `-4120` must use Algo Order API → permanent
- `-2019` margin insufficient → permanent
- `-4005` qty greater than max → permanent
- `-4130` open stop/TP already exists → permanent
- `-4028` leverage not valid for symbol → permanent (skip nhanh)
- `-2027` exceeded max position at leverage → permanent
- `-1021` timestamp error → resync + retry
- 429/418 rate limit → sleep Retry-After

### Backtest reality check
- Continuous compounding (Jan2024–Jun2026) cho kết quả "dream-like" (LV6 +7000%/năm)
- 31 monthly backtest riêng cho thấy thực tế: worst month -61%, 23-35 LIQ
- **Monthly backtest là con số thực tế hơn** — continuous che giấu rủi ro

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

### VPS Kamatera
- IP: 74.113.235.40 (Singapore)
- Trial 30 ngày từ 2026-06-24 → hết hạn ~2026-07-24
- Sau trial: ~$4/tháng (Type A, 1 vCPU, 1GB RAM, 20GB NVMe)
- Root password: lưu trong password manager (KHÔNG commit vào repo)
- Repo clone tại `/opt/trading`
- venv tại `/opt/trading/venv`
- Log tại `/opt/trading/production/live/bot_testnet_lv{4,5,6}.log`

## Tech stack
- Python 3.14 (VPS) / 3.12 (laptop)
- `requests` (REST API, không dùng websocket)
- `pandas` (indicators)
- SQLite (state persistence, `state_{mode}_{strategy}.db`)
- Telegram Bot API (HTTP, không cần library)
- paramiko (SSH scripts quản lý VPS từ laptop)

## Git
- Remote: `origin` (GitHub: ngominhtam1998/Trading)
- Branch: `main`
- `.env` + `state_*.db` + `bot_*.log` đã trong `.gitignore`
