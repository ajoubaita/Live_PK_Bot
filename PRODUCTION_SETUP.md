# Production Deployment Guide
## Deploying to Cloud Server (159.65.170.253)

This guide provides step-by-step instructions for deploying the arbitrage trading bot to a production Linux server.

---

## 📋 Prerequisites

### Server Requirements
- **OS**: Ubuntu 20.04+ or Debian 11+
- **CPU**: 2+ cores recommended
- **RAM**: 2GB+ minimum, 4GB recommended
- **Disk**: 20GB+ available space
- **Network**: Stable internet connection with low latency

### Access Requirements
- SSH access to server
- Sudo privileges
- Server IP: `159.65.170.253`

---

## 🚀 Deployment Steps

### Step 1: Connect to Server

```bash
# SSH into your server
ssh root@159.65.170.253

# Or if using a non-root user
ssh your-user@159.65.170.253
```

### Step 2: System Update

```bash
# Update package lists
sudo apt update

# Upgrade existing packages
sudo apt upgrade -y

# Install essential build tools
sudo apt install -y build-essential software-properties-common
```

### Step 3: Install Python 3.11+

```bash
# Add deadsnakes PPA for latest Python
sudo add-apt-repository ppa:deadsnakes/ppa -y
sudo apt update

# Install Python 3.11
sudo apt install -y python3.11 python3.11-venv python3.11-dev

# Install pip
sudo apt install -y python3-pip

# Verify installation
python3.11 --version
```

### Step 4: Install System Dependencies

```bash
# Install required system packages
sudo apt install -y \
    git \
    tmux \
    sqlite3 \
    libssl-dev \
    libffi-dev \
    curl \
    wget \
    htop \
    net-tools

# Install supervisor (optional, for daemon mode)
sudo apt install -y supervisor
```

### Step 5: Create Bot User (Recommended)

```bash
# Create dedicated user for the bot
sudo useradd -m -s /bin/bash arbitrage-bot

# Add to necessary groups
sudo usermod -aG sudo arbitrage-bot

# Switch to bot user
sudo su - arbitrage-bot
```

### Step 6: Clone Repository

```bash
# Create application directory
cd /opt
sudo mkdir -p /opt/arbitrage-bot
sudo chown arbitrage-bot:arbitrage-bot /opt/arbitrage-bot

# Clone repository
cd /opt/arbitrage-bot
git clone <your-repo-url> .

# Or upload files via SCP from local machine:
# scp -r ./Live_PK_Bot/* arbitrage-bot@159.65.170.253:/opt/arbitrage-bot/
```

### Step 7: Setup Python Environment

```bash
# Navigate to bot directory
cd /opt/arbitrage-bot

# Create virtual environment
python3.11 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install dependencies
pip install -r requirements.txt

# Verify installation
pip list
```

### Step 8: Configure Environment

```bash
# Copy production environment template
cp .env.production .env

# Edit configuration file
nano .env
```

**Required configurations in `.env`:**

```env
# API Credentials
KALSHI_EMAIL=your_email@example.com
KALSHI_PASSWORD=your_password

POLYMARKET_API_KEY=your_api_key  # If you have one

# Logging
LOG_FILE=/var/log/arbitrage-bot/trading_bot.log
TRADE_LOG_FILE=/var/log/arbitrage-bot/trades.jsonl

# Database
DB_FILE=/var/lib/arbitrage-bot/trading_bot.db

# Performance
LOG_LEVEL=INFO
MIN_PROFIT_THRESHOLD=0.01
UPDATE_INTERVAL=0.1
```

**Secure the .env file:**

```bash
chmod 600 .env
```

### Step 9: Create Data Directories

```bash
# Create log directory
sudo mkdir -p /var/log/arbitrage-bot
sudo chown -R arbitrage-bot:arbitrage-bot /var/log/arbitrage-bot

# Create data directory
sudo mkdir -p /var/lib/arbitrage-bot
sudo chown -R arbitrage-bot:arbitrage-bot /var/lib/arbitrage-bot

# Verify permissions
ls -ld /var/log/arbitrage-bot
ls -ld /var/lib/arbitrage-bot
```

