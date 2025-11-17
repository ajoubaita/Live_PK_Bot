# Runtime Issues - Fixes and Deployment Guide

## 🔍 Issues Identified

After 14 hours of runtime, the following issues were observed:

### 1. **Polymarket WebSocket Disconnect Loop** ❌
- Connects and subscribes successfully
- Disconnects within 1-2 seconds
- Reconnects immediately in infinite loop
- No data processed

**Root Causes:**
- Sending 50 subscriptions too fast (rate limiting)
- No throttling between subscription messages
- Reconnect delay capped at 60s instead of 120s
- Poor error logging (no stack traces)
- No heartbeat monitoring

### 2. **Zero Arbitrage Opportunities Detected** ❌
- 1301 markets tracked
- 0 opportunities found
- 0 trades simulated
- $0.00 profit

**Root Causes:**
- No logging for why opportunities are skipped
- MIN_PROFIT_THRESHOLD might be too high (0.01 = 1 cent)
- No visibility into market pairs
- No logging of spreads that don't meet threshold

### 3. **Poor Observability** ❌
- Exceptions don't show stack traces
- No periodic summary metrics
- Can't tell if system is healthy or stuck

---

## ✅ Fixes Implemented

### Enhanced Polymarket WebSocket Client

**File**: `polymarket_client_enhanced.py`

**Improvements:**
1. ✅ **Exponential backoff up to 120s** (was 60s)
2. ✅ **Throttled subscriptions**: 10 at a time with 500ms delays
3. ✅ **Heartbeat monitoring**: Detects stale connections
4. ✅ **Ping/pong handling**: Explicit pings if no messages
5. ✅ **Better error logging**: All exceptions include stack traces
6. ✅ **Reconnection tracking**: Counts total reconnections
7. ✅ **Message debugging**: Logs first 5 messages for verification
8. ✅ **Subscription tracking**: Tracks which markets are subscribed

**Key Changes:**
```python
# OLD: No throttling
for market_id in market_ids:
    await ws.send(json.dumps(subscribe_msg))

# NEW: Throttled batches
batch_size = 10
for i in range(0, len(market_ids), batch_size):
    batch = market_ids[i:i + batch_size]
    for market_id in batch:
        await ws.send(json.dumps(subscribe_msg))
    await asyncio.sleep(0.5)  # Wait between batches
```

### Enhanced Arbitrage Engine

**File**: `arbitrage_engine_enhanced.py`

**Improvements:**
1. ✅ **Detailed skip logging**: Logs WHY opportunities are skipped
2. ✅ **Spread calculation logging**: Shows actual spreads vs threshold
3. ✅ **Periodic summaries**: Logs summary every 5 minutes
4. ✅ **Debug counters**: Tracks markets checked, skipped reasons
5. ✅ **Stack traces**: All errors include full stack traces
6. ✅ **Better opportunity logging**: Shows profit percentages

**Sample Logs:**
```
Skipped kalshi/MARKET123: Spread 0.008 below threshold 0.01
Skipped pair Trump Election (K->P): Spread 0.005 below threshold 0.01
✓ Intra-platform arbitrage on polymarket/MARKET456:
  Buy YES@0.48 + NO@0.51 = $0.99, Spread: $0.01, Profit: $1.00 (1.0%)

ARBITRAGE SCAN SUMMARY
Markets checked this scan: 1301
Skipped (no orderbook data): 842
Skipped (spread too low): 459
Market pairs available: 37
```

### Enhanced Market Discovery

**File**: `market_discovery_enhanced.py`

**Improvements:**
1. ✅ **Logs matched pairs at startup**: Shows sample pairs
2. ✅ **Pairing statistics**: High/medium/low confidence counts
3. ✅ **Sample market logging**: Shows first 5 from each platform
4. ✅ **Stack traces**: All errors logged with traces
5. ✅ **Detailed pairing summary**: Shows matching quality

**Sample Logs:**
```
Sample Market Pairs:
  1. [0.85] Kalshi: 'Trump wins 2024 election' <->
            Polymarket: 'Donald Trump 2024 Election Winner'
  2. [0.78] Kalshi: 'Fed rate hike March' <->
            Polymarket: 'Federal Reserve Rate Increase March 2024'
```

---

## 🚀 Deployment Instructions

