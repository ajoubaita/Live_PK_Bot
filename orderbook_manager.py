"""
Order book manager module.
Maintains in-memory order books and processes real-time updates.
"""

import asyncio
import logging
from typing import Dict, Optional, Tuple
from datetime import datetime

from models import Market, OrderBook, Platform, Outcome, PriceLevel
from config import get_config

logger = logging.getLogger(__name__)


class OrderBookManager:
    """
    Manages in-memory order books for all tracked markets.
    Processes WebSocket updates and maintains current best bid/ask.
    """

    def __init__(self):
        """Initialize the order book manager."""
        self.config = get_config()
        # Dictionary structure: {platform: {market_id: {outcome: OrderBook}}}
        self.orderbooks: Dict[Platform, Dict[str, Dict[Outcome, OrderBook]]] = {
            Platform.KALSHI: {},
            Platform.POLYMARKET: {}
        }
        self._lock = asyncio.Lock()

    async def initialize_market(self, market: Market):
        """
        Initialize order books for a market.

        Args:
            market: Market object to initialize
        """
        async with self._lock:
            platform = market.platform
            market_id = market.market_id

            if platform not in self.orderbooks:
                self.orderbooks[platform] = {}

            if market_id not in self.orderbooks[platform]:
                self.orderbooks[platform][market_id] = {
                    Outcome.YES: OrderBook(
                        platform=platform,
                        market_id=market_id,
                        outcome=Outcome.YES
                    ),
                    Outcome.NO: OrderBook(
                        platform=platform,
                        market_id=market_id,
                        outcome=Outcome.NO
                    )
                }

                logger.debug(f"Initialized orderbooks for {platform.value} market {market_id}")

    async def handle_websocket_message(self, platform: Platform, message: Dict):
        """
        Process WebSocket messages and update order books.

        Args:
            platform: Platform the message came from
            message: Message data dictionary
        """
        try:
            if platform == Platform.KALSHI:
                await self._handle_kalshi_message(message)
            elif platform == Platform.POLYMARKET:
                await self._handle_polymarket_message(message)

        except Exception as e:
            logger.error(f"Error handling WebSocket message from {platform.value}: {e}")

    async def _handle_kalshi_message(self, message: Dict):
        """
        Handle Kalshi WebSocket messages.

        Args:
            message: Kalshi message data
        """
        try:
            msg_type = message.get('type', '')

            if msg_type == 'orderbook_delta':
                # Kalshi sends orderbook delta updates
                market_id = message.get('market_ticker')
                if not market_id:
                    return

                # Get the orderbook data
                orderbook_data = message.get('orderbook', {})

                # Update YES orderbook
                yes_bids = orderbook_data.get('yes', {}).get('bids', [])
                yes_asks = orderbook_data.get('yes', {}).get('asks', [])

                if yes_bids:
                    best_yes_bid = yes_bids[0]  # [price, size]
                    await self.update_orderbook(
                        platform=Platform.KALSHI,
                        market_id=market_id,
                        outcome=Outcome.YES,
                        bid_price=best_yes_bid[0] / 100.0,  # Kalshi prices in cents
                        bid_size=best_yes_bid[1],
                        ask_price=None,
                        ask_size=None
                    )

                if yes_asks:
                    best_yes_ask = yes_asks[0]
                    await self.update_orderbook(
                        platform=Platform.KALSHI,
                        market_id=market_id,
                        outcome=Outcome.YES,
                        bid_price=None,
                        bid_size=None,
                        ask_price=best_yes_ask[0] / 100.0,
                        ask_size=best_yes_ask[1]
                    )

                # Update NO orderbook
                no_bids = orderbook_data.get('no', {}).get('bids', [])
                no_asks = orderbook_data.get('no', {}).get('asks', [])

                if no_bids:
                    best_no_bid = no_bids[0]
                    await self.update_orderbook(
                        platform=Platform.KALSHI,
                        market_id=market_id,
                        outcome=Outcome.NO,
                        bid_price=best_no_bid[0] / 100.0,
                        bid_size=best_no_bid[1],
                        ask_price=None,
                        ask_size=None
                    )

                if no_asks:
                    best_no_ask = no_asks[0]
                    await self.update_orderbook(
                        platform=Platform.KALSHI,
                        market_id=market_id,
                        outcome=Outcome.NO,
                        bid_price=None,
                        bid_size=None,
                        ask_price=best_no_ask[0] / 100.0,
                        ask_size=best_no_ask[1]
                    )

        except Exception as e:
            logger.error(f"Error processing Kalshi message: {e}")

    async def _handle_polymarket_message(self, message: Dict):
        """
        Handle Polymarket WebSocket messages.

        Args:
            message: Polymarket message data
        """
        try:
            msg_type = message.get('type', '')

            if msg_type == 'book':
                # Polymarket sends full book updates
                market_id = message.get('market')
                if not market_id:
                    return

                # Get book data
                bids = message.get('bids', [])
                asks = message.get('asks', [])

                # Polymarket typically sends YES outcome data
                # You may need to adjust based on actual API response structure
                if bids:
                    best_bid = bids[0]  # [price, size]
                    await self.update_orderbook(
                        platform=Platform.POLYMARKET,
                        market_id=market_id,
                        outcome=Outcome.YES,
                        bid_price=float(best_bid['price']),
                        bid_size=int(best_bid['size']),
                        ask_price=None,
                        ask_size=None
                    )

                if asks:
                    best_ask = asks[0]
                    await self.update_orderbook(
                        platform=Platform.POLYMARKET,
                        market_id=market_id,
                        outcome=Outcome.YES,
                        bid_price=None,
                        bid_size=None,
                        ask_price=float(best_ask['price']),
                        ask_size=int(best_ask['size'])
                    )

        except Exception as e:
            logger.error(f"Error processing Polymarket message: {e}")

    async def update_orderbook(
        self,
        platform: Platform,
        market_id: str,
        outcome: Outcome,
        bid_price: Optional[float] = None,
        bid_size: Optional[int] = None,
        ask_price: Optional[float] = None,
        ask_size: Optional[int] = None
    ):
        """
        Update order book with new bid/ask data.

        Args:
            platform: Trading platform
            market_id: Market identifier
            outcome: YES or NO
            bid_price: Best bid price (optional)
            bid_size: Best bid size (optional)
            ask_price: Best ask price (optional)
            ask_size: Best ask size (optional)
        """
        async with self._lock:
            # Ensure market is initialized
            if platform not in self.orderbooks or market_id not in self.orderbooks[platform]:
                logger.warning(f"Orderbook not initialized for {platform.value}/{market_id}")
                return

            orderbook = self.orderbooks[platform][market_id][outcome]

            # Update bid
            if bid_price is not None and bid_size is not None:
                orderbook.update_bid(bid_price, bid_size)

            # Update ask
            if ask_price is not None and ask_size is not None:
                orderbook.update_ask(ask_price, ask_size)

            logger.debug(
                f"Updated {platform.value}/{market_id}/{outcome.value}: "
                f"bid={orderbook.best_bid.price if orderbook.best_bid else None}, "
                f"ask={orderbook.best_ask.price if orderbook.best_ask else None}"
            )

    async def get_orderbook(
        self,
        platform: Platform,
        market_id: str,
        outcome: Outcome
    ) -> Optional[OrderBook]:
        """
        Get order book for a specific market and outcome.

        Args:
            platform: Trading platform
            market_id: Market identifier
            outcome: YES or NO

        Returns:
            OrderBook object or None if not found
        """
        async with self._lock:
            if platform in self.orderbooks and market_id in self.orderbooks[platform]:
                return self.orderbooks[platform][market_id].get(outcome)
            return None

    async def get_best_prices(
        self,
        platform: Platform,
        market_id: str,
        outcome: Outcome
    ) -> Tuple[Optional[float], Optional[float]]:
        """
        Get best bid and ask prices for a market outcome.

        Args:
            platform: Trading platform
            market_id: Market identifier
            outcome: YES or NO

        Returns:
            Tuple of (best_bid_price, best_ask_price)
        """
        orderbook = await self.get_orderbook(platform, market_id, outcome)

        if not orderbook:
            return None, None

        best_bid = orderbook.best_bid.price if orderbook.best_bid else None
        best_ask = orderbook.best_ask.price if orderbook.best_ask else None

        return best_bid, best_ask

    async def is_orderbook_stale(
        self,
        platform: Platform,
        market_id: str,
        outcome: Outcome,
        timeout_seconds: int = None
    ) -> bool:
        """
        Check if an order book is stale.

        Args:
            platform: Trading platform
            market_id: Market identifier
            outcome: YES or NO
            timeout_seconds: Timeout in seconds (uses config default if None)

        Returns:
            True if stale, False otherwise
        """
        if timeout_seconds is None:
            timeout_seconds = self.config.websocket_timeout

        orderbook = await self.get_orderbook(platform, market_id, outcome)

        if not orderbook:
            return True

        return orderbook.is_stale(timeout_seconds)

    async def get_market_count(self) -> int:
        """
        Get total number of markets being tracked.

        Returns:
            Total market count
        """
        async with self._lock:
            count = 0
            for platform_books in self.orderbooks.values():
                count += len(platform_books)
            return count
