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

### Build/Test commands
- Test data verify: `python -m live.test_data_verify` (40/40 PASS)
- Test SL fix: `python -m live.test_sl_fix` (8/9 PASS)
- Test funding: `python -m live.test_funding` (10/10 PASS)
- Test recovery: `python -m live.test_recovery` (17/17 PASS)
- Cleanup: `python -m live.cleanup`

### Git
- Remote: `origin` (github.com/ngominhtam1998/Trading)
- Branch: `main`
- `.env`, `state_*.db`, `bot_*.log` trong `.gitignore`
- **KHÔNG tự động `git push`**. Chỉ push khi user nói rõ "push" / "commit và push" / "deploy".
- Commit local có thể tự làm, nhưng push luôn cần xác nhận user.

### Key fixes đã apply
1. SL atomic swap (place new before cancel old + price validation)
2. Telegram SSL (verify=False trên testnet, verify=True trên live)
3. Funding rate filter (skip SHORT+funding âm, LONG+funding dương >= 0.1%)
4. -4028, -2027, -4046, -4045, -4130 in PERMANENT_CODES
5. Margin auto-scale (check avail >= margin/pos)
6. Cooldown 6 bar sau 2 SL liên tiếp (match backtest)
7. Liquidation warning (Telegram khi price trong 20% liq price)
8. Funding cost tracking (warn khi daily funding > 5% equity)
9. SL vs TP detection trên close (so sánh exit price vs SL/TP price)

### Khi lên live
1. SSH vào VPS
2. `nano /opt/trading/production/live/.env` → `BOT_MODE=live` + fill live keys
3. `systemctl restart trading-bot-lv4 lv5 lv6`
4. Monitor sát ngày đầu