### Step 1: Backup Current Files

```bash
cd /opt/arbitrage-bot

# Create backup directory
mkdir -p backups

# Backup current files
cp polymarket_client.py backups/polymarket_client.py.backup
cp arbitrage_engine.py backups/arbitrage_engine.py.backup
cp market_discovery.py backups/market_discovery.py.backup

echo "✓ Backup complete"
```

### Step 2: Stop the Bot

```bash
cd /opt/arbitrage-bot

# Stop bot
./startup.sh --stop

# Verify it's stopped
./startup.sh --status
```

### Step 3: Update Files from Git

```bash
cd /opt/arbitrage-bot

# Pull latest code with fixes
git pull origin claude/arbitrage-trading-bot-01HbkRunfc3TjZ292rRf1Eea

# Replace old files with enhanced versions
mv polymarket_client_enhanced.py polymarket_client.py
mv arbitrage_engine_enhanced.py arbitrage_engine.py
mv market_discovery_enhanced.py market_discovery.py

echo "✓ Files updated"
```

### Step 4: Update Configuration (Optional - For Testing)

**Reduce profit threshold temporarily to test detection:**

```bash
# Edit .env
nano /opt/arbitrage-bot/.env

# Change this line:
# MIN_PROFIT_THRESHOLD=0.01

# To this (for testing):
MIN_PROFIT_THRESHOLD=0.001

# Save and exit (Ctrl+X, Y, Enter)
```

**Enable DEBUG logging:**

```bash
# In .env, change:
# LOG_LEVEL=INFO

# To:
LOG_LEVEL=DEBUG
```

### Step 5: Restart the Bot

```bash
cd /opt/arbitrage-bot

# Activate virtual environment
source venv/bin/activate

# Start bot
./startup.sh --background

# Check status
./startup.sh --status
```

### Step 6: Monitor Logs

```bash
# Watch logs in real-time
tail -f /var/log/arbitrage-bot/trading_bot.log

# You should now see:
# - "Subscribed to batch X/Y" messages (throttling working)
# - "Skipped X: Spread Y below threshold Z" (detailed logging)
# - "MARKET PAIRING SUMMARY" at startup
# - "ARBITRAGE SCAN SUMMARY" every 5 minutes
# - Full stack traces for any errors
```

---

## 📊 What to Look For

### Healthy Polymarket WebSocket:

```
✓ Polymarket WebSocket connected (Total connections: 1)
Subscribing to 50 Polymarket markets in batches of 10...
Subscribed to batch 1/5
Subscribed to batch 2/5
...
✓ Successfully subscribed to 50 Polymarket markets
Polymarket message #1: {"type":"book","market":"0x..."}
Polymarket message #2: {"type":"book","market":"0x..."}
```

**Good signs:**
- Only reconnects once initially
- Batched subscription messages
- Receiving "book" messages
- No immediate disconnect loop

**Bad signs:**
- "Polymarket WebSocket connection closed" within 1-2 seconds
- No messages received
- Reconnect loop continues

### Healthy Arbitrage Detection:

```
MARKET PAIRING SUMMARY
Market pairs found: 37
Sample Market Pairs:
  1. [0.85] Kalshi: 'Trump wins...' <-> Polymarket: 'Donald Trump...'
  ...

Scanning 150 kalshi markets for intra-platform arbitrage...
Skipped kalshi/MARKET1: Spread 0.008 below threshold 0.001
Skipped kalshi/MARKET2: Spread 0.0005 below threshold 0.001
✓ Intra-platform arbitrage on kalshi/MARKET3: ... Profit: $5.00
```

**Good signs:**
- Market pairs being found (>0)
- Detailed skip reasons
- Some opportunities found (even if rare)
- Periodic summaries every 5 minutes

**Bad signs:**
- 0 market pairs found
- All markets "Skipped: Missing orderbook data"
- No summary logs appear

---

## 🔧 Troubleshooting

### Issue: Polymarket Still Disconnecting Immediately

**Check:**
```bash
# Look for this in logs:
tail -100 /var/log/arbitrage-bot/trading_bot.log | grep -A 5 "Polymarket WebSocket"
```

**Possible causes:**
- API endpoint changed (check Polymarket docs)
- Subscription message format incorrect
- Rate limit still being hit (increase delay)