### Step 10: Test Run

```bash
# Activate virtual environment
cd /opt/arbitrage-bot
source venv/bin/activate

# Test run (Ctrl+C to stop)
python main.py
```

**Expected output:**
```
╔══════════════════════════════════════════════════════════════════════╗
║     High-Frequency Arbitrage Trading Bot                            ║
║     Status: SIMULATION MODE (No Real Trades)                        ║
╚══════════════════════════════════════════════════════════════════════╝

2025-01-15 10:30:45 - INFO - Configuration loaded
2025-01-15 10:30:45 - INFO - Initializing bot components...
2025-01-15 10:30:46 - INFO - Kalshi client connected successfully
2025-01-15 10:30:46 - INFO - Polymarket client connected successfully
...
```

Press `Ctrl+C` to stop and verify everything works.

---

## 🔄 Production Launch Options

### Option A: Tmux Background Session (Recommended for Quick Setup)

```bash
# Make startup script executable
chmod +x startup.sh

# Start in background
./startup.sh --background

# Verify status
./startup.sh --status

# View logs
./startup.sh --logs

# Attach to session
tmux attach -t arbitrage-bot

# Detach: Press Ctrl+B then D
```

### Option B: Systemd Service (Recommended for Production)

Create systemd service file:

```bash
sudo nano /etc/systemd/system/arbitrage-bot.service
```

Add this content:

```ini
[Unit]
Description=Arbitrage Trading Bot
After=network.target

[Service]
Type=simple
User=arbitrage-bot
Group=arbitrage-bot
WorkingDirectory=/opt/arbitrage-bot
Environment="PATH=/opt/arbitrage-bot/venv/bin"
ExecStart=/opt/arbitrage-bot/venv/bin/python /opt/arbitrage-bot/main.py
Restart=always
RestartSec=10
StandardOutput=append:/var/log/arbitrage-bot/stdout.log
StandardError=append:/var/log/arbitrage-bot/stderr.log

[Install]
WantedBy=multi-user.target
```

Enable and start service:

```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable service (start on boot)
sudo systemctl enable arbitrage-bot

# Start service
sudo systemctl start arbitrage-bot

# Check status
sudo systemctl status arbitrage-bot

# View logs
sudo journalctl -u arbitrage-bot -f

# Stop service
sudo systemctl stop arbitrage-bot

# Restart service
sudo systemctl restart arbitrage-bot
```

### Option C: Supervisor (Alternative Process Manager)

Create supervisor config:

```bash
sudo nano /etc/supervisor/conf.d/arbitrage-bot.conf
```

Add configuration:

```ini
[program:arbitrage-bot]
command=/opt/arbitrage-bot/venv/bin/python /opt/arbitrage-bot/main.py
directory=/opt/arbitrage-bot
user=arbitrage-bot
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/var/log/arbitrage-bot/supervisor.log
stdout_logfile_maxbytes=50MB
stdout_logfile_backups=10
environment=PATH="/opt/arbitrage-bot/venv/bin"
```

Start with supervisor:

```bash
# Update supervisor
sudo supervisorctl reread
sudo supervisorctl update

# Start bot
sudo supervisorctl start arbitrage-bot

# Check status
sudo supervisorctl status

# Stop bot
sudo supervisorctl stop arbitrage-bot

# Restart bot
sudo supervisorctl restart arbitrage-bot

# View logs
sudo supervisorctl tail -f arbitrage-bot
```

---

## 📊 Monitoring & Maintenance

### Check Bot Status

```bash
# If using tmux
tmux ls
tmux attach -t arbitrage-bot

# If using systemd
sudo systemctl status arbitrage-bot

# If using supervisor
sudo supervisorctl status arbitrage-bot
```

