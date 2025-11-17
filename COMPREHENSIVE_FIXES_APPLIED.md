# Comprehensive Production Fixes Applied

## ✅ Fix 1: Dual-Window Rate Limiting for Burst + Sustained (COMPLETE)

**File**: `utils.py`
**Lines**: 17-96

**What was fixed**:
- Created `DualWindowRateLimiter` class that tracks call timestamps
- Enforces BOTH burst and sustained limits simultaneously
- Example: POST /order enforces 2400 req/10s AND 24000 req/10min

**Implementation**:
```python
class DualWindowRateLimiter:
    # Tracks call timestamps
    # Removes expired calls outside sustained window
    # Checks both burst (10s) and sustained (600s) windows
    # Waits if either limit would be exceeded
```

**Impact**: Prevents API bans from exceeding sustained limits after burst phase

---

## ✅ Fix 2: PolymarketRateLimiter with All Documented Limits (COMPLETE)

**File**: `utils.py`
**Lines**: 442-586

**What was fixed**:
- Added ALL Polymarket rate limits from documentation
- Used `DualWindowRateLimiter` for trading endpoints with burst+sustained
- Added CLOB Balance limit (125 req/10s)
- RELAYER /submit correctly set to 15 req/1min (strict)

**Rate limits now enforced**:
- Data API: General (200/10s), /trades (75/10s)
- GAMMA: /markets (125/10s), /events (100/10s)
- CLOB Market Data: /book (200/10s), /books (80/10s), /price (200/10s)
- CLOB Balance: GET (125/10s)
- CLOB Trading with DUAL WINDOWS:
  - POST /order: 2400/10s burst, 24000/10min sustained
  - DELETE /order: 2400/10s burst, 24000/10min sustained
  - POST /orders: 800/10s burst, 12000/10min sustained
  - DELETE /orders: 800/10s burst, 12000/10min sustained
  - DELETE /cancel-all: 200/10s burst, 3000/10min sustained
  - DELETE /cancel-market: 800/10s burst, 12000/10min sustained

**Impact**: Comprehensive rate limit compliance, no throttling errors

---

## 🔧 Fix 3: Polymarket WebSocket Handshake Wait (TO BE APPLIED)

**Problem**: Subscriptions start immediately after `websockets.connect()`, causing "no close frame" errors

**Solution**:
1. Wait 1 second after connection before subscriptions
2. Add connection state validation
3. Reduce initial subscription throttle from 0.25s to 0.5s
4. Fix keepalive interval inconsistency (20s → 15s)

**Changes needed in `polymarket_client.py`**:
```python
# After websockets.connect():
await asyncio.sleep(1.0)  # Wait for handshake completion
logger.info("WebSocket handshake complete, starting subscriptions...")

# In _subscribe_with_throttling():
await asyncio.sleep(0.5)  # Slower throttle: 0.25s → 0.5s
```

---

## 🔧 Fix 4: Market Pairing Improvements (TO BE APPLIED)

**Problem**: 0 matches out of 302,000 comparisons. Stop words too aggressive, threshold too high.

**Solutions**:
1. Reduce stop words (keep important words like "will", "be")
2. Lower similarity threshold from 0.6 to 0.4
3. Add keyword-based fallback matching
4. Add comprehensive debug logging

**Changes needed in `market_discovery.py`**:
```python
# Minimal stop words
stop_words = {'the', 'a', 'an'}  # Removed: will, be, in, on, at, to, for, of

# Lower threshold
similarity_threshold = 0.4  # Was 0.6

# Add debug logging
logger.info(f"Comparing: '{kalshi_market.title}' vs '{poly_market.title}' = {similarity:.3f}")

# Keyword fallback
if best_score < 0.4:
    # Try exact keyword matching
    kalshi_keywords = set(norm1.split())
    poly_keywords = set(norm2.split())
    overlap = len(kalshi_keywords & poly_keywords) / len(kalshi_keywords | poly_keywords)
    if overlap > 0.3:
        logger.info(f"Keyword match fallback: {overlap:.3f}")
```

---

## 🔧 Fix 5: Kalshi Rate Limiting (TO BE APPLIED)

**Problem**: No rate limiting on Kalshi API calls

**Solution**: Create KalshiRateLimiter similar to Polymarket

**Changes needed**:
- Add `KalshiRateLimiter` class in `utils.py`
- Apply to `fetch_markets()` and `fetch_orderbook()` in `kalshi_client.py`
- Kalshi rate limits (estimated from best practices):
  - General: 100 req/10s
  - Markets: 50 req/10s
  - Orderbook: 100 req/10s

---

## 🔧 Fix 6: Kalshi Authentication Improvements (TO BE APPLIED)

**Problem**: Token not persisting, 401 errors on WebSocket

**Solution**:
1. Retry authentication on failure with exponential backoff
2. Log authentication status clearly
3. Ensure token is refreshed before expiry

**Changes in `kalshi_client.py`**:
```python
async def _authenticate(self):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # ... auth logic ...
            if response.status == 200:
                logger.info("Kalshi authentication successful")
                return
            else:
                logger.error(f"Auth failed (attempt {attempt+1}/{max_retries})")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
        except Exception as e:
            logger.error(f"Auth exception (attempt {attempt+1}): {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)

    logger.error("Kalshi authentication failed after all retries")
```

---

## 📊 Priority Summary

| Fix | Status | Severity | Impact |
|-----|--------|----------|--------|
| Dual-Window Rate Limiter | ✅ COMPLETE | CRITICAL | Prevents API bans |
| Polymarket Rate Limits | ✅ COMPLETE | CRITICAL | Full compliance |
| Polymarket WS Handshake | 🔧 PENDING | CRITICAL | Fixes disconnects |
| Market Pairing | 🔧 PENDING | CRITICAL | Enables cross-platform arb |
| Kalshi Rate Limiting | 🔧 PENDING | HIGH | Prevents throttling |
| Kalshi Auth Retry | 🔧 PENDING | HIGH | Fixes 401 errors |

---

## Next Steps

1. Apply fixes 3-6 (handshake wait, market pairing, Kalshi improvements)
2. Test syntax with `python3 -m py_compile`
3. Commit all changes
4. Deploy to production
5. Monitor logs for:
   - "WebSocket handshake complete" message
   - Market pairing success count
   - No 401 errors from Kalshi
   - Rate limit wait messages (should be rare)
