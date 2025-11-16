# High-Frequency Arbitrage Trading Bot

A production-grade, fully autonomous arbitrage trading bot for Kalshi and Polymarket prediction markets. The bot operates in **simulation mode only** - no real trades are executed.

## 🎯 Features

### Core Capabilities
- **Dual-Platform Support**: Monitors both Kalshi and Polymarket simultaneously
- **Real-Time Data**: WebSocket connections for low-latency price updates
- **Arbitrage Detection**:
  - Intra-platform arbitrage (when YES + NO prices < $1.00)
  - Cross-platform arbitrage (price differences between platforms)
- **Automatic Market Pairing**: Fuzzy matching to identify equivalent markets
- **Simulation Mode**: All trades are simulated and logged, zero financial risk

### Technical Features
- **Fully Asynchronous**: Built with asyncio for maximum performance
- **Auto-Recovery**: Automatic reconnection with exponential backoff
- **Persistent Logging**: Dual storage (JSON Lines + SQLite)
- **Health Monitoring**: Real-time status checks and metrics
- **Graceful Shutdown**: Proper cleanup on SIGINT/SIGTERM
- **Cloud-Ready**: Designed for 24/7 operation in cloud environments

## 📋 Requirements

- Python 3.9+
- Linux/macOS (Windows supported but uvloop unavailable)
- Internet connection for API access

## 🚀 Installation

### 1. Clone the Repository

```bash
git clone <repository-url>
cd Live_PK_Bot
```

### 2. Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` and add your API credentials:

```env
# Kalshi API Configuration
KALSHI_EMAIL=your_email@example.com
KALSHI_PASSWORD=your_password
KALSHI_API_KEY=your_api_key  # Optional

# Polymarket API Configuration
POLYMARKET_API_KEY=your_api_key  # Optional
POLYMARKET_SECRET=your_secret    # Optional

# Bot Configuration
MIN_PROFIT_THRESHOLD=0.01
MAX_TRADE_SIZE=100
UPDATE_INTERVAL=0.1
```

> **Note**: API credentials are optional for read-only market data access. Some endpoints may require authentication.

## 🎮 Usage

### Start the Bot

```bash
python main.py
```

### Monitor Logs

The bot outputs to both console and log files:

```bash
# Watch main log
tail -f trading_bot.log

# Watch trade log (JSON Lines format)
tail -f trades.jsonl
```

### Stop the Bot

Press `Ctrl+C` for graceful shutdown. The bot will:
1. Close all WebSocket connections
2. Flush logs to disk
3. Save final metrics
4. Exit cleanly

## 📊 Output & Monitoring

### Console Output

The bot displays periodic status updates every 30 seconds:

```
================================================================================
Bot Status - Uptime: 01:23:45
--------------------------------------------------------------------------------
Markets Tracked: 150
Opportunities Detected: 25
Trades Simulated: 8
Total Simulated Profit: $12.45
Kalshi Connected: ✓
Polymarket Connected: ✓
================================================================================
```

### Trade Logs

Simulated trades are logged to `trades.jsonl`:

```json
{
  "opportunity_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2025-01-15T10:30:45.123456",
  "type": "cross-platform",
  "buy": {
    "platform": "kalshi",
    "market_id": "ECON-INFLATION-2025",
    "outcome": "yes",
    "price": 0.45,
    "size": 100
  },
  "sell": {
    "platform": "polymarket",
    "market_id": "0x1234...",
    "outcome": "yes",
    "price": 0.52,
    "size": 100
  },
  "profit": 7.0,
  "return_pct": 15.56
}
```

### SQLite Database

Query the database for analytics:

```bash
sqlite3 trading_bot.db

# Get recent trades
SELECT * FROM trades ORDER BY timestamp DESC LIMIT 10;

# Calculate total profit
SELECT SUM(expected_profit) FROM trades;

# Get metrics history
SELECT * FROM metrics ORDER BY timestamp DESC LIMIT 20;
```

## 🏗️ Architecture

### Project Structure

```
Live_PK_Bot/
├── main.py                 # Entry point
├── supervisor.py           # Runtime orchestration
├── config.py              # Configuration management
├── models.py              # Data models
├── kalshi_client.py       # Kalshi API client
├── polymarket_client.py   # Polymarket API client
├── market_discovery.py    # Market pairing logic
├── orderbook_manager.py   # Order book management
├── arbitrage_engine.py    # Arbitrage detection
├── trade_logger.py        # Persistent logging
├── requirements.txt       # Dependencies
├── .env.example          # Example configuration
└── README.md             # This file
```

### Component Flow

