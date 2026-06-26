# Trading — Crypto Scalping Bot (Binance Futures)

## Tổng quan dự án

Dự án phát triển bot scalping crypto trên Binance Futures (USDT perpetuals), từ backtest research đến live trading bot. Toàn bộ quá trình kéo dài qua nhiều phiên làm việc, evolve qua 15+ version chiến lược.

**Chiến lược production hiện tại:** `strategy_aggressive.py` (V15r2) — 100% tháng có lãi trong 31 tháng backtest, avg +38.9%/tháng, 0 liquidation.

---

## Lịch sử phát triển đầy đủ

### Phase 1: Backtest Framework (V2–V11)

**V2–V6 (không còn file):** Khung backtest cơ bản trên Bybit API, test SMA crossover, Bollinger + RSI. Kết quả kém, bỏ.

**V7–V9 (`universal_v7/v8/v9.py` — đã xóa):** Chuyển sang Binance API, thêm EMA9/21/50 crossover, ATR-based SL/TP, RSI filter. Bắt đầu có tín hiệu khả dụng nhưng PF < 1.2.

**V10 (`universal_v10.py` — đã xóa):** Thêm ADX filter (>=18), volume spike confirmation (1.5x avg), BTC daily regime (bull/bear/neutral). PF ~1.3, nhưng drawdown cao.

**V11 (`universal_v11.py` — đã xóa):** Thêm 1h higher-timeframe trend filter (EMA9 vs EMA21 trên 1h). Giảm false signal. PF ~1.35.

### Phase 2: V12 — Multi-coin scanning

**V12 (`v12_*.py` — đã xóa):**
- Scan toàn bộ USDT perpetuals (~500 coins) thay vì fix danh sách
- Chọn top-volume coins mỗi tháng
- Rolling test thay vì fix tháng
- Kết quả: PF 1.3–1.5, nhưng vẫn có tháng lỗ nặng (-15%)
- Vấn đề: position size cố định ($70/trade) → dưới-utilize vốn khi thắng, rủi ro cao khi thua

### Phase 3: V13 — Signal refinement

**V13 (`v13_*.py` — đã xóa):**
- Thêm EMA50 slope filter (>0.05%)
- Tighten RSI bands: LONG 40–65, SHORT 35–60
- Score-based entry (5–10 points)
- Kết quả: PF ~1.4, WR ~58%, nhưng vẫn 5 liquidation trong 31 tháng

### Phase 4: V14 — Risk management + compounding

**V14 Fixed (`v14_production.py` → `strategy_balanced.py`):**
- Position size cố định $70/trade
- 31 tháng backtest: 26/31 profitable (84%), avg +24.68%/tháng
- PF 1.33, nhưng 5 liquidation → nguy hiểm

**V14 Compound (`v14_compound.py` → merge vào `strategy_balanced.py`):**
- **Thay đổi quan trọng:** position size = 7% equity hiện tại (compounding)
- Thắng → position lớn dần (lãi kép), Thua → position nhỏ dần (de-risk)
- Min notional $5 + max vol 10% (partial fill handling)
- Error handling entry/exit
- Tracking peak/trough equity
- Kết quả 31 tháng: 26/31 (84%) profitable, avg +24.84%, PF 1.44, **0 liquidation**

**V14 6-month continuous test (3 windows):**
- H1-2025: +58.66% (CAGR 8%/mo)
- H2-2025: +113.78% (CAGR 13.5%/mo)
- H2-2022: -7.22% (bear market, CAGR -1.24%/mo)
- Kết luận: avg +24%/tháng là arithmetic mean, realistic CAGR 8–13% do geometric mean

### Phase 5: V15r1 — Tighter filters (thất bại)

**V15r1 (`v15_compound.py` bản đầu — đã sửa):**
- ADX >= 22 (was 20)
- Volume spike 1.8x (was 1.5x)
- RSI bands tightened: 42–62 / 38–58
- Body > 0.3% (hard filter)
- EMA200 hard filter (only trade with trend)
- RR 3.5 (was 3.0), SL 1.3x ATR (was 1.5)
- BE 0.5R (was 0.7R), Trail 1.2R (was 1.5R)
- MIN_SCORE 7, MAX_CONCURRENT 8, POSITION_PCT 6%

**Kết quả 31 tháng:**
- 26/31 profitable (84%) — giống V14
- Avg return: **+9.13%** — giảm mạnh từ +24.84%
- PF 1.76, MaxDD 4.2% — tốt hơn nhưng return quá thấp
- Filter quá chặt → loại cả trade tốt lẫn trade xấu