### View Logs

```bash
# Real-time logs
tail -f /var/log/arbitrage-bot/trading_bot.log

# Trade logs
tail -f /var/log/arbitrage-bot/trades.jsonl

# Last 100 lines
tail -n 100 /var/log/arbitrage-bot/trading_bot.log

# Search for errors
grep "ERROR" /var/log/arbitrage-bot/trading_bot.log
```

### Monitor System Resources

```bash
# CPU and Memory usage
htop

# Disk usage
df -h

# Network connections
netstat -tupln | grep python

# Process info
ps aux | grep python
```

### Database Queries

```bash
# Connect to database
sqlite3 /var/lib/arbitrage-bot/trading_bot.db

# View recent trades
SELECT * FROM trades ORDER BY timestamp DESC LIMIT 10;

# Calculate total profit
SELECT SUM(expected_profit) as total FROM trades;

# Count trades
SELECT COUNT(*) FROM trades;

# Exit
.exit
```

---

## 🔒 Security Hardening

### Firewall Configuration

```bash
# Enable UFW firewall
sudo ufw enable

# Allow SSH
sudo ufw allow 22/tcp

# Deny all other incoming
sudo ufw default deny incoming
sudo ufw default allow outgoing

# Check status
sudo ufw status
```

### SSH Hardening

```bash
# Edit SSH config
sudo nano /etc/ssh/sshd_config

# Disable password authentication (use SSH keys only)
# PasswordAuthentication no
# PermitRootLogin no

# Restart SSH
sudo systemctl restart sshd
```

### Fail2Ban (Brute Force Protection)

```bash
# Install fail2ban
sudo apt install -y fail2ban

# Enable and start
sudo systemctl enable fail2ban
sudo systemctl start fail2ban
```

### Automatic Security Updates

```bash
# Install unattended-upgrades
sudo apt install -y unattended-upgrades

# Configure
sudo dpkg-reconfigure -plow unattended-upgrades
```

---

## 🔄 Update Procedure

### Update Bot Code

```bash
# Stop bot
./startup.sh --stop  # or sudo systemctl stop arbitrage-bot

# Pull latest code
cd /opt/arbitrage-bot
git pull origin main

# Update dependencies
source venv/bin/activate
pip install --upgrade -r requirements.txt

# Start bot
./startup.sh --background  # or sudo systemctl start arbitrage-bot
```

### Update Python Dependencies

```bash
cd /opt/arbitrage-bot
source venv/bin/activate
pip install --upgrade -r requirements.txt
```

---

## 💾 Backup Strategy

### Database Backup

```bash
# Create backup
sqlite3 /var/lib/arbitrage-bot/trading_bot.db ".backup '/var/backups/trading_bot_$(date +%Y%m%d).db'"

# Or use cp
cp /var/lib/arbitrage-bot/trading_bot.db "/var/backups/trading_bot_$(date +%Y%m%d).db"
```

### Automated Backups (Crontab)

```bash
# Edit crontab
crontab -e

# Add daily backup at 2 AM
0 2 * * * sqlite3 /var/lib/arbitrage-bot/trading_bot.db ".backup '/var/backups/trading_bot_$(date +\%Y\%m\%d).db'"

# Add weekly cleanup (keep last 7 days)
0 3 * * 0 find /var/backups -name "trading_bot_*.db" -mtime +7 -delete
```

---

## 🐛 Troubleshooting

### Bot Won't Start

```bash
# Check Python version
python3 --version

# Check virtual environment
source venv/bin/activate
which python

# Check .env file
cat .env | grep -v "PASSWORD\|KEY\|SECRET"

# Check dependencies
pip list | grep -E "aiohttp|websockets|pydantic"

# Check logs
tail -50 /var/log/arbitrage-bot/trading_bot.log
```

### WebSocket Connection Issues

