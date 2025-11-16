# Deployment Guide

This guide covers deploying the arbitrage trading bot to a cloud server for 24/7 operation.

## 🌐 Cloud Platform Options

### Option 1: AWS EC2 (Recommended)

**Advantages:**
- Low latency to US-based APIs
- Reliable uptime
- Scalable resources
- Spot instances for cost savings

**Recommended Instance:**
- Type: `t3.small` or `t3.micro`
- Region: `us-east-1` (close to API endpoints)
- OS: Ubuntu 22.04 LTS

### Option 2: DigitalOcean

**Advantages:**
- Simple setup
- Predictable pricing
- Good documentation

**Recommended Droplet:**
- Size: Basic ($6/month)
- Region: New York
- OS: Ubuntu 22.04 LTS

### Option 3: Google Cloud Platform

**Advantages:**
- Generous free tier
- Global network

**Recommended Instance:**
- Type: `e2-micro`
- Region: `us-east1`
- OS: Ubuntu 22.04 LTS

## 🚀 Deployment Steps

### 1. Provision Server

**AWS EC2:**
```bash
# Launch instance via AWS Console or CLI
aws ec2 run-instances \
  --image-id ami-0557a15b87f6559cf \
  --instance-type t3.small \
  --key-name your-key \
  --security-group-ids sg-xxxxx
```

**DigitalOcean:**
```bash
# Create droplet via web interface or doctl
doctl compute droplet create trading-bot \
  --size s-1vcpu-1gb \
  --image ubuntu-22-04-x64 \
  --region nyc1 \
  --ssh-keys your-key-id
```

### 2. Connect to Server

```bash
ssh ubuntu@your-server-ip
```

### 3. Install Dependencies

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python 3.11
sudo apt install -y python3.11 python3.11-venv python3-pip

# Install system dependencies
sudo apt install -y git build-essential libssl-dev libffi-dev

# Install supervisor (for process management)
sudo apt install -y supervisor

# Install SQLite (usually pre-installed)
sudo apt install -y sqlite3
```

### 4. Clone Repository

```bash
# Create app directory
mkdir -p /opt/trading-bot
cd /opt/trading-bot

# Clone repo (replace with your repo URL)
git clone <your-repo-url> .

# Or upload files via SCP
# scp -r ./Live_PK_Bot ubuntu@your-server-ip:/opt/trading-bot/
```

### 5. Setup Python Environment

```bash
# Create virtual environment
python3.11 -m venv venv

# Activate environment
source venv/bin/activate

# Install requirements
pip install --upgrade pip
pip install -r requirements.txt
```

### 6. Configure Environment

```bash
# Create .env file
cp .env.example .env

# Edit with your credentials
nano .env
```

Add your configuration:
```env
KALSHI_EMAIL=your_email@example.com
KALSHI_PASSWORD=your_secure_password
# ... other settings
```

**Security:** Ensure `.env` has restricted permissions:
```bash
chmod 600 .env
```

### 7. Test Run

```bash
# Test the bot manually first
python main.py
```

Watch for successful startup and connection. Press Ctrl+C to stop.

### 8. Setup Supervisor (Process Manager)

Create supervisor config:
```bash
sudo nano /etc/supervisor/conf.d/trading-bot.conf
```

Add this configuration:
```ini
[program:trading-bot]
command=/opt/trading-bot/venv/bin/python /opt/trading-bot/main.py
directory=/opt/trading-bot
user=ubuntu
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/var/log/trading-bot/output.log
stdout_logfile_maxbytes=50MB
stdout_logfile_backups=10
environment=PATH="/opt/trading-bot/venv/bin"
```

Create log directory:
```bash
sudo mkdir -p /var/log/trading-bot
sudo chown ubuntu:ubuntu /var/log/trading-bot
```

Update supervisor:
```bash
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start trading-bot
```

### 9. Verify Deployment

```bash
# Check status
sudo supervisorctl status trading-bot

# View logs
tail -f /var/log/trading-bot/output.log
tail -f /opt/trading-bot/trading_bot.log
tail -f /opt/trading-bot/trades.jsonl
```

## 📊 Monitoring

### Check Bot Status

```bash
# Supervisor status
sudo supervisorctl status

# View live logs
sudo supervisorctl tail -f trading-bot

# Check process
ps aux | grep python
```

### Monitor System Resources

```bash
# Install monitoring tools
sudo apt install -y htop iotop

# Monitor CPU/Memory
htop

# Monitor disk I/O
sudo iotop

# Check disk space
df -h
```

### Database Queries

```bash
# Connect to database
sqlite3 /opt/trading-bot/trading_bot.db

# View recent trades
SELECT * FROM trades ORDER BY timestamp DESC LIMIT 10;

# Calculate profit
SELECT SUM(expected_profit) as total_profit FROM trades;

# Exit
.exit
```

## 🔄 Maintenance

### Update Code

```bash
cd /opt/trading-bot
git pull origin main
sudo supervisorctl restart trading-bot
```

### View Logs

```bash
# Recent logs
tail -n 100 /var/log/trading-bot/output.log

# Follow logs in real-time
tail -f /var/log/trading-bot/output.log

# Search logs
grep "ERROR" /var/log/trading-bot/output.log
```

### Restart Bot

```bash
sudo supervisorctl restart trading-bot
```

### Stop Bot

```bash
sudo supervisorctl stop trading-bot
```

### Backup Data

```bash
# Backup database and logs
tar -czf backup-$(date +%Y%m%d).tar.gz \
  trading_bot.db trades.jsonl trading_bot.log