**Kết luận:** V15r1 quá bảo thủ. User yêu cầu đánh đổi risk hơn để reward cao hơn.

### Phase 6: V15r2 — PRODUCTION (strategy_aggressive.py)

**V15r2 (rename → `strategy_aggressive.py`):**
Giữ nguyên V14 base params, chỉ thay đổi 3 thứ:
1. **RR = 3.5** (was 3.0) — TP xa hơn, winner lớn hơn
2. **SL = 1.3x ATR** (was 1.5) — SL chặt hơn, ít mất hơn khi sai
3. **BE 0.5R + Trail 1.2R** (was 0.7R + 1.5R) — bảo vệ vốn sớm hơn

EMA200 + body filter giữ nhưng là **SOFT bonus** (cộng điểm score) thay vì hard reject.

Params giữ nguyên V14: ADX>=20, RSI 40-65/35-60, score>=6, conc=10, pos=7%, vol 1.5x.

**Kết quả 31 tháng — BACKTEST:**

| Metric | V14 Balanced | V15r2 Aggressive |
|---|---|---|
| Tháng có lãi | 26/31 (84%) | **31/31 (100%)** |
| Avg return | +24.84% | **+38.90%** |
| Median return | +20.80% | **+32.46%** |
| Avg PF | 1.44 | **1.89** |
| Avg MaxDD | 10.3% | **6.8%** |
| Total LIQ | 0 | **0** |
| Worst month | -11.45% | **+2.44%** |
| Best month | +85.57% | **+97.43%** |

**6-month continuous test (3 windows):**

| Window | Return | End Cap | CAGR/mo | MaxDD | LIQ |
|---|---|---|---|---|---|
| H1-2025 | +76.56% | $1,766 | +9.94% | 22.6% | 0 |
| H2-2025 | +275.35% | $3,754 | +24.66% | 9.1% | 0 |
| H2-2022 | +464.36% | $5,644 | +33.43% | 8.5% | 0 |

3/3 windows có lãi, avg CAGR +22.68%/tháng, 0 liquidation.

### Phase 7: Live Trading Bot

**File:** `production/live/` directory

Build live bot trên Binance USDT-M Futures API, tái sử dụng nguyên `decide_v15` từ `strategy_aggressive.py` (KHÔNG thay đổi logic trade).

**Kiến trúc safety 2 lớp:**

1. **SL/TP là lệnh thật trên sàn** (`STOP_MARKET` + `TAKE_PROFIT_MARKET`, `closePosition=true`): Bot chết → sàn vẫn tự đóng vị thế.

2. **SQLite state + reconciliation khi restart:**
   - Vị thế + SL/TP intact → tiếp tục quản lý
   - Vị thế mất SL/TP → đặt lại từ giá lưu trong DB
   - Vị thế mồ côi (không có trong DB) → nhận nuôi + đặt SL khẩn cấp
   - Vị thế đã đóng lúc bot chết → ghi nhận, dọn DB
   - Lệnh rác không có vị thế → hủy

**Xử lý lỗi:**
- Mọi REST call: retry + exponential backoff (5 lần)
- Rate limit 429/418: sleep theo Retry-After header
- Timestamp error -1021: resync server time + retry
- Permanent errors (bad params, insufficient funds): raise, caller xử lý
- Entry khớp nhưng SL đặt fail → **đóng vị thế ngay** (không để hở)

**Test đã verify:**
- Pipeline dữ liệu: 528 symbols, BTC regime, signal ✓
- Recovery logic: 7/7 mock test PASS ✓
- Đặt lệnh thật trên testnet: **CHƯA TEST** (cần testnet API key)

**Modes:**
- `testnet` (default): Binance Futures Testnet, tiền ảo
- `dry`: real market data, không đặt lệnh thật
- `live`: tiền thật (chỉ sau khi testnet verified)

**VPS:** Bot cần VPS chạy 24/7. Binance chỉ giữ SL/TP (tự đóng khi chạm giá), bot phải chạy để: vào lệnh mới, dời SL breakeven/trailing, đóng lệnh max-hold. Nếu VPS sập → SL/TP vẫn bảo vệ, khi VPS lên lại bot tự reconcile.

### Phase 8: Aggressive LV2 — Higher risk, higher reward

**File:** `production/strategy_aggressive_lv2.py`

User yêu cầu version risk hơn, reward cao hơn nữa. Based on aggressive (V15r2) với các thay đổi:

1. **RR = 4.5** (was 3.5) — TP xa hơn nữa, winner lớn hơn nhiều
2. **SL = 1.1x ATR** (was 1.3) — SL chặt hơn, rủi ro mỗi trade nhỏ hơn nhưng hit rate thấp hơn
3. **BE at 0.7R** (was 0.5R) — để winner breathe trước khi bảo vệ
4. **Trail from 1.5R** (was 1.2R) — trail muộn hơn, ride trend lớn hơn
5. **POSITION_PCT = 9.0** (was 7.0) — position size lớn hơn, compounding mạnh hơn
6. **MAX_CONCURRENT = 12** (was 10) — nhiều vị thế đồng thời hơn
7. **MAX_LEVERAGE = 12** (was 10) — leverage cao hơn
8. **DAILY_LOSS_LIMIT = 7.0** (was 5.0) — chấp nhận daily DD lớn hơn
9. **LIQ_SAFETY_ROE = 50.0** (was 45.0) — SL gần liquidation hơn
10. **MIN_SCORE = 5** (was 6) — take lower-confidence trades
11. **DECISION_EVERY = 12 bars** (was 16) — scan entry mỗi 3h thay vì 4h
12. **Neutral regime: max 7 concurrent, 7x lev** (was 5/5)

**Kết quả 31 tháng backtest:**

| Metric | Balanced (V14) | Aggressive (V15r2) | Aggressive LV2 |
|---|---|---|---|
| Tháng có lãi | 26/31 (84%) | 31/31 (100%) | 29/31 (94%) |
| Avg return | +24.84% | +38.90% | **+73.99%** |
| Median return | +20.80% | +32.46% | **+54.84%** |
| Avg PF | 1.44 | 1.89 | 1.58 |
| Avg MaxDD | 10.3% | 6.8% | 14.4% |
| Total LIQ | 0 | 0 | 0 |
| Worst month | -11.45% | +2.44% | -6.43% |
| Best month | +85.57% | +97.43% | **+219.72%** |
| Avg trades/month | 254 | 266 | 345 |

**Phân tích:**
- Return gần gấp đôi aggressive (+74% vs +39%)
- Compounding cực mạnh: Dec 2023 $1000→$3,197 (3.2x), Aug 2024 $1000→$2,674 (2.7x)
- Trade-off: 2 tháng lỗ (Oct 2025 -2.26%, Nov 2024 -6.43%), MaxDD avg 14.4% (có tháng 28.3%)
- PF thấp hơn (1.58 vs 1.89) do SL chặt + RR cao → hit rate thấp hơn
- Trough equity hầu hết >$900, tối đa -17.3% (Nov 2024: $827)
- **0 liquidation** — position size tự giảm khi equity giảm
- LV2 thắng aggressive ở 20/31 tháng, thua 11

**Kết luận:** LV2 phù hợp user chấp nhận drawdown 20-30% để đổi return cao. Aggressive (V15r2) vẫn là production chính (100% tháng lãi, an toàn hơn). LV2 là option high-risk/high-reward.

### Phase 9: Aggressive LV3 — Even higher risk/reward than LV2

**File:** `production/strategy_aggressive_lv3.py`

User yêu cầu version risk hơn nữa, reward cao hơn nữa. Based on LV2 với các thay đổi:

1. **RR = 5.5** (was 4.5) — TP xa hơn nữa, winner lớn hơn nhiều
2. **SL = 0.9x ATR** (was 1.1) — SL chặt hơn nữa, rủi ro mỗi trade nhỏ hơn nhưng hit rate thấp hơn
3. **BE at 0.9R** (was 0.7R) — để winner breathe lâu hơn trước khi bảo vệ
4. **Trail from 2.0R** (was 1.5R) — trail muộn hơn, ride trend lớn hơn nữa
5. **POSITION_PCT = 12.0** (was 9.0) — position size lớn hơn nữa, compounding mạnh hơn
6. **MAX_CONCURRENT = 15** (was 12) — nhiều vị thế đồng thời hơn
7. **MAX_LEVERAGE = 15** (was 12) — leverage cao hơn
8. **DAILY_LOSS_LIMIT = 10.0** (was 7.0) — chấp nhận daily DD lớn hơn
9. **LIQ_SAFETY_ROE = 55.0** (was 50.0) — SL gần liquidation hơn
10. **MIN_SCORE = 4** (was 5) — take even lower-confidence trades
11. **DECISION_EVERY = 8 bars** (was 12) — scan entry mỗi 2h thay vì 3h
12. **Neutral regime: max 10 concurrent, 10x lev** (was 7/7)

