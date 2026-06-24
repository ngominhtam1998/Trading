# Hướng dẫn setup Oracle Cloud Always Free VPS cho Trading Bot

## Tổng quan
- Oracle Cloud cho phép tạo VPS miễn phí 24/7, không hết hạn
- Cấu hình: 4 OCPU ARM + 24GB RAM (dư sức chạy 3 bot)
- Chi phí: $0/tháng (cần credit card verify, không charge)

## Bước 1: Tạo tài khoản Oracle Cloud

1. Vào https://cloud.oracle.com → Sign Up for Free Tier
2. Điền thông tin:
   - Email, password
   - Tên, số điện thoại
   - **Credit card** (để verify, KHÔNG charge)
3. **QUAN TRỌNG - Chọn Home Region:**
   - Region không đổi được sau khi tạo
   - Chọn **Singapore** hoặc **Tokyo** (gần Binance server, latency thấp)
   - Nếu không có Singapore/Tokyo, chọn **Mumbai** hoặc **Seoul**
4. Chờ email confirm (5-10 phút)
5. Đăng nhập vào Oracle Cloud Console

## Bước 2: Tạo VM Instance (ARM, Always Free)

1. Vào **Compute → Instances → Create Instance**
2. Cấu hình:
   - **Name:** trading-bot
   - **Image:** Canonical Ubuntu 22.04 (click "Change image" → Ubuntu 22.04)
   - **Shape:** Click "Change shape" → Ampere → **VM.Standard.A1.Flex**
     - OCPU: **4**
     - Memory: **24 GB**
     - (Đây là max Always Free)
   - **Networking:** để default (tạo VPC mới tự động)
     - Check "Assign a public IPv4 address" (PHẢI có)
   - **SSH Keys:** QUAN TRỌNG!
     - Chọn "Generate a key pair"
     - **Download PRIVATE KEY** (.key) → lưu cẩn thận, không mất!
     - **Download PUBLIC KEY** (.pub)
     - Hoặc dùng SSH key có sẵn nếu bạn đã có
3. Click **Create**
4. Chờ 2-5 phút, instance sẽ ở trạng thái RUNNING
5. **Ghi lại Public IP** (ví dụ: 129.150.xx.xx)

## Bước 3: Kết nối SSH

### Trên Windows (PowerShell)
```powershell
# Di chuyển private key vào thư mục an toàn
# Đổi quyền (Windows)
icacls .\ssh-key-*.key /inheritance:r
icacls .\ssh-key-*.key /grant:r "$env:USERNAME:(R)"

# Kết nối (đổi IP và tên key file)
ssh -i .\ssh-key-2024.key ubuntu@129.150.xx.xx
```

### Trên Mac/Linux
```bash
chmod 400 ssh-key-*.key
ssh -i ssh-key-*.key ubuntu@129.150.xx.xx
```

### Lỗi "Permission denied"?
```powershell
# Windows: đảm bảo file key chỉ có quyền read cho user hiện tại
icacls .\ssh-key-*.key /inheritance:r /grant:r "$env:USERNAME:R"
```

## Bước 4: Cài đặt Python + dependencies

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Cài Python 3.11+ và tools
sudo apt install -y python3 python3-pip python3-venv git tmux

# Kiểm tra Python version
python3 --version  # cần >= 3.10

# Tạo thư mục bot
mkdir -p ~/trading
cd ~/trading

# Clone repo
git clone https://github.com/ngominhtam1998/Trading.git .
```

## Bước 5: Cài Python dependencies

```bash
cd ~/trading

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
cd ~/trading/production/live

# Tạo .env từ example
cp .env.example .env

# Edit .env (dùng nano)
nano .env
```

Nội dung .env (điền API keys + Telegram):
```
BOT_MODE=testnet
BOT_STRATEGY=v15

BINANCE_TESTNET_KEY_LV4=<key_lv4>
BINANCE_TESTNET_SECRET_LV4=<secret_lv4>
BINANCE_TESTNET_KEY_LV5=<key_lv5>
BINANCE_TESTNET_SECRET_LV5=<secret_lv5>
BINANCE_TESTNET_KEY_LV6=<key_lv6>
BINANCE_TESTNET_SECRET_LV6=<secret_lv6>

TELEGRAM_BOT_TOKEN=<bot_token>
TELEGRAM_CHAT_LV4=@trading_v4
TELEGRAM_CHAT_LV5=@trading_v5
TELEGRAM_CHAT_LV6=@trading_v6
```

Lưu: Ctrl+O → Enter → Ctrl+X

## Bước 7: Mở port (không bắt buộc, chỉ cần nếu dùng webhook)

```bash
# Oracle Cloud: cần mở port trong Security List
# 1. Vào Oracle Console → Networking → Virtual Cloud Networks
# 2. Click VCN → Security Lists → Default Security List
# 3. Add Ingress Rule: Source 0.0.0.0/0, IP Protocol TCP, Dest Port 22 (SSH)

# Bot KHÔNG cần mở port thêm (chỉ gọi API ra ngoài, không nhận incoming)
# Chỉ cần SSH (port 22) là đủ
```

## Bước 8: Chạy 3 bot bằng tmux (24/7)

```bash
cd ~/trading/production

# Tạo 3 session tmux riêng (mỗi bot 1 session)
# Bot LV4
tmux new-session -d -s bot_lv4 'cd ~/trading/production && source venv/bin/activate && BOT_MODE=testnet BOT_STRATEGY=lv4 PYTHONIOENCODING=utf-8 python3 -u -m live.bot 2>&1 | tee -a ~/trading/production/live/bot_testnet_lv4.log'

