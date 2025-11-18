"""
Utility functions and helpers for the trading bot.
Includes retry logic, rate limiting, validation, and sanitization.
"""

import asyncio
import logging
from typing import Optional, Callable, Any, List
from datetime import datetime, timedelta
from functools import wraps
import hashlib
import re

logger = logging.getLogger(__name__)


class DualWindowRateLimiter:
    """
    Dual-window rate limiter for handling both burst and sustained rate limits.

    Example: POST /order has:
    - Burst: 2400 req / 10s (240/s)
    - Sustained: 24000 req / 10min (40/s)

    Both limits must be honored simultaneously.
    """

    def __init__(
        self,
        burst_calls: int,
        burst_window: float,
        sustained_calls: int,
        sustained_window: float
    ):
        """Initialize dual-window rate limiter."""
        self.burst_calls = burst_calls
        self.burst_window = burst_window
        self.sustained_calls = sustained_calls
        self.sustained_window = sustained_window

        # Track call timestamps
        self.call_times: List[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self):
        """
        Acquire permission to make an API call.
        Blocks if either burst or sustained limit would be exceeded.
        """
        async with self._lock:
            now = datetime.utcnow().timestamp()

            # Remove old calls outside sustained window
            cutoff = now - self.sustained_window
            self.call_times = [t for t in self.call_times if t > cutoff]

            # Check burst limit (shorter window)
            burst_cutoff = now - self.burst_window
            recent_burst_calls = sum(1 for t in self.call_times if t > burst_cutoff)

            # Check sustained limit (longer window)
            recent_sustained_calls = len(self.call_times)

            # Calculate wait time needed
            wait_time = 0.0

            # If burst limit exceeded, wait until oldest burst call expires
            if recent_burst_calls >= self.burst_calls:
                burst_calls_in_window = [t for t in self.call_times if t > burst_cutoff]
                if burst_calls_in_window:
                    oldest_burst = min(burst_calls_in_window)
                    wait_burst = (oldest_burst + self.burst_window - now) + 0.1
                    wait_time = max(wait_time, wait_burst)

            # If sustained limit exceeded, wait until oldest sustained call expires
            if recent_sustained_calls >= self.sustained_calls:
                oldest_sustained = min(self.call_times)
                wait_sustained = (oldest_sustained + self.sustained_window - now) + 0.1
                wait_time = max(wait_time, wait_sustained)

            # Wait if necessary
            if wait_time > 0:
                logger.debug(f"Rate limit: waiting {wait_time:.2f}s (burst: {recent_burst_calls}/{self.burst_calls}, sustained: {recent_sustained_calls}/{self.sustained_calls})")
                await asyncio.sleep(wait_time)
                now = datetime.utcnow().timestamp()

            # Record this call
            self.call_times.append(now)


class RateLimiter:
    """
    Token bucket rate limiter for API calls.
    Prevents exceeding platform rate limits.
    """

    def __init__(self, calls_per_second: float = 10.0, burst: int = 20):
        """
        Initialize rate limiter.

        Args:
            calls_per_second: Average calls allowed per second
            burst: Maximum burst size
        """
        self.rate = calls_per_second
        self.burst = burst
        self.tokens = float(burst)
        self.last_update = datetime.utcnow()
        self._lock = asyncio.Lock()

    async def acquire(self):
        """
        Acquire permission to make an API call.
        Blocks if rate limit would be exceeded.
        """
        async with self._lock:
            now = datetime.utcnow()
            elapsed = (now - self.last_update).total_seconds()

            # Add tokens based on elapsed time
            self.tokens = min(
                self.burst,
                self.tokens + (elapsed * self.rate)
            )
            self.last_update = now

            # Wait if no tokens available
            if self.tokens < 1.0:
                wait_time = (1.0 - self.tokens) / self.rate
                await asyncio.sleep(wait_time)
                self.tokens = 0.0
            else:
                self.tokens -= 1.0


