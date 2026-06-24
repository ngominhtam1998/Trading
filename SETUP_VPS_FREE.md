# Hướng dẫn setup VPS cho Trading Bot

> **Lưu ý quan trọng:** Free VPS không credit card thực tế rất hiếm. Hầu hết các trang quảng cáo "free VPS no CC" đều redirect về paid provider (Kamatera, Hetzner, v.v.) hoặc yêu cầu verify bằng email edu/GitHub. File này tập trung vào các giải pháp thực tế.

## Giải pháp khuyến nghị

| Giải pháp | Giá | Credit Card | Uptime | Phù hợp |
|---|---|---|---|---|
| **Kamatera** | $4/tháng | Cần | 99.95% SLA | Trial 30 ngày free, sau đó trả phí |
| **Hetzner** | $4.5/tháng | PayPal OK | 99.9% | Ổn định nhất, không cần card |
| **GitHub Actions** | $0 | Không | Cron 5-15 phút | Cần sửa bot thành one-shot |
| **PC cá nhân** | $0 | Không | Không 24/7 | Chỉ test khi máy bật |

## 1. Kamatera (khuyến nghị nếu đã có credit card)

### Bước 1: Đăng ký + add credit card
- Vào https://kamatera.com
- Sign up, verify email, add credit card
- Không charge trong 30 ngày trial nếu trong limit

### Bước 2: Tạo server
1. Login console: https://console.kamatera.com
2. Menu trái → **My Cloud → Create New Server**
3. **Location:** Singapore hoặc Hong Kong (gần Binance)
4. **Server Type:** Type A – Availability (rẻ nhất)
5. **CPU:** 1 vCPU
6. **RAM:** 1 GB (3 bot tốn 247MB, dư)
7. **Storage:** 20 GB NVMe SSD
8. **OS:** Ubuntu Server 22.04 LTS
9. **Network:** để default (5 TB traffic)
10. **Billing:** Monthly hoặc Hourly
11. Click **Create Server**
12. Đợi 1-2 phút, ghi lại IP + root password

### Bước 3: SSH vào VPS
```bash
# Windows PowerShell
ssh root@<IP>

# Mac/Linux
ssh root@<IP>
```

### Bước 4: Cài đặt Python
```bash
apt update && apt upgrade -y
apt install -y python3 python3-pip python3-venv git tmux nano curl
python3 --version
```

### Bước 5: Clone repo + setup
```bash
mkdir -p /opt/trading
cd /opt/trading
git clone https://github.com/ngominhtam1998/Trading.git .

python3 -m venv venv
source venv/bin/activate
pip install pandas requests

python3 -c "import pandas, requests; print('OK')"
```

### Bước 6: Tạo .env
```bash
cd /opt/trading/production/live
cp .env.example .env
nano .env
```

Điền:
```
BOT_MODE=testnet
BOT_STRATEGY=v15

BINANCE_TESTNET_KEY_LV4=<paste>
BINANCE_TESTNET_SECRET_LV4=<paste>
BINANCE_TESTNET_KEY_LV5=<paste>
BINANCE_TESTNET_SECRET_LV5=<paste>
BINANCE_TESTNET_KEY_LV6=<paste>
BINANCE_TESTNET_SECRET_LV6=<paste>

TELEGRAM_BOT_TOKEN=<paste>
TELEGRAM_CHAT_LV4=@trading_v4
TELEGRAM_CHAT_LV5=@trading_v5
TELEGRAM_CHAT_LV6=@trading_v6
```

