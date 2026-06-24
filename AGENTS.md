# Project Rules — Trading Bot

## Quick Reference

### VPS (production)
- **IP:** 74.113.235.40 (Kamatera Singapore)
- **SSH:** `ssh root@74.113.235.40`
- **3 bots:** systemd services `trading-bot-lv4`, `trading-bot-lv5`, `trading-bot-lv6`
- **Repo:** `/opt/trading` (venv: `/opt/trading/venv`)
- **Log:** `/opt/trading/production/live/bot_testnet_lv{4,5,6}.log`
- **Trial hết hạn:** ~2026-07-24 (30 ngày từ 2026-06-24)

### Quản lý VPS
```bash
ssh root@74.113.235.40
systemctl status trading-bot-lv4      # status
systemctl restart trading-bot-lv4 lv5 lv6  # restart all
cd /opt/trading && git pull origin main    # update code
systemctl restart trading-bot-lv4 lv5 lv6  # restart after update
tail -f /opt/trading/production/live/bot_testnet_lv4.log  # log
```

### Laptop (dev/fallback)
- Repo: `D:\Tam\trading`
- Run: `cd D:\Tam\trading\production; $env:BOT_MODE="testnet"; $env:BOT_STRATEGY="lv4"; python -m live.bot`
- SSH scripts: `setup_vps.py`, `setup_vps_bots.py`, `start_vps_bots.py`, `check_vps_bots.py`, `fix_vps.py`, `fix_vps_logs.py`
- **Bot status + PnL**: `python check_bots_status.py` (shows balance, positions, open orders, today's realized PnL)

### Build/Test commands
#### Mock tests (no API keys, chạy local)
- Test recovery: `python -m live.test_recovery` (17/17 PASS)
- Test decision cadence: `python -m live.test_decision_bars` (6/6 PASS)
- Test SL move: `python -m live.test_sl_move` (6/6 PASS)
- Test realized PnL: `python -m live.test_realized_pnl` (4/4 PASS)

#### Real-API tests (cần .env keys, chạy trên VPS)
- Test data verify: `python -m live.test_data_verify` (40/40 PASS)
- Test SL fix: `python -m live.test_sl_fix` (8/9 PASS)
- Test funding: `python -m live.test_funding` (10/10 PASS)

#### Utility
- Cleanup: `python -m live.cleanup`

### Git
- Remote: `origin` (github.com/ngominhtam1998/Trading)
- Branch: `main`
- `.env`, `state_*.db`, `bot_*.log` trong `.gitignore`
- **KHÔNG tự động `git push`**. Chỉ push khi user nói rõ "push" / "commit và push" / "deploy".
- Commit local có thể tự làm, nhưng push luôn cần xác nhận user.

### Rules khi làm việc
- **Phân tích kỹ yêu cầu user** trước khi làm. Nếu không rõ, hỏi lại. Không tự đoán.
- Với thay đổi rủi ro (live deploy, đóng positions, xóa dữ liệu), **luôn xác nhận lại** với user.

### Superpowers workflow (cài tại `.devin/skills/`)
- Trước khi code: **hỏi rõ** → đề xuất 2-3 phương án → trình design → chờ duyệt.
- Sau khi design duyệt: viết plan với todo list cụ thể, từng bước verify.
- Mỗi thay đổi code: tự review (logic, lỗi, security, style), chạy test liên quan.
- Không tuyên bố "xong" khi chưa verify bằng lệnh/test thực tế.

### Key fixes đã apply
1. SL move (BE/trail): cancel old SL first, then place new SL; restore old SL if new fails
2. Telegram SSL (verify=False trên testnet, verify=True trên live)
3. Funding rate filter (skip SHORT+funding âm, LONG+funding dương >= 0.1%)
4. -4028, -2027, -4046, -4045, -4130 in PERMANENT_CODES
5. Margin auto-scale (check avail >= margin/pos)
6. Cooldown 6 bar sau 2 SL liên tiếp (match backtest)
7. Liquidation warning (Telegram khi price trong 20% liq price)
8. Funding cost tracking (warn khi daily funding > 5% equity)
9. SL vs TP detection trên close (income API + exit price + PnL sign fallback)
10. DECISION_EVERY_BARS enforcement (entry scan matches backtest cadence)
11. Multi-instance file lock (prevent duplicate bot processes)
12. Proactive time sync every 30 minutes

### Khi lên live
1. SSH vào VPS
2. `nano /opt/trading/production/live/.env` → `BOT_MODE=live` + fill live keys
3. `systemctl restart trading-bot-lv4 lv5 lv6`
4. Monitor sát ngày đầu