**Fix:**
```python
# In polymarket_client.py, increase delay
delay_between_batches = 1.0  # Change from 0.5 to 1.0 second
```

### Issue: Still 0 Opportunities Found

**Check if markets are being discovered:**
```bash
tail -100 /var/log/arbitrage-bot/trading_bot.log | grep "Discovered"
# Should show: "Discovered X Kalshi markets and Y Polymarket markets"
```

**Check if pairs are being created:**
```bash
tail -100 /var/log/arbitrage-bot/trading_bot.log | grep "MARKET PAIRING SUMMARY" -A 10
# Should show number of pairs found
```

**Check if orderbook data is available:**
```bash
tail -500 /var/log/arbitrage-bot/trading_bot.log | grep "Skipped.*Missing orderbook"
# If this shows hundreds of markets, orderbook data isn't coming through
```

**Temporary fix to test detection:**
```bash
# Lower threshold even more
nano /opt/arbitrage-bot/.env
# Set: MIN_PROFIT_THRESHOLD=0.0001

# Restart
./startup.sh --stop && ./startup.sh --background
```

### Issue: No Summary Logs Appearing

**Check scan count:**
```bash
tail -100 /var/log/arbitrage-bot/trading_bot.log | grep "scan_count"
```

**If scans aren't running:**
- Check if arbitrage loop is stuck
- Look for errors in supervisor
- Restart the bot

---

## 📈 Performance Improvements

### After Fixes Applied:

**WebSocket Stability:**
- ✅ Should maintain connection for hours/days
- ✅ Only reconnects on actual network issues
- ✅ Receives continuous price updates

**Arbitrage Detection:**
- ✅ Clear visibility into why opportunities are missed
- ✅ Can tune MIN_PROFIT_THRESHOLD based on logs
- ✅ Knows how many market pairs are available

**Observability:**
- ✅ Summary every 5 minutes
- ✅ Full stack traces for debugging
- ✅ Can see system health at a glance

---

## 🎯 Expected Behavior After Fixes

### First 10 Minutes:
1. Bot starts and discovers markets
2. Logs "MARKET PAIRING SUMMARY" with pairs found
3. Subscribes to Polymarket markets in batches
4. Shows "Subscribed to batch X/Y" messages
5. Starts receiving orderbook updates
6. Begins scanning for arbitrage
7. Logs "Skipped" messages with reasons

### First Hour:
1. Periodic "ARBITRAGE SCAN SUMMARY" every 5 minutes
2. Polymarket WebSocket stays connected
3. Opportunities detected (if market conditions allow)
4. Trades simulated and logged

### After 14 Hours:
1. Polymarket reconnections: 0-2 (only on real network issues)
2. Markets tracked: 1000+
3. Opportunities detected: 0-100+ (depends on markets)
4. Detailed logs showing WHY most are skipped

---

## ✅ Success Criteria

**Polymarket WebSocket:**
- [ ] Stays connected for >1 hour
- [ ] Receives orderbook messages
- [ ] Reconnect count < 5 in 24 hours

**Arbitrage Detection:**
- [ ] Market pairs found > 0
- [ ] "Skipped" logs show reasons
- [ ] Summaries appear every 5 minutes
- [ ] At least 1 opportunity found (even if threshold lowered)

**Observability:**
- [ ] Stack traces visible for errors
- [ ] Can see why opportunities missed
- [ ] Summary metrics every 5 minutes

---

## 📞 Next Steps

1. **Deploy the fixes** using instructions above
2. **Monitor for 1 hour** to verify WebSocket stability
3. **Check logs** to see skip reasons
4. **Adjust MIN_PROFIT_THRESHOLD** based on logged spreads
5. **Report back** with:
   - Polymarket reconnect count after 1 hour
   - Sample "Skipped" messages from logs
   - Number of market pairs found
   - Any opportunities detected

---

## 🔄 Rollback Plan

If issues persist:

```bash
cd /opt/arbitrage-bot

# Stop bot
./startup.sh --stop

# Restore backups
cp backups/polymarket_client.py.backup polymarket_client.py
cp backups/arbitrage_engine.py.backup arbitrage_engine.py
cp backups/market_discovery.py.backup market_discovery.py

# Restart
./startup.sh --background
```

---

**All fixes are backward compatible. The enhanced versions are drop-in replacements.**
