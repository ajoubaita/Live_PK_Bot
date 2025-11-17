# Production Issues Found - Critical Analysis

## Issue 1: Rate Limiter Does NOT Handle Burst + Sustained Dual Windows ❌
**Severity**: CRITICAL
**Location**: utils.py PolymarketRateLimiter

**Problem**:
- POST/DELETE /order requires BOTH:
  - Burst: 2400 req / 10s (240/s)
  - Sustained: 24000 req / 10min (40/s)
- DELETE /cancel-all requires BOTH:
  - Burst: 200 req / 10s
  - Sustained: 3000 req / 10min
- Current implementation only uses single window token bucket
- Will exceed sustained limits after initial burst

**Impact**: API throttling after burst phase, connection instability

---

## Issue 2: Polymarket WebSocket Subscribes Immediately After Connect ❌
**Severity**: CRITICAL
**Location**: polymarket_client.py:394-397

**Problem**:
- Subscriptions start immediately after `websockets.connect()`
- No wait for WebSocket handshake completion or ready state
- No confirmation that server is ready to receive subscriptions
- Disconnects after 2/40 markets suggests server rejecting early messages

**Impact**: "no close frame received" errors, unstable connections

---

## Issue 3: Market Pairing Returns 0 Matches (302,000 Comparisons) ❌
**Severity**: CRITICAL
**Location**: market_discovery.py:83-104, 124-177

**Problems**:
1. Stop words removal too aggressive - removes "will", "be", "in", "on", "at"
   - "Will Trump win" → "trump win"
   - "Will Biden be president" → "biden president"
   - Loses semantic meaning
2. Threshold 0.6 too high for prediction markets with different phrasing
3. No debug logging to see what's being compared
4. No fallback strategies (keyword matching, exact substring)

**Impact**: Zero cross-platform arbitrage opportunities detected

---

## Issue 4: Kalshi Token Not Persisting Across Reconnections ❌
**Severity**: HIGH
**Location**: kalshi_client.py:96-137

**Problem**:
- Token fetched in `_authenticate()`
- Set to expire after 23 hours
- But if initial auth fails, token remains None
- WebSocket connects with None token → 401
- No retry of authentication after failure

**Impact**: Persistent 401 errors, no Kalshi data

---

## Issue 5: Rate Limiters NOT Applied to All API Calls ❌
**Severity**: HIGH
**Location**: polymarket_client.py, kalshi_client.py

**Problem**:
- Rate limiter only applied to `fetch_markets()` and `fetch_orderbook()`
- NOT applied to:
  - Kalshi fetch_markets() - line 156
  - Kalshi fetch_orderbook() - line 202
  - Any future API calls
- Kalshi has no rate limiter at all

**Impact**: Potential API bans from Kalshi, unpredictable throttling

---

## Issue 6: WebSocket Subscription Uses Wrong Interval ❌
**Severity**: MEDIUM
**Location**: polymarket_client.py:276, kalshi_client.py:265

**Problem**:
- Code has conflicting keepalive intervals:
  - polymarket_client.py:276: `await asyncio.sleep(20)`
  - polymarket_client.py:380: `ping_interval=15`
  - Requirements specify 15s
- Inconsistency causes confusion

**Impact**: Suboptimal keepalive, potential connection drops

---

## Issue 7: No Graceful WebSocket Handshake Wait ❌
**Severity**: MEDIUM
**Location**: polymarket_client.py:357-410

**Problem**:
- After `websockets.connect()` returns, code immediately calls `_subscribe_with_throttling()`
- WebSocket connection might not be fully established
- Should wait for first message or confirmation before flooding with subscriptions

**Impact**: Early disconnections, "no close frame" errors