**Kết quả 31 tháng backtest:**

| Metric | Balanced (V14) | Aggressive (V15r2) | Aggressive LV2 | **Aggressive LV3** |
|---|---|---|---|---|
| Tháng có lãi | 26/31 (84%) | 31/31 (100%) | 29/31 (94%) | **30/31 (97%)** |
| Avg return | +24.84% | +38.90% | +73.99% | **+181.63%** |
| Median return | +20.80% | +32.46% | +54.84% | **+148.19%** |
| Avg PF | 1.44 | 1.89 | 1.58 | 1.66 |
| Avg MaxDD | 10.3% | 6.8% | 14.4% | **19.3%** |
| Total LIQ | 0 | 0 | 0 | **9** |
| Worst month | -11.45% | +2.44% | -6.43% | **-4.57%** |
| Best month | +85.57% | +97.43% | +219.72% | **+557.50%** |
| Avg trades/month | 254 | 266 | 345 | 439 |

**Phân tích:**
- Return gần gấp 2.5x LV2 (+182% vs +74%), gần 5x Aggressive (+182% vs +39%)
- Compounding cực kỳ mạnh: Aug 2024 $1000→$6,575 (6.6x), Mar 2023 $1000→$5,391 (5.4x), Apr 2025 $1000→$4,938 (4.9x)
- **CRITICAL: 9 liquidations** (Dec 2023: 1, Jun 2023: 1, Jan 2026: 1, Nov 2025: 2, + 5 others) — LV2/LV1 có 0
- 1 tháng lỗ (Sep 2024 -4.57%), MaxDD avg 19.3% (có tháng 40.6% Feb 2025, 34.9% Nov 2024)
- PF 1.66 (hơi tốt hơn LV2 1.58 do RR 5.5 bù hit rate thấp)
- Trough equity có tháng xuống $705 (Feb 2025, -29.5%), $734 (Jul 2022, -26.6%)
- LV3 thắng aggressive ở 30/31 tháng, chỉ thua Sep 2024 (-4.57% vs +21.82%)

**Return distribution:**
- -10% to 0%: 1 tháng (Sep 2024)
- +10% to +30%: 2 tháng
- +50% to +100%: 4 tháng
- +100% to +200%: 13 tháng
- +200% to +500%: 10 tháng
- +500% to +1000%: 1 tháng (Aug 2024 +557.50%)

**Kết luận:** LV3 phù hợp user chấp nhận drawdown 30-40% và **chấp nhận rủi ro liquidation** để đổi return cực cao. **9 liquidations trong 31 tháng là red flag lớn** — đây là điểm khác biệt quan trọng nhất vs LV2 (0 LIQ). Aggressive (V15r2) vẫn là production chính (100% tháng lãi, 0 LIQ, an toàn nhất). LV2 là sweet spot high-risk/reward (0 LIQ, +74%). LV3 là extreme high-risk/reward (9 LIQ, +182%) — chỉ dùng nếu chấp nhận mất toàn bộ margin của 1 vài vị thế.

### Phase 10: Aggressive LV4 / LV5 / LV6 — Maximum risk tiers + LIVE DEPLOYMENT

**Files:**
- `production/strategy_aggressive_lv4.py` — LV4 (very high risk, 23 LIQ, +283%/mo)
- `production/strategy_aggressive_lv5.py` — LV5 (extreme risk, 34 LIQ, +645%/mo)
- `production/strategy_aggressive_lv6.py` — LV6 (maximum risk, 35 LIQ, +719%/mo)
- `production/strategy_aggressive_lv4_test.py`, `_lv5_test.py`, `_lv6_test.py` — 31 tháng backtest
- `production/continuous_2024_lv{2,3,4,5,6}.py`, `continuous_2024_v15.py` — continuous Jan2024–Jun2026 backtest

User yêu cầu thêm 3 tier risk cao hơn LV3. Mỗi tier tăng POSITION_PCT, MAX_CONCURRENT, MAX_LEVERAGE, RR, giảm SL ATR multiplier:

| Param | LV3 | LV4 | LV5 | LV6 |
|---|---|---|---|---|
| RR | 5.5 | 6.5 | 7.5 | 8.5 |
| SL (ATR) | 0.9 | 0.8 | 0.7 | 0.6 |
| BE at R | 0.9 | 1.1 | 1.3 | 1.5 |
| Trail from R | 2.0 | 2.5 | 3.0 | 3.5 |
| POSITION_PCT | 12 | 15 | 18 | 22 |
| MAX_CONCURRENT | 15 | 18 | 20 | 25 |
| MAX_LEVERAGE | 15 | 18 | 20 | 22 |
| DAILY_LOSS_LIMIT | 10 | 12 | 15 | 18 |

**Kết quả 31 tháng backtest (individual monthly, KHÔNG continuous compounding):**

| Metric | LV4 | LV5 | LV6 |
|---|---|---|---|
| Tháng có lãi | 27/31 (87%) | 25/31 (81%) | 24/31 (77%) |
| Avg return | +283% | +645% | +719% |
| Total LIQ | 23 | 34 | 35 |
| Worst month | -42.89% | -56.12% | -61.34% |
| Best month | +1200%+ | +2500%+ | +2800%+ |

**Lưu ý QUAN TRỌNG về backtest:** Continuous compounding (Jan2024–Jun2026 một mạch) cho kết quả "dream-like" (LV6 +7000%/năm), nhưng 31 monthly backtest riêng cho thấy thực tế khắc nghiệt hơn nhiều: worst month -61%, 23-35 liquidations. **Monthly backtest là con số thực tế hơn** — continuous compounding che giấu rủi ro bằng cách pha loãng qua thời gian dài.

### Phase 11: Live Bot Production Deployment (TESTNET VERIFIED)

**Mục tiêu:** Deploy 3 bot (LV4, LV5, LV6) song song trên Binance Futures Testnet, mỗi bot 1 account riêng, Telegram notify 3 channel riêng.

**Các việc đã làm + verify:**

1. **3 testnet account riêng** (mỗi account $5000 ảo, API key riêng trong `.env`):
   - `BINANCE_TESTNET_KEY_LV4` / `BINANCE_TESTNET_SECRET_LV4`
   - `BINANCE_TESTNET_KEY_LV5` / `BINANCE_TESTNET_SECRET_LV5`
   - `BINANCE_TESTNET_KEY_LV6` / `BINANCE_TESTNET_SECRET_LV6`
   - Account riêng tránh cross-bot conflict (bot A không adopt position của bot B)

2. **Binance Algo Order API migration** (breaking change Dec 9, 2025):
   - Binance bắt buộc dùng `/fapi/v1/algoOrder` cho STOP_MARKET / TAKE_PROFIT_MARKET
   - Endpoint cũ `/fapi/v1/order` trả error `-4120` cho conditional orders
   - `binance_client.py` đã migrate: `new_stop_market()`, `new_take_profit_market()`, `open_algo_orders()`, `cancel_algo_order()`
   - Test `test_algo.py` PASS: mở position → đặt SL+TP → verify hiển thị → cancel → close, cleanup sạch

3. **Telegram async notifications** (`telegram.py`):
   - Background queue + worker thread, fire-and-forget, KHÔNG block trading loop
   - 3 channel: `@trading_v4`, `@trading_v5`, `@trading_v6` (1 bot token, 3 chat_id)
   - Noti chi tiết: entry (coin/hướng/lev/giá/volume/margin/SL/TP/RR/score/thời gian), exit (PnL tiền+%/hold time/reason), SL move (BE/trail), daily halt, startup/shutdown, error
   - Queue full → drop oldest, never block
   - Verified: 3 channel đều nhận message (test trực tiếp API + bot gửi)

4. **Recovery test 17/17 PASS** (`test_recovery.py`):
   - 6 scenario: clean shutdown, bot crash (DB có position sống), orphan position (DB trống exchange có position), stale DB (position đã đóng), rác orders, disconnect/reconnect
   - Bot nhận đúng lệnh của mình (prefix `scbot_`), adopt orphan + đặt SL emergency, cleanup rác

5. **Margin auto-scale fix** (QUAN TRỌNG):
   - Bug: `POSITION_PCT × MAX_CONCURRENT` = 270%-550% equity →不可能 mở đủ slots
   - Fix: `scan_entries()` check `avail >= margin_per_pos` trước mỗi entry, dừng khi hết margin
   - Giống backtest logic `if cash < margin: continue`
   - **Bot tự scale theo equity — $100 cũng chạy được** (chỉ mở ít lệnh hơn)
   - Thêm `-4046` (margin type already set) + `-4045` (leverage not changed) vào `PERMANENT_CODES` → không retry, tiết kiệm 30s/cycle

