"""
Data models for the arbitrage trading bot.
Defines the core data structures used throughout the system.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, List
from decimal import Decimal


class Platform(str, Enum):
    """Trading platform enumeration."""
    KALSHI = "kalshi"
    POLYMARKET = "polymarket"


class Side(str, Enum):
    """Trade side enumeration."""
    BUY = "buy"
    SELL = "sell"


class Outcome(str, Enum):
    """Market outcome enumeration."""
    YES = "yes"
    NO = "no"


@dataclass
class PriceLevel:
    """Represents a price level in an order book."""
    price: float
    size: int
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self):
        """Validate price level data."""
        if self.price < 0 or self.price > 1:
            raise ValueError(f"Price must be between 0 and 1, got {self.price}")
        if self.size < 0:
            raise ValueError(f"Size must be non-negative, got {self.size}")


@dataclass
class OrderBook:
    """
    Represents an order book for a market outcome.
    Maintains best bid and ask prices.
    """
    platform: Platform
    market_id: str
    outcome: Outcome
    best_bid: Optional[PriceLevel] = None
    best_ask: Optional[PriceLevel] = None
    last_update: datetime = field(default_factory=datetime.utcnow)

    def update_bid(self, price: float, size: int):
        """Update the best bid price."""
        self.best_bid = PriceLevel(price=price, size=size)
        self.last_update = datetime.utcnow()

    def update_ask(self, price: float, size: int):
        """Update the best ask price."""
        self.best_ask = PriceLevel(price=price, size=size)
        self.last_update = datetime.utcnow()

    def is_stale(self, timeout_seconds: int = 30) -> bool:
        """
        Check if the order book is stale (hasn't been updated recently).

        Args:
            timeout_seconds: Number of seconds before considering data stale

        Returns:
            True if data is stale, False otherwise
        """
        if not self.last_update:
            return True
        elapsed = (datetime.utcnow() - self.last_update).total_seconds()
        return elapsed > timeout_seconds

    def has_valid_prices(self) -> bool:
        """Check if both bid and ask are available."""
        return self.best_bid is not None and self.best_ask is not None


@dataclass
class Market:
    """
    Represents a market on a trading platform.
    """
    platform: Platform
    market_id: str
    title: str
    question: str
    active: bool = True
    yes_orderbook: Optional[OrderBook] = None
    no_orderbook: Optional[OrderBook] = None
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self):
        """Initialize order books if not provided."""
        if self.yes_orderbook is None:
            self.yes_orderbook = OrderBook(
                platform=self.platform,
                market_id=self.market_id,
                outcome=Outcome.YES
            )
        if self.no_orderbook is None:
            self.no_orderbook = OrderBook(
                platform=self.platform,
                market_id=self.market_id,
                outcome=Outcome.NO
            )

    def get_normalized_title(self) -> str:
        """
        Get a normalized version of the market title for matching.
        Converts to lowercase and removes special characters.
        """
        import re
        normalized = self.title.lower()
        normalized = re.sub(r'[^\w\s]', '', normalized)
        normalized = ' '.join(normalized.split())
        return normalized


@dataclass
class MarketPair:
    """
    Represents a pair of matching markets across platforms.
    """
    kalshi_market: Market
    polymarket_market: Market
    confidence: float = 1.0  # Confidence in the pairing (0-1)
    created_at: datetime = field(default_factory=datetime.utcnow)

    def __str__(self):
        return f"Pair: {self.kalshi_market.title} <-> {self.polymarket_market.title}"


@dataclass
class ArbitrageOpportunity:
    """
    Represents a detected arbitrage opportunity.
    """
    opportunity_id: str
    timestamp: datetime
    opportunity_type: str  # 'intra-platform' or 'cross-platform'
    platform: Optional[Platform]  # For intra-platform arb
    market_pair: Optional[MarketPair]  # For cross-platform arb
    single_market: Optional[Market]  # For intra-platform arb

    # Trade details
    buy_platform: Platform
    buy_market_id: str
    buy_outcome: Outcome
    buy_price: float
    buy_size: int

    sell_platform: Platform
    sell_market_id: str
    sell_outcome: Outcome
    sell_price: float
    sell_size: int

    # Profit calculation
    expected_profit: float
    expected_return_pct: float

    # Execution status
    simulated: bool = False
    simulation_timestamp: Optional[datetime] = None

    def to_dict(self) -> Dict:
        """Convert to dictionary for logging."""
        return {
            'opportunity_id': self.opportunity_id,
            'timestamp': self.timestamp.isoformat(),
            'type': self.opportunity_type,
            'buy': {
                'platform': self.buy_platform.value,
                'market_id': self.buy_market_id,
                'outcome': self.buy_outcome.value,
                'price': self.buy_price,
                'size': self.buy_size
            },
            'sell': {
                'platform': self.sell_platform.value,
                'market_id': self.sell_market_id,
                'outcome': self.sell_outcome.value,
                'price': self.sell_price,
                'size': self.sell_size
            },
            'profit': self.expected_profit,
            'return_pct': self.expected_return_pct,
            'simulated': self.simulated,
            'simulation_timestamp': self.simulation_timestamp.isoformat() if self.simulation_timestamp else None
        }


@dataclass
class BotMetrics:
    """
    Runtime metrics for the trading bot.
    """
    start_time: datetime = field(default_factory=datetime.utcnow)
    markets_tracked: int = 0
    opportunities_detected: int = 0
    trades_simulated: int = 0
    total_simulated_profit: float = 0.0
    last_opportunity_time: Optional[datetime] = None
    kalshi_connected: bool = False
    polymarket_connected: bool = False
    last_error: Optional[str] = None
    last_error_time: Optional[datetime] = None

    def uptime(self) -> float:
        """Get uptime in seconds."""
        return (datetime.utcnow() - self.start_time).total_seconds()

    def uptime_str(self) -> str:
        """Get uptime as a formatted string (HH:MM:SS)."""
        seconds = int(self.uptime())
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    def to_dict(self) -> Dict:
        """Convert metrics to dictionary."""
        return {
            'uptime': self.uptime_str(),
            'markets_tracked': self.markets_tracked,
            'opportunities_detected': self.opportunities_detected,
            'trades_simulated': self.trades_simulated,
            'total_simulated_profit': round(self.total_simulated_profit, 2),
            'kalshi_connected': self.kalshi_connected,
            'polymarket_connected': self.polymarket_connected,
            'last_error': self.last_error,
            'last_error_time': self.last_error_time.isoformat() if self.last_error_time else None
        }
