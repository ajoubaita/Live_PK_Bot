"""
Kalshi API client module.
Handles REST API calls and WebSocket connections to Kalshi.
"""

import asyncio
import logging
from typing import List, Dict, Optional, Callable
from datetime import datetime, timedelta
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
        self.token_expiry: Optional[datetime] = None
        self.is_connected = False
        self._message_handlers: List[Callable] = []

        # Load private key from file if specified
        self.private_key: Optional[str] = None
        if self.config.kalshi_private_key_file:
            try:
                with open(self.config.kalshi_private_key_file, 'r') as f:
                    self.private_key = f.read()
                logger.info("Loaded Kalshi private key from file")
            except Exception as e:
                logger.warning(f"Could not load Kalshi private key file: {e}")

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
        Authenticate with Kalshi API.
        Uses API key authentication only (email/password is deprecated).
        """
        # Use API key authentication (preferred and only supported method)
        if self.config.kalshi_api_key:
            logger.info("Using Kalshi API key authentication")
            # API key will be used in headers for each request
            # No need to obtain a separate token
        else:
            raise ValueError("KALSHI_API_KEY is required for authentication")

    async def _ensure_auth_token(self):
        """
        Ensure we have a valid authentication token.
        Refreshes the token if it's expired or about to expire.
        """
        # Check if token exists and is not expired
        if self.auth_token and self.token_expiry:
            time_until_expiry = (self.token_expiry - datetime.utcnow()).total_seconds()
            if time_until_expiry > 300:  # Token valid for more than 5 minutes
                return

        # Token is missing, expired, or expiring soon - refresh it
        logger.info("Refreshing Kalshi authentication token...")
        await self._authenticate()

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

    async def _keepalive_task(self, ws: websockets.WebSocketClientProtocol):
        """
        Send periodic pings to keep the WebSocket connection alive.

        Args:
            ws: Active WebSocket connection
        """
        try:
            while not ws.closed:
                try:
                    # Send ping and wait for pong
                    pong_waiter = await ws.ping()
                    await asyncio.wait_for(pong_waiter, timeout=10)
                    logger.debug("Kalshi WebSocket keepalive: ping/pong successful")
                except asyncio.TimeoutError:
                    logger.warning("Kalshi WebSocket keepalive: pong timeout")
                    break
                except websockets.exceptions.ConnectionClosed:
                    logger.warning("Kalshi WebSocket keepalive: connection closed")
                    break

                # Wait 15 seconds before next ping (as per requirements)
                await asyncio.sleep(15)

        except Exception as e:
            logger.error(f"Kalshi keepalive task error: {e}")

    async def connect_websocket(self, market_ids: List[str] = None):
        """
        Connect to Kalshi WebSocket feed and subscribe to markets.
        Uses API key authentication for data access.

        Args:
            market_ids: List of market tickers to subscribe to (None = all)
        """
        reconnect_delay = self.config.reconnect_base_delay
        reconnect_count = 0

        # Validate API key is available
        if not self.config.kalshi_api_key:
            raise ValueError("KALSHI_API_KEY is required for WebSocket connection")

        while True:
            try:
                logger.info(f"Connecting to Kalshi WebSocket (attempt {reconnect_count + 1})...")

                # Use API key authentication directly
                extra_headers = {
                    "Authorization": f"Bearer {self.config.kalshi_api_key}"
                }

                async with websockets.connect(
                    self.ws_url,
                    extra_headers=extra_headers if extra_headers else None,
                    ping_interval=15,  # 15s keepalive as per requirements
                    ping_timeout=10
                ) as ws:
                    self.ws_connection = ws
                    logger.info("Kalshi WebSocket connected successfully")

                    # Start keepalive task in background
                    keepalive_task = asyncio.create_task(self._keepalive_task(ws))

                    try:
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
                        reconnect_count = 0

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

                    finally:
                        # Clean up keepalive task
                        keepalive_task.cancel()
                        try:
                            await keepalive_task
                        except asyncio.CancelledError:
                            pass

            except websockets.exceptions.InvalidStatusCode as e:
                if e.status_code == 401:
                    logger.error("Kalshi WebSocket authentication failed (401). Check your KALSHI_API_KEY.")
                    # Don't retry indefinitely on auth failure
                    if reconnect_count >= 3:
                        raise ValueError("Kalshi authentication failed after 3 attempts - check API key")
                    reconnect_count += 1
                else:
                    logger.error(f"Kalshi WebSocket invalid status code: {e.status_code}")
                    reconnect_count += 1
            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"Kalshi WebSocket connection closed: {e}")
                reconnect_count += 1
            except Exception as e:
                logger.error(f"Kalshi WebSocket error: {e}", exc_info=True)
                reconnect_count += 1

            # Exponential backoff for reconnection (start at 2s, cap at 60 seconds)
            logger.info(f"Reconnecting to Kalshi WebSocket in {reconnect_delay}s... (attempt {reconnect_count})")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 60)

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

    async def update_subscriptions(self, new_market_ids: List[str]):
        """
        Dynamically update subscriptions without reconnecting.

        Args:
            new_market_ids: Updated list of market tickers to be subscribed
        """
        if not self.ws_connection or self.ws_connection.closed:
            logger.warning("Cannot update subscriptions: WebSocket not connected")
            return

        # For Kalshi, we can send additional subscribe messages
        # to add new markets (no explicit unsubscribe needed for most use cases)
        current_subscribed = getattr(self, '_subscribed_tickers', set())
        new_set = set(new_market_ids)

        to_subscribe = new_set - current_subscribed

        if to_subscribe:
            try:
                subscribe_msg = {
                    "type": "subscribe",
                    "channels": [
                        {
                            "name": "orderbook_delta",
                            "market_tickers": list(to_subscribe)
                        }
                    ]
                }
                await self.ws_connection.send(json.dumps(subscribe_msg))

                if not hasattr(self, '_subscribed_tickers'):
                    self._subscribed_tickers = set()
                self._subscribed_tickers.update(to_subscribe)

                logger.info(f"Kalshi subscription update: +{len(to_subscribe)} markets")
            except Exception as e:
                logger.error(f"Error updating Kalshi subscriptions: {e}")