6. **3 bot chạy song song trên testnet (VERIFIED ~8.6 giờ overnight):**

| Bot | Equity | Avail | Positions | Channel |
|-----|--------|-------|-----------|---------|
| LV4 | $4501→$4573 | $447 | 6 SHORT | @trading_v4 |
| LV5 | $4563→$4644 | $454 | 5 SHORT | @trading_v5 |
| LV6 | $4553→$4609 | $544 | 4 SHORT | @trading_v6 |

   - Bot không vào lệnh mới khi hết margin → **đúng logic**
   - Network error retry OK (Connection aborted → retry → success)
   - SL/TP algo orders đặt đúng, hiển thị trong `open_algo_orders()`

**Files đã sửa trong phase này:**
- `production/live/config.py` — multi-strategy support, per-strategy API key, Telegram config, BE/Trail R multiples per level
- `production/live/binance_client.py` — Algo Order API, `equity_usdt()`, `position_risk()` v3, `-4046`/`-4045` permanent
- `production/live/bot.py` — margin check trước entry, detailed Telegram notifications, `_realized()`/`_notify_exit()` helpers
- `production/live/telegram.py` — async queue + worker, formatted notifications
- `production/live/strategy_adapter.py` — dynamic strategy module import
- `production/live/.env` — 3 testnet API keys + Telegram token/chat IDs (KHÔNG commit, trong .gitignore)
- `production/live/.env.example` — template
- `production/live/cleanup.py` — one-shot cleanup (close all positions + cancel all orders)
- `production/live/test_algo.py` — Algo Order API integration test
- `production/live/test_noti.py` — Telegram notification test

---

## Cấu trúc file hiện tại

```
D:/Temp/Trading/
├── README.md                          # Tổng quan + so sánh strategies
├── PROJECT_HISTORY.md                 # File này — lịch sử đầy đủ
│
├── production/                        # ← Strategies đã test + live bot
│   ├── strategy_aggressive.py             # V15r2 — PRODUCTION (100% tháng lãi, +39%)
│   ├── strategy_aggressive_test.py        # Test 31 tháng
│   ├── strategy_aggressive_6month_test.py # Test 6 tháng liên tục (3 windows)
│   ├── strategy_aggressive_lv2.py         # LV2 — HIGH RISK (94% tháng lãi, +74%, 0 LIQ)
│   ├── strategy_aggressive_lv2_test.py    # Test 31 tháng
│   ├── strategy_aggressive_lv3.py         # LV3 — EXTREME HIGH RISK (97% tháng lãi, +182%, 9 LIQ)
│   ├── strategy_aggressive_lv3_test.py    # Test 31 tháng
│   ├── strategy_aggressive_lv4.py         # LV4 — VERY EXTREME (87% tháng lãi, +283%, 23 LIQ)
│   ├── strategy_aggressive_lv4_test.py    # Test 31 tháng
│   ├── strategy_aggressive_lv5.py         # LV5 — MAXIMUM RISK (81% tháng lãi, +645%, 34 LIQ)
│   ├── strategy_aggressive_lv5_test.py    # Test 31 tháng
│   ├── strategy_aggressive_lv6.py         # LV6 — ULTRA MAXIMUM (77% tháng lãi, +719%, 35 LIQ)
│   ├── strategy_aggressive_lv6_test.py    # Test 31 tháng
│   ├── continuous_2024_v15.py             # Continuous backtest V15r2 Jan2024–Jun2026
│   ├── continuous_2024_lv{2,3,4,5,6}.py   # Continuous backtest LV2-LV6
│   ├── strategy_balanced.py               # V14 — conservative (+25%)
│   ├── strategy_balanced_test.py          # Test 31 tháng
│   ├── strategy_balanced_6month_test.py   # Test 6 tháng liên tục
│   └── live/                              # Live trading bot
│       ├── README_LIVE.md                 # Hướng dẫn live bot
│       ├── config.py                      # Mode, keys, params
│       ├── binance_client.py              # REST client + retry/backoff
│       ├── exchange_filters.py            # Precision, min-notional
│       ├── state_db.py                    # SQLite state persistence
│       ├── strategy_adapter.py            # Live klines → decide_v15
│       ├── bot.py                         # Reconciliation + main loop + Telegram notify
│       ├── telegram.py                    # Async Telegram notifications (queue + worker)
│       ├── cleanup.py                     # One-shot: close all positions + cancel all orders
│       ├── test_recovery.py               # Offline recovery self-test (17/17 PASS)
│       ├── test_algo.py                   # Algo Order API integration test (PASS)
│       ├── test_noti.py                   # Telegram notification test
│       ├── .env                           # API keys + Telegram config (gitignored)
│       └── .env.example                   # Template for .env
│
├── experimental/                     # ← Version thử nghiệm (trống, sẽ thêm sau)
│
├── legacy/                            # ← Code cũ không dùng
│   ├── main.py                             # Legacy entry point
│   ├── mock_llm.py / mock_llm_agent.py     # Mock LLM
│   ├── run_llm_agent.py                    # LLM agent runner
│   ├── backtest/                           # Backtest framework (V2-V11)
│   ├── strategies/                         # Strategy templates (V2-V11)
│   ├── features/                           # Feature engineering
│   ├── data/                               # Data fetcher (Bybit)
│   └── config*.yaml                        # Legacy configs
```

