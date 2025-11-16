#!/bin/bash
###############################################################################
# ONE-COMMAND DEPLOYMENT SCRIPT
# Copy and paste this entire block into your droplet console
###############################################################################

set -e

echo "=========================================="
echo "Deploying Arbitrage Bot"
echo "=========================================="

# Navigate to bot directory
cd /opt/arbitrage-bot

# Pull latest code
echo "Pulling latest code..."
git pull origin claude/arbitrage-trading-bot-01HbkRunfc3TjZ292rRf1Eea

# Create keys directory
mkdir -p /opt/arbitrage-bot/keys

# Create Kalshi private key file
cat > /opt/arbitrage-bot/keys/kalshi_private.key << 'KEYEOF'
-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEAvHt/AWmu13Lg8u2lbaeKt0+urowSogt+arralfVdEzywJr8w
AJxuUCwpAapRgO6e1BRKTKdYQBh2yIfk2tNQu51kjSlnDD/5r7r69WuZlmiqaF6d
jAO12iJOfB+vbAyRu61GoyWRHKa+1L1qHsoaRu5zrCie4E4cFVkmVtmAkp1Mvo+k
VGbseDNXqgrPwOMTZsPKKqCuLxNsEhGIIiA1gTy5bDMoOEY2DCHFc6PI7qPiJUxH
8+huqQgcPc8HdwFu48EJuPN7rA3zblVCvAmOGJDgtKJm3x/U/LUdmnb9H7D1pVTg
Oa4UsO9yY9A+Y5Pz6eRaNpkHZ9KFcGABF2VtZwIDAQABAoIBAC19+TeUFHk35wd7
SHRg/eAkwVqrwEuQTqDgHKYZJK/h8/pGJwXeu9lp7zPRsf5WmctCYnSB55EA1pqs
Aha27kN6R6yyk4anYlKB5NSbdeSRup+aRphmxNuzcBIRa7u+hOYxel0iUhYCQQkD
9rsbuJ/qKc0huMcW0zxr2g8YTCoWl0aLhreQmur9l8BggPOvTugrmRjIAdTB/92V
r+ffpYqLJ7qj6j7iMo5bZodw3K0Yg0Ks9QUPweyyT2Ox3hqu3UHysTMeQL/Y71hY
yc1Xyd75zTqhVtMjVWCrG/VfCsuM0IuvO7RSc6clQRekss04wpKy32vqGDQ41ehy
V8MiyYECgYEA2XU++4/CLkhHvViMiBxJ9RMcyhyR9TK/AuzQAr+XOG+skGjR58E7
8Ig9Zg66v37v7KOPNwLkV5I1ld1dTRv3Z+hLAZ3Prmi/WdjtKrCAEJFPF5WXQzVe
avYAZnt4cc/LajSwbSlBXc8013deo2Dqg7PWBOKzRdq3TObX8b/qS6ECgYEA3eOJ
WQ9cOvkc2uz8Za12eZTE2wUCSIa025suNJncDgbF86Qw2Nds6A8sUBIGdSiJ15yZ
weXmrxUzPVqhR7LWoKc9ZrBdteyAKy/2ahinHrWlWMvx9za/sLfhqiI3BiPI/pDJ
njfYujjhvAWQm2ZtfupCN7K2NIzc6PSZ9Maf3AcCgYEAgD21s/M2p8a2kAJ9dfOA
5gesbcDljr2ridUQYt6MFps9IDjAuTTq3VHrK5m6Jh587YgTeHS7Jq2x7jyKvmOk
xuFmAoEHripV1m2oiAlorNyU0SrF9rutf9StrcJY6H2Lz4ldFjNDOkhtODhMVntc
MelHaMAsyyBOAwsMBKSSTqECgYAS7s9RYhYkkgz8QSxoIJzzUtZZOdwwBA56josq
wdYc/Eb3uxLP7dHFG0ZUrrUOWh8o3pvgB5XfapesrIcGbyQRITQEBxh35W4qQTVt
aB0aabVqFjzXMzy3/3ip47F+PJ9x2Tja3zkG6sOYH4FvQRYmtiZgSkdxxHM1DWn1
kN0jEQKBgQChhet9Bn7PFlx3W+FeYud8665KrVDRgCcb23yxAd1zeHKpJ4FI5Hmh
XpQvpxRBUbCu4MJykCWUYMMOXMwBEF4mO03wlrIQQFDSMztM/+bK1an3zfVpuj/1
8ax8AX2unJe57Trhh+5+9uG2OtFYnQb7Bk2x2FwVyJe/m2EZMwzSNw==
-----END RSA PRIVATE KEY-----
KEYEOF

chmod 400 /opt/arbitrage-bot/keys/kalshi_private.key
echo "✓ Private key file created"

# Create .env file
cat > /opt/arbitrage-bot/.env << 'ENVEOF'
KALSHI_API_BASE=https://api.elections.kalshi.com
KALSHI_WS_URL=wss://api.elections.kalshi.com/trade-api/ws/v2
KALSHI_PRIVATE_KEY_FILE=/opt/arbitrage-bot/keys/kalshi_private.key
KALSHI_FEE_RATE=0.007
POLYMARKET_API_BASE=https://gamma-api.polymarket.com
POLYMARKET_WS_URL=wss://ws-subscriptions-clob.polymarket.com/ws/market
POLYMARKET_API_KEY=0x5af2eecb46cacb22366bcaf38998dd260c788d17ec0df50527e6913dbc492358
POLYMARKET_PRIVATE_KEY=0x804622ace5372e85a682a972e83714f971b83cb00cf5bdeeb5b12894bcead9c9
POLYMARKET_FEE_RATE=0.02
MIN_PROFIT_THRESHOLD=0.01
MAX_TRADE_SIZE=100
UPDATE_INTERVAL=0.1
MARKET_REFRESH_INTERVAL=300
HEARTBEAT_INTERVAL=15
WEBSOCKET_TIMEOUT=30
STALE_DATA_THRESHOLD=30
MAX_RECONNECT_ATTEMPTS=10
RECONNECT_BASE_DELAY=2
CIRCUIT_BREAKER_THRESHOLD=5
CIRCUIT_BREAKER_TIMEOUT=60
KALSHI_RATE_LIMIT=10.0
POLYMARKET_RATE_LIMIT=10.0
LOG_LEVEL=INFO
LOG_FILE=/var/log/arbitrage-bot/trading_bot.log
TRADE_LOG_FILE=/var/log/arbitrage-bot/trades.jsonl
LOG_MAX_BYTES=10485760
LOG_BACKUP_COUNT=5
DB_FILE=/var/lib/arbitrage-bot/trading_bot.db
ENVEOF

chmod 600 /opt/arbitrage-bot/.env
echo "✓ Environment file created"

# Activate virtual environment
source /opt/arbitrage-bot/venv/bin/activate

# Test the bot
echo ""
echo "=========================================="
echo "Testing bot (will run for 10 seconds)..."
echo "=========================================="
timeout 10 python3.11 main.py || true

echo ""
echo "=========================================="
echo "Starting bot in background..."
echo "=========================================="

# Make startup script executable
chmod +x /opt/arbitrage-bot/startup.sh

# Start in background
./startup.sh --background

echo ""
echo "=========================================="
echo "Deployment Complete!"
echo "=========================================="
echo ""
echo "Check status: ./startup.sh --status"
echo "View logs:    tail -f /var/log/arbitrage-bot/trading_bot.log"
echo "Attach:       tmux attach -t arbitrage-bot"
echo "Stop:         ./startup.sh --stop"
echo ""
