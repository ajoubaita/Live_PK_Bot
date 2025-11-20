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

---

## 🔐 Authentication Deep Dive

### Kalshi API Authentication

#### Primary Method: API Key Authentication
The bot uses API key authentication as the primary method for Kalshi:

```python
# Headers sent with every request
headers = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "X-API-Key": "your_kalshi_api_key"
}
```

**Configuration** (`config.py:39-42`):
```python
kalshi_api_key: Optional[str] = Field(
    default=None,
    description="Kalshi API key"
)
```

#### Legacy Method: Email/Password Login (Deprecated)
The bot attempts email/password authentication first but falls back to API key:

```python
# POST /trade-api/v2/login
payload = {
    "email": "your_email",
    "password": "your_password"
}
# Returns: {"token": "jwt_token_here"}
```

**Token Lifecycle** (`kalshi_client.py:96-133`):
- Token expiry: 23 hours after authentication
- Auto-refresh: When token has < 5 minutes remaining
- Fallback: Uses API key if login fails

#### WebSocket Authentication
Kalshi WebSocket requires authentication via HTTP headers:

```python
# Connection with auth headers
extra_headers = {}

# Priority 1: Bearer token (if available from login)
if self.auth_token:
    extra_headers["Authorization"] = f"Bearer {self.auth_token}"

# Priority 2: API key (recommended)
elif self.config.kalshi_api_key:
    extra_headers["X-API-Key"] = self.config.kalshi_api_key

# WebSocket connection
async with websockets.connect(
    "wss://api.kalshi.com/trade-api/ws/v2",
    extra_headers=extra_headers,
    ping_interval=15,  # 15s keepalive
    ping_timeout=10
) as ws:
```

**401 Handling** (`kalshi_client.py:374-386`):
- Automatically attempts token refresh on 401 errors
- Falls back to API key authentication
- Exponential backoff on repeated failures

---

### Polymarket API Authentication

#### REST API Authentication
Polymarket uses Bearer token authentication for REST endpoints:

```python
# Headers for REST API calls
headers = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Authorization": f"Bearer {polymarket_api_key}"
}
```

**Configuration** (`config.py:48-68`):
```python
# REST API base
polymarket_api_base: str = "https://gamma-api.polymarket.com"

# Authentication credentials
polymarket_api_key: Optional[str] = Field(default=None)
polymarket_private_key: Optional[str] = Field(default=None)  # For signing
polymarket_secret: Optional[str] = Field(default=None)
```

#### WebSocket Authentication
Polymarket WebSocket does **NOT** require authentication for public market data:

```python
# No auth headers needed
async with websockets.connect(
    "wss://ws-subscriptions-clob.polymarket.com/ws/market",
    ping_interval=15,
    ping_timeout=10
) as ws:
```

**Note**: Private operations (trading) require signed requests using the private key.

---

## 📡 Data Request Methods & Frequency

### REST API Endpoints

#### Kalshi REST Calls

| Endpoint | Method | Purpose | Rate Limit |
|----------|--------|---------|------------|
| `/trade-api/v2/markets` | GET | Fetch all open markets | 10 req/s |
| `/trade-api/v2/markets/{id}/orderbook` | GET | Get orderbook for market | 10 req/s |
| `/trade-api/v2/login` | POST | Authenticate (deprecated) | N/A |

**Market Discovery** (`kalshi_client.py:168-216`):
```python
# Fetch up to 1000 open markets
url = f"{base_url}/trade-api/v2/markets"
params = {
    "status": "open",
    "limit": 1000
}
```

**Orderbook Fetch** (`kalshi_client.py:218-242`):
```python
# Fetch orderbook for specific market
url = f"{base_url}/trade-api/v2/markets/{market_id}/orderbook"
```

#### Polymarket REST Calls

| Endpoint | Method | Purpose | Rate Limit |
|----------|--------|---------|------------|
| `/events` | GET | Fetch events with markets | 100 req/10s |
| `/book` | GET | Get orderbook for token | 200 req/10s |

**Market Discovery with Pagination** (`polymarket_client.py:110-250`):
```python
# Paginated event fetching (5 pages = 500 events max)
for page in range(max_pages):
    url = f"{base_url}/events"
    params = {
        "closed": "false",
        "limit": 100,
        "offset": page * 100
    }
```

