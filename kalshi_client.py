"""
Kalshi API client module.
Handles REST API calls and WebSocket connections to Kalshi.
"""

import asyncio
import logging
from typing import List, Dict, Optional, Callable
from datetime import datetime
import aiohttp
import websockets
import json

from config import get_config
from models import Market, Platform, OrderBook, Outcome, PriceLevel

logger = logging.getLogger(__name__)


class KalshiClient:
    """
    Asynchronous client for Kalshi API.
    Handles authentication, market data fetching, and WebSocket connections.
    """

    def __init__(self):
        """Initialize the Kalshi client."""
        self.config = get_config()
        self.base_url = self.config.kalshi_api_base
        self.ws_url = self.config.kalshi_ws_url
        self.session: Optional[aiohttp.ClientSession] = None
        self.ws_connection: Optional[websockets.WebSocketClientProtocol] = None
        self.auth_token: Optional[str] = None
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
        Establish HTTP session and authenticate.
        """
        try:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )

            # Authenticate if credentials are provided
            if self.config.kalshi_email and self.config.kalshi_password:
                await self._authenticate()

            self.is_connected = True
            logger.info("Kalshi client connected successfully")

        except Exception as e:
            logger.error(f"Failed to connect Kalshi client: {e}")
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
            logger.info("Kalshi client disconnected")

        except Exception as e:
            logger.error(f"Error disconnecting Kalshi client: {e}")

    async def _authenticate(self):
        """
        Authenticate with Kalshi API using email and password.
        """
        try:
            auth_url = f"{self.base_url}/trade-api/v2/login"
            payload = {
                "email": self.config.kalshi_email,
                "password": self.config.kalshi_password
            }

            async with self.session.post(auth_url, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    self.auth_token = data.get('token')
                    logger.info("Kalshi authentication successful")
                else:
                    error_text = await response.text()
                    logger.error(f"Kalshi authentication failed: {response.status} - {error_text}")

        except Exception as e:
            logger.error(f"Error during Kalshi authentication: {e}")
            # Continue without auth - some endpoints may still work

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

        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        elif self.config.kalshi_api_key:
            headers["X-API-Key"] = self.config.kalshi_api_key

        return headers

    async def fetch_markets(self) -> List[Market]:
        """
        Fetch all active markets from Kalshi.

        Returns:
            List of Market objects
        """
        markets = []

        try:
            url = f"{self.base_url}/trade-api/v2/markets"
            params = {
                "status": "open",
                "limit": 1000  # Fetch up to 1000 markets
            }

            headers = self._get_headers()

            async with self.session.get(url, headers=headers, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    market_data = data.get('markets', [])

                    for market_info in market_data:
                        try:
                            market = Market(
                                platform=Platform.KALSHI,
                                market_id=market_info.get('ticker', market_info.get('id')),
                                title=market_info.get('title', ''),
                                question=market_info.get('subtitle', market_info.get('title', '')),
                                active=market_info.get('status') == 'open',
                                metadata=market_info
                            )
                            markets.append(market)

                        except Exception as e:
                            logger.warning(f"Error parsing Kalshi market: {e}")
                            continue

                    logger.info(f"Fetched {len(markets)} markets from Kalshi")

                else:
                    error_text = await response.text()
                    logger.error(f"Failed to fetch Kalshi markets: {response.status} - {error_text}")

        except Exception as e:
            logger.error(f"Error fetching Kalshi markets: {e}")

        return markets

    async def fetch_orderbook(self, market_id: str) -> Optional[Dict]:
        """
        Fetch order book for a specific market.

        Args:
            market_id: The market ticker/ID

        Returns:
            Order book data dictionary or None
        """
        try:
            url = f"{self.base_url}/trade-api/v2/markets/{market_id}/orderbook"
            headers = self._get_headers()

            async with self.session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get('orderbook', {})
                else:
                    logger.warning(f"Failed to fetch orderbook for {market_id}: {response.status}")
                    return None

        except Exception as e:
            logger.error(f"Error fetching orderbook for {market_id}: {e}")
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
        Connect to Kalshi WebSocket feed and subscribe to markets.

        Args:
            market_ids: List of market tickers to subscribe to (None = all)
        """
        reconnect_delay = self.config.reconnect_base_delay

        while True:
            try:
                logger.info("Connecting to Kalshi WebSocket...")

                # Connect to WebSocket
                extra_headers = {}
                if self.auth_token:
                    extra_headers["Authorization"] = f"Bearer {self.auth_token}"

                async with websockets.connect(
                    self.ws_url,
                    extra_headers=extra_headers if extra_headers else None,
                    ping_interval=20,
                    ping_timeout=10
                ) as ws:
                    self.ws_connection = ws
                    logger.info("Kalshi WebSocket connected")

                    # Subscribe to markets
                    if market_ids:
                        subscribe_msg = {
                            "type": "subscribe",
                            "channels": [
                                {
                                    "name": "orderbook_delta",
                                    "market_tickers": market_ids
                                }
                            ]
                        }
                        await ws.send(json.dumps(subscribe_msg))
                        logger.info(f"Subscribed to {len(market_ids)} Kalshi markets")

                    # Reset reconnect delay on successful connection
                    reconnect_delay = self.config.reconnect_base_delay

                    # Listen for messages
                    async for message in ws:
                        try:
                            data = json.loads(message)

                            # Notify all registered handlers
                            for handler in self._message_handlers:
                                asyncio.create_task(handler(Platform.KALSHI, data))

                        except json.JSONDecodeError:
                            logger.warning(f"Received invalid JSON from Kalshi: {message}")
                        except Exception as e:
                            logger.error(f"Error processing Kalshi WebSocket message: {e}")

            except websockets.exceptions.ConnectionClosed:
                logger.warning("Kalshi WebSocket connection closed")
            except Exception as e:
                logger.error(f"Kalshi WebSocket error: {e}")

            # Exponential backoff for reconnection
            logger.info(f"Reconnecting to Kalshi WebSocket in {reconnect_delay}s...")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 60)  # Cap at 60 seconds

    async def subscribe_to_market(self, market_id: str):
        """
        Subscribe to a specific market's updates via WebSocket.

        Args:
            market_id: The market ticker to subscribe to
        """
        if not self.ws_connection or self.ws_connection.closed:
            logger.warning(f"Cannot subscribe to {market_id}: WebSocket not connected")
            return

        try:
            subscribe_msg = {
                "type": "subscribe",
                "channels": [
                    {
                        "name": "orderbook_delta",
                        "market_tickers": [market_id]
                    }
                ]
            }
            await self.ws_connection.send(json.dumps(subscribe_msg))
            logger.debug(f"Subscribed to Kalshi market: {market_id}")

        except Exception as e:
            logger.error(f"Error subscribing to Kalshi market {market_id}: {e}")
