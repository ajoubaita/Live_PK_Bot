# Kalshi-Polymarket Arbitrage Trading Bot

Production-grade, fully autonomous arbitrage trading bot for Kalshi and Polymarket prediction markets. Operates in **simulation mode only** - no real trades executed.

## 🚀 Quick Start

```bash
# Navigate to bot directory
cd /opt/arbitrage-bot

# Install dependencies (first time only)
./startup.sh --install

# Configure credentials
nano .env  # Add your API keys

# Start the bot
./startup.sh --background

# Monitor logs
./startup.sh --logs
```

## ✨ Features

- **Real-Time WebSocket Feeds**: Low-latency market data from both exchanges
- **Dual Arbitrage Detection**: Intra-platform (YES + NO < $1.00) and cross-platform opportunities
- **Auto-Recovery**: Exponential backoff reconnection with circuit breakers
- **Rate Limiting**: Respects all API limits (burst + sustained windows)
- **Subscription Rotation**: Efficiently handles 1000+ markets
- **Comprehensive Logging**: Debug, info, and error tracking with 5-minute summaries
- **24/7 Operation**: Cloud-ready with tmux/systemd support

## 📋 Requirements

- Python 3.9+
- Linux server (Ubuntu recommended)
- Kalshi API key
- Polymarket API credentials

## ⚙️ Configuration

Edit `/opt/arbitrage-bot/.env`:

```bash
# Kalshi API
KALSHI_API_BASE=https://api.kalshi.com
KALSHI_WS_URL=wss://api.kalshi.com/trade-api/ws/v2
KALSHI_API_KEY=your_api_key_here

# Polymarket API
POLYMARKET_API_KEY=your_api_key
POLYMARKET_PRIVATE_KEY=your_private_key

# Trading Parameters
MIN_PROFIT_THRESHOLD=0.01        # 1 cent minimum profit
MAX_TRADE_SIZE=100               # Max shares per trade
UPDATE_INTERVAL=0.1              # Scan every 0.1s (10 Hz)
MARKET_SIMILARITY_THRESHOLD=0.5  # Fuzzy matching threshold
```

## 🎮 Commands

```bash
./startup.sh                # Start in foreground
./startup.sh --background   # Start in tmux (recommended)
./startup.sh --stop         # Stop the bot
./startup.sh --status       # Check if running
./startup.sh --logs         # View real-time logs
./startup.sh --install      # Install dependencies
```

### Tmux Session Management

```bash
# Attach to running session
tmux attach -t arbitrage-bot

# Detach (keep bot running)
# Press: Ctrl+B, then D

# Kill session
tmux kill-session -t arbitrage-bot
```

## 📊 Monitoring

### Log Files

```bash
# Main bot log
tail -f /var/log/arbitrage-bot/trading_bot.log

# Trade history (JSON Lines)
tail -f /var/log/arbitrage-bot/trades.jsonl

# Or use startup script
./startup.sh --logs
```

### Expected Output

**Successful Startup:**
```
[INFO] Polymarket WebSocket connected, waiting for handshake completion...
[INFO] WebSocket handshake complete, ready for subscriptions
[INFO] Successfully subscribed to 20/20 markets (group 1/66)
[INFO] Using Kalshi API key authentication for data access
[INFO] Kalshi WebSocket connected successfully
[INFO] Found X market pairs
[INFO] Starting arbitrage scanning...
```

**Periodic Summary (every 5 minutes):**
```
[INFO] Arbitrage Scan Summary (last 5min):
Markets checked: 1500
Skipped (no data): 400
Skipped (low spread): 1050
Skipped (no size): 50
Opportunities found: 2
```

## 🏗️ Architecture

### Core Components

| File | Purpose |
|------|---------|
| `main.py` | Entry point and initialization |
| `supervisor.py` | Runtime orchestration and health checks |
| `kalshi_client.py` | Kalshi API/WebSocket with API key auth |
| `polymarket_client.py` | Polymarket API/WebSocket with rotation |
| `arbitrage_engine.py` | Opportunity detection with fee calculation |
| `market_discovery.py` | Fuzzy market pairing |
| `orderbook_manager.py` | Real-time order book tracking |
| `trade_logger.py` | SQLite + JSON Lines persistence |
| `utils.py` | Rate limiting (dual-window), circuit breakers |

### Data Flow

```
WebSocket → Order Book → Arbitrage Engine → Trade Logger
                ↓
         Market Discovery
```

## 🔧 Advanced Settings