**Market Quality Filtering**:
- Requires `enableOrderBook: true`
- Must be active and not closed
- Valid token ID required
- Optional liquidity threshold ($100 default)

---

### WebSocket Subscription Formats

#### Kalshi WebSocket Protocol

**Connection URL**: `wss://api.kalshi.com/trade-api/ws/v2`

**Subscription Message** (`kalshi_client.py:336-346`):
```json
{
    "type": "subscribe",
    "channels": [
        {
            "name": "orderbook_delta",
            "market_tickers": ["MARKET-1", "MARKET-2", "..."]
        }
    ]
}
```

**Received Message Format** (orderbook_delta):
```json
{
    "type": "orderbook_delta",
    "market_ticker": "MARKET-ID",
    "orderbook": {
        "yes": {
            "bids": [[price_cents, size], ...],
            "asks": [[price_cents, size], ...]
        },
        "no": {
            "bids": [[price_cents, size], ...],
            "asks": [[price_cents, size], ...]
        }
    }
}
```
**Note**: Kalshi prices are in cents (divide by 100 for decimal).

#### Polymarket WebSocket Protocol

**Connection URL**: `wss://ws-subscriptions-clob.polymarket.com/ws/market`

**Subscription Message** (`polymarket_client.py:436-439`):
```json
{
    "assets_ids": ["token_id_1", "token_id_2", "..."],
    "type": "market"
}
```

**Received Message Format** (book event):
```json
{
    "event_type": "book",
    "asset_id": "token_id",
    "bids": [[price, size], ...],
    "asks": [[price, size], ...]
}
```
**Note**: Can also receive arrays of messages (batch updates).

---

### Timing & Frequency Parameters

#### Core Intervals

| Parameter | Value | Description | Location |
|-----------|-------|-------------|----------|
| `update_interval` | 0.1s | Arbitrage scan frequency (10 Hz) | `config.py:79-82` |
| `market_refresh_interval` | 300s | Market discovery refresh | `config.py:83-86` |
| `heartbeat_interval` | 15s | WebSocket ping/pong | `config.py:119-122` |
| `websocket_timeout` | 30s | Connection timeout | `config.py:115-118` |
| `stale_data_threshold` | 30s | Orderbook staleness check | `config.py:123-126` |
| `reconnect_base_delay` | 2s | Initial reconnect wait | `config.py:111-114` |

#### WebSocket Timing

**Connection Setup**:
```python
# Handshake wait (prevents "no close frame" errors)
await asyncio.sleep(2.0)  # polymarket_client.py:603
```

**Keepalive** (`polymarket_client.py:499-524`):
```python
# Ping/pong every 15 seconds
while not ws.closed:
    pong_waiter = await ws.ping()
    await asyncio.wait_for(pong_waiter, timeout=10)
    await asyncio.sleep(15)
```

**Reconnection** (`polymarket_client.py:679-682`):
```python
# Exponential backoff: 2s → 4s → 8s → 16s → 32s → 60s (cap)
reconnect_delay = min(reconnect_delay * 2, 60)
```

#### Subscription Batching

**Polymarket Batch Subscriptions** (`polymarket_client.py:395-483`):
```python
# 20 markets per batch
batch_size = 20

# Wait between batches
await asyncio.sleep(2.0)  # After each batch for confirmations
await asyncio.sleep(1.0)  # Between batches

# Rotation interval
rotation_interval = 300  # 5 minutes
```

**Subscription Groups**:
- Markets split into groups of 20
- Rotates to next group every 5 minutes
- Unsubscribes from current before subscribing to next

---

### Rate Limiting Implementation

#### Kalshi Rate Limiting

**Token Bucket Algorithm** (`utils.py:91-134`):
```python
class RateLimiter:
    def __init__(self, calls_per_second: float = 10.0, burst: int = 20):
        self.rate = calls_per_second
        self.burst = burst
        self.tokens = float(burst)
```

**Configuration** (`config.py:139-142`):
```python
kalshi_rate_limit: float = Field(
    default=10.0,
    description="Kalshi API calls per second"
)
```

#### Polymarket Rate Limiting

**Dual-Window Rate Limiter** (`utils.py:17-89`):
Handles both burst (short-term) and sustained (long-term) limits simultaneously.

