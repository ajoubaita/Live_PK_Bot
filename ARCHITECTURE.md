# Architecture Documentation

## System Overview

The arbitrage trading bot is a fully asynchronous, event-driven system designed for high-frequency trading simulations across Kalshi and Polymarket prediction markets.

## Core Components

### 1. Configuration Layer (`config.py`)
- **Purpose**: Centralized configuration management
- **Features**:
  - Environment variable loading with `.env` support
  - Pydantic-based validation
  - Type-safe configuration access
  - Sensible defaults

### 2. Data Models (`models.py`)
- **Purpose**: Type-safe data structures
- **Key Models**:
  - `Platform`: Enum for KALSHI/POLYMARKET
  - `Market`: Represents a prediction market
  - `OrderBook`: In-memory order book with best bid/ask
  - `MarketPair`: Cross-platform market pairing
  - `ArbitrageOpportunity`: Detected arbitrage with full details
  - `BotMetrics`: Runtime performance metrics

### 3. API Clients

#### Kalshi Client (`kalshi_client.py`)
- **REST API**: Market fetching, order book snapshots
- **WebSocket**: Real-time orderbook delta updates
- **Authentication**: Email/password or API key
- **Auto-reconnect**: Exponential backoff on failures

#### Polymarket Client (`polymarket_client.py`)
- **REST API**: Event/market fetching via Gamma API
- **WebSocket**: Real-time price updates
- **Authentication**: Optional API key
- **Auto-reconnect**: Exponential backoff on failures

### 4. Market Discovery (`market_discovery.py`)
- **Purpose**: Find and pair equivalent markets
- **Features**:
  - Concurrent market fetching from both platforms
  - Fuzzy text matching using SequenceMatcher
  - Normalized title comparison
  - Confidence scoring for pairs
  - Periodic refresh to catch new markets

### 5. Order Book Manager (`orderbook_manager.py`)
- **Purpose**: Maintain real-time order books in memory
- **Features**:
  - In-memory storage: `{platform: {market_id: {outcome: OrderBook}}}`
  - WebSocket message processing
  - Thread-safe updates with asyncio locks
  - Staleness detection
  - Fast price lookups (O(1))

### 6. Arbitrage Engine (`arbitrage_engine.py`)
- **Purpose**: Detect and evaluate arbitrage opportunities
- **Strategies**:

  **Intra-Platform:**
  - Buy YES + NO when combined price < $1.00
  - Guaranteed profit on settlement

  **Cross-Platform:**
  - Buy low on Platform A, sell high on Platform B
  - Profit from price inefficiencies

- **Features**:
  - Continuous scanning
  - Profit threshold filtering
  - Trade size optimization
  - Re-validation before execution

### 7. Trade Logger (`trade_logger.py`)
- **Purpose**: Persistent storage of trades and metrics
- **Dual Storage**:
  - **JSON Lines**: Human-readable, easily parseable
  - **SQLite**: Queryable database for analytics
- **Features**:
  - Async I/O for non-blocking writes
  - Structured logging
  - Metrics tracking over time
  - Trade history queries

### 8. Supervisor (`supervisor.py`)
- **Purpose**: Orchestrate all components and manage lifecycle
- **Responsibilities**:
  - Component initialization
  - Task spawning and management
  - Health monitoring
  - Graceful shutdown
  - Signal handling (SIGINT/SIGTERM)
- **Background Tasks**:
  - Arbitrage scanning loop
  - Market refresh loop
  - Health check loop
  - Metrics logging loop
  - Status display loop

### 9. Main Entry Point (`main.py`)
- **Purpose**: Application bootstrap
- **Features**:
  - Logging configuration
  - Event loop setup (with optional uvloop)
  - Supervisor initialization
  - Error handling
  - Clean exit codes

## Data Flow

### Market Data Flow
```
API (REST) → Client → Market Discovery → Market Storage
                ↓
        WebSocket Subscribe
                ↓
API (WS) → Client → OrderBook Manager → In-Memory Books
                                              ↓
                                    Arbitrage Engine
                                              ↓
                                    Trade Logger → SQLite + JSON
```

### Arbitrage Detection Flow
```
Arbitrage Engine (scan timer)
    ↓
Get all market order books
    ↓
For each market/pair:
    - Calculate potential profit
    - Check threshold
    - Validate sizes
    ↓
If opportunity found:
    - Re-validate current prices
    - Calculate trade size
    - Simulate execution
    - Log to storage
    - Update metrics
```

