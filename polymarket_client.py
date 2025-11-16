"""
Polymarket API client module.
Handles REST API calls and WebSocket connections to Polymarket.
"""

import asyncio
import logging
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
            logger.info("Polymarket client connected successfully")

        except Exception as e:
            logger.error(f"Failed to connect Polymarket client: {e}")
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

                                except Exception as e:
                                    logger.warning(f"Error parsing Polymarket market: {e}")
                                    continue

                        except Exception as e:
                            logger.warning(f"Error parsing Polymarket event: {e}")
                            continue

                    logger.info(f"Fetched {len(markets)} markets from Polymarket")

                else:
                    error_text = await response.text()
                    logger.error(f"Failed to fetch Polymarket markets: {response.status} - {error_text}")

        except Exception as e:
            logger.error(f"Error fetching Polymarket markets: {e}")

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

        Args:
            market_ids: List of market/token IDs to subscribe to (None = all)
        """
        reconnect_delay = self.config.reconnect_base_delay

        while True:
            try:
                logger.info("Connecting to Polymarket WebSocket...")

                async with websockets.connect(
                    self.ws_url,
                    ping_interval=20,
                    ping_timeout=10
                ) as ws:
                    self.ws_connection = ws
                    logger.info("Polymarket WebSocket connected")

                    # Subscribe to markets
                    if market_ids:
                        for market_id in market_ids:
                            subscribe_msg = {
                                "type": "subscribe",
                                "channel": "market",
                                "market": market_id
                            }
                            await ws.send(json.dumps(subscribe_msg))

                        logger.info(f"Subscribed to {len(market_ids)} Polymarket markets")

                    # Reset reconnect delay on successful connection
                    reconnect_delay = self.config.reconnect_base_delay

                    # Listen for messages
                    async for message in ws:
                        try:
                            data = json.loads(message)

                            # Notify all registered handlers
                            for handler in self._message_handlers:
                                asyncio.create_task(handler(Platform.POLYMARKET, data))

                        except json.JSONDecodeError:
                            logger.warning(f"Received invalid JSON from Polymarket: {message}")
                        except Exception as e:
                            logger.error(f"Error processing Polymarket WebSocket message: {e}")

            except websockets.exceptions.ConnectionClosed:
                logger.warning("Polymarket WebSocket connection closed")
            except Exception as e:
                logger.error(f"Polymarket WebSocket error: {e}")

            # Exponential backoff for reconnection
            logger.info(f"Reconnecting to Polymarket WebSocket in {reconnect_delay}s...")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 60)  # Cap at 60 seconds

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