### WebSocket Performance

- **Handshake wait**: 2 seconds (prevents "no close frame" errors)
- **Subscription throttle**: 1 second per market
- **Group size**: 20 markets per subscription group
- **Rotation**: Every 5 minutes
- **Keepalive**: 15-second ping/pong

### Rate Limits

Polymarket uses dual-window rate limiting:
- **Burst**: Short-term limit (e.g., 2400 req/10s)
- **Sustained**: Long-term limit (e.g., 24000 req/10min)

Kalshi uses token bucket algorithm with API key authentication.

### Profit Calculation

```python
# Includes exchange fees
kalshi_fee = 0.007   # 0.7%
polymarket_fee = 0.02 # 2%

profit = sell_price * (1 - sell_fee) - buy_price * (1 + buy_fee)
```

## 🐛 Troubleshooting

| Issue | Solution |
|-------|----------|
| `ModuleNotFoundError: pydantic_settings` | Run `./startup.sh --install` |
| WebSocket disconnects after 2 markets | Fixed - handshake wait now implemented |
| Kalshi 404/401 errors | Fixed - uses API key auth, not deprecated login |
| 0 market pairs found | Lower MARKET_SIMILARITY_THRESHOLD to 0.4-0.5 |
| High CPU usage | Verify UPDATE_INTERVAL=0.1 in .env |

### Debug Mode

```bash
# Edit .env
LOG_LEVEL=DEBUG

# Restart
./startup.sh --stop && ./startup.sh --background
```

### Health Checks

```bash
# Check process
ps aux | grep "python.*main.py"

# Verify WebSocket connections
grep "WebSocket connected" /var/log/arbitrage-bot/trading_bot.log | tail -5

# Check subscriptions
grep "Successfully subscribed" /var/log/arbitrage-bot/trading_bot.log | tail -10

# Find market pairs
grep "Found.*market pairs" /var/log/arbitrage-bot/trading_bot.log

# Watch for opportunities
grep "arbitrage" /var/log/arbitrage-bot/trading_bot.log | tail -20
```

## 📈 Performance

### Resource Usage

- **CPU**: <5% idle, ~15% during active scanning
- **Memory**: 100-200 MB
- **Network**: Minimal (WebSocket streams only)
- **Disk**: ~10 MB/day logs (with rotation)

### Timing

- **Initial subscription**: ~24 minutes (1302 markets at 1s/market)
- **Scan frequency**: 10 Hz (0.1s interval)
- **Market refresh**: Every 5 minutes
- **Reconnect backoff**: 2s → 60s exponential cap

## 🔐 Security

- API keys in `.env` (not tracked by git)
- Private keys in separate files with `chmod 600`
- No credentials in logs
- Simulation mode only (paper trading)

## 📚 Documentation

- **README.md**: This file - main documentation
- **DEPLOYMENT_INSTRUCTIONS.md**: Detailed deployment guide with fixes
- **requirements.txt**: Python dependencies
- **.env.production**: Environment variable template

## 🎯 Success Criteria

Bot is working correctly when logs show:

1. ✅ "WebSocket handshake complete, ready for subscriptions"
2. ✅ "Successfully subscribed to 20/20 markets"
3. ✅ "Using Kalshi API key authentication"
4. ✅ "Found X market pairs" (X > 0)
5. ✅ No disconnection loops or auth errors
6. ✅ Periodic "Arbitrage Scan Summary" every 5 minutes

## ⚠️ Important Notes

### Simulation Only

**No real trades are executed.** All opportunities are simulated and logged for analysis.

### API Rate Limits

The bot respects all documented rate limits to prevent throttling or bans.

### Network Requirements

- Stable internet connection
- Low latency preferred (deploy near exchange servers)
- Recommend AWS us-east-1 or similar

## 🚀 Deployment

See **DEPLOYMENT_INSTRUCTIONS.md** for complete deployment steps including:
- Server setup
- Environment configuration
- Critical fixes applied
- Monitoring and verification

## 📝 Version History

- **1.0.0** (Nov 2024): Production release with critical WebSocket and auth fixes

## 📧 Support

For issues:
1. Check logs: `./startup.sh --logs`
2. Review troubleshooting section
3. See DEPLOYMENT_INSTRUCTIONS.md

## ⚠️ Disclaimer

Educational and research purposes only. Use at your own risk. Authors not responsible for losses. Comply with platform ToS and regulations.

---

**Status**: Production-ready | **Mode**: Simulation Only | **Version**: 1.0.0