# Download backup
scp ubuntu@your-server-ip:/opt/trading-bot/backup-*.tar.gz ./
```

## 🔐 Security Best Practices

### 1. Firewall Configuration

```bash
# Enable UFW
sudo ufw enable

# Allow SSH
sudo ufw allow 22/tcp

# Deny all other incoming
sudo ufw default deny incoming
sudo ufw default allow outgoing

# Check status
sudo ufw status
```

### 2. SSH Hardening

```bash
# Disable password authentication
sudo nano /etc/ssh/sshd_config

# Set these values:
# PasswordAuthentication no
# PermitRootLogin no
# PubkeyAuthentication yes

# Restart SSH
sudo systemctl restart sshd
```

### 3. Automatic Security Updates

```bash
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```

### 4. Fail2Ban (Brute Force Protection)

```bash
sudo apt install -y fail2ban
sudo systemctl enable fail2ban
sudo systemctl start fail2ban
```

## 📈 Performance Tuning

### 1. Optimize Network Settings

```bash
# Edit sysctl
sudo nano /etc/sysctl.conf

# Add these lines:
net.ipv4.tcp_fin_timeout = 15
net.ipv4.tcp_tw_reuse = 1
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216

# Apply changes
sudo sysctl -p
```

### 2. Increase File Limits

```bash
# Edit limits
sudo nano /etc/security/limits.conf

# Add:
ubuntu soft nofile 65536
ubuntu hard nofile 65536

# Reboot or re-login for changes to take effect
```

### 3. Use Process Priority

```bash
# Run with higher priority
sudo renice -n -5 -p $(pgrep -f "python main.py")
```

## 🚨 Troubleshooting

### Bot Not Starting

```bash
# Check supervisor logs
sudo supervisorctl tail -f trading-bot stderr

# Check system logs
sudo journalctl -u supervisor -n 50

# Verify Python environment
/opt/trading-bot/venv/bin/python --version
```

### High CPU Usage

```bash
# Check what's consuming CPU
top
htop

# Reduce scan frequency in .env
UPDATE_INTERVAL=0.5  # Slower scanning
```

### Memory Leaks

```bash
# Monitor memory over time
watch -n 5 free -h

# If memory grows unbounded, restart periodically
# Add to crontab:
0 */6 * * * sudo supervisorctl restart trading-bot
```

### Database Lock Errors

```bash
# Only one process should access database
# Check for multiple instances
ps aux | grep "python main.py"

# Kill duplicates if needed
sudo supervisorctl stop trading-bot
pkill -f "python main.py"
sudo supervisorctl start trading-bot
```

### WebSocket Disconnections

```bash
# Check network connectivity
ping api.elections.kalshi.com
ping gamma-api.polymarket.com

# Check if firewall is blocking
sudo iptables -L
sudo ufw status
```

## 💰 Cost Optimization

### Use Spot/Preemptible Instances

**AWS Spot:**
```bash
# Launch spot instance (70-90% cheaper)
aws ec2 request-spot-instances \
  --spot-price "0.05" \
  --instance-count 1 \
  --type "one-time" \
  --launch-specification file://spec.json
```

**GCP Preemptible:**
- 80% cheaper than regular instances
- May be terminated with 30s notice
- Add restart logic to handle terminations

### Monitor Costs

```bash
# AWS
aws ce get-cost-and-usage ...

# GCP
gcloud billing accounts list
```

## 📊 Monitoring & Alerts

### Setup CloudWatch (AWS)

```bash
# Install CloudWatch agent
wget https://s3.amazonaws.com/amazoncloudwatch-agent/ubuntu/amd64/latest/amazon-cloudwatch-agent.deb
sudo dpkg -i amazon-cloudwatch-agent.deb

# Configure agent to monitor logs
sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-config-wizard
```

### Email Alerts

Create a monitoring script:
```bash
#!/bin/bash
# /opt/trading-bot/monitor.sh

# Check if bot is running
if ! pgrep -f "python main.py" > /dev/null; then
    echo "Trading bot is down!" | mail -s "Bot Alert" your@email.com
    sudo supervisorctl start trading-bot
fi
```

Add to crontab:
```bash
crontab -e
# Add:
*/5 * * * * /opt/trading-bot/monitor.sh
```

## 🔄 Auto-Updates

Create update script:
```bash
#!/bin/bash
# /opt/trading-bot/update.sh

cd /opt/trading-bot
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
sudo supervisorctl restart trading-bot
```

Schedule weekly updates:
```bash
crontab -e
# Add (every Sunday at 3 AM):
0 3 * * 0 /opt/trading-bot/update.sh >> /var/log/trading-bot/updates.log 2>&1
```

## ✅ Deployment Checklist

- [ ] Server provisioned and accessible
- [ ] Python 3.11+ installed
- [ ] Dependencies installed
- [ ] Repository cloned
- [ ] Virtual environment created
- [ ] `.env` configured with credentials
- [ ] Bot tested manually
- [ ] Supervisor configured
- [ ] Bot running as service
- [ ] Logs are being written
- [ ] Firewall configured
- [ ] SSH hardened
- [ ] Backups scheduled
- [ ] Monitoring setup
- [ ] Alerts configured

## 📞 Support

If you encounter issues:
1. Check logs: `/var/log/trading-bot/output.log`
2. Verify configuration: `.env` file
3. Test network connectivity
4. Review recent code changes
5. Open an issue on GitHub

---

**Happy Trading! 🚀**
