"""
Polymarket API client module.
Handles REST API calls and WebSocket connections to Polymarket.
"""

import asyncio
import logging
from typing import List, Dict, Optional, Callable, Set
from datetime import datetime
import aiohttp
import websockets
import json

from config import get_config
from models import Market, Platform, OrderBook, Outcome
from utils import PolymarketRateLimiter

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
        self.rate_limiter = PolymarketRateLimiter()

        # Subscription tracking (persistent connection, no rotation)
        self.subscribed_assets: Set[str] = set()
        self.pending_subscriptions: Set[str] = set()
        self.failed_subscriptions: Dict[str, int] = {}  # Market ID -> retry count

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

    async def fetch_markets(self, max_pages: int = 5, min_liquidity: float = 100.0) -> List[Market]:
        """
        Fetch all active, liquid markets from Polymarket with pagination.

        Args:
            max_pages: Maximum number of pages to fetch (default 5 = 500 events)
            min_liquidity: Minimum liquidity in USD to consider market viable (default $100)

        Returns:
            List of Market objects filtered by health criteria
        """
        markets = []
        fetched_count = 0
        filtered_count = 0

        try:
            # Pagination support
            for page in range(max_pages):
                offset = page * 100

                # Fetch events (which contain markets)
                url = f"{self.base_url}/events"
                params = {
                    "closed": "false",  # Only open events
                    "limit": 100,
                    "offset": offset
                }

                headers = self._get_headers()

                # Apply rate limiting
                await self.rate_limiter.acquire_for_endpoint(url)

                async with self.session.get(url, headers=headers, params=params) as response:
                    if response.status == 200:
                        data = await response.json()

                        # Break if no more events
                        if not data or len(data) == 0:
                            logger.info(f"No more events on page {page + 1}, stopping pagination")
                            break

                        # Polymarket returns events, each containing markets
                        for event in data:
                            try:
                                # Check if this event supports order book trading
                                if not event.get('enableOrderBook', False):
                                    continue

                                # Health check: Skip if event is inactive
                                if not event.get('active', False) or event.get('closed', False):
                                    continue

                                # Extract markets from the event
                                event_markets = event.get('markets', [])

                                for market_info in event_markets:
                                    try:
                                        fetched_count += 1

                                        # Market health filtering
                                        # Check 1: Has valid token ID
                                        token_id = market_info.get('tokenID') or market_info.get('clobTokenIds', [None])[0]
                                        if not token_id:
                                            logger.debug(f"Filtered market: no token ID found in {list(market_info.keys())}")
                                            filtered_count += 1
                                            continue

                                        # Check 2: Check liquidity if available (RELAXED - only filter if explicitly too low)
                                        # Many markets don't report liquidity, so we'll be lenient
                                        liquidity = market_info.get('liquidity') or market_info.get('liquidityNum', 0)
                                        if isinstance(liquidity, str):
                                            try:
                                                liquidity = float(liquidity)
                                            except:
                                                liquidity = 0

                                        # Only filter if liquidity is explicitly reported and very low
                                        if liquidity > 0 and liquidity < min_liquidity:
                                            logger.debug(f"Filtered market {token_id}: low liquidity ${liquidity:.2f}")
                                            filtered_count += 1
                                            continue

                                        # Check 3: Has valid volume data (RELAXED - allow zero volume for new markets)
                                        # We'll accept markets even with zero volume as long as they're active
                                        volume = market_info.get('volume') or market_info.get('volumeNum', 0) or event.get('volume', 0)
                                        if isinstance(volume, str):
                                            try:
                                                volume = float(volume)
                                            except:
                                                volume = 0

                                        # Don't filter by volume anymore - accept all active markets

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
                                                'token_id': token_id,
                                                'liquidity': liquidity,
                                                'volume': volume,
                                                'quality_score': self._calculate_market_quality(market_info, event)
                                            }
                                        )
                                        markets.append(market)

                                    except Exception as e:
                                        logger.warning(f"Error parsing Polymarket market: {e}")
                                        filtered_count += 1
                                        continue

                            except Exception as e:
                                logger.warning(f"Error parsing Polymarket event: {e}")
                                continue

                        logger.info(f"Fetched page {page + 1}/{max_pages}: {len(data)} events, {len(markets)} viable markets so far")

                    else:
                        error_text = await response.text()
                        logger.error(f"Failed to fetch Polymarket markets (page {page + 1}): {response.status} - {error_text}")
                        break

            # Sort by quality score (highest first)
            markets.sort(key=lambda m: m.metadata.get('quality_score', 0), reverse=True)

            logger.info(
                f"Polymarket market discovery complete: "
                f"{len(markets)} viable markets (fetched {fetched_count}, filtered {filtered_count})"
            )

        except Exception as e:
            logger.error(f"Error fetching Polymarket markets: {e}")

        return markets

    def _calculate_market_quality(self, market_info: dict, event: dict) -> float:
        """
        Calculate quality score for a market (0-100).

        Factors:
        - Liquidity (higher is better)
        - Volume (higher is better)
        - Recent activity
        - Event engagement

        Args:
            market_info: Market data
            event: Event data

        Returns:
            Quality score (0-100)
        """
        score = 0.0

        # Liquidity score (0-40 points) - Handle missing data gracefully
        liquidity = market_info.get('liquidity') or market_info.get('liquidityNum', 0)
        if isinstance(liquidity, str):
            try:
                liquidity = float(liquidity)
            except:
                liquidity = 0

        if liquidity >= 10000:
            score += 40
        elif liquidity >= 5000:
            score += 30
        elif liquidity >= 1000:
            score += 20
        elif liquidity >= 100:
            score += 10
        elif liquidity == 0:
            # No liquidity data - give modest base score
            score += 15

        # Volume score (0-30 points) - Handle missing data gracefully
        volume = market_info.get('volume') or market_info.get('volumeNum', 0) or event.get('volume', 0)
        if isinstance(volume, str):
            try:
                volume = float(volume)
            except:
                volume = 0

        if volume >= 100000:
            score += 30
        elif volume >= 50000:
            score += 20
        elif volume >= 10000:
            score += 15
        elif volume >= 1000:
            score += 10
        elif volume >= 100:
            score += 5
        elif volume == 0:
            # No volume data - give modest base score
            score += 10

        # Active status (0-20 points)
        if event.get('active', False) and not event.get('closed', False):
            score += 20

        # Order book enabled (0-10 points)
        if event.get('enableOrderBook', False):
            score += 10

        return score

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

            # Apply rate limiting
            await self.rate_limiter.acquire_for_endpoint(url)

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

    def _handle_subscription_ack(self, message: dict):
        """
        Handle subscription confirmation via book updates from Polymarket WebSocket.

        Polymarket doesn't send explicit ACKs - instead, they immediately start
        sending "book" events for subscribed assets.

        Args:
            message: WebSocket message data
        """
        try:
            # Polymarket sends book updates as confirmation
            # Message format: {"event_type": "book", "asset_id": "...", ...}
            event_type = message.get('event_type', '')
            asset_id = message.get('asset_id', '')

            # Any message with asset_id confirms that asset is subscribed
            if asset_id:
                # If this is a pending subscription, mark as confirmed
                if asset_id in self.pending_subscriptions:
                    self.subscribed_assets.add(asset_id)
                    self.pending_subscriptions.discard(asset_id)
                    logger.debug(f"Confirmed subscription to asset {asset_id} via '{event_type}' event")
                # Even if not pending, track it as subscribed (might be from previous session)
                elif asset_id not in self.subscribed_assets:
                    self.subscribed_assets.add(asset_id)
                    logger.debug(f"Received data for asset {asset_id}, marking as subscribed")

        except Exception as e:
            logger.debug(f"Error handling subscription confirmation: {e}")

    async def _subscribe_all(self, ws: websockets.WebSocketClientProtocol, market_ids: List[str]) -> int:
        """
        Subscribe to ALL markets in a single message.

        Polymarket supports up to 65,000 subscriptions per connection,
        so no batching or rotation is needed.

        Args:
            ws: Active WebSocket connection
            market_ids: List of token IDs to subscribe to

        Returns:
            Number of markets subscribed
        """
        if not market_ids:
            logger.warning("No market IDs provided for subscription")
            return 0

        logger.info(f"Subscribing to {len(market_ids)} Polymarket markets in single message...")

        try:
            # Single subscription message with all assets
            subscribe_msg = {
                "assets_ids": market_ids,
                "type": "market"
            }

            await ws.send(json.dumps(subscribe_msg))

            # Track all as subscribed
            self.subscribed_assets.update(market_ids)
            self.pending_subscriptions.update(market_ids)

            # Wait for initial data to arrive
            await asyncio.sleep(2.0)

            logger.info(f"Subscription complete: {len(market_ids)} markets")
            return len(market_ids)

        except websockets.exceptions.ConnectionClosed as e:
            logger.error(f"WebSocket closed during subscription: code={e.code}, reason={e.reason}")
            return 0
        except Exception as e:
            logger.error(f"Error sending subscription: {e}", exc_info=True)
            return 0

    async def update_subscriptions(self, new_market_ids: List[str]):
        """
        Dynamically update subscriptions without reconnecting.

        Call this when markets are refreshed to add new markets
        and remove closed ones.

        Args:
            new_market_ids: Updated list of market IDs to be subscribed
        """
        if not self.ws_connection or self.ws_connection.closed:
            logger.warning("Cannot update subscriptions: WebSocket not connected")
            return

        new_set = set(new_market_ids)

        # Markets to add
        to_subscribe = new_set - self.subscribed_assets
        # Markets to remove
        to_unsubscribe = self.subscribed_assets - new_set

        # Unsubscribe from closed markets
        if to_unsubscribe:
            for asset_id in to_unsubscribe:
                try:
                    unsubscribe_msg = {
                        "assets_ids": [asset_id],
                        "type": "unsubscribe"
                    }
                    await self.ws_connection.send(json.dumps(unsubscribe_msg))
                    self.subscribed_assets.discard(asset_id)
                except Exception as e:
                    logger.debug(f"Error unsubscribing from {asset_id}: {e}")

        # Subscribe to new markets
        if to_subscribe:
            try:
                subscribe_msg = {
                    "assets_ids": list(to_subscribe),
                    "type": "market"
                }
                await self.ws_connection.send(json.dumps(subscribe_msg))
                self.subscribed_assets.update(to_subscribe)
            except Exception as e:
                logger.error(f"Error subscribing to new markets: {e}")

        logger.info(
            f"Subscription update: +{len(to_subscribe)} -{len(to_unsubscribe)} "
            f"= {len(self.subscribed_assets)} total"
        )

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
                    logger.debug("Polymarket WebSocket keepalive: ping/pong successful")
                except asyncio.TimeoutError:
                    logger.warning("Polymarket WebSocket keepalive: pong timeout")
                    break
                except websockets.exceptions.ConnectionClosed:
                    logger.warning("Polymarket WebSocket keepalive: connection closed")
                    break

                # Wait 15 seconds before next ping (as per requirements)
                await asyncio.sleep(15)

        except Exception as e:
            logger.error(f"Polymarket keepalive task error: {e}")

    async def connect_websocket(self, market_ids: List[str] = None):
        """
        Connect to Polymarket WebSocket feed with persistent connection.

        No rotation - subscribes to ALL markets at once and maintains connection.

        Args:
            market_ids: List of market/token IDs to subscribe to (None = all)
        """
        reconnect_delay = self.config.reconnect_base_delay
        reconnect_count = 0

        while True:
            try:
                logger.info(f"Connecting to Polymarket WebSocket (attempt {reconnect_count + 1})...")

                async with websockets.connect(
                    self.ws_url,
                    ping_interval=30,  # 30s keepalive (Polymarket preference)
                    ping_timeout=10,
                    close_timeout=5,
                    max_size=10 * 1024 * 1024  # 10MB for large orderbooks
                ) as ws:
                    self.ws_connection = ws
                    self.is_connected = True
                    logger.info("Polymarket WebSocket connected, waiting for handshake completion...")

                    # Wait for WebSocket handshake to complete
                    await asyncio.sleep(1.0)
                    logger.info("WebSocket handshake complete, ready for subscriptions")

                    # Start keepalive task in background
                    keepalive_task = asyncio.create_task(self._keepalive_task(ws))

                    try:
                        # Subscribe to ALL markets at once (no batching/rotation)
                        if market_ids:
                            successful_subs = await self._subscribe_all(ws, market_ids)

                            if successful_subs == 0:
                                logger.error("Failed to subscribe to any markets, will reconnect")
                                keepalive_task.cancel()
                                continue

                            logger.info(f"Subscribed to {successful_subs} Polymarket markets")
                        else:
                            logger.info("No specific markets to subscribe to, listening to all updates")

                        # Reset reconnect delay on successful connection
                        reconnect_delay = self.config.reconnect_base_delay
                        reconnect_count = 0

                        # Listen for messages
                        async for message in ws:
                            try:
                                data = json.loads(message)

                                # Handle subscription acknowledgments
                                self._handle_subscription_ack(data)

                                # Notify all registered handlers
                                for handler in self._message_handlers:
                                    asyncio.create_task(handler(Platform.POLYMARKET, data))

                            except json.JSONDecodeError:
                                logger.warning(f"Received invalid JSON from Polymarket: {message}")
                            except Exception as e:
                                logger.error(f"Error processing Polymarket WebSocket message: {e}")

                    finally:
                        # Clean up keepalive task
                        keepalive_task.cancel()
                        try:
                            await keepalive_task
                        except asyncio.CancelledError:
                            pass
                        self.is_connected = False

            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(
                    f"Polymarket WebSocket connection closed: "
                    f"code={e.code}, reason={e.reason or 'no reason provided'}"
                )
                self.is_connected = False
                reconnect_count += 1
            except Exception as e:
                logger.error(f"Polymarket WebSocket error: {e}", exc_info=True)
                self.is_connected = False
                reconnect_count += 1

            # Exponential backoff for reconnection (start at 2s, cap at 60s)
            logger.info(f"Reconnecting to Polymarket WebSocket in {reconnect_delay}s... (attempt {reconnect_count})")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 60)

    async def subscribe_to_market(self, token_id: str):
        """
        Subscribe to a specific market's updates via WebSocket using Polymarket's format.

        Args:
            token_id: The market token ID to subscribe to
        """
        if not self.ws_connection or self.ws_connection.closed:
            logger.warning(f"Cannot subscribe to {token_id}: WebSocket not connected")
            return

        if token_id in self.subscribed_assets:
            return  # Already subscribed

        try:
            subscribe_msg = {
                "assets_ids": [token_id],
                "type": "market"
            }
            await self.ws_connection.send(json.dumps(subscribe_msg))
            self.subscribed_assets.add(token_id)
            logger.debug(f"Subscribed to Polymarket token: {token_id}")

        except Exception as e:
            logger.error(f"Error subscribing to Polymarket token {token_id}: {e}")
