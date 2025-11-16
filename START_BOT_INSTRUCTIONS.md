# 🚀 Start Bot Instructions for 159.65.170.253

## Quick Start (15 minutes)

Follow these steps to deploy and start your arbitrage trading bot on your DigitalOcean droplet.

---

## Step 1: Connect to Your Server

```bash
# From your local machine, SSH into the droplet
ssh root@159.65.170.253

# When prompted for password, enter:
# PolyMarket123$a
```

---

## Step 2: Install System Dependencies

```bash
# Update package lists
apt update

# Install Python 3.11 (if not already installed)
add-apt-repository ppa:deadsnakes/ppa -y
apt update
apt install -y python3.11 python3.11-venv python3.11-dev python3-pip

# Install required system packages
apt install -y \
    build-essential \
    git \
    tmux \
    sqlite3 \
    libssl-dev \
    libffi-dev \
    curl \
    wget \
    htop

# Verify Python installation
python3.11 --version
# Should show: Python 3.11.x
```

---

## Step 3: Create Bot Directory and Upload Files

### Option A: Using SCP (from your local machine)

```bash
# From your LOCAL machine (in a new terminal), navigate to the bot directory
cd /home/user/Live_PK_Bot

# Create directory on server
ssh root@159.65.170.253 "mkdir -p /opt/arbitrage-bot"

# Upload all files to the server
scp -r ./* root@159.65.170.253:/opt/arbitrage-bot/

# This will copy all bot files to the server
```

### Option B: Using Git (on the server)

```bash
# On the server
cd /opt
git clone <your-repo-url> arbitrage-bot
cd arbitrage-bot
```

---

## Step 4: Setup Python Environment

```bash
# Navigate to bot directory (on server)
cd /opt/arbitrage-bot

# Create virtual environment
python3.11 -m venv venv

# Activate virtual environment
source venv/bin/activate

# You should see (venv) in your prompt

# Upgrade pip
pip install --upgrade pip

# Install dependencies
pip install -r requirements.txt

# This may take 1-2 minutes
```

---

## Step 5: Create Required Directories

```bash
# Create log directory
mkdir -p /var/log/arbitrage-bot
chmod 755 /var/log/arbitrage-bot

# Create data directory
mkdir -p /var/lib/arbitrage-bot
chmod 755 /var/lib/arbitrage-bot

# Verify directories created
ls -ld /var/log/arbitrage-bot
ls -ld /var/lib/arbitrage-bot
```

---

## Step 6: Configure Environment

Your `.env` file is already configured with your credentials! Just ensure it has correct permissions:

```bash
# Secure the .env file
chmod 600 /opt/arbitrage-bot/.env

# Verify it exists
cat /opt/arbitrage-bot/.env | head -20
# You should see your Kalshi and Polymarket configuration
```

---

## Step 7: Test Run (Optional but Recommended)

Before running in background, do a quick test:

```bash
# Make sure you're in the bot directory with venv activated
cd /opt/arbitrage-bot
source venv/bin/activate

# Run the bot in foreground mode
python3.11 main.py

# You should see:
# ╔══════════════════════════════════════════════════════════════════════╗
# ║     High-Frequency Arbitrage Trading Bot                            ║
# ║     Status: SIMULATION MODE (No Real Trades)                        ║
# ╚══════════════════════════════════════════════════════════════════════╝
#
# 2025-XX-XX XX:XX:XX - INFO - Configuration loaded
# 2025-XX-XX XX:XX:XX - INFO - Initializing bot components...
# 2025-XX-XX XX:XX:XX - INFO - Kalshi client connected successfully
# 2025-XX-XX XX:XX:XX - INFO - Polymarket client connected successfully
# ...

# Watch for about 30 seconds to ensure no critical errors

# Press Ctrl+C to stop
```

**Expected behavior:**
- ✅ "Configuration loaded" message
- ✅ "Kalshi client connected successfully"
- ✅ "Polymarket client connected successfully"
- ✅ "Discovered X markets from Kalshi and Y markets from Polymarket"
- ✅ "Found Z market pairs"
- ✅ Status updates every 30 seconds

**If you see errors:**
- Check API credentials in `.env`
- Verify internet connectivity: `ping api.elections.kalshi.com`
- Check firewall: `ufw status`

---

## Step 8: Start Bot in Background

### Option A: Using Tmux (Recommended for Quick Setup)

```bash
# Make startup script executable
chmod +x /opt/arbitrage-bot/startup.sh

# Start bot in background using tmux
cd /opt/arbitrage-bot
./startup.sh --background

# You should see:
# [INFO] Starting bot in background (tmux)...
# [INFO] Creating tmux session: arbitrage-bot
# [INFO] Bot started successfully ✓
```

**Tmux Commands:**