---

## Phase: strategy_reversal_scalp (v6.1) — BỎ (2026-06-25)

**Mục tiêu:** Mean-reversion scalping 1m, catch tops/bottoms trên top active coins, leverage cao (~22x), TP/SL adaptive nhỏ.

**Kết quả backtest 15 ngày (8 coins: BTC/ETH/SOL/HYPE/ZEC/AAVE/DOGE/XRP):**

| Version | PnL | WR | Trades | Liquidations |
|---|---|---|---|---|
| v1 (gốc: RSI78/22, BB 2.0σ, spike 1.5%) | -12.3% | 39.5% | 43 | 0 |
| v2 (+trend filter +confirmed close) | -6.87% | 33.3% | 18 | 0 |
| v3 (tighter RSI + HTF slope filter) | -9.28% | 25.0% | 8 | 0 |
| v4 (looser entry + lower spike 1.2%) | -23.25% | 21.7% | 23 | 0 |

**Kết luận: BỎ strategy.** Không có edge sau 4 lần backtest. Nguyên nhân:
1. RSI 1m >78 + BB breakout = **momentum tiếp tục**, không phải đảo chiều. Overbought kéo dài rất lâu trong trend mạnh.
2. Spike 1.2-1.5% trong 5 phút trên top coins (BTC/ETH) **quá hiếm** → ít trade, không đủ ý nghĩa thống kê.
3. Khi spike xảy ra, thường do **tin tức** → tiếp tục chứ không reverse.
4. SL 0.3-2% quá gần → bị **wick out** liên tục với leverage 22x.
5. TP 0.3-1.5% cần **WR >60%** mới có lời sau phí — không đạt được.

**Files giữ lại:** `strategy_reversal_scalp.py`, `backtest_reversal_scalp.py` (reference, không dùng production).

---

## Chiến lược chi tiết (strategy_aggressive.py)

### Indicators (15m chart)
- EMA9, EMA21, EMA50, EMA200
- RSI14
- ATR14 (as % of price)
- ADX14
- EMA50 slope (5-bar change)
- Body (close - open)

### Entry conditions (LONG)
1. EMA9 > EMA21 > EMA50 (trend alignment)
2. EMA50 slope > 0.05% (momentum)
3. ADX >= 20 (trending market)
4. ATR < 1.5% (avoid high vol)
5. RSI 40–65 (normal) or > 65 + volume spike (breakout)
6. Body > 0 (green candle)
7. BTC regime != bear (bull/neutral OK)
8. 1h trend != down

### Entry conditions (SHORT)
- Mirror of LONG
- RSI 35–60 (normal) or < 50 + volume spike
- BTC regime != bull
- 1h trend != up
- Special: RSI < 25 + ATR > 0.3% → deep oversold bounce short

### Scoring (5–10)
- Base: 5- +1 volume spike (1.5x avg)
- +1 strong slope (>0.15%)
- +1 trend alignment (EMA9>21>50)
- +1 ADX > 25
- +1 EMA200 alignment (soft bonus)
- +1 strong body (>0.5%)
- -1 neutral BTC regime
- Min score to enter: 6

### Leverage (anti-liquidation)
- ATR < 0.5% → 20x, < 0.8% → 15x, < 1.2% → 10x, else 5x
- Cap at 10x (5x in neutral regime)
- Auto-reduce if ROE at SL > 45% or SL > 80% of liq threshold
- Liquidation thresholds: 25x→2.2%, 10x→8.5%, 5x→19%

