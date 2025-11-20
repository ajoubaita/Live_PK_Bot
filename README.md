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
- **Smart Market Pairing**: Category-based matching with time-horizon alignment
- **Profitability Tracking**: Detailed per-trade logging with session profit summaries
- **Auto-Recovery**: Exponential backoff reconnection with circuit breakers
- **Rate Limiting**: Respects all API limits (burst + sustained windows)
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
| `market_discovery.py` | Category-based market pairing with time-horizon alignment |
| `orderbook_manager.py` | Real-time order book tracking |
| `trade_logger.py` | SQLite + JSON Lines persistence |
| `utils.py` | Rate limiting (dual-window), circuit breakers |

### Data Flow

```
WebSocket → Order Book → Arbitrage Engine → Trade Logger
                ↓
         Market Discovery
```

### Market Discovery Algorithm

The bot uses a sophisticated category-based pairing algorithm to find equivalent markets across exchanges:

**Algorithm Steps:**
1. **Category Detection**: Classify markets into SPORTS, POLITICS, MACRO_ECON, CRYPTO, ENTERTAINMENT, WEATHER, OTHER
2. **Time-Horizon Grouping**: Extract resolution dates and group markets by close time
3. **Pre-filtering**: Only compare markets in the SAME category with compatible time horizons
4. **Token Normalization**: Strip noise (player names, stat thresholds) before fuzzy matching
5. **Multi-Component Scoring**: `final_score = text_similarity × category_score × time_score`

**Tunable Constants** (`market_discovery.py`):
```python
MIN_FINAL_SCORE = 0.55              # Minimum score to accept pair
MIN_TEXT_SIMILARITY = 0.35          # Minimum text match
MAX_RESOLUTION_DIFF_DAYS = 45       # Max days apart for resolution
IDEAL_RESOLUTION_DIFF_DAYS = 7      # Full score within this range
```

**Why Category-Based?**
- Eliminates garbage matches (NFL props → Fed rate cuts)
- Sports markets stay with sports, politics with politics
- Time alignment ensures markets resolve in similar windows

### Profitability Tracking

The arbitrage engine provides comprehensive logging for profitability analysis:

**Per-Opportunity Logging:**
```
============================================================
💰 ARBITRAGE OPPORTUNITY DETECTED
============================================================
Type: CROSS-PLATFORM
Buy: kalshi @ $0.4500
  Market: Will Fed cut rates in Dec 2025?
Sell: polymarket @ $0.4800
  Market: Fed rate cut December 2025
Spread: $0.0300
Trade Size: 100 contracts
Expected Profit: $3.00
Return: 6.67%
Time: 2024-11-20 15:30:45 UTC
============================================================
```

**Session Summary (every 5 minutes):**
```
============================================================
📊 ARBITRAGE SCAN SUMMARY (last 5 minutes)
============================================================
Markets checked: 1500
Skipped (no data): 400
Skipped (low spread): 1050
Skipped (no size): 50
Opportunities found this period: 3
============================================================
📈 SESSION PROFITABILITY (running 2h 30m)
============================================================
Total opportunities: 15
  - Intra-platform: 8
  - Cross-platform: 7
Total potential profit: $45.50
Best single opportunity: $5.20 (8.50%)
Avg profit per opportunity: $3.03
============================================================
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

#### Dynamic Subscription Management

**⚠️ IMPORTANT: The rotation-based approach has been deprecated.**

The bot now uses **persistent connections** with **in-place subscription updates**:

```python
# Startup: Subscribe to ALL markets in single message
subscribe_msg = {
    "assets_ids": all_token_ids,  # Can be 1000+ markets
    "type": "market"
}

# Runtime: Add new markets without reconnecting
async def subscribe_to_market(self, asset_id: str):
    if asset_id not in self.subscribed_assets:
        await ws.send(json.dumps({
            "assets_ids": [asset_id],
            "type": "market"
        }))
        self.subscribed_assets.add(asset_id)

# Runtime: Remove closed markets without reconnecting
async def unsubscribe_from_market(self, asset_id: str):
    if asset_id in self.subscribed_assets:
        await ws.send(json.dumps({
            "assets_ids": [asset_id],
            "type": "unsubscribe"
        }))
        self.subscribed_assets.discard(asset_id)
```

**Why No Rotation?**
- Polymarket supports **65,000+ subscriptions** per connection
- Rotation causes unnecessary reconnects and data gaps
- Dynamic add/remove is more efficient and reliable
- Eliminates Cloudflare throttling from connection churn

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
   - Kalshi: All markets in single subscription message
   - Polymarket: All markets in single subscription message
8. **Wait for Initial Data** (~2-5 seconds)
9. **Start Arbitrage Scanning** (10 Hz)

#### Runtime Loop

```
Every 0.1s:  Scan orderbooks for arbitrage opportunities
Every 15s:   WebSocket keepalive (ping/pong)
Every 30s:   Check for stale orderbook data
Every 5min:  Refresh market lists from REST APIs
Every 5min:  Update subscriptions in-place (add new, remove closed)
Every 5min:  Print scan summary
```

**Note**: No reconnection or rotation occurs during normal operation. Subscriptions are updated dynamically without interrupting the WebSocket connection.

## 🔧 Advanced Settings

### WebSocket Performance

- **Handshake wait**: 1-2 seconds (connection stabilization)
- **Subscription**: Single message with all markets (no batching/rotation)
- **Max subscriptions**: 65,000 per Polymarket connection
- **Keepalive**:
  - Kalshi: 15-second ping/pong
  - Polymarket: 30-second ping/pong (recommended)
- **Reconnect strategy**: Exponential backoff (2s → 60s cap)
- **Connection persistence**: Maintain single connection, update subscriptions in-place

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

## 🔴 Known Issues & Recommended Fixes

### Critical Architecture Issues

The current implementation has several issues that cause WebSocket instability:

#### 1. Subscription Rotation (DEPRECATED)

**Location**: `polymarket_client.py:526-570`

**Problem**: The bot rotates through 20-market batches every 5 minutes, causing:
- Unnecessary WebSocket reconnects
- Data gaps during rotation
- Cloudflare throttling from connection churn

**Fix Required**:
```python
# REMOVE these from polymarket_client.py:
- _rotation_task method
- subscription_groups logic
- rotation_interval usage