```bash
# Attach to see bot running
tmux attach -t arbitrage-bot

# Detach (return to normal terminal)
# Press: Ctrl+B, then press D

# Check status
./startup.sh --status

# View logs
./startup.sh --logs

# Stop bot
./startup.sh --stop
```

### Option B: Using Systemd (Recommended for Production)

```bash
# Create systemd service file
cat > /etc/systemd/system/arbitrage-bot.service << 'EOF'
[Unit]
Description=Arbitrage Trading Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/arbitrage-bot
Environment="PATH=/opt/arbitrage-bot/venv/bin"
ExecStart=/opt/arbitrage-bot/venv/bin/python /opt/arbitrage-bot/main.py
Restart=always
RestartSec=10
StandardOutput=append:/var/log/arbitrage-bot/stdout.log
StandardError=append:/var/log/arbitrage-bot/stderr.log

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd
systemctl daemon-reload

# Enable service (start on boot)
systemctl enable arbitrage-bot

# Start service
systemctl start arbitrage-bot

# Check status
systemctl status arbitrage-bot

# You should see: "active (running)"
```

**Systemd Commands:**

```bash
# Start bot
systemctl start arbitrage-bot

# Stop bot
systemctl stop arbitrage-bot

# Restart bot
systemctl restart arbitrage-bot

# Check status
systemctl status arbitrage-bot

# View logs
journalctl -u arbitrage-bot -f

# View last 100 lines
journalctl -u arbitrage-bot -n 100
```

---

## Step 9: Verify Bot is Running

```bash
# Check process
ps aux | grep "python.*main.py"

# Should show python process running

# Check logs
tail -f /var/log/arbitrage-bot/trading_bot.log

# Should show ongoing activity, status updates every 30s

# Check database
sqlite3 /var/lib/arbitrage-bot/trading_bot.db "SELECT COUNT(*) FROM trades;"

# May show 0 initially (opportunities are rare)

# Press Ctrl+C to stop viewing logs
```

---

## Step 10: Monitor Bot Activity

### View Real-time Logs

```bash
# Main bot log
tail -f /var/log/arbitrage-bot/trading_bot.log

# Trade log (JSON format)
tail -f /var/log/arbitrage-bot/trades.jsonl

# If using systemd
journalctl -u arbitrage-bot -f
```

### Check for Arbitrage Opportunities

```bash
# Query database for trades
sqlite3 /var/lib/arbitrage-bot/trading_bot.db

# Inside SQLite:
SELECT COUNT(*) FROM trades;
SELECT * FROM trades ORDER BY timestamp DESC LIMIT 5;
SELECT SUM(expected_profit) as total_profit FROM trades;

# Exit SQLite:
.exit
```

### Monitor System Resources

```bash
# CPU and memory usage
htop

# Look for python process
# Press F3, type "python", press Enter

# Disk usage
df -h

# Network connections
netstat -tupln | grep python
```

---

## Common Commands Reference

### Start/Stop Bot

```bash
# If using tmux
cd /opt/arbitrage-bot
./startup.sh --background  # Start
./startup.sh --stop        # Stop
./startup.sh --status      # Check status

# If using systemd
systemctl start arbitrage-bot   # Start
systemctl stop arbitrage-bot    # Stop
systemctl status arbitrage-bot  # Check status
```

### View Logs

```bash
# Main log
tail -f /var/log/arbitrage-bot/trading_bot.log

# Trade log
tail -f /var/log/arbitrage-bot/trades.jsonl

# System log (if using systemd)
journalctl -u arbitrage-bot -f
```

### Attach to Running Bot (if using tmux)

```bash
# Attach to see live output
tmux attach -t arbitrage-bot

# Detach without stopping: Ctrl+B, then D
```

---

## Troubleshooting

### Bot Won't Start

```bash
# Check Python version
python3.11 --version

# Check virtual environment
source /opt/arbitrage-bot/venv/bin/activate
which python

# Check dependencies
pip list | grep -E "aiohttp|websockets|pydantic"

# Check .env file
cat /opt/arbitrage-bot/.env | grep -E "KALSHI|POLYMARKET"
```

### WebSocket Connection Errors

```bash
# Test network connectivity
ping -c 3 api.elections.kalshi.com
ping -c 3 gamma-api.polymarket.com

# Check DNS
nslookup api.elections.kalshi.com

# Check firewall
ufw status
# If active, ensure outgoing connections allowed
```

### No Trades Detected

This is **normal**! Arbitrage opportunities are rare. The bot is working if you see:
- Markets discovered
- WebSocket connections active
- Status updates every 30 seconds
- No critical errors in logs

### High CPU/Memory Usage

```bash
# Check resource usage
htop

# If too high, reduce scan frequency
nano /opt/arbitrage-bot/.env
# Change: UPDATE_INTERVAL=0.5

# Restart bot
systemctl restart arbitrage-bot
```

