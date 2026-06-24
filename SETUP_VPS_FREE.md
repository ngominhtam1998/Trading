# Hướng dẫn setup FreeVPS.it.com cho Trading Bot (không cần credit card)

## Tổng quan
- FreeVPS.it.com: VPS free forever, không cần credit card (chỉ email)
- Cấu hình: 4GB RAM, 2 vCPU, 50GB NVMe SSD
- Đủ chạy 3 bot Python (lv4, lv5, lv6)
- **Rủi ro:** không có SLA, có thể shutdown bất ngờ. Chỉ dùng cho testnet.
  Khi lên live → chuyển Hetzner ($4.5/tháng, PayPal).

## Bước 1: Tạo tài khoản FreeVPS.it.com

1. Vào https://freevps.it.com
2. Click "Get Started" hoặc "Sign Up"
3. Điền email (chỉ cần email, KHÔNG cần credit card/PayPal)
4. Confirm email (check inbox + spam folder)
5. Đăng nhập vào dashboard

## Bước 2: Tạo VPS

1. Trong dashboard, click "Create Server" hoặc "Deploy"
2. Cấu hình:
   - **OS:** Ubuntu 22.04 (hoặc 24.04)
   - **Plan:** Starter (Free) — 4GB RAM, 2 vCPU, 50GB NVMe
   - **Location:** chọn gần Binance server nhất (Singapore/Tokyo nếu có,
     không có thì EU cũng OK — bot không cần ultra-low latency)
   - **Hostname:** trading-bot (tùy ý)
3. Click "Deploy" / "Create"
4. Chờ 1-5 phút, server sẽ ở trạng thái Running
5. **Ghi lại:**
   - Public IP (ví dụ: 192.168.xx.xx)
   - Root password (hoặc SSH key nếu có option)

## Bước 3: Kết nối SSH

### Trên Windows (PowerShell)
```powershell
# Nếu có SSH key
ssh -i .\your-key.key root@<IP>

# Nếu dùng password
ssh root@<IP>
# Nhập password khi prompted
```

### Trên Mac/Linux
```bash
ssh root@<IP>
```

### Lỗi "Connection refused"?
- Chờ thêm 2-3 phút (server đang boot)
- Kiểm tra IP đúng chưa
- Trong dashboard FreeVPS, xem server status = Running

### Lỗi "Permission denied"?
```bash
# Đảm bảo file key có đúng quyền
chmod 400 your-key.key  # Mac/Linux
# Windows: right-click key → Properties → Security → chỉ giữ user hiện tại Read
```

## Bước 4: Cài đặt Python + dependencies

```bash
# Update system
apt update && apt upgrade -y

# Cài Python 3 + tools
apt install -y python3 python3-pip python3-venv git tmux nano curl

# Kiểm tra Python version
python3 --version  # cần >= 3.10
```

## Bước 5: Clone repo + setup

```bash
# Tạo thư mục
mkdir -p /opt/trading
cd /opt/trading

# Clone repo
git clone https://github.com/ngominhtam1998/Trading.git .

# Tạo virtual environment
python3 -m venv venv
source venv/bin/activate

# Cài packages
pip install pandas requests

# Kiểm tra
python3 -c "import pandas, requests; print('OK')"
```

## Bước 6: Tạo file .env

```bash
cd /opt/trading/production/live

# Copy template
cp .env.example .env

# Edit
nano .env
```

Nội dung .env (điền API keys + Telegram):
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

## Bước 7: Test chạy 1 bot (verify hoạt động)

```bash
cd /opt/trading/production
source venv/bin/activate

# Chạy lv4 thử (Ctrl+C để stop sau khi thấy OK)
BOT_MODE=testnet BOT_STRATEGY=lv4 PYTHONIOENCODING=utf-8 python3 -u -m live.bot
```

Nếu thấy:
```
=== Starting bot in MODE=testnet STRATEGY=lv4 ===
Time synced, offset=...
Loaded filters for 528 symbols
--- Reconciliation start ---
...
ENTER ... SHORT ...
Telegram delivered to @trading_v4 (...)
```

→ Bot chạy OK. `Ctrl+C` để stop.

## Bước 8: Chạy 3 bot 24/7 bằng systemd

