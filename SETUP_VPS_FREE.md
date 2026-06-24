# Hướng dẫn setup GratisVPS.net cho Trading Bot (không cần credit card)

## Tổng quan
- GratisVPS.net: VPS free forever, không cần credit card (chỉ email)
- Cấu hình: 1GB RAM, 1 vCPU, 20GB NVMe SSD, 1TB bandwidth
- **RAM thực tế 3 bot tốn: 247MB** (đo trên laptop, mỗi bot ~82MB)
- → 1GB RAM **dư sức** chạy 3 bot (còn dư ~750MB)
- **Rủi ro:** không có SLA, community support only. Chỉ dùng cho testnet.
  Khi lên live → chuyển Hetzner ($4.5/tháng, PayPal).

## Bước 1: Tạo tài khoản GratisVPS.net

1. Vào https://gratisvps.net/free-vps.html
2. Click "Get Your Free VPS Instantly" (hoặc "Claim Your Free Server Now")
3. Đăng ký bằng email (KHÔNG cần credit card/PayPal)
4. Confirm email (check inbox + spam)
5. Đăng nhập vào dashboard

## Bước 2: Tạo VPS

1. Trong dashboard, chọn "Deploy" hoặc "Create Server"
2. Cấu hình:
   - **OS:** Ubuntu 22.04 (hoặc 24.04)
   - **Plan:** Free — 1 vCPU, 1GB RAM, 20GB NVMe
   - **Location:** chọn gần Binance nhất (Singapore/Tokyo nếu có,
     EU cũng OK — bot không cần ultra-low latency, chỉ fetch klines mỗi 15m)
3. Click "Deploy"
4. Chờ 30-60 giây
5. **Ghi lại:**
   - Public IP
   - Root password (hoặc SSH key)

## Bước 3: Kết nối SSH

```bash
# Windows PowerShell
ssh root@<IP>
# Nhập password khi prompted

# Mac/Linux
ssh root@<IP>
```

Lỗi "Connection refused"? Chờ thêm 1-2 phút (server đang boot).

## Bước 4: Cài đặt Python + tools

```bash
# Update system
apt update && apt upgrade -y

# Cài Python 3 + tools
apt install -y python3 python3-pip python3-venv git tmux nano curl

# Kiểm tra
python3 --version  # cần >= 3.10
```

## Bước 5: Thêm swap 1GB (phòng hờ)

Bot tốn 247MB RAM, dư ~750MB. Nhưng thêm swap cho an toàn:

```bash
fallocate -l 1G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
free -h  # verify swap = 1GB
```

## Bước 6: Clone repo + setup

```bash
mkdir -p /opt/trading
cd /opt/trading
git clone https://github.com/ngominhtam1998/Trading.git .

# Virtual environment + packages
python3 -m venv venv
source venv/bin/activate
pip install pandas requests

# Verify
python3 -c "import pandas, requests; print('OK')"
```

## Bước 7: Tạo file .env

```bash
cd /opt/trading/production/live
cp .env.example .env
nano .env
```

Nội dung .env:
```
BOT_MODE=testnet
BOT_STRATEGY=v15

BINANCE_TESTNET_KEY_LV4=<paste_key_lv4>
BINANCE_TESTNET_SECRET_LV4=<paste_secret_lv4>
BINANCE_TESTNET_KEY_LV5=<paste_key_lv5>
BINANCE_TESTNET_SECRET_LV5=<paste_secret_lv5>
BINANCE_TESTNET_KEY_LV6=<paste_key_lv6>
BINANCE_TESTNET_SECRET_LV6=<paste_secret_lv6>

TELEGRAM_BOT_TOKEN=<paste_bot_token>
TELEGRAM_CHAT_LV4=@trading_v4
TELEGRAM_CHAT_LV5=@trading_v5
TELEGRAM_CHAT_LV6=@trading_v6
```

Lưu: `Ctrl+O` → `Enter` → `Ctrl+X`

## Bước 8: Test chạy 1 bot

```bash
cd /opt/trading/production
source venv/bin/activate

# Chạy thử lv4 (Ctrl+C để stop sau khi thấy OK)
BOT_MODE=testnet BOT_STRATEGY=lv4 PYTHONIOENCODING=utf-8 python3 -u -m live.bot
```

