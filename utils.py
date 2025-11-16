"""
Utility functions and helpers for the trading bot.
Includes retry logic, rate limiting, validation, and sanitization.
"""

import asyncio
import logging
from typing import Optional, Callable, Any
from datetime import datetime, timedelta
from functools import wraps
import hashlib
import re

logger = logging.getLogger(__name__)


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