```bash
# Test network connectivity
ping -c 3 api.elections.kalshi.com
ping -c 3 gamma-api.polymarket.com

# Check firewall
sudo ufw status

# Check DNS
nslookup api.elections.kalshi.com

# Test WebSocket (install websocat)
# sudo apt install websocat
# websocat wss://api.elections.kalshi.com/trade-api/ws/v2
```

### High CPU/Memory Usage

```bash
# Check resource usage
htop

# Reduce scan frequency in .env
# UPDATE_INTERVAL=0.5  # Slower scanning

# Limit markets tracked
# MAX_MARKETS_PER_PLATFORM=25

# Restart bot
sudo systemctl restart arbitrage-bot
```

### Database Lock Errors

```bash
# Ensure only one instance running
ps aux | grep "python main.py"

# Kill duplicate processes
pkill -f "python main.py"

# Check database integrity
sqlite3 /var/lib/arbitrage-bot/trading_bot.db "PRAGMA integrity_check;"
```

### Disk Space Full

```bash
# Check disk usage
df -h

# Find large files
du -sh /var/log/arbitrage-bot/*
du -sh /var/lib/arbitrage-bot/*

# Rotate logs manually
mv /var/log/arbitrage-bot/trading_bot.log "/var/log/arbitrage-bot/trading_bot.log.$(date +%Y%m%d)"

# Clean old logs
find /var/log/arbitrage-bot -name "*.log.*" -mtime +7 -delete
```

---

## 📈 Performance Optimization

### For High-Frequency Trading

```bash
# Use uvloop (already in requirements.txt)
# Ensure it's installed
pip install uvloop

# Increase file limits
sudo nano /etc/security/limits.conf
# Add:
# arbitrage-bot soft nofile 65536
# arbitrage-bot hard nofile 65536

# Optimize network stack
sudo nano /etc/sysctl.conf
# Add:
# net.ipv4.tcp_fin_timeout = 15
# net.core.rmem_max = 16777216
# net.core.wmem_max = 16777216

# Apply changes
sudo sysctl -p
```

---

## ✅ Deployment Checklist

- [ ] Server provisioned and accessible
- [ ] SSH access configured
- [ ] Python 3.11+ installed
- [ ] System dependencies installed
- [ ] Bot user created
- [ ] Repository cloned to /opt/arbitrage-bot
- [ ] Virtual environment created
- [ ] Dependencies installed
- [ ] .env file configured with credentials
- [ ] .env file permissions set (chmod 600)
- [ ] Log directory created (/var/log/arbitrage-bot)
- [ ] Data directory created (/var/lib/arbitrage-bot)
- [ ] Bot tested in foreground mode
- [ ] Production launch method configured (tmux/systemd/supervisor)
- [ ] Bot running and stable
- [ ] Logs being written correctly
- [ ] Firewall configured
- [ ] SSH hardened
- [ ] Fail2ban installed
- [ ] Backup cron job configured
- [ ] Monitoring setup
- [ ] Documentation reviewed

---

## 📞 Support & Maintenance

### Daily Tasks
- Check bot status: `./startup.sh --status`
- Review logs for errors
- Verify trades are being logged

### Weekly Tasks
- Review total simulated profit
- Check disk space
- Review and rotate logs if needed
- Update dependencies if needed

### Monthly Tasks
- Review and optimize configuration
- Backup database
- Update bot code if new version available
- Security audit

---

## 🎯 Quick Reference

```bash
# Start bot
./startup.sh --background

# Stop bot
./startup.sh --stop

# Check status
./startup.sh --status

# View logs
./startup.sh --logs

# Restart bot (systemd)
sudo systemctl restart arbitrage-bot

# View database
sqlite3 /var/lib/arbitrage-bot/trading_bot.db

# Backup database
cp /var/lib/arbitrage-bot/trading_bot.db ~/backup.db
```

---

**Your bot should now be running in production! 🚀**

For issues, check logs and refer to the Troubleshooting section.
