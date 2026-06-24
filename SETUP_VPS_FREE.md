# Hướng dẫn setup AlaVPS cho Trading Bot (không cần credit card)

## Tổng quan
- **AlaVPS.com**: https://alavps.com/vps.html
- VPS free, không cần credit card (chỉ email)
- Cấu hình: **8GB RAM, 2 vCPU, 128GB NVMe SSD** — rất tốt
- 3 bot tốn ~247MB RAM → dư nhiều
- **Lưu ý:** Free slots có thể hết, nếu đầy sẽ bị waitlist. Chỉ dùng cho testnet.
  Khi lên live → chuyển Hetzner ($4.5/tháng, PayPal).

## Bước 1: Tạo tài khoản

1. Vào https://alavps.com/vps.html
2. Click "Activate Free VPS (No CC)" hoặc "Start Free VPS Now"
3. Đăng ký tại https://manage.alavps.com
4. Điền email (chỉ email, KHÔNG cần credit card)
5. Confirm email (check inbox + spam)
6. Đăng nhập vào client portal

## Bước 2: Tạo VPS

1. Trong client portal, chọn **Products/Services → Order New Services**
2. Chọn category **Free VPS (No Credit Card)**
3. Cấu hình:
   - **OS:** Ubuntu 22.04 LTS (hoặc 24.04)
   - **Location:** Singapore/Tokyo nếu có. Không có thì chọn EU (Germany/France)
   - **Plan:** Free VPS (8GB RAM, 2 vCPU, 128GB NVMe)
4. Click Continue / Checkout
5. Chờ email nhận thông tin đăng nhập (IP, root password, hoặc SSH key)

## Bước 3: Kết nối SSH

```bash
# Windows PowerShell
ssh root@<IP>
# Nhập root password khi prompted

# Mac/Linux
ssh root@<IP>
```

Lỗi "Connection refused"? Chờ 2-5 phút (server đang boot).

## Bước 4: Cài đặt Python + tools

```bash
# Update system
apt update && apt upgrade -y

# Cài Python 3 + tools
apt install -y python3 python3-pip python3-venv git tmux nano curl

# Kiểm tra
python3 --version  # cần >= 3.10
```

## Bước 5: Clone repo + setup

```bash
mkdir -p /opt/trading
cd /opt/trading
git clone https://github.com/ngominhtam1998/Trading.git .

# Virtual environment + packages
python3 -m venv venv
source venv/bin/activate
pip install pandas requests

python3 -c "import pandas, requests; print('OK')"
```

## Bước 6: Tạo file .env

```bash
cd /opt/trading/production/live
cp .env.example .env
nano .env
```

Điền API keys + Telegram:
```
BOT_MODE=testnet
BOT_STRATEGY=v15

BINANCE_TESTNET_KEY_LV4=<paste>
BINANCE_TESTNET_SECRET_LV4=<paste>
...

TELEGRAM_BOT_TOKEN=<paste>
TELEGRAM_CHAT_LV4=@trading_v4
TELEGRAM_CHAT_LV5=@trading_v5
TELEGRAM_CHAT_LV6=@trading_v6
```

Lưu: `Ctrl+O` → `Enter` → `Ctrl+X`

## Bước 7: Test 1 bot

```bash
cd /opt/trading/production
source venv/bin/activate

BOT_MODE=testnet BOT_STRATEGY=lv4 PYTHONIOENCODING=utf-8 python3 -u -m live.bot
```

Thấy `ENTER ... SHORT ...` và `Telegram delivered` là OK. `Ctrl+C` để stop.

## Bước 8: Chạy 3 bot 24/7 bằng systemd

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

## Bước 9: Quản lý

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

# Check RAM
free -h
ps aux | grep live.bot
```

## Bước 10: Backup state

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

## Khi lên LIVE

1. Tạo Hetzner account (https://hetzner.cloud) — PayPal
2. Tạo CX22 server (~$4.5/tháng, 4GB RAM)
3. Đổi `.env` thành `BOT_MODE=live` + fill live keys
4. Restart bots

## Nếu AlaVPS không còn slot

Thử các alternative:
1. **VPSWala.org** — 30-day trial + $100 credit, 8GB RAM
2. **Hetzner** — $4.5/tháng, PayPal, ổn định nhất
3. **GitHub Actions** — free, nhưng cần sửa bot thành cron job

## Tóm tắt
- AlaVPS: **$0/tháng**, 8GB RAM, 2 cores, 128GB NVMe
- 3 bot tốn **247MB RAM**
- Không cần sửa bot gì
- Chỉ cần email, không credit card