# ADD instead:
async def update_subscriptions(self, new_market_ids: List[str]):
    """Update subscriptions in-place without reconnecting."""
    new_set = set(new_market_ids)
    to_subscribe = new_set - self.subscribed_assets
    to_unsubscribe = self.subscribed_assets - new_set
    # Subscribe/unsubscribe in-place
```

#### 2. Market Refresh Doesn't Update Subscriptions

**Location**: `supervisor.py:325-342`

**Problem**: `_market_refresh_loop` calls `refresh_markets()` but never updates WebSocket subscriptions. New markets discovered after startup are never subscribed to.

**Fix Required**:
```python
async def _market_refresh_loop(self):
    while self.running:
        await asyncio.sleep(self.config.market_refresh_interval)
        await self.market_discovery.refresh_markets()

        # ADD: Update subscriptions dynamically
        new_poly_ids = [m.metadata.get('token_id')
                       for m in self.market_discovery.polymarket_markets.values()]
        await self.polymarket_client.update_subscriptions(new_poly_ids)

        new_kalshi_ids = list(self.market_discovery.kalshi_markets.keys())
        await self.kalshi_client.update_subscriptions(new_kalshi_ids)
```

#### 3. Kalshi Auth Flow Creates Retry Loops

**Location**: `kalshi_client.py:96-133`

**Problem**: Bot tries email/password login first, gets 401, then falls back to API key. This creates unnecessary auth churn.

**Fix Required**:
```python
# Skip email/password entirely - use API key only
async def _authenticate(self):
    if self.config.kalshi_api_key:
        logger.info("Using Kalshi API key authentication")
        return  # API key used in headers
    else:
        raise ValueError("KALSHI_API_KEY required")
```

#### 4. Incorrect Ping Interval for Polymarket

**Location**: `polymarket_client.py:593-597`

**Problem**: Uses 15-second ping interval, but Polymarket prefers 30 seconds.

**Fix Required**:
```python
async with websockets.connect(
    self.ws_url,
    ping_interval=30,  # Changed from 15
    ping_timeout=10
) as ws:
```

#### 5. Config Access Pattern Issue

**Location**: `supervisor.py:188`

**Problem**: Uses `self.config.__dict__.get()` which is fragile.

**Fix Required**:
```python
# Change from:
max_markets = self.config.__dict__.get('max_markets_per_platform', 50)

# To:
max_markets = getattr(self.config, 'max_markets_per_platform', 50)
```

### Recommended Architecture Changes

1. **Single persistent connection** per platform (no rotation)
2. **Subscribe to ALL markets** at startup in single message
3. **Dynamic add/remove** subscriptions when markets change
4. **Skip deprecated auth** methods (use API key only for Kalshi)
5. **Update ping interval** to 30s for Polymarket

---

## 🐛 Troubleshooting

| Issue | Solution |
|-------|----------|
| `ModuleNotFoundError: pydantic_settings` | Run `./startup.sh --install` |
| WebSocket disconnects frequently | Check for rotation code (should be removed); verify ping intervals |
| Kalshi 401 errors | Verify KALSHI_API_KEY is set; don't use email/password |
| Polymarket no data received | Ensure token IDs are valid; check subscription message format |
| 0 market pairs found | Lower MARKET_SIMILARITY_THRESHOLD to 0.4-0.5 |
| High CPU usage | Verify UPDATE_INTERVAL=0.1 in .env |
| Cloudflare blocking | Reduce reconnection frequency; use persistent connections |
| Stale orderbook data | Check WebSocket connection health; verify keepalive timing |
| Memory growing over time | Ensure closed markets are unsubscribed and removed from tracking |
| New markets not receiving data | Implement dynamic subscription updates (see Issue #2 above) |

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

- **Initial subscription**: ~2-5 seconds (all markets in single message)
- **Scan frequency**: 10 Hz (0.1s interval)
- **Market refresh**: Every 5 minutes (REST API calls)
- **Subscription updates**: In-place, ~100ms per add/remove
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

- **1.1.0** (Nov 2024): Market discovery rewrite with category-based pairing
  - Category detection (SPORTS, POLITICS, MACRO_ECON, CRYPTO, etc.)
  - Time-horizon alignment for resolution dates
  - Multi-component scoring pipeline
  - Enhanced profitability logging with session summaries
  - Detailed per-opportunity trade logging
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