class CircuitBreaker:
    """
    Circuit breaker pattern for API calls.
    Opens circuit after repeated failures to prevent cascade.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        timeout: int = 60,
        expected_exception: type = Exception
    ):
        """
        Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening
            timeout: Seconds to wait before attempting reset
            expected_exception: Exception type to catch
        """
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.expected_exception = expected_exception
        self.failure_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.state = "closed"  # closed, open, half_open

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with circuit breaker protection.

        Args:
            func: Async function to call
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Function result

        Raises:
            Exception: If circuit is open or function fails
        """
        if self.state == "open":
            if self._should_attempt_reset():
                self.state = "half_open"
            else:
                raise Exception("Circuit breaker is OPEN - too many failures")

        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result

        except self.expected_exception as e:
            self._on_failure()
            raise e

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset."""
        if not self.last_failure_time:
            return True

        elapsed = (datetime.utcnow() - self.last_failure_time).total_seconds()
        return elapsed >= self.timeout

    def _on_success(self):
        """Handle successful call."""
        self.failure_count = 0
        self.state = "closed"

    def _on_failure(self):
        """Handle failed call."""
        self.failure_count += 1
        self.last_failure_time = datetime.utcnow()

        if self.failure_count >= self.failure_threshold:
            self.state = "open"
            logger.error(
                f"Circuit breaker OPENED after {self.failure_count} failures"
            )


async def retry_with_backoff(
    func: Callable,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential: bool = True,
    *args,
    **kwargs
) -> Any:
    """
    Retry an async function with exponential backoff.

    Args:
        func: Async function to retry
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        exponential: Use exponential backoff if True
        *args: Function positional arguments
        **kwargs: Function keyword arguments

    Returns:
        Function result

    Raises:
        Exception: If all retries exhausted
    """
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)

        except asyncio.CancelledError:
            raise  # Don't retry cancellations

        except Exception as e:
            last_exception = e

            if attempt < max_retries:
                if exponential:
                    delay = min(base_delay * (2 ** attempt), max_delay)
                else:
                    delay = base_delay

                logger.warning(
                    f"Attempt {attempt + 1}/{max_retries + 1} failed: {e}. "
                    f"Retrying in {delay:.1f}s..."
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    f"All {max_retries + 1} attempts failed. Last error: {e}"
                )

    raise last_exception


def sanitize_log_record(record: logging.LogRecord) -> logging.LogRecord:
    """
    Sanitize log records to remove sensitive information.

    Args:
        record: Log record to sanitize

    Returns:
        Sanitized log record
    """
    # Patterns to redact
    patterns = [
        (r'api[_-]?key["\']?\s*[:=]\s*["\']?([^"\'\s]+)', r'api_key=***REDACTED***'),
        (r'password["\']?\s*[:=]\s*["\']?([^"\'\s]+)', r'password=***REDACTED***'),
        (r'secret["\']?\s*[:=]\s*["\']?([^"\'\s]+)', r'secret=***REDACTED***'),
        (r'token["\']?\s*[:=]\s*["\']?([^"\'\s]+)', r'token=***REDACTED***'),
        (r'bearer\s+([^\s]+)', r'bearer ***REDACTED***'),
    ]

    # Sanitize message
    message = record.getMessage()
    for pattern, replacement in patterns:
        message = re.sub(pattern, replacement, message, flags=re.IGNORECASE)

    # Update record
    record.msg = message
    record.args = ()

    return record


class SanitizingFilter(logging.Filter):
    """Logging filter that sanitizes sensitive data."""

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Filter and sanitize log record.

        Args:
            record: Log record

        Returns:
            True to include record
        """
        sanitize_log_record(record)
        return True


def is_stale(timestamp: datetime, max_age_seconds: int = 30) -> bool:
    """
    Check if a timestamp is stale.

    Args:
        timestamp: Timestamp to check
        max_age_seconds: Maximum age before considering stale

    Returns:
        True if stale, False otherwise
    """
    if not timestamp:
        return True

    elapsed = (datetime.utcnow() - timestamp).total_seconds()
    return elapsed > max_age_seconds


def validate_price(price: float) -> bool:
    """
    Validate that a price is reasonable for prediction markets.

    Args:
        price: Price to validate (0-1 range)

    Returns:
        True if valid
    """
    if not isinstance(price, (int, float)):
        return False

    return 0.0 <= price <= 1.0


def validate_market_data(data: dict, required_fields: list) -> bool:
    """
    Validate that market data contains required fields.

    Args:
        data: Market data dictionary
        required_fields: List of required field names

    Returns:
        True if all required fields present
    """
    if not isinstance(data, dict):
        return False

    return all(field in data for field in required_fields)


def calculate_fees(
    price: float,
    size: int,
    platform: str,
    fee_rate: float = 0.01
) -> float:
    """
    Calculate trading fees for a platform.

    Args:
        price: Price per share
        size: Number of shares
        platform: Platform name (for platform-specific fees)
        fee_rate: Fee rate (default 1%)

    Returns:
        Total fees
    """
    # Platform-specific fee structures
    fee_rates = {
        'kalshi': 0.007,  # 0.7% fee
        'polymarket': 0.02,  # 2% fee on some markets
    }

    rate = fee_rates.get(platform.lower(), fee_rate)
    notional = price * size
    return notional * rate