### Component Lifecycle
```
main.py
    ↓
Setup Logging
    ↓
Create Supervisor
    ↓
Initialize Components
    ↓
Start Background Tasks ─┐
    │                   │
    ├─ WebSocket Feeds  │
    ├─ Arbitrage Loop   │
    ├─ Market Refresh   ├─ Run until shutdown signal
    ├─ Health Checks    │
    ├─ Metrics Logger   │
    └─ Status Display   │
                        ↓
Signal Received (SIGINT/SIGTERM)
    ↓
Set Shutdown Event
    ↓
Cancel All Tasks
    ↓
Close Connections
    ↓
Flush Logs
    ↓
Exit
```

## Concurrency Model

### Async Task Management
- **Main Event Loop**: Single-threaded asyncio
- **Concurrent WebSockets**: One persistent connection per platform
- **Non-blocking I/O**: All network and disk operations are async
- **Task Isolation**: Each background task is independent
- **Shared State**: Protected by asyncio.Lock for thread-safety

### Task Priority
1. **High**: WebSocket message processing (real-time data)
2. **Medium**: Arbitrage scanning (opportunity detection)
3. **Low**: Metrics logging, status display (background)

## Error Handling Strategy

### Levels of Recovery

**Level 1 - Retry**
- Network timeouts
- Temporary API errors
- WebSocket disconnections
→ Exponential backoff and retry

**Level 2 - Skip & Log**
- Malformed data
- Missing order book data
- Invalid market info
→ Log warning, continue operation

**Level 3 - Component Restart**
- Client connection failures
- Database errors
→ Reinitialize component

**Level 4 - Graceful Shutdown**
- Fatal configuration errors
- Unrecoverable API issues
→ Log error, clean shutdown

## Performance Considerations

### Optimizations
1. **In-Memory Storage**: O(1) order book lookups
2. **Async I/O**: Non-blocking operations throughout
3. **uvloop**: Optional faster event loop (Linux/macOS)
4. **Connection Pooling**: Reuse HTTP connections
5. **Batch Operations**: Group database writes when possible

### Bottlenecks
- **Network Latency**: Primary factor in arbitrage detection
- **WebSocket Throughput**: Message processing rate
- **Database Writes**: Async to minimize impact
- **Scanning Frequency**: Configurable via UPDATE_INTERVAL

### Scalability
- **Vertical**: Add more CPU/memory for faster scanning
- **Horizontal**: Run multiple instances with different market subsets
- **Geographic**: Deploy closer to API endpoints for lower latency

## Security Architecture

### Credentials Management
- Environment variables for secrets
- No hardcoded credentials
- .env file with restricted permissions (600)
- .gitignore protection

### Network Security
- HTTPS for all REST calls
- WSS (WebSocket Secure) for real-time data
- Firewall rules to restrict access
- Optional VPN for additional security

### Data Security
- SQLite file permissions
- Log rotation to prevent disk filling
- Sensitive data not logged
- Simulation mode prevents real financial risk

## Monitoring & Observability

### Metrics Collected
- Markets tracked
- Opportunities detected
- Trades simulated
- Total profit (simulated)
- Connection status
- Uptime
- Last error timestamp

### Logging Levels
- **DEBUG**: Detailed execution flow
- **INFO**: Normal operations, trades
- **WARNING**: Recoverable issues
- **ERROR**: Serious problems

### Health Checks
- WebSocket connection status
- Last message timestamp
- Order book staleness
- Component initialization status

## Deployment Architecture

### Development
```
Local Machine
    ├─ Python 3.9+
    ├─ Virtual Environment
    ├─ .env file
    └─ Manual execution
```

### Production
```
Cloud Server (AWS/GCP/DO)
    ├─ Ubuntu 22.04 LTS
    ├─ Supervisor (process manager)
    ├─ Python 3.11
    ├─ Virtual Environment
    ├─ .env with secrets
    ├─ Firewall (UFW)
    ├─ Auto-restart on failure
    └─ Log rotation
```

## Testing Strategy

### Component Testing
- Mock API responses
- Simulated WebSocket messages
- Order book state verification
- Arbitrage calculation validation

### Integration Testing
- End-to-end flow with test data
- Database operations
- Configuration validation

### Performance Testing
- Load testing with multiple markets
- WebSocket throughput
- Memory leak detection
- CPU profiling

## Future Enhancements

### Potential Features
1. **Real Trading**: Order placement and execution
2. **Machine Learning**: Price prediction models
3. **Multi-Strategy**: Additional arbitrage strategies
4. **Risk Management**: Position sizing, stop-loss
5. **Web Dashboard**: Real-time monitoring UI
6. **Backtesting**: Historical data analysis
7. **Alert System**: Email/SMS notifications
8. **API Server**: Expose metrics via REST API

### Scalability Improvements
1. Redis for distributed order books
2. Message queue (RabbitMQ) for event processing
3. Microservices architecture
4. Load balancing across instances
5. Time-series database (InfluxDB) for metrics

---

**Built for high-frequency, low-latency arbitrage trading**
