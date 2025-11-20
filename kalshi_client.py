"""
Kalshi API client module.
Handles REST API calls and WebSocket connections to Kalshi.
"""

import asyncio
import logging
import time
import base64
from typing import List, Dict, Optional, Callable
from datetime import datetime, timedelta
import aiohttp
import websockets
import json

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, ec
from cryptography.hazmat.backends import default_backend

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
        # Use elections WebSocket URL
        self.ws_url = "wss://api.elections.kalshi.com/trade-api/ws/v2"
        self.session: Optional[aiohttp.ClientSession] = None
        self.ws_connection: Optional[websockets.WebSocketClientProtocol] = None
        self.auth_token: Optional[str] = None
        self.token_expiry: Optional[datetime] = None
        self.is_connected = False
        self.ws_healthy = False  # True only after receiving WS messages
        self._message_handlers: List[Callable] = []
        self._subscribed_tickers: set = set()

        # Load private key from file if specified
        self.private_key = None
        self.private_key_type = None  # 'RSA' or 'EC'
        if self.config.kalshi_private_key_file:
            try:
                with open(self.config.kalshi_private_key_file, 'rb') as f:
                    key_data = f.read()
                    # Try to load as PEM
                    try:
                        self.private_key = serialization.load_pem_private_key(
                            key_data, password=None, backend=default_backend()
                        )
                        # Determine key type
                        if hasattr(self.private_key, 'sign'):
                            from cryptography.hazmat.primitives.asymmetric import rsa, ec
                            if isinstance(self.private_key, rsa.RSAPrivateKey):
                                self.private_key_type = 'RSA'
                            elif isinstance(self.private_key, ec.EllipticCurvePrivateKey):
                                self.private_key_type = 'EC'
                        logger.info(f"Loaded Kalshi {self.private_key_type} private key from file")
                    except Exception as e:
                        logger.error(f"Failed to parse private key: {e}")
            except Exception as e:
                logger.warning(f"Could not load Kalshi private key file: {e}")

    def _sign_request(self, timestamp_str: str, method: str, path: str) -> str:
        """
        Sign a request using the private key.

        Args:
            timestamp_str: Timestamp in milliseconds as string
            method: HTTP method (GET, POST, etc.)
            path: API path

        Returns:
            Base64-encoded signature
        """
        if not self.private_key:
            raise ValueError("No private key loaded for signing")

        # Construct message to sign
        message = f"{timestamp_str}{method}{path}"
        message_bytes = message.encode('utf-8')

        # Sign based on key type
        if self.private_key_type == 'RSA':
            signature = self.private_key.sign(
                message_bytes,
                padding.PKCS1v15(),
                hashes.SHA256()
            )
        elif self.private_key_type == 'EC':
            signature = self.private_key.sign(
                message_bytes,
                ec.ECDSA(hashes.SHA256())
            )
        else:
            raise ValueError(f"Unsupported key type: {self.private_key_type}")

        return base64.b64encode(signature).decode('utf-8')

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
            logger.info("Kalshi REST client connected successfully")

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
            self.ws_healthy = False
            logger.info("Kalshi client disconnected")

        except Exception as e:
            logger.error(f"Error disconnecting Kalshi client: {e}")

    def _get_headers(self) -> Dict[str, str]:
        """
        Get HTTP headers for REST API requests.

        Returns:
            Dictionary of headers
        """
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        # Use signature-based auth for REST if we have a private key
        if self.private_key and self.config.kalshi_api_key:
            timestamp_str = str(int(time.time() * 1000))
            # For REST, we'd need the specific path, but for simple GET we can use API key
            headers["KALSHI-ACCESS-KEY"] = self.config.kalshi_api_key
        elif self.config.kalshi_api_key:
            # Fallback to simple API key
            headers["KALSHI-ACCESS-KEY"] = self.config.kalshi_api_key

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
                "limit": 1000
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
                    pong_waiter = await ws.ping()
                    await asyncio.wait_for(pong_waiter, timeout=10)
                    logger.debug("Kalshi WebSocket keepalive: ping/pong successful")
                except asyncio.TimeoutError:
                    logger.warning("Kalshi WebSocket keepalive: pong timeout")
                    break
                except websockets.exceptions.ConnectionClosed:
                    logger.warning("Kalshi WebSocket keepalive: connection closed")
                    break

                await asyncio.sleep(15)

        except Exception as e:
            logger.error(f"Kalshi keepalive task error: {e}")

    async def connect_websocket(self, market_ids: List[str] = None):
        """
        Connect to Kalshi WebSocket feed and subscribe to markets.
        Uses signature-based authentication.

        Args:
            market_ids: List of market tickers to subscribe to (None = all)
        """
        reconnect_delay = self.config.reconnect_base_delay
        reconnect_count = 0

        # Validate we have credentials for WebSocket
        if not self.config.kalshi_api_key:
            raise ValueError("KALSHI_API_KEY is required for WebSocket connection")

        if not self.private_key:
            logger.warning("No private key loaded - WebSocket authentication may fail")

        while True:
            try:
                logger.info(f"Connecting to Kalshi WebSocket (attempt {reconnect_count + 1})...")
                self.ws_healthy = False

                # Build signature-based auth headers for WebSocket
                timestamp_str = str(int(time.time() * 1000))

                extra_headers = {
                    "KALSHI-ACCESS-KEY": self.config.kalshi_api_key,
                    "KALSHI-ACCESS-TIMESTAMP": timestamp_str,
                }

                # Sign the WebSocket connection request
                if self.private_key:
                    signature = self._sign_request(timestamp_str, "GET", "/trade-api/ws/v2")
                    extra_headers["KALSHI-ACCESS-SIGNATURE"] = signature
                    logger.debug("Using signature-based WebSocket authentication")
                else:
                    logger.warning("No signature - WebSocket auth may fail")

                async with websockets.connect(
                    self.ws_url,
                    extra_headers=extra_headers,
                    ping_interval=15,
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
                                "id": 1,
                                "cmd": "subscribe",
                                "params": {
                                    "channels": ["orderbook_delta"],
                                    "market_tickers": market_ids
                                }
                            }
                            await ws.send(json.dumps(subscribe_msg))
                            self._subscribed_tickers.update(market_ids)
                            logger.info(f"Subscribed to {len(market_ids)} Kalshi markets")

                        # Reset reconnect delay on successful connection
                        reconnect_delay = self.config.reconnect_base_delay
                        reconnect_count = 0

                        # Listen for messages
                        async for message in ws:
                            try:
                                data = json.loads(message)

                                # Mark WebSocket as healthy on first message
                                if not self.ws_healthy:
                                    self.ws_healthy = True
                                    logger.info("Kalshi WebSocket receiving data - marked healthy")

                                # Log message type for debugging
                                msg_type = data.get('type', data.get('id', 'unknown'))
                                logger.debug(f"Kalshi WS message type: {msg_type}")

                                # Notify all registered handlers
                                for handler in self._message_handlers:
                                    asyncio.create_task(handler(Platform.KALSHI, data))

                            except json.JSONDecodeError:
                                logger.warning(f"Received invalid JSON from Kalshi: {message}")
                            except Exception as e:
                                logger.error(f"Error processing Kalshi WebSocket message: {e}")

                    finally:
                        keepalive_task.cancel()
                        try:
                            await keepalive_task
                        except asyncio.CancelledError:
                            pass
                        self.ws_healthy = False

            except websockets.exceptions.InvalidStatusCode as e:
                if e.status_code == 401:
                    logger.error(f"Kalshi WebSocket 401 Unauthorized. Check API key and signature.")
                    logger.error("Ensure KALSHI_PRIVATE_KEY_FILE points to valid RSA/EC private key")
                    if reconnect_count >= 3:
                        raise ValueError("Kalshi WebSocket authentication failed after 3 attempts")
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

            self.ws_healthy = False
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
                "id": 2,
                "cmd": "subscribe",
                "params": {
                    "channels": ["orderbook_delta"],
                    "market_tickers": [market_id]
                }
            }
            await self.ws_connection.send(json.dumps(subscribe_msg))
            self._subscribed_tickers.add(market_id)
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

        new_set = set(new_market_ids)
        to_subscribe = new_set - self._subscribed_tickers

        if to_subscribe:
            try:
                subscribe_msg = {
                    "id": 3,
                    "cmd": "subscribe",
                    "params": {
                        "channels": ["orderbook_delta"],
                        "market_tickers": list(to_subscribe)
                    }
                }
                await self.ws_connection.send(json.dumps(subscribe_msg))
                self._subscribed_tickers.update(to_subscribe)
                logger.info(f"Kalshi subscription update: +{len(to_subscribe)} markets")
            except Exception as e:
                logger.error(f"Error updating Kalshi subscriptions: {e}")