Tạo service file cho mỗi bot:

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
# Status 3 bot
systemctl status trading-bot-lv4
systemctl status trading-bot-lv5
systemctl status trading-bot-lv6

# Log realtime
tail -f /opt/trading/production/live/bot_testnet_lv4.log
```

## Bước 9: Quản lý bot

```bash
# Stop bot
systemctl stop trading-bot-lv4

# Start bot
systemctl start trading-bot-lv4

# Restart bot
systemctl restart trading-bot-lv4

# Xem log realtime
journalctl -u trading-bot-lv4 -f

# Xem log 100 dòng cuối
journalctl -u trading-bot-lv4 -n 100

# Update code từ git
cd /opt/trading
git pull origin main
systemctl restart trading-bot-lv4 trading-bot-lv5 trading-bot-lv6

# Kiểm tra RAM
free -h

# Kiểm tra bot processes
ps aux | grep live.bot
```

## Bước 10: Backup state (QUAN TRỌNG)

VPS free có thể mất bất ngờ. Backup state DB định kỳ:

```bash
# Tạo cron backup hàng giờ
crontab -e
```

Thêm dòng:
```
0 * * * * tar czf /opt/trading/backup/state_$(date +\%Y\%m\%d_\%H).tar.gz /opt/trading/production/live/state_*.db 2>/dev/null
```

Hoặc backup lên GitHub (an toàn hơn):
```bash
# Script backup đơn giản
cat > /opt/trading/backup.sh << 'EOF'
#!/bin/bash
cd /opt/trading
git add production/live/state_*.db
git commit -m "backup: state $(date +'%Y-%m-%d %H:%M')" 2>/dev/null
git push origin main 2>/dev/null
EOF
chmod +x /opt/trading/backup.sh

# Cron mỗi 6 tiếng
crontab -e
# Thêm:
0 */6 * * * /opt/trading/backup.sh
```

## Khi lên LIVE

**KHÔNG nên chạy live trên VPS free.** Chuyển sang Hetzner:

1. Tạo Hetzner account (https://hetzner.cloud) — PayPal, không cần credit card
2. Tạo CX22 server (~$4.5/tháng, 4GB RAM, 2 vCPU)
3. Làm lại Bước 4-9 (nhưng đổi .env `BOT_MODE=live` + fill live keys)
4. Hoặc: backup state từ FreeVPS → restore trên Hetzner

## Troubleshooting

### Bot crash liên tục
```bash
# Xem log
journalctl -u trading-bot-lv4 -n 50
# Thường là: sai API key, sai .env, thiếu package
```

### RAM hết (OOM)
```bash
# Thêm swap 4GB
fallocate -l 4G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

### VPS bị shutdown (free tier rủi ro)
- Binance vẫn giữ SL/TP (algo orders tự đóng khi chạm giá)
- Khi VPS lên lại → bot tự reconcile (adopt positions, đặt lại SL nếu thiếu)
- Nếu VPS mất hẳn → tạo VPS mới, clone repo, restore state backup

### Không kết nối được Binance API
```bash
# Test kết nối
curl -s https://testnet.binancefuture.com/fapi/v1/time
# Nếu timeout → VPS bị chặn IP, liên hệ FreeVPS support
```

### pandas install lỗi
```bash
# ARM: dùng binary wheel
pip install --only-binary :all: pandas
# Nếu không có wheel: build từ source (chậm 5-10 phút)
pip install pandas
```

## Tóm tắt chi phí
- FreeVPS.it.com: **$0/tháng** (chỉ email, không credit card)
- Python + pandas + requests: **free**
- Git repo (GitHub): **free**
- Telegram Bot API: **free**
- **Tổng: $0/tháng**

## So sánh FreeVPS vs Oracle vs Hetzner

| | FreeVPS | Oracle Cloud | Hetzner |
|---|---|---|---|
| Giá | $0 | $0 | ~$4.5/tháng |
| Credit card | Không cần | Cần | PayPal OK |
| RAM | 4GB | 24GB (ARM) | 4GB |
| Uptime SLA | Không có | 99.9% | 99.9% |
| Rủi ro shutdown | Cao | Thấp | Rất thấp |
| Phù hợp | Testnet | Testnet | Live |