### Bước 7: Chạy 3 bot bằng systemd
```bash
# Bot LV4
cat > /etc/systemd/system/trading-bot-lv4.service << 'EOF'
[Unit]
Description=Trading Bot LV4
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/trading/production
Environment=BOT_MODE=testnet
Environment=BOT_STRATEGY=lv4
Environment=PYTHONIOENCODING=utf-8
ExecStart=/opt/trading/production/venv/bin/python3 -u -m live.bot
Restart=always
RestartSec=30
StandardOutput=append:/opt/trading/production/live/bot_testnet_lv4.log
StandardError=append:/opt/trading/production/live/bot_testnet_lv4.log

[Install]
WantedBy=multi-user.target
EOF

# Bot LV5
cat > /etc/systemd/system/trading-bot-lv5.service << 'EOF'
[Unit]
Description=Trading Bot LV5
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/trading/production
Environment=BOT_MODE=testnet
Environment=BOT_STRATEGY=lv5
Environment=PYTHONIOENCODING=utf-8
ExecStart=/opt/trading/production/venv/bin/python3 -u -m live.bot
Restart=always
RestartSec=30
StandardOutput=append:/opt/trading/production/live/bot_testnet_lv5.log
StandardError=append:/opt/trading/production/live/bot_testnet_lv5.log

[Install]
WantedBy=multi-user.target
EOF

# Bot LV6
cat > /etc/systemd/system/trading-bot-lv6.service << 'EOF'
[Unit]
Description=Trading Bot LV6
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/trading/production
Environment=BOT_MODE=testnet
Environment=BOT_STRATEGY=lv6
Environment=PYTHONIOENCODING=utf-8
ExecStart=/opt/trading/production/venv/bin/python3 -u -m live.bot
Restart=always
RestartSec=30
StandardOutput=append:/opt/trading/production/live/bot_testnet_lv6.log
StandardError=append:/opt/trading/production/live/bot_testnet_lv6.log

[Install]
WantedBy=multi-user.target
EOF

# Start
systemctl daemon-reload
systemctl enable trading-bot-lv4 trading-bot-lv5 trading-bot-lv6
systemctl start trading-bot-lv4 trading-bot-lv5 trading-bot-lv6

# Check status
systemctl status trading-bot-lv4
```

### Bước 8: Quản lý
```bash
# Stop / Start / Restart
systemctl stop trading-bot-lv4
systemctl start trading-bot-lv4
systemctl restart trading-bot-lv4

# Log
journalctl -u trading-bot-lv4 -f
journalctl -u trading-bot-lv4 -n 100

# Update code
cd /opt/trading
git pull origin main
systemctl restart trading-bot-lv4 trading-bot-lv5 trading-bot-lv6

# RAM
free -h
ps aux | grep live.bot
```

### Bước 9: Backup state
```bash
# Backup state DB lên GitHub mỗi 6 tiếng
cat > /opt/trading/backup.sh << 'EOF'
#!/bin/bash
cd /opt/trading
git add production/live/state_*.db 2>/dev/null
git commit -m "backup: state $(date +'%Y-%m-%d %H:%M')" 2>/dev/null
git push origin main 2>/dev/null
EOF
chmod +x /opt/trading/backup.sh

(crontab -l 2>/dev/null; echo "0 */6 * * * /opt/trading/backup.sh") | crontab -
```

### Khi lên LIVE
1. Đổi `.env` thành `BOT_MODE=live`
2. Fill `BINANCE_LIVE_KEY_LV4/5/6` + secrets
3. Restart:
```bash
systemctl restart trading-bot-lv4 trading-bot-lv5 trading-bot-lv6
```

## 2. Hetzner (nếu không có credit card, chỉ có PayPal)

- https://hetzner.cloud
- Tạo account bằng PayPal
- Tạo CX22 server: 4GB RAM, 2 vCPU, ~$4.5/tháng
- Setup y hệt Kamatera (Bước 3-9)

## 3. GitHub Actions (free, không cần VPS)

Nếu không có VPS nào khả thi, có thể dùng GitHub Actions:
- Free 2000 phút/tháng
- Chạy bot mỗi 15 phút (cron)
- Cần sửa bot thành "one-shot" mode
- Liên hệ mình nếu muốn làm giải pháp này

## 4. PC cá nhân (tạm thời)

Nếu không có VPS nào:
- Để laptop chạy 24/7, không sleep
- Mở 3 PowerShell, chạy 3 bot
- Dùng cho test ngắn hạn, không phù hợp live

## Lưu ý quan trọng

- **Trial 30 ngày:** Đặt reminder 25 ngày sau để quyết định tiếp tục hay cancel
- **Không dùng free VPS không rõ nguồn gốc cho live trading:** rủi ro mất VPS, mất state
- **Luôn backup state DB:** cron đẩy lên GitHub mỗi 6 tiếng