### Exit logic
- **SL:** 1.3x ATR (min 0.3%) — placed as real STOP_MARKET order on exchange
- **TP:** 3.5x SL distance — placed as TAKE_PROFIT_MARKET order
- **Breakeven:** at 0.5R profit, move SL to entry + 0.01% (LONG) / entry - 0.01% (SHORT)
- **Trailing:** at 1.2R profit, move SL to entry + 1R (lock profit)
- **Max hold:** 48 bars (12h) — force close

### Position sizing (compounding)
- margin = current_equity * 7%
- notional = margin * leverage
- qty = notional / price
- Win → equity up → position up (compound)
- Lose → equity down → position down (de-risk)
- Min notional $5 (Binance minimum)
- Max 10% of bar volume (partial fill handling)

### BTC Regime (daily chart)
- price > EMA50 > EMA200 → bull (only LONG)
- price < EMA50 < EMA200 → bear (only SHORT)
- else → neutral (both, max 5x lev, max 5 concurrent)

### No look-ahead verification
- Entry signal: uses bar[i-1] (closed), entry at bar[i] open
- 1h trend: uses previous closed 1h bar
- Exit: SL/TP checked before SL update (SL applies next bar)
- Liquidation: checked first (worst case wick)

---

## Cách chạy

### Backtest
```bash
python strategy_aggressive_test.py          # 31 tháng
python strategy_aggressive_6month_test.py   # 6 tháng x 3 windows
python strategy_balanced_test.py            # V14 31 tháng
```

### Live bot
```bash
# Testnet (fake money) — 3 bot song song
# .env đã có API keys + Telegram config, chỉ cần set strategy:
$env:BOT_MODE="testnet"; $env:BOT_STRATEGY="lv4"; python -m live.bot   # shell 1
$env:BOT_MODE="testnet"; $env:BOT_STRATEGY="lv5"; python -m live.bot   # shell 2
$env:BOT_MODE="testnet"; $env:BOT_STRATEGY="lv6"; python -m live.bot   # shell 3

# Dry run (real data, no orders)
$env:BOT_MODE="dry"; $env:BOT_STRATEGY="v15"; python -m live.bot

# Live (real money — after testnet verified)
# Fill BINANCE_LIVE_KEY_LV4 etc in .env first
$env:BOT_MODE="live"; $env:BOT_STRATEGY="lv4"; python -m live.bot

# Cleanup (close all positions + cancel all orders on current account)
$env:BOT_STRATEGY="lv4"; python -m live.cleanup

# Tests
python -m live.test_recovery   # recovery 17/17
python -m live.test_algo       # Algo Order API
python -m live.test_noti       # Telegram
```

### Recovery test (no keys needed)
```bash
python -m live.test_recovery
```

---

## Kết luận

- **Production strategy:** `strategy_aggressive.py` (V15r2) — 100% tháng lãi, +39%/mo avg, 0 LIQ
- **Backup strategy:** `strategy_balanced.py` (V14) — 84% tháng lãi, +25%/mo, 0 LIQ
- **High-risk option:** `strategy_aggressive_lv2.py` (LV2) — 94% tháng lãi, +74%/mo, 0 LIQ (sweet spot)
- **Extreme high-risk option:** `strategy_aggressive_lv3.py` (LV3) — 97% tháng lãi, +182%/mo, **9 LIQ**
- **Very extreme:** `strategy_aggressive_lv4.py` (LV4) — 87% tháng lãi, +283%/mo, **23 LIQ**
- **Maximum risk:** `strategy_aggressive_lv5.py` (LV5) — 81% tháng lãi, +645%/mo, **34 LIQ**
- **Ultra maximum:** `strategy_aggressive_lv6.py` (LV6) — 77% tháng lãi, +719%/mo, **35 LIQ**
- **Live bot:** `live/` — crash recovery đầy đủ, **TESTNET VERIFIED** (3 bot chạy song song overnight)
- **Current deployment:** 3 bot (LV4/LV5/LV6) đang chạy trên testnet, Telegram notify 3 channel
- **Next step:** Monitor testnet thêm vài ngày → nếu ổn → switch `BOT_MODE=live` + fill `BINANCE_LIVE_KEY_*` trong `.env`

## Lưu ý quan trọng

- Backtest dùng data Binance public API (không cần key)
- Kết quả backtest là lịch sử, không đảm bảo tương lai
- Compounding means position size thay đổi theo equity — cần monitor khi live
- **Luôn test testnet trước khi live**
- Bot cần VPS chạy 24/7 (Binance chỉ giữ SL/TP, bot phải chạy để vào lệnh mới + trailing)
