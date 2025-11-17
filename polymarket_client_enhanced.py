"""
Polymarket API client module - ENHANCED VERSION
Handles REST API calls and WebSocket connections to Polymarket.

FIXES:
- Exponential backoff up to 120s
- Throttled subscription (10 at a time with delays)
- Better error logging with stack traces
- Reconnection attempt tracking
- Ping/pong heartbeat handling
- Proper message validation
"""

import asyncio
import logging
import traceback
from typing import List, Dict, Optional, Callable
from datetime import datetime
import aiohttp
import websockets
import json

from config import get_config
from models import Market, Platform, OrderBook, Outcome

logger = logging.getLogger(__name__)


class PolymarketClient:
    """
    Asynchronous client for Polymarket Gamma API.
    Handles market data fetching and WebSocket connections.
    """

    def __init__(self):
        """Initialize the Polymarket client."""
        self.config = get_config()
        self.base_url = self.config.polymarket_api_base
        self.ws_url = self.config.polymarket_ws_url
        self.session: Optional[aiohttp.ClientSession] = None
        self.ws_connection: Optional[websockets.WebSocketClientProtocol] = None
        self.is_connected = False
        self._message_handlers: List[Callable] = []
        self.reconnect_count = 0
        self.last_message_time: Optional[datetime] = None
        self.subscribed_markets: List[str] = []

    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect()

    async def connect(self):
        """
        Establish HTTP session.
        """
        try:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
            self.is_connected = True
            logger.info("Polymarket HTTP client connected successfully")

        except Exception as e:
            logger.error(f"Failed to connect Polymarket client: {e}")
            logger.error(traceback.format_exc())
            raise

    async def disconnect(self):
        """
        Close all connections gracefully.
        """
        try:
            if self.ws_connection:
                await self.ws_connection.close()
                self.ws_connection = None

            if self.session:
                await self.session.close()
                self.session = None

            self.is_connected = False
            logger.info("Polymarket client disconnected")

        except Exception as e:
            logger.error(f"Error disconnecting Polymarket client: {e}")
            logger.error(traceback.format_exc())

    def _get_headers(self) -> Dict[str, str]:
        """
        Get HTTP headers for API requests.

        Returns:
            Dictionary of headers
        """
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        if self.config.polymarket_api_key:
            headers["Authorization"] = f"Bearer {self.config.polymarket_api_key}"

        return headers

    async def fetch_markets(self) -> List[Market]:
        """
        Fetch all active markets from Polymarket.

        Returns:
            List of Market objects
        """
        markets = []

        try:
            # Fetch events (which contain markets)
            url = f"{self.base_url}/events"
            params = {
                "closed": "false",  # Only open events
                "limit": 100
            }

            headers = self._get_headers()

            async with self.session.get(url, headers=headers, params=params) as response:
                if response.status == 200:
                    data = await response.json()

                    # Polymarket returns events, each containing markets
                    for event in data:
                        try:
                            # Check if this event supports order book trading
                            if not event.get('enableOrderBook', False):
                                logger.debug(f"Skipping non-orderbook event: {event.get('title')}")
                                continue

                            # Extract markets from the event
                            event_markets = event.get('markets', [])

                            for market_info in event_markets:
                                try:
                                    # Polymarket markets can be binary or multi-outcome
                                    # For simplicity, we'll focus on binary markets
                                    market = Market(
                                        platform=Platform.POLYMARKET,
                                        market_id=market_info.get('conditionId', market_info.get('id', '')),
                                        title=event.get('title', ''),
                                        question=market_info.get('question', event.get('title', '')),
                                        active=event.get('active', True) and not event.get('closed', False),
                                        metadata={
                                            'event': event,
                                            'market': market_info,
                                            'token_id': market_info.get('tokenID')
                                        }
                                    )
                                    markets.append(market)
                                    logger.debug(f"Added Polymarket market: {market.title} (ID: {market.market_id})")

                                except Exception as e:
                                    logger.warning(f"Error parsing Polymarket market: {e}")
                                    logger.debug(traceback.format_exc())
                                    continue

                        except Exception as e:
                            logger.warning(f"Error parsing Polymarket event: {e}")
                            logger.debug(traceback.format_exc())
                            continue

                    logger.info(f"Fetched {len(markets)} markets from Polymarket")

                else:
                    error_text = await response.text()
                    logger.error(f"Failed to fetch Polymarket markets: {response.status} - {error_text}")

        except Exception as e:
            logger.error(f"Error fetching Polymarket markets: {e}")
            logger.error(traceback.format_exc())

        return markets

    async def fetch_orderbook(self, token_id: str) -> Optional[Dict]:
        """
        Fetch order book for a specific market token.

        Args:
            token_id: The market token ID

        Returns:
            Order book data dictionary or None
        """
        try:
            url = f"{self.base_url}/book"
            params = {
                "token_id": token_id
            }
            headers = self._get_headers()

            async with self.session.get(url, headers=headers, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return data
                else:
                    logger.warning(f"Failed to fetch orderbook for {token_id}: {response.status}")
                    return None

        except Exception as e:
            logger.error(f"Error fetching orderbook for {token_id}: {e}")
            logger.error(traceback.format_exc())
            return None

    def register_message_handler(self, handler: Callable):
        """
        Register a callback function to handle WebSocket messages.

        Args:
            handler: Async function that takes (platform, message) as arguments
        """
        self._message_handlers.append(handler)

    async def connect_websocket(self, market_ids: List[str] = None):
        """
        Connect to Polymarket WebSocket feed and subscribe to markets.
        ENHANCED: Exponential backoff up to 120s, throttled subscriptions, better logging.

        Args:
            market_ids: List of market/token IDs to subscribe to (None = all)
        """
        reconnect_delay = self.config.reconnect_base_delay
        max_reconnect_delay = 120  # Cap at 120 seconds
        consecutive_failures = 0

        while True:
            try:
                logger.info(f"Connecting to Polymarket WebSocket... (Attempt #{self.reconnect_count + 1})")

                async with websockets.connect(
                    self.ws_url,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=10
                ) as ws:
                    self.ws_connection = ws
                    self.reconnect_count += 1
                    logger.info(f"✓ Polymarket WebSocket connected (Total connections: {self.reconnect_count})")

                    # Subscribe to markets with throttling
                    if market_ids:
                        await self._subscribe_with_throttling(ws, market_ids)

                    # Reset reconnect delay and consecutive failures on successful connection
                    reconnect_delay = self.config.reconnect_base_delay
                    consecutive_failures = 0
                    self.last_message_time = datetime.utcnow()

                    # Start heartbeat task
                    heartbeat_task = asyncio.create_task(self._heartbeat_monitor(ws))

                    # Listen for messages
                    message_count = 0
                    async for message in ws:
                        try:
                            message_count += 1
                            self.last_message_time = datetime.utcnow()

                            # Log first few messages for debugging
                            if message_count <= 5:
                                logger.debug(f"Polymarket message #{message_count}: {message[:200]}")

                            data = json.loads(message)

                            # Notify all registered handlers
                            for handler in self._message_handlers:
                                asyncio.create_task(handler(Platform.POLYMARKET, data))

                        except json.JSONDecodeError as e:
                            logger.warning(f"Received invalid JSON from Polymarket: {message[:100]}")
                            logger.debug(traceback.format_exc())
                        except Exception as e:
                            logger.error(f"Error processing Polymarket WebSocket message: {e}")
                            logger.error(traceback.format_exc())

                    # Cancel heartbeat task when connection closes
                    heartbeat_task.cancel()

            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"Polymarket WebSocket connection closed: {e.code} {e.reason}")
                consecutive_failures += 1
            except Exception as e:
                logger.error(f"Polymarket WebSocket error: {e}")
                logger.error(traceback.format_exc())
                consecutive_failures += 1

            # Calculate exponential backoff with cap
            reconnect_delay = min(
                self.config.reconnect_base_delay * (2 ** consecutive_failures),
                max_reconnect_delay
            )

            logger.warning(
                f"Polymarket WebSocket disconnected. "
                f"Reconnecting in {reconnect_delay}s... "
                f"(Consecutive failures: {consecutive_failures})"
            )

            await asyncio.sleep(reconnect_delay)

    async def _subscribe_with_throttling(self, ws: websockets.WebSocketClientProtocol, market_ids: List[str]):
        """
        Subscribe to markets with throttling to avoid overwhelming the server.

        Args:
            ws: WebSocket connection
            market_ids: List of market IDs to subscribe to
        """
        batch_size = 10  # Send 10 subscriptions at a time
        delay_between_batches = 0.5  # Wait 500ms between batches

        logger.info(f"Subscribing to {len(market_ids)} Polymarket markets in batches of {batch_size}...")

        for i in range(0, len(market_ids), batch_size):
            batch = market_ids[i:i + batch_size]

            for market_id in batch:
                try:
                    subscribe_msg = {
                        "type": "subscribe",
                        "channel": "market",
                        "market": market_id
                    }
                    await ws.send(json.dumps(subscribe_msg))
                    self.subscribed_markets.append(market_id)

                except Exception as e:
                    logger.error(f"Failed to subscribe to market {market_id}: {e}")
                    logger.error(traceback.format_exc())

            logger.debug(f"Subscribed to batch {i//batch_size + 1}/{(len(market_ids)-1)//batch_size + 1}")

            # Wait between batches (except for last batch)
            if i + batch_size < len(market_ids):
                await asyncio.sleep(delay_between_batches)

        logger.info(f"✓ Successfully subscribed to {len(self.subscribed_markets)} Polymarket markets")

    async def _heartbeat_monitor(self, ws: websockets.WebSocketClientProtocol):
        """
        Monitor WebSocket connection health and send pings if needed.

        Args:
            ws: WebSocket connection
        """
        try:
            while True:
                await asyncio.sleep(30)  # Check every 30 seconds

                if self.last_message_time:
                    elapsed = (datetime.utcnow() - self.last_message_time).total_seconds()

                    if elapsed > 60:
                        logger.warning(
                            f"No Polymarket messages received for {elapsed:.0f}s. "
                            f"Connection may be stale."
                        )

                    # Send explicit ping if no messages for a while
                    if elapsed > 45:
                        try:
                            pong_waiter = await ws.ping()
                            await asyncio.wait_for(pong_waiter, timeout=5.0)
                            logger.debug("Polymarket ping successful")
                        except asyncio.TimeoutError:
                            logger.error("Polymarket ping timeout - connection may be dead")
                            break
                        except Exception as e:
                            logger.error(f"Polymarket ping failed: {e}")
                            break

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Heartbeat monitor error: {e}")
            logger.error(traceback.format_exc())

    async def subscribe_to_market(self, market_id: str):
        """
        Subscribe to a specific market's updates via WebSocket.

        Args:
            market_id: The market/token ID to subscribe to
        """
        if not self.ws_connection or self.ws_connection.closed:
            logger.warning(f"Cannot subscribe to {market_id}: WebSocket not connected")
            return

        try:
            subscribe_msg = {
                "type": "subscribe",
                "channel": "market",
                "market": market_id
            }
            await self.ws_connection.send(json.dumps(subscribe_msg))
            logger.debug(f"Subscribed to Polymarket market: {market_id}")

        except Exception as e:
            logger.error(f"Error subscribing to Polymarket market {market_id}: {e}")
            logger.error(traceback.format_exc())