```
┌─────────────────────────────────────────────────────────────┐
│                      Supervisor                              │
│  (Orchestrates all components + health checks)              │
└─────────────────────────────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│   Kalshi     │   │ Polymarket   │   │   Market     │
│   Client     │   │   Client     │   │  Discovery   │
│  (WebSocket) │   │  (WebSocket) │   │   (Pairing)  │
└──────┬───────┘   └──────┬───────┘   └──────────────┘
       │                  │
       └────────┬─────────┘
                ▼
    ┌──────────────────────┐
    │  OrderBook Manager   │
    │  (In-memory books)   │
    └──────────┬───────────┘
               ▼
    ┌──────────────────────┐
    │  Arbitrage Engine    │
    │  (Opportunity scan)  │
    └──────────┬───────────┘
               ▼
    ┌──────────────────────┐
    │   Trade Logger       │
    │ (SQLite + JSON Lines)│
    └──────────────────────┘
```

## ⚙️ Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MIN_PROFIT_THRESHOLD` | Minimum profit per share to trigger trade | `0.01` |
| `MAX_TRADE_SIZE` | Maximum shares per simulated trade | `100` |
| `UPDATE_INTERVAL` | Seconds between arbitrage scans | `0.1` |
| `MARKET_REFRESH_INTERVAL` | Seconds between market discovery | `300` |
| `LOG_LEVEL` | Logging level (DEBUG/INFO/WARNING/ERROR) | `INFO` |
| `WEBSOCKET_TIMEOUT` | Seconds before considering WS dead | `30` |
| `RECONNECT_BASE_DELAY` | Base delay for exponential backoff | `2` |

### Customization

Edit `config.py` to add new configuration parameters or modify validation logic.

## 🔍 How It Works

### 1. Market Discovery
- Fetches all active markets from Kalshi and Polymarket
- Uses fuzzy text matching to pair equivalent markets
- Continuously refreshes to detect new markets

### 2. Real-Time Data Ingestion
- Establishes WebSocket connections to both platforms
- Maintains in-memory order books with best bid/ask
- Auto-reconnects on disconnection with exponential backoff

### 3. Arbitrage Detection

**Intra-Platform Arbitrage:**
- Detects when `BestAsk(YES) + BestAsk(NO) < $1.00`
- Simulates buying both outcomes for guaranteed profit

**Cross-Platform Arbitrage:**
- Compares prices of paired markets
- Detects when `Price(Platform A) < Price(Platform B) - threshold`
- Simulates buy low / sell high strategy

### 4. Trade Simulation
- Validates opportunity is still profitable
- Calculates optimal trade size
- Logs simulated trade with all details
- Updates metrics and profit tracking

### 5. Health Monitoring
- Periodic connection health checks
- Automatic reconnection on failures
- Metrics logging every minute
- Status display every 30 seconds

## 🚨 Important Notes

### Simulation Only
**This bot does NOT execute real trades.** All arbitrage opportunities are simulated and logged. To enable real trading, you would need to:
1. Implement order placement functions in the API clients
2. Add risk management and position tracking
3. Handle order fills and cancellations
4. Implement proper error handling for failed orders

### API Rate Limits
Be mindful of API rate limits:
- Kalshi: Check their documentation for current limits
- Polymarket: Check their documentation for current limits

The bot uses WebSockets for real-time data to minimize REST API calls.

### Network Requirements
- Stable internet connection required
- Low latency preferred for competitive arbitrage
- Consider deploying near API endpoints (AWS us-east-1, etc.)

## 🐛 Troubleshooting

### WebSocket Disconnections
The bot automatically reconnects with exponential backoff. Check logs for connection errors.

### No Opportunities Found
This is normal. Arbitrage opportunities are rare and fleeting. The bot continuously monitors and will log opportunities when detected.

### Database Locked Errors
Ensure only one instance of the bot is running. SQLite has limited concurrency.

### Authentication Failures
Verify your API credentials in `.env`. Some endpoints work without authentication.

## 📈 Performance Optimization

### For Production Deployment:

1. **Use uvloop** (Linux/macOS only):
   ```bash
   pip install uvloop
   ```

2. **Use faster JSON parser**:
   ```bash
   pip install orjson
   ```

3. **Deploy on cloud**:
   - AWS EC2 (us-east-1 for low latency)
   - DigitalOcean Droplet
   - Google Cloud Compute

4. **Adjust scan frequency**:
   ```env
   UPDATE_INTERVAL=0.05  # Scan every 50ms
   ```

5. **Monitor system resources**:
   ```bash
   htop  # CPU/Memory usage
   iotop # Disk I/O
   ```

## 🔐 Security

- Never commit `.env` file to version control
- Use environment variables for secrets
- Rotate API keys regularly
- Use read-only API keys when possible
- Run with minimal system privileges

## 📝 License

[Add your license here]

## 🤝 Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Submit a pull request

## 📧 Support

For issues or questions:
- Open an issue on GitHub
- Check logs for error messages
- Review configuration settings

## ⚠️ Disclaimer

This software is for educational and research purposes only. Use at your own risk. The authors are not responsible for any financial losses or damages. Always comply with platform terms of service and applicable regulations.

---

**Built with ❤️ using Python and asyncio**
