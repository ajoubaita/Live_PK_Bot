"""
Runtime supervisor module.
Orchestrates all bot components and manages lifecycle.
"""

import asyncio
import logging
import signal
from typing import Optional
from datetime import datetime

from models import BotMetrics, Platform
from config import get_config
from kalshi_client import KalshiClient
from polymarket_client import PolymarketClient
from market_discovery import MarketDiscovery
from orderbook_manager import OrderBookManager
from arbitrage_engine import ArbitrageEngine
from trade_logger import TradeLogger

logger = logging.getLogger(__name__)


class BotSupervisor:
    """
    Main supervisor that coordinates all bot components.
    Manages lifecycle, health checks, and graceful shutdown.
    """

    def __init__(self):
        """Initialize the bot supervisor."""
        self.config = get_config()
        self.metrics = BotMetrics()
        self.running = False
        self.shutdown_event = asyncio.Event()

        # Component instances
        self.kalshi_client: Optional[KalshiClient] = None
        self.polymarket_client: Optional[PolymarketClient] = None
        self.market_discovery: Optional[MarketDiscovery] = None
        self.orderbook_manager: Optional[OrderBookManager] = None
        self.arbitrage_engine: Optional[ArbitrageEngine] = None
        self.trade_logger: Optional[TradeLogger] = None

        # Background tasks
        self.tasks = []

    async def initialize(self):
        """
        Initialize all bot components.
        """
        logger.info("Initializing bot components...")

        try:
            # Initialize clients
            self.kalshi_client = KalshiClient()
            self.polymarket_client = PolymarketClient()

            await self.kalshi_client.connect()
            await self.polymarket_client.connect()

            self.metrics.kalshi_connected = True
            self.metrics.polymarket_connected = True

            # Initialize market discovery
            self.market_discovery = MarketDiscovery(
                self.kalshi_client,
                self.polymarket_client
            )

            # Initialize orderbook manager
            self.orderbook_manager = OrderBookManager()

            # Register WebSocket message handlers
            self.kalshi_client.register_message_handler(
                self.orderbook_manager.handle_websocket_message
            )
            self.polymarket_client.register_message_handler(
                self.orderbook_manager.handle_websocket_message
            )

            # Initialize arbitrage engine
            self.arbitrage_engine = ArbitrageEngine(
                self.orderbook_manager,
                self.market_discovery,
                self.metrics
            )

            # Initialize trade logger
            self.trade_logger = TradeLogger()
            await self.trade_logger.initialize()

            logger.info("All components initialized successfully")

        except Exception as e:
            logger.error(f"Error during initialization: {e}")
            self.metrics.last_error = str(e)
            self.metrics.last_error_time = datetime.utcnow()
            raise

    async def start(self):
        """
        Start the bot and all background tasks.
        """
        logger.info("Starting arbitrage trading bot...")
        self.running = True

        try:
            # Discover markets initially
            await self.market_discovery.discover_all_markets()
            self.market_discovery.find_market_pairs()

            # Initialize orderbooks for all discovered markets
            for market in self.market_discovery.get_all_markets():
                await self.orderbook_manager.initialize_market(market)

            # Update market count metric
            self.metrics.markets_tracked = await self.orderbook_manager.get_market_count()

            # Start WebSocket feeds
            kalshi_market_ids = self.market_discovery.get_market_ids_by_platform(Platform.KALSHI)
            polymarket_market_ids = self.market_discovery.get_market_ids_by_platform(Platform.POLYMARKET)

            kalshi_ws_task = asyncio.create_task(
                self.kalshi_client.connect_websocket(kalshi_market_ids[:50])  # Limit for demo
            )
            polymarket_ws_task = asyncio.create_task(
                self.polymarket_client.connect_websocket(polymarket_market_ids[:50])
            )

            self.tasks.extend([kalshi_ws_task, polymarket_ws_task])

            # Start arbitrage scanning loop
            arb_task = asyncio.create_task(self._arbitrage_loop())
            self.tasks.append(arb_task)

            # Start market refresh loop
            refresh_task = asyncio.create_task(self._market_refresh_loop())
            self.tasks.append(refresh_task)

            # Start health check loop
            health_task = asyncio.create_task(self._health_check_loop())
            self.tasks.append(health_task)

            # Start metrics logging loop
            metrics_task = asyncio.create_task(self._metrics_loop())
            self.tasks.append(metrics_task)

            # Start status display loop
            status_task = asyncio.create_task(self._status_display_loop())
            self.tasks.append(status_task)

            logger.info("Bot started successfully - monitoring for arbitrage opportunities")

            # Wait for shutdown signal
            await self.shutdown_event.wait()

        except Exception as e:
            logger.error(f"Error during bot execution: {e}")
            self.metrics.last_error = str(e)
            self.metrics.last_error_time = datetime.utcnow()
            raise

        finally:
            await self.stop()

    async def stop(self):
        """
        Stop the bot and cleanup resources.
        """
        logger.info("Stopping bot...")
        self.running = False

        # Cancel all background tasks
        for task in self.tasks:
            if not task.done():
                task.cancel()

        # Wait for tasks to complete
        await asyncio.gather(*self.tasks, return_exceptions=True)

        # Close all connections
        if self.kalshi_client:
            await self.kalshi_client.disconnect()

        if self.polymarket_client:
            await self.polymarket_client.disconnect()

        if self.trade_logger:
            await self.trade_logger.close()

        logger.info("Bot stopped")

    async def _arbitrage_loop(self):
        """
        Main arbitrage scanning loop.
        Continuously checks for opportunities and simulates trades.
        """
        while self.running:
            try:
                # Scan for opportunities
                opportunities = await self.arbitrage_engine.scan_for_opportunities()

                # Simulate trades for each opportunity
                for opp in opportunities:
                    # Re-validate opportunity is still good
                    if await self.arbitrage_engine.evaluate_opportunity(opp):
                        # Log the simulated trade
                        await self.trade_logger.log_simulated_trade(opp)

                        # Update metrics
                        self.metrics.trades_simulated += 1
                        self.metrics.total_simulated_profit += opp.expected_profit

                        logger.info(
                            f"SIMULATED TRADE: {opp.opportunity_type} | "
                            f"Buy {opp.buy_outcome.value} on {opp.buy_platform.value}@{opp.buy_price:.4f} | "
                            f"Sell {opp.sell_outcome.value} on {opp.sell_platform.value}@{opp.sell_price:.4f} | "
                            f"Profit: ${opp.expected_profit:.2f} ({opp.expected_return_pct:.2f}%)"
                        )

                # Sleep before next scan
                await asyncio.sleep(self.config.update_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in arbitrage loop: {e}")
                self.metrics.last_error = str(e)
                self.metrics.last_error_time = datetime.utcnow()
                await asyncio.sleep(1)  # Brief pause before retrying

    async def _market_refresh_loop(self):
        """
        Periodically refresh market data.
        """
        while self.running:
            try:
                await asyncio.sleep(self.config.market_refresh_interval)
                await self.market_discovery.refresh_markets()

                # Update market count
                self.metrics.markets_tracked = await self.orderbook_manager.get_market_count()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in market refresh loop: {e}")
                self.metrics.last_error = str(e)
                self.metrics.last_error_time = datetime.utcnow()

    async def _health_check_loop(self):
        """
        Periodically check health of connections and components.
        """
        while self.running:
            try:
                await asyncio.sleep(self.config.heartbeat_interval)

                # Check client connections
                self.metrics.kalshi_connected = self.kalshi_client.is_connected if self.kalshi_client else False
                self.metrics.polymarket_connected = self.polymarket_client.is_connected if self.polymarket_client else False

                # Log health status
                if not self.metrics.kalshi_connected:
                    logger.warning("Kalshi client is disconnected")

                if not self.metrics.polymarket_connected:
                    logger.warning("Polymarket client is disconnected")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in health check loop: {e}")

    async def _metrics_loop(self):
        """
        Periodically log metrics to database.
        """
        while self.running:
            try:
                await asyncio.sleep(60)  # Log metrics every minute
                await self.trade_logger.log_metrics(self.metrics)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in metrics loop: {e}")

    async def _status_display_loop(self):
        """
        Periodically display bot status to console.
        """
        while self.running:
            try:
                await asyncio.sleep(30)  # Display every 30 seconds

                status = (
                    f"\n{'='*80}\n"
                    f"Bot Status - Uptime: {self.metrics.uptime_str()}\n"
                    f"{'-'*80}\n"
                    f"Markets Tracked: {self.metrics.markets_tracked}\n"
                    f"Opportunities Detected: {self.metrics.opportunities_detected}\n"
                    f"Trades Simulated: {self.metrics.trades_simulated}\n"
                    f"Total Simulated Profit: ${self.metrics.total_simulated_profit:.2f}\n"
                    f"Kalshi Connected: {'✓' if self.metrics.kalshi_connected else '✗'}\n"
                    f"Polymarket Connected: {'✓' if self.metrics.polymarket_connected else '✗'}\n"
                )

                if self.metrics.last_error:
                    status += f"Last Error: {self.metrics.last_error[:50]}...\n"

                status += f"{'='*80}\n"

                logger.info(status)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in status display loop: {e}")

    def setup_signal_handlers(self):
        """
        Setup signal handlers for graceful shutdown.
        """
        def signal_handler(sig, frame):
            logger.info(f"Received signal {sig}, initiating shutdown...")
            self.shutdown_event.set()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