def generate_correlation_id() -> str:
    """
    Generate a unique correlation ID for request tracing.

    Returns:
        Correlation ID string
    """
    timestamp = datetime.utcnow().isoformat()
    return hashlib.sha256(timestamp.encode()).hexdigest()[:16]


async def with_timeout(coro, timeout_seconds: float, default=None):
    """
    Execute coroutine with timeout.

    Args:
        coro: Coroutine to execute
        timeout_seconds: Timeout in seconds
        default: Default value to return on timeout

    Returns:
        Coroutine result or default value
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout_seconds)
    except asyncio.TimeoutError:
        logger.warning(f"Operation timed out after {timeout_seconds}s")
        return default


class PolymarketRateLimiter:
    """
    Comprehensive rate limiter for Polymarket API endpoints.
    Implements all documented rate limits across different API categories.
    """

    def __init__(self):
        """Initialize rate limiters for all Polymarket API endpoints."""
        # General rate limits
        self.general = RateLimiter(calls_per_second=5000/10, burst=5000)  # 5000 req / 10s
        self.ok_endpoint = RateLimiter(calls_per_second=50/10, burst=50)  # 50 req / 10s

        # Data API
        self.data_general = RateLimiter(calls_per_second=200/10, burst=200)  # 200 req / 10s
        self.data_trades = RateLimiter(calls_per_second=75/10, burst=75)  # 75 req / 10s
        self.data_ok = RateLimiter(calls_per_second=10/10, burst=10)  # 10 req / 10s

        # GAMMA API
        self.gamma_general = RateLimiter(calls_per_second=750/10, burst=750)  # 750 req / 10s
        self.gamma_events = RateLimiter(calls_per_second=100/10, burst=100)  # 100 req / 10s
        self.gamma_markets = RateLimiter(calls_per_second=125/10, burst=125)  # 125 req / 10s
        self.gamma_markets_events = RateLimiter(calls_per_second=100/10, burst=100)  # 100 req / 10s
        self.gamma_tags = RateLimiter(calls_per_second=100/10, burst=100)  # 100 req / 10s
        self.gamma_search = RateLimiter(calls_per_second=300/10, burst=300)  # 300 req / 10s

        # CLOB Market Data
        self.clob_book = RateLimiter(calls_per_second=200/10, burst=200)  # 200 req / 10s
        self.clob_books = RateLimiter(calls_per_second=80/10, burst=80)  # 80 req / 10s
        self.clob_price = RateLimiter(calls_per_second=200/10, burst=200)  # 200 req / 10s
        self.clob_prices = RateLimiter(calls_per_second=80/10, burst=80)  # 80 req / 10s
        self.clob_midprice = RateLimiter(calls_per_second=200/10, burst=200)  # 200 req / 10s
        self.clob_midprices = RateLimiter(calls_per_second=80/10, burst=80)  # 80 req / 10s

        # CLOB Ledger
        self.clob_ledger_general = RateLimiter(calls_per_second=300/10, burst=300)  # 300 req / 10s
        self.clob_data_orders = RateLimiter(calls_per_second=150/10, burst=150)  # 150 req / 10s
        self.clob_data_trades = RateLimiter(calls_per_second=150/10, burst=150)  # 150 req / 10s
        self.clob_notifications = RateLimiter(calls_per_second=125/10, burst=125)  # 125 req / 10s

        # CLOB Markets & Pricing
        self.clob_price_history = RateLimiter(calls_per_second=100/10, burst=100)  # 100 req / 10s
        self.clob_markets_list = RateLimiter(calls_per_second=250/10, burst=250)  # 250 req / 10s
        self.clob_market_detail = RateLimiter(calls_per_second=50/10, burst=50)  # 50 req / 10s
        self.clob_tick_size = RateLimiter(calls_per_second=50/10, burst=50)  # 50 req / 10s
        self.clob_markets_listing = RateLimiter(calls_per_second=100/10, burst=100)  # 100 req / 10s

        # CLOB Trading - DUAL WINDOW (burst + sustained)
        # POST /order: 2400 req/10s burst, 24000 req/10min sustained
        self.clob_order_post = DualWindowRateLimiter(
            burst_calls=2400, burst_window=10,
            sustained_calls=24000, sustained_window=600
        )
        # DELETE /order: same as POST
        self.clob_order_delete = DualWindowRateLimiter(
            burst_calls=2400, burst_window=10,
            sustained_calls=24000, sustained_window=600
        )
        # POST /orders: 800 req/10s burst, 12000 req/10min sustained
        self.clob_orders_post = DualWindowRateLimiter(
            burst_calls=800, burst_window=10,
            sustained_calls=12000, sustained_window=600
        )
        # DELETE /orders: same as POST
        self.clob_orders_delete = DualWindowRateLimiter(
            burst_calls=800, burst_window=10,
            sustained_calls=12000, sustained_window=600
        )
        # DELETE /cancel-all: 200 req/10s burst, 3000 req/10min sustained
        self.clob_cancel_all = DualWindowRateLimiter(
            burst_calls=200, burst_window=10,
            sustained_calls=3000, sustained_window=600
        )
        # DELETE /cancel-market-orders: 800 req/10s burst, 12000 req/10min sustained
        self.clob_cancel_market = DualWindowRateLimiter(
            burst_calls=800, burst_window=10,
            sustained_calls=12000, sustained_window=600
        )

        # Other
        self.relayer_submit = RateLimiter(calls_per_second=15/60, burst=15)  # 15 req / 1 min
        self.user_pnl = RateLimiter(calls_per_second=100/10, burst=100)  # 100 req / 10s

    async def acquire_for_endpoint(self, endpoint: str):
        """
        Acquire rate limit permission for a specific endpoint.

        Args:
            endpoint: API endpoint path or category
        """
        # Map endpoints to appropriate rate limiters
        if '/events' in endpoint:
            await self.gamma_events.acquire()
        elif '/markets' in endpoint and 'gamma-api' in endpoint:
            await self.gamma_markets.acquire()
        elif '/book' in endpoint:
            if '/books' in endpoint:
                await self.clob_books.acquire()
            else:
                await self.clob_book.acquire()
        elif '/price' in endpoint:
            if '/prices' in endpoint:
                await self.clob_prices.acquire()
            elif '/midprice' in endpoint:
                await self.clob_midprices.acquire()
            else:
                await self.clob_price.acquire()
        elif '/trades' in endpoint:
            if 'data-api' in endpoint:
                await self.data_trades.acquire()
            else:
                await self.clob_data_trades.acquire()
        elif '/orders' in endpoint:
            await self.clob_data_orders.acquire()
        elif '/notifications' in endpoint:
            await self.clob_notifications.acquire()
        elif '/search' in endpoint:
            await self.gamma_search.acquire()
        elif '/tags' in endpoint:
            await self.gamma_tags.acquire()
        elif '/submit' in endpoint:
            await self.relayer_submit.acquire()
        elif '/pnl' in endpoint:
            await self.user_pnl.acquire()
        else:
            # Default to general rate limit
            await self.general.acquire()


def format_uptime(seconds: float) -> str:
    """
    Format uptime in human-readable format.

    Args:
        seconds: Uptime in seconds

    Returns:
        Formatted string (e.g., "2d 3h 45m")
    """
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if secs > 0 or not parts:
        parts.append(f"{secs}s")

    return " ".join(parts)


class HealthCheck:
    """
    Health check utility for monitoring component status.
    """

    def __init__(self):
        """Initialize health check."""
        self.checks = {}
        self.last_check_time = {}

    def register(self, name: str, check_func: Callable):
        """
        Register a health check function.

        Args:
            name: Check name
            check_func: Async function that returns bool
        """
        self.checks[name] = check_func

    async def run_all(self) -> dict:
        """
        Run all registered health checks.

        Returns:
            Dictionary of check results
        """
        results = {}

        for name, check_func in self.checks.items():
            try:
                result = await check_func()
                results[name] = {
                    'status': 'healthy' if result else 'unhealthy',
                    'timestamp': datetime.utcnow().isoformat()
                }
                self.last_check_time[name] = datetime.utcnow()

            except Exception as e:
                results[name] = {
                    'status': 'error',
                    'error': str(e),
                    'timestamp': datetime.utcnow().isoformat()
                }
                logger.error(f"Health check '{name}' failed: {e}")

        return results

    def get_overall_status(self, results: dict) -> str:
        """
        Get overall health status.

        Args:
            results: Health check results

        Returns:
            'healthy', 'degraded', or 'unhealthy'
        """
        if not results:
            return 'unknown'

        statuses = [r['status'] for r in results.values()]

        if all(s == 'healthy' for s in statuses):
            return 'healthy'
        elif any(s == 'error' for s in statuses):
            return 'unhealthy'
        else:
            return 'degraded'