Thấy log:
```
=== Starting bot in MODE=testnet STRATEGY=lv4 ===
Time synced, offset=...
Loaded filters for 528 symbols
ENTER ... SHORT ...
Telegram delivered to @trading_v4 (...)
```

→ Bot chạy OK. `Ctrl+C` để stop.

## Bước 9: Chạy 3 bot 24/7 bằng systemd

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
```

Enable + start:

```bash
systemctl daemon-reload
systemctl enable trading-bot-lv4 trading-bot-lv5 trading-bot-lv6
systemctl start trading-bot-lv4 trading-bot-lv5 trading-bot-lv6
```

Kiểm tra:

```bash
# Status
systemctl status trading-bot-lv4
systemctl status trading-bot-lv5
systemctl status trading-bot-lv6

# Log realtime
tail -f /opt/trading/production/live/bot_testnet_lv4.log
```

## Bước 10: Quản lý bot

```bash
# Stop / Start / Restart
systemctl stop trading-bot-lv4
systemctl start trading-bot-lv4
systemctl restart trading-bot-lv4

# Log
journalctl -u trading-bot-lv4 -f          # realtime
journalctl -u trading-bot-lv4 -n 100      # 100 dòng cuối

# Update code
cd /opt/trading
git pull origin main
systemctl restart trading-bot-lv4 trading-bot-lv5 trading-bot-lv6

# RAM usage
free -h

# Bot processes
ps aux | grep live.bot
```

## Bước 11: Backup state (QUAN TRỌNG)

VPS free có thể mất bất ngờ. Backup state DB:

```bash
# Backup lên GitHub mỗi 6 tiếng
cat > /opt/trading/backup.sh << 'EOF'
#!/bin/bash
cd /opt/trading
git add production/live/state_*.db 2>/dev/null
git commit -m "backup: state $(date +'%Y-%m-%d %H:%M')" 2>/dev/null
git push origin main 2>/dev/null
EOF
chmod +x /opt/trading/backup.sh

# Cron mỗi 6 tiếng
(crontab -l 2>/dev/null; echo "0 */6 * * * /opt/trading/backup.sh") | crontab -
```

## Khi lên LIVE

**KHÔNG nên chạy live trên VPS free.** Chuyển sang Hetzner:

1. Tạo Hetzner account (https://hetzner.cloud) — PayPal, không cần credit card
2. Tạo CX22 server (~$4.5/tháng, 4GB RAM, 2 vCPU)
3. Làm lại Bước 4-9 (đổi .env `BOT_MODE=live` + fill live keys)
4. Hoặc: backup state từ GratisVPS → restore trên Hetzner

## Troubleshooting

### Bot crash liên tục
```bash
journalctl -u trading-bot-lv4 -n 50
# Thường: sai API key, sai .env, thiếu package
```

### RAM hết (OOM killer kill bot)
```bash
# Kiểm tra swap
free -h
# Nếu swap = 0, tạo lại (Bước 5)
# Nếu vẫn hết, giảm bot: chỉ chạy 1-2 bot thay vì 3
```

### VPS bị shutdown
- Binance vẫn giữ SL/TP (algo orders tự đóng khi chạm giá)
- Khi VPS lên lại → bot tự reconcile (adopt positions, đặt lại SL)
- Nếu VPS mất hẳn → tạo VPS mới, clone repo, restore state backup

### Không kết nối được Binance API
```bash
curl -s https://testnet.binancefuture.com/fapi/v1/time
# Timeout → VPS bị chặn IP, thử VPN hoặc đổi VPS
```

## Tóm tắt chi phí
- GratisVPS.net: **$0/tháng** (chỉ email)
- Python + pandas + requests: **free**
- GitHub repo: **free**
- Telegram Bot API: **free**
- **Tổng: $0/tháng**

## RAM thực tế (đo trên laptop)
| Bot | RAM |
|-----|-----|
| LV4 | 82 MB |
| LV5 | 83 MB |
| LV6 | 82 MB |
| **Tổng** | **247 MB** |

GratisVPS 1GB RAM → dư ~750MB. An toàn.
