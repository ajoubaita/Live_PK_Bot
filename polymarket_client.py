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

        # Subscription rotation
        self.subscription_groups: List[List[str]] = []
        self.current_group_index: int = 0
        self.last_rotation_time: Optional[datetime] = None
        self.rotation_interval: int = 300  # 5 minutes in seconds
        self.markets_per_group: int = 20  # Subscribe to 20 markets at a time (reduced for stability)

        # Subscription tracking
        self.subscribed_markets: set = set()  # Successfully subscribed markets
        self.pending_subscriptions: set = set()  # Markets awaiting acknowledgment
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
                    self.subscribed_markets.add(asset_id)
                    self.pending_subscriptions.discard(asset_id)
                    logger.debug(f"Confirmed subscription to asset {asset_id} via '{event_type}' event")
                # Even if not pending, track it as subscribed (might be from previous session)
                elif asset_id not in self.subscribed_markets:
                    self.subscribed_markets.add(asset_id)
                    logger.debug(f"Received data for asset {asset_id}, marking as subscribed")

        except Exception as e:
            logger.debug(f"Error handling subscription confirmation: {e}")

    async def _subscribe_with_batching(self, ws: websockets.WebSocketClientProtocol, market_ids: List[str], batch_size: int = 20) -> int:
        """
        Subscribe to markets using Polymarket's correct format with batching.

        Polymarket WebSocket expects:
        {
            "assets_ids": ["token_id1", "token_id2", ...],
            "type": "market"
        }

        Args:
            ws: Active WebSocket connection
            market_ids: List of token IDs to subscribe to
            batch_size: Number of markets per subscription batch (default 20)

        Returns:
            Number of markets subscribed
        """
        if not market_ids:
            logger.warning("No market IDs provided for subscription")
            return 0

        logger.info(f"Subscribing to {len(market_ids)} Polymarket markets using batched subscription (batch size: {batch_size})...")

        # Extract token IDs from market IDs (market_id might be conditionId, we need tokenID)
        # For Polymarket, we'll use the market_ids as-is since they should be token IDs
        total_subscribed = 0

        # Split into batches
        for batch_start in range(0, len(market_ids), batch_size):
            batch = market_ids[batch_start:batch_start + batch_size]
            batch_num = (batch_start // batch_size) + 1
            total_batches = (len(market_ids) + batch_size - 1) // batch_size

            # Check if connection is still open
            if ws.closed:
                logger.error(f"WebSocket closed during subscription at batch {batch_num}/{total_batches}")
                break

            try:
                # Use Polymarket's documented format
                subscribe_msg = {
                    "assets_ids": batch,  # Array of token IDs
                    "type": "market"      # Channel type
                }

                logger.info(f"Sending subscription batch {batch_num}/{total_batches} ({len(batch)} markets)")
                logger.debug(f"Subscription payload: {json.dumps(subscribe_msg)}")

                # Send subscription message
                await ws.send(json.dumps(subscribe_msg))

                # Track all markets in this batch as pending
                for market_id in batch:
                    self.pending_subscriptions.add(market_id)

                # Wait for first messages to arrive (Polymarket sends book updates, not ACKs)
                await asyncio.sleep(2.0)

                # Count how many we got confirmations for
                confirmed_in_batch = 0
                for market_id in batch:
                    if market_id in self.subscribed_markets:
                        confirmed_in_batch += 1

                total_subscribed += len(batch)  # Consider all sent as subscribed
                logger.info(
                    f"Batch {batch_num}/{total_batches} sent ({len(batch)} markets). "
                    f"Received data for {confirmed_in_batch} markets so far. "
                    f"Total: {total_subscribed}/{len(market_ids)}"
                )

                # Throttle between batches (not too aggressive)
                if batch_start + batch_size < len(market_ids):
                    await asyncio.sleep(1.0)

            except websockets.exceptions.ConnectionClosed as e:
                logger.error(f"WebSocket closed during subscription: code={e.code}, reason={e.reason}")
                break
            except Exception as e:
                logger.error(f"Error sending subscription batch {batch_num}: {e}", exc_info=True)
                # Continue with next batch
                continue

        logger.info(
            f"Subscription complete: sent {total_subscribed} markets in {total_batches} batches. "
            f"Confirmed via messages: {len(self.subscribed_markets)}"
        )
        return total_subscribed

    def _create_subscription_groups(self, market_ids: List[str]):
        """
        Create subscription groups for rotation.

        Args:
            market_ids: Full list of market IDs
        """
        self.subscription_groups = []
        for i in range(0, len(market_ids), self.markets_per_group):
            group = market_ids[i:i + self.markets_per_group]
            self.subscription_groups.append(group)

        logger.info(f"Created {len(self.subscription_groups)} subscription groups with {self.markets_per_group} markets each")

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

    async def _rotation_task(self, ws: websockets.WebSocketClientProtocol):
        """
        Rotate subscriptions between market groups.

        Args:
            ws: Active WebSocket connection
        """
        try:
            while not ws.closed:
                # Wait for rotation interval
                await asyncio.sleep(self.rotation_interval)

                if not self.subscription_groups or ws.closed:
                    break

                # Unsubscribe from current group
                current_group = self.subscription_groups[self.current_group_index]
                for market_id in current_group:
                    try:
                        unsubscribe_msg = {
                            "type": "unsubscribe",
                            "channel": "market",
                            "market": market_id
                        }
                        await ws.send(json.dumps(unsubscribe_msg))
                    except Exception as e:
                        logger.debug(f"Error unsubscribing from {market_id}: {e}")

                # Move to next group
                self.current_group_index = (self.current_group_index + 1) % len(self.subscription_groups)
                next_group = self.subscription_groups[self.current_group_index]

                logger.info(f"Rotating subscriptions: group {self.current_group_index + 1}/{len(self.subscription_groups)} ({len(next_group)} markets)")

                # Subscribe to next group using batched subscription
                successful = await self._subscribe_with_batching(ws, next_group, batch_size=20)
                self.last_rotation_time = datetime.utcnow()

                logger.info(f"Subscription rotation complete: {successful} markets subscribed")

        except asyncio.CancelledError:
            # Normal cancellation
            pass
        except Exception as e:
            logger.error(f"Polymarket rotation task error: {e}")

    async def connect_websocket(self, market_ids: List[str] = None):
        """
        Connect to Polymarket WebSocket feed and subscribe to markets with rotation.

        Args:
            market_ids: List of market/token IDs to subscribe to (None = all)
        """
        reconnect_delay = self.config.reconnect_base_delay
        reconnect_count = 0

        # Create subscription groups if market IDs provided
        if market_ids and len(market_ids) > self.markets_per_group:
            self._create_subscription_groups(market_ids)
            initial_subscription = self.subscription_groups[0] if self.subscription_groups else market_ids
        else:
            initial_subscription = market_ids

        while True:
            try:
                logger.info(f"Connecting to Polymarket WebSocket (attempt {reconnect_count + 1})...")

                async with websockets.connect(
                    self.ws_url,
                    ping_interval=15,  # 15s keepalive as per requirements
                    ping_timeout=10
                ) as ws:
                    self.ws_connection = ws
                    logger.info("Polymarket WebSocket connected, waiting for handshake completion...")

                    # CRITICAL FIX: Wait for WebSocket handshake to complete
                    # This prevents "no close frame received or sent" errors
                    await asyncio.sleep(2.0)
                    logger.info("WebSocket handshake complete, ready for subscriptions")

                    # Start keepalive task in background
                    keepalive_task = asyncio.create_task(self._keepalive_task(ws))

                    # Start rotation task if using groups
                    rotation_task = None
                    if self.subscription_groups:
                        rotation_task = asyncio.create_task(self._rotation_task(ws))

                    try:
                        # Subscribe to initial markets using correct Polymarket format
                        if initial_subscription:
                            # Use batched subscription with Polymarket's documented format
                            successful_subs = await self._subscribe_with_batching(ws, initial_subscription, batch_size=20)

                            if successful_subs == 0:
                                logger.error("Failed to send any subscription batches, will reconnect")
                                keepalive_task.cancel()
                                if rotation_task:
                                    rotation_task.cancel()
                                continue

                            if self.subscription_groups:
                                logger.info(f"Subscribed to {successful_subs} markets in group 1/{len(self.subscription_groups)}")
                                self.last_rotation_time = datetime.utcnow()
                            else:
                                logger.info(f"Subscribed to {successful_subs} Polymarket markets")
                        else:
                            logger.info("No specific markets to subscribe to, listening to all updates")

                        # Reset reconnect delay on successful connection and subscription
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
                        # Clean up tasks
                        keepalive_task.cancel()
                        if rotation_task:
                            rotation_task.cancel()
                        try:
                            await keepalive_task
                            if rotation_task:
                                await rotation_task
                        except asyncio.CancelledError:
                            pass

            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(
                    f"Polymarket WebSocket connection closed: "
                    f"code={e.code}, reason={e.reason or 'no reason provided'}"
                )
                logger.debug(f"Close details: rcvd={e.rcvd}, sent={e.sent}")
                reconnect_count += 1
            except Exception as e:
                logger.error(f"Polymarket WebSocket error: {e}", exc_info=True)
                reconnect_count += 1

            # Exponential backoff for reconnection (start at 2s, cap at 60s as per requirements)
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

        try:
            # Use Polymarket's documented format: {"assets_ids": [...], "type": "market"}
            subscribe_msg = {
                "assets_ids": [token_id],
                "type": "market"
            }
            await self.ws_connection.send(json.dumps(subscribe_msg))
            logger.debug(f"Subscribed to Polymarket token: {token_id}")

        except Exception as e:
            logger.error(f"Error subscribing to Polymarket token {token_id}: {e}")