```python
class DualWindowRateLimiter:
    def __init__(
        self,
        burst_calls: int,      # e.g., 2400
        burst_window: float,   # e.g., 10 seconds
        sustained_calls: int,  # e.g., 24000
        sustained_window: float # e.g., 600 seconds (10 min)
    ):
```

**Endpoint-Specific Limits** (`utils.py:434-559`):

| Category | Endpoint | Burst (10s) | Sustained (10min) |
|----------|----------|-------------|-------------------|
| General | Default | 5000 | - |
| GAMMA | `/events` | 100 | - |
| GAMMA | `/markets` | 125 | - |
| GAMMA | `/search` | 300 | - |
| CLOB | `/book` | 200 | - |
| CLOB | `/books` | 80 | - |
| CLOB | `/price` | 200 | - |
| Trading | `POST /order` | 2400 | 24000 |
| Trading | `DELETE /order` | 2400 | 24000 |
| Trading | `POST /orders` | 800 | 12000 |
| Trading | `DELETE /cancel-all` | 200 | 3000 |
| Relayer | `/submit` | 15/min | - |

**Rate Limit Enforcement**:
```python
async def acquire_for_endpoint(self, endpoint: str):
    """Acquire rate limit permission for a specific endpoint."""
    if '/events' in endpoint:
        await self.gamma_events.acquire()
    elif '/book' in endpoint:
        await self.clob_book.acquire()
    # ... etc
```

---

### Circuit Breaker Pattern

**Configuration** (`config.py:148-156`):
```python
circuit_breaker_threshold: int = Field(
    default=5,
    description="Failures before circuit breaker opens"
)
circuit_breaker_timeout: int = Field(
    default=60,
    description="Seconds to wait before circuit reset attempt"
)
```

**States** (`utils.py:136-216`):
- **Closed**: Normal operation, requests pass through
- **Open**: Circuit tripped, requests fail immediately
- **Half-Open**: Testing if service recovered

```python
# Failure handling
if self.failure_count >= self.failure_threshold:
    self.state = "open"
    logger.error(f"Circuit breaker OPENED after {self.failure_count} failures")
```

---

### Data Processing Pipeline

#### Orderbook Update Flow

1. **WebSocket Message Received**
2. **Platform-Specific Parsing** (`orderbook_manager.py:63-243`)
   - Kalshi: Prices in cents, divided by 100
   - Polymarket: Prices as decimals (0-1)
3. **Orderbook Update** (`orderbook_manager.py:245-287`)
4. **Staleness Check** (`orderbook_manager.py:338-365`)

**Kalshi Price Handling** (`orderbook_manager.py:109`):
```python
bid_price = best_yes_bid[0] / 100.0  # Kalshi prices in cents
```

**Polymarket Format Support** (`orderbook_manager.py:195-204`):
```python
# Can be either [price, size] or {"price": x, "size": y}
if isinstance(best_bid, (list, tuple)):
    bid_price = float(best_bid[0])
    bid_size = float(best_bid[1])
elif isinstance(best_bid, dict):
    bid_price = float(best_bid.get('price', 0))
    bid_size = float(best_bid.get('size', 0))
```

---

### Example Request Sequence

#### Startup Sequence

1. **Initialize HTTP Sessions** (30s timeout)
2. **Authenticate with Kalshi** (API key or login)
3. **Fetch Markets**
   - Kalshi: Single request, up to 1000 markets
   - Polymarket: 5 paginated requests, 100 events each
4. **Quality Filter** (Polymarket): Liquidity, volume, order book enabled
5. **Market Discovery**: Fuzzy match markets between platforms
6. **WebSocket Connections**
   - Kalshi: Connect with auth headers
   - Polymarket: Connect (no auth), wait 2s handshake
7. **Subscribe to Markets**
   - Kalshi: All markets in single subscription
   - Polymarket: Batched (20/batch, 1-2s between batches)
8. **Start Arbitrage Scanning** (10 Hz)

#### Runtime Loop

```
Every 0.1s:  Scan orderbooks for arbitrage opportunities
Every 15s:   WebSocket keepalive (ping/pong)
Every 30s:   Check for stale orderbook data
Every 5min:  Rotate Polymarket subscriptions
Every 5min:  Print scan summary
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
