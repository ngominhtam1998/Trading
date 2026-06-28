# OPUS_TRADING — bàn giao & cách test sát thực tế

Chiến lược mới `opus` thay thế `v8` trên account **LV4**. Mục tiêu: vào lệnh chắc tay,
đa khung, có lọc BTC, quản trị 1 phút, và **được đánh giá bằng test mô phỏng khớp lệnh
thật (intrabar)** thay vì backtest theo giá đóng nến (vốn là lý do v7/v8 lãi giả).

## 1. Vì sao v7/v8 backtest lãi mà testnet lỗ (đã sửa trong opus)

1. Backtest cắt lỗ theo **giá ĐÓNG nến 1m**, nhưng `STOP_MARKET` live khớp theo **wick**
   → live bị quét SL mà backtest "sống sót". → opus đặt SL rộng (swing + ATR) và
   **test khớp SL/TP theo wick** (`test_opus_replay.py`).
2. Backtest quản lý mỗi 1m, live mỗi 15m → opus chạy vòng lặp **`LOOP_SECONDS=60`**.
3. Entry chỉ xét 1 nến 15m + BTC regime ngày → cứ short vào nhịp hồi. → opus yêu cầu
   **đồng thuận đa khung (1m/5m/15m/1h)** + **lọc BTC ngắn hạn** + **chốt chặn bounce**.

## 2. File liên quan

| File | Vai trò |
|------|---------|
| `strategy_opus.py` | Logic chiến lược. Lõi quyết định thuần: `decide_mtf(...)`. Quản trị: `compute_trail_sl(...)`. BTC: `btc_context_from_frames/get_btc_context_live`. |
| `live/config.py` | Đăng ký `opus` → account LV4; đọc `LOOP_SECONDS`, `ENTRY_EVERY_LOOPS`. |
| `live/strategy_adapter.py` | Dùng `analyze_live` + `get_btc_context` nếu strategy có (không phá v6/v7/v8). |
| `live/bot.py` | Vòng lặp theo `LOOP_SECONDS`; entry mỗi `ENTRY_EVERY_LOOPS`; trail/BE 1m qua `compute_trail_sl`. |
| `test_opus_replay.py` | **Test sát thực tế** (intrabar fill + phí + slippage + funding). |

`decide_mtf` là **một nguồn sự thật duy nhất** — cả live (`analyze_live`) lẫn test
(`test_opus_replay`) đều gọi nó, nên không bao giờ lệch nhau.

## 3. Cách chạy test (dành cho model tune)

```bash
cd D:\Tam\trading\production
python test_opus_replay.py            # 7 ngày gần nhất, 12 coin top volume
python test_opus_replay.py 5 20 777   # 5 ngày, 20 coin, seed 777
python test_opus_replay.py 14 25      # 14 ngày, 25 coin
```

- Dữ liệu klines 1m/5m/15m/1h thật được cache vào `_cache_opus/`.
- Output gồm: return %, **WR, PF, MaxDD**, phân loại exit, và **SIGNAL FUNNEL**
  (gate nào loại bao nhiêu %) để biết nên nới/siết chỗ nào.

### Tiêu chí trước khi nghĩ tới tiền thật
Chạy **≥ 2 cửa sổ thời gian khác nhau** (ví dụ 7d gần nhất và 14d trước đó). Yêu cầu:
`return > 0` **và** `PF > 1.3` **và** `MaxDD < 25%` **và** `liquidations = 0` ở cả hai.
KHÔNG tin một con số đẹp ở một cửa sổ duy nhất (đó chính là cái bẫy của v7/v8).

## 4. Kết quả tham chiếu (1 cửa sổ — CHƯA đủ để deploy)

`python test_opus_replay.py 5 20 777` (intrabar, fee 0.04%/side, slippage 0.03%):
`+16.4% / 5 ngày | WR 59% | PF 1.18 | MaxDD 14% | 188 lệnh | 0 cháy`.

## 5. Tham số tune (trong `strategy_opus.py`)

- **Đánh đổi WR ↔ lợi nhuận**: `RR` thấp + `BE_R`/`BE_LOCK_PCT` sớm → WR cao, payoff thấp.
  `RR` cao + trail xa → WR thấp, winner to. (Quan sát: `BE_LOCK_PCT` PHẢI > tổng phí+slippage
  ~0.14%, nếu không exit BE thực chất lỗ và giết WR.)
- Gate đa khung: `ADX_MIN_15M/5M`, `SLOPE_MIN_15M`.
- Chống bounce: `RSI_SHORT_FLOOR`, `RSI_LONG_CEIL`, `BOUNCE_ATR_MULT`, `EXHAUSTION_GREEN_RED`.
- Lọc BTC: `BTC_BOUNCE_ATR_MULT`, `BTC_SYMBOLS_STRICT` (coin vốn hóa lớn bị siết hơn).
- SL/đòn bẩy: `SL_MIN_PCT/SL_MAX_PCT/SL_ATR_MULT`, `MAX_LEVERAGE`, `LIQ_SAFETY_ROE`.
- Quy mô: `POSITION_PCT`, `POS_SCORE_*`, `MAX_CONCURRENT`, `MIN_SCORE`.

## 6. Deploy (chỉ khi user xác nhận)

```bash
# VPS
ssh root@74.113.235.40
cd /opt/trading && git pull origin main
# Đổi service LV4 sang opus: BOT_STRATEGY=opus (BOT_ACCOUNT vẫn LV4)
systemctl restart trading-bot-lv4
tail -f /opt/trading/production/live/bot_testnet_opus.log
```
> Lưu ý: state DB và log của opus là `state_testnet_opus.db` / `bot_testnet_opus.log`
> (tách biệt với v8), nên có thể chạy song song A/B nếu muốn.