### Database Locked

```bash
# Ensure only one instance running
ps aux | grep "python.*main.py"

# Kill duplicates if found
pkill -f "python main.py"

# Restart
systemctl start arbitrage-bot
```

---

## Expected Performance

### Normal Operation

- **CPU Usage**: 2-5% average
- **Memory**: 50-100 MB
- **Network**: 1-5 MB/hour
- **Log Size**: ~1 MB/day
- **DB Size**: ~500 KB/day

### Status Updates (every 30 seconds)

```
================================================================================
Bot Status - Uptime: 01:23:45
--------------------------------------------------------------------------------
Markets Tracked: 150
Opportunities Detected: 12
Trades Simulated: 3
Total Simulated Profit: $5.25
Kalshi Connected: ✓
Polymarket Connected: ✓
================================================================================
```

### When Arbitrage Detected

```
SIMULATED TRADE: cross-platform |
Buy yes on kalshi@0.4500 | Sell yes on polymarket@0.5200 |
Profit: $7.00 (15.56%)
```

---

## Security Recommendations

### Firewall Setup

```bash
# Enable firewall
ufw enable

# Allow SSH
ufw allow 22/tcp

# Deny all other incoming
ufw default deny incoming
ufw default allow outgoing

# Check status
ufw status
```

### SSH Hardening (Optional)

```bash
# Disable password authentication (use SSH keys only)
nano /etc/ssh/sshd_config

# Set:
# PasswordAuthentication no
# PermitRootLogin no

# Restart SSH
systemctl restart sshd
```

### Regular Backups

```bash
# Backup database daily
crontab -e

# Add this line:
0 2 * * * cp /var/lib/arbitrage-bot/trading_bot.db /var/backups/trading_bot_$(date +\%Y\%m\%d).db

# Keep last 7 days only:
0 3 * * 0 find /var/backups -name "trading_bot_*.db" -mtime +7 -delete
```

---

## Maintenance

### Daily

```bash
# Check status
systemctl status arbitrage-bot

# Review logs for errors
tail -100 /var/log/arbitrage-bot/trading_bot.log | grep ERROR
```

### Weekly

```bash
# Check disk space
df -h

# Check database size
ls -lh /var/lib/arbitrage-bot/trading_bot.db

# Review simulated profits
sqlite3 /var/lib/arbitrage-bot/trading_bot.db "SELECT SUM(expected_profit) FROM trades;"
```

### Monthly

```bash
# Update dependencies
cd /opt/arbitrage-bot
source venv/bin/activate
pip install --upgrade -r requirements.txt

# Restart bot
systemctl restart arbitrage-bot
```

---

## Support

### Documentation
- `README.md` - General documentation
- `PRODUCTION_SETUP.md` - Detailed deployment guide
- `FIXES_SUMMARY.md` - All improvements made
- `CODE_REVIEW.md` - Technical audit details

### Logs Location
- Main: `/var/log/arbitrage-bot/trading_bot.log`
- Trades: `/var/log/arbitrage-bot/trades.jsonl`
- System: `journalctl -u arbitrage-bot` (if using systemd)

### Database Location
- `/var/lib/arbitrage-bot/trading_bot.db`

---

## Quick Reference Card

```bash
# START BOT
cd /opt/arbitrage-bot && ./startup.sh --background

# STOP BOT
./startup.sh --stop

# CHECK STATUS
./startup.sh --status

# VIEW LOGS
tail -f /var/log/arbitrage-bot/trading_bot.log

# ATTACH TO BOT (tmux)
tmux attach -t arbitrage-bot

# DETACH FROM BOT
Ctrl+B, then D

# QUERY DATABASE
sqlite3 /var/lib/arbitrage-bot/trading_bot.db

# RESTART BOT (systemd)
systemctl restart arbitrage-bot

# CHECK SYSTEM RESOURCES
htop
```

---

## Success Checklist

- [ ] Connected to server (159.65.170.253)
- [ ] Python 3.11 installed
- [ ] System dependencies installed
- [ ] Bot files uploaded to /opt/arbitrage-bot
- [ ] Virtual environment created
- [ ] Dependencies installed
- [ ] Directories created (/var/log and /var/lib)
- [ ] .env file configured and secured
- [ ] Test run successful
- [ ] Bot started in background
- [ ] Status check shows bot running
- [ ] Logs show markets discovered
- [ ] No critical errors in logs
- [ ] Database file created

---

**Your bot is now running! 🚀**

It will continuously monitor Kalshi and Polymarket for arbitrage opportunities and log all detected trades. Remember, this is **SIMULATION MODE** - no real trades are executed.

**Monitor logs for the first hour to ensure stable operation.**

For any issues, refer to the Troubleshooting section or check `PRODUCTION_SETUP.md` for detailed guidance.