# Bot LV5
tmux new-session -d -s bot_lv5 'cd ~/trading/production && source venv/bin/activate && BOT_MODE=testnet BOT_STRATEGY=lv5 PYTHONIOENCODING=utf-8 python3 -u -m live.bot 2>&1 | tee -a ~/trading/production/live/bot_testnet_lv5.log'

# Bot LV6
tmux new-session -d -s bot_lv6 'cd ~/trading/production && source venv/bin/activate && BOT_MODE=testnet BOT_STRATEGY=lv6 PYTHONIOENCODING=utf-8 python3 -u -m live.bot 2>&1 | tee -a ~/trading/production/live/bot_testnet_lv6.log'

# Kiểm tra đang chạy
tmux ls
# Expected: bot_lv4, bot_lv5, bot_lv6

# Xem log bot LV4
tmux attach -t bot_lv4
# Thoát khỏi tmux (KHÔNG kill): Ctrl+B rồi D

# Xem log realtime
tail -f ~/trading/production/live/bot_testnet_lv4.log
```

## Bước 9: Auto-restart khi VPS reboot (systemd)

Tạo service file cho mỗi bot:

```bash
# Bot LV4
sudo tee /etc/systemd/system/trading-bot-lv4.service > /dev/null << 'EOF'
[Unit]
Description=Trading Bot LV4
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/trading/production
Environment=BOT_MODE=testnet
Environment=BOT_STRATEGY=lv4
Environment=PYTHONIOENCODING=utf-8
ExecStart=/home/ubuntu/trading/production/venv/bin/python3 -u -m live.bot
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF

# Bot LV5
sudo tee /etc/systemd/system/trading-bot-lv5.service > /dev/null << 'EOF'
[Unit]
Description=Trading Bot LV5
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/trading/production
Environment=BOT_MODE=testnet
Environment=BOT_STRATEGY=lv5
Environment=PYTHONIOENCODING=utf-8
ExecStart=/home/ubuntu/trading/production/venv/bin/python3 -u -m live.bot
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF

# Bot LV6
sudo tee /etc/systemd/system/trading-bot-lv6.service > /dev/null << 'EOF'
[Unit]
Description=Trading Bot LV6
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/trading/production
Environment=BOT_MODE=testnet
Environment=BOT_STRATEGY=lv6
Environment=PYTHONIOENCODING=utf-8
ExecStart=/home/ubuntu/trading/production/venv/bin/python3 -u -m live.bot
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF

# Enable + start
sudo systemctl daemon-reload
sudo systemctl enable trading-bot-lv4 trading-bot-lv5 trading-bot-lv6
sudo systemctl start trading-bot-lv4 trading-bot-lv5 trading-bot-lv6

# Kiểm tra status
sudo systemctl status trading-bot-lv4
sudo systemctl status trading-bot-lv5
sudo systemctl status trading-bot-lv6

# Xem log
sudo journalctl -u trading-bot-lv4 -f
```

## Bước 10: Quản lý bot

```bash
# Stop bot
sudo systemctl stop trading-bot-lv4

# Start bot
sudo systemctl start trading-bot-lv4

# Restart bot
sudo systemctl restart trading-bot-lv4

# Xem log realtime
sudo journalctl -u trading-bot-lv4 -f

# Xem log 100 dòng cuối
sudo journalctl -u trading-bot-lv4 -n 100

# Update code từ git
cd ~/trading
git pull origin main
sudo systemctl restart trading-bot-lv4 trading-bot-lv5 trading-bot-lv6
```

## Bước 11: Monitor

```bash
# RAM usage
free -h

# CPU usage
top -o %CPU

# Disk usage
df -h

# Bot processes
ps aux | grep live.bot
```

## Troubleshooting

### Lỗi: "No Always Free shape available"
- Oracle hay hết resource ARM ở region phổ biến
- Thử lại vào lúc khác (giờ thấp điểm)
- Hoặc đổi region (Singapore, Tokyo, Mumbai, Seoul)
- Hoặc dùng shape x86 micro (1GB RAM, 2 instances) → chạy 1 bot/instance

### Lỗi: "Permission denied (publickey)"
```bash
# Kiểm tra quyền file key
chmod 400 ~/ssh-key-*.key
# Kết nối lại
ssh -i ~/ssh-key-*.key ubuntu@<IP>
```

### Lỗi: Python pandas install chậm trên ARM
```bash
# Cài binary wheel (nhanh hơn)
pip install --only-binary :all: pandas
# Nếu không có wheel, build từ source (chậm 5-10 phút)
pip install pandas
```

### Lỗi: Bot crash, không restart
```bash
# Kiểm tra systemd
sudo systemctl status trading-bot-lv4
# Restart=always trong service file → tự restart sau 30s
```

### Lỗi: RAM hết (OOM)
```bash
# Thêm swap 4GB
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

## Khi lên LIVE

1. Đổi `BOT_MODE=live` trong .env
2. Fill `BINANCE_LIVE_KEY_LV4` etc trong .env
3. Restart bots:
```bash
sudo systemctl restart trading-bot-lv4 trading-bot-lv5 trading-bot-lv6
```
4. Monitor sát ngày đầu tiên

## Tóm tắt chi phí
- Oracle Cloud Always Free: **$0/tháng**
- Python + pandas + requests: **free**
- Git repo (GitHub): **free**
- Telegram Bot API: **free**
- **Tổng: $0/tháng**
