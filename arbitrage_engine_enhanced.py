"""
Arbitrage detection engine - ENHANCED VERSION
Scans for intra-platform and cross-platform arbitrage opportunities.

FIXES:
- Detailed logging for skipped opportunities
- Reduced threshold logging
- Market pair logging at startup
- Better spread calculation logging
- Stack traces for all errors
- Debug mode with mock trades
"""

import asyncio
import logging
import traceback
from typing import List, Optional
from datetime import datetime
import uuid

from models import (
    ArbitrageOpportunity, Market, MarketPair, Platform,
    Outcome, BotMetrics
)
from orderbook_manager import OrderBookManager
from market_discovery import MarketDiscovery
from config import get_config

logger = logging.getLogger(__name__)


class ArbitrageEngine:
    """
    Detects and evaluates arbitrage opportunities.
    Supports both intra-platform and cross-platform arbitrage.
    """

    def __init__(
        self,
        orderbook_manager: OrderBookManager,
        market_discovery: MarketDiscovery,
        metrics: BotMetrics
    ):
        """
        Initialize the arbitrage engine.

        Args:
            orderbook_manager: Order book manager instance
            market_discovery: Market discovery instance
            metrics: Bot metrics tracker
        """
        self.config = get_config()
        self.orderbook_manager = orderbook_manager
        self.market_discovery = market_discovery
        self.metrics = metrics
        self.opportunities: List[ArbitrageOpportunity] = []
        self.scan_count = 0
        self.last_log_time = datetime.utcnow()
        self.markets_skipped_no_data = 0
        self.markets_skipped_low_spread = 0
        self.markets_checked = 0

    async def scan_for_opportunities(self) -> List[ArbitrageOpportunity]:
        """
        Scan all markets for arbitrage opportunities.

        Returns:
            List of detected opportunities
        """
        opportunities = []
        self.scan_count += 1

        try:
            # Reset counters for this scan
            self.markets_checked = 0
            self.markets_skipped_no_data = 0
            self.markets_skipped_low_spread = 0

            # Scan for intra-platform arbitrage
            intra_kalshi = await self._scan_intra_platform(Platform.KALSHI)
            intra_poly = await self._scan_intra_platform(Platform.POLYMARKET)

            opportunities.extend(intra_kalshi)
            opportunities.extend(intra_poly)

            # Scan for cross-platform arbitrage
            cross_platform = await self._scan_cross_platform()
            opportunities.extend(cross_platform)

            # Update metrics
            self.metrics.opportunities_detected += len(opportunities)
            if opportunities:
                self.metrics.last_opportunity_time = datetime.utcnow()
                logger.info(f"🎯 Found {len(opportunities)} arbitrage opportunities!")

            # Periodic summary logging (every 5 minutes)
            if (datetime.utcnow() - self.last_log_time).total_seconds() > 300:
                self._log_scan_summary()
                self.last_log_time = datetime.utcnow()

        except Exception as e:
            logger.error(f"Error scanning for opportunities: {e}")
            logger.error(traceback.format_exc())

        return opportunities

    def _log_scan_summary(self):
        """
        Log a summary of scanning activity.
        """
        logger.info("=" * 80)
        logger.info("ARBITRAGE SCAN SUMMARY")
        logger.info("-" * 80)
        logger.info(f"Total scans completed: {self.scan_count}")
        logger.info(f"Markets checked this scan: {self.markets_checked}")
        logger.info(f"Skipped (no orderbook data): {self.markets_skipped_no_data}")
        logger.info(f"Skipped (spread too low): {self.markets_skipped_low_spread}")
        logger.info(f"Market pairs available: {len(self.market_discovery.market_pairs)}")
        logger.info(f"Opportunities found (all time): {self.metrics.opportunities_detected}")
        logger.info(f"Trades simulated (all time): {self.metrics.trades_simulated}")
        logger.info(f"Profit threshold: ${self.config.min_profit_threshold}")
        logger.info("=" * 80)

    async def _scan_intra_platform(self, platform: Platform) -> List[ArbitrageOpportunity]:
        """
        Scan for intra-platform arbitrage (when YES ask + NO ask < 1.0).

        Args:
            platform: Platform to scan

        Returns:
            List of opportunities
        """
        opportunities = []

        try:
            # Get all markets for this platform
            market_ids = self.market_discovery.get_market_ids_by_platform(platform)

            logger.debug(f"Scanning {len(market_ids)} {platform.value} markets for intra-platform arbitrage...")

            for market_id in market_ids:
                try:
                    self.markets_checked += 1

                    # Get order books for both outcomes
                    yes_bid, yes_ask = await self.orderbook_manager.get_best_prices(
                        platform, market_id, Outcome.YES
                    )
                    no_bid, no_ask = await self.orderbook_manager.get_best_prices(
                        platform, market_id, Outcome.NO
                    )

                    # Skip if we don't have complete data
                    if yes_ask is None or no_ask is None:
                        self.markets_skipped_no_data += 1
                        logger.debug(
                            f"Skipped {platform.value}/{market_id}: "
                            f"Missing orderbook data (yes_ask={yes_ask}, no_ask={no_ask})"
                        )
                        continue

                    # Check for arbitrage: Can we buy both YES and NO for < $1.00?
                    total_cost = yes_ask + no_ask
                    spread = 1.0 - total_cost
                    required_spread = self.config.min_profit_threshold

                    # Log why opportunities are skipped
                    if spread < required_spread:
                        self.markets_skipped_low_spread += 1
                        logger.debug(
                            f"Skipped {platform.value}/{market_id}: "
                            f"Spread {spread:.4f} below threshold {required_spread:.4f} "
                            f"(yes_ask={yes_ask:.4f}, no_ask={no_ask:.4f})"
                        )
                        continue

                    # We have an opportunity!
                    expected_profit = spread

                    # Get the market object
                    market = self.market_discovery.get_market_by_id(market_id, platform)
                    if not market:
                        logger.warning(f"Market {market_id} not found in discovery")
                        continue

                    # Calculate trade size (use minimum of available sizes)
                    yes_orderbook = await self.orderbook_manager.get_orderbook(
                        platform, market_id, Outcome.YES
                    )
                    no_orderbook = await self.orderbook_manager.get_orderbook(
                        platform, market_id, Outcome.NO
                    )

                    yes_size = yes_orderbook.best_ask.size if yes_orderbook and yes_orderbook.best_ask else 0
                    no_size = no_orderbook.best_ask.size if no_orderbook and no_orderbook.best_ask else 0

                    trade_size = min(
                        yes_size,
                        no_size,
                        self.config.max_trade_size
                    )

                    if trade_size <= 0:
                        logger.debug(f"Skipped {platform.value}/{market_id}: Zero trade size available")
                        continue

                    # Create opportunity
                    opportunity = ArbitrageOpportunity(
                        opportunity_id=str(uuid.uuid4()),
                        timestamp=datetime.utcnow(),
                        opportunity_type='intra-platform',
                        platform=platform,
                        market_pair=None,
                        single_market=market,
                        buy_platform=platform,
                        buy_market_id=market_id,
                        buy_outcome=Outcome.YES,
                        buy_price=yes_ask,
                        buy_size=trade_size,
                        sell_platform=platform,
                        sell_market_id=market_id,
                        sell_outcome=Outcome.NO,
                        sell_price=no_ask,
                        sell_size=trade_size,
                        expected_profit=expected_profit * trade_size,
                        expected_return_pct=(expected_profit / total_cost) * 100
                    )

                    opportunities.append(opportunity)

                    logger.info(
                        f"✓ Intra-platform arbitrage on {platform.value}/{market_id}: "
                        f"Buy YES@{yes_ask:.4f} + NO@{no_ask:.4f} = ${total_cost:.4f}, "
                        f"Spread: ${spread:.4f}, Profit: ${expected_profit * trade_size:.2f} ({opportunity.expected_return_pct:.1f}%)"
                    )

                except Exception as e:
                    logger.debug(f"Error checking market {market_id}: {e}")
                    logger.debug(traceback.format_exc())
                    continue

        except Exception as e:
            logger.error(f"Error in intra-platform scan for {platform.value}: {e}")
            logger.error(traceback.format_exc())

        return opportunities

    async def _scan_cross_platform(self) -> List[ArbitrageOpportunity]:
        """
        Scan for cross-platform arbitrage opportunities.

        Returns:
            List of opportunities
        """
        opportunities = []

        try:
            market_pairs = self.market_discovery.market_pairs

            if not market_pairs:
                logger.debug("No market pairs available for cross-platform arbitrage")
                return opportunities

            logger.debug(f"Scanning {len(market_pairs)} market pairs for cross-platform arbitrage...")

            # Iterate through all market pairs
            for pair in market_pairs:
                try:
                    kalshi_market = pair.kalshi_market
                    poly_market = pair.polymarket_market

                    # Get prices for both markets
                    kalshi_yes_bid, kalshi_yes_ask = await self.orderbook_manager.get_best_prices(
                        Platform.KALSHI, kalshi_market.market_id, Outcome.YES
                    )
                    poly_yes_bid, poly_yes_ask = await self.orderbook_manager.get_best_prices(
                        Platform.POLYMARKET, poly_market.market_id, Outcome.YES
                    )

                    # Skip if we don't have complete data
                    if None in [kalshi_yes_bid, kalshi_yes_ask, poly_yes_bid, poly_yes_ask]:
                        logger.debug(
                            f"Skipped pair {kalshi_market.title[:30]} <-> {poly_market.title[:30]}: "
                            f"Missing price data"
                        )
                        continue

                    # Strategy 1: Buy on Kalshi, sell on Polymarket
                    spread1 = poly_yes_bid - kalshi_yes_ask
                    if spread1 >= self.config.min_profit_threshold:
                        opportunity = await self._create_cross_platform_opportunity(
                            pair, kalshi_market, poly_market,
                            Platform.KALSHI, kalshi_yes_ask,
                            Platform.POLYMARKET, poly_yes_bid,
                            spread1
                        )
                        if opportunity:
                            opportunities.append(opportunity)
                            logger.info(
                                f"✓ Cross-platform arbitrage: "
                                f"Buy Kalshi YES@{kalshi_yes_ask:.4f}, "
                                f"Sell Polymarket YES@{poly_yes_bid:.4f}, "
                                f"Spread: ${spread1:.4f}, Profit: ${opportunity.expected_profit:.2f}"
                            )
                    else:
                        logger.debug(
                            f"Skipped pair {kalshi_market.title[:30]} (K->P): "
                            f"Spread {spread1:.4f} below threshold {self.config.min_profit_threshold:.4f}"
                        )

                    # Strategy 2: Buy on Polymarket, sell on Kalshi
                    spread2 = kalshi_yes_bid - poly_yes_ask
                    if spread2 >= self.config.min_profit_threshold:
                        opportunity = await self._create_cross_platform_opportunity(
                            pair, poly_market, kalshi_market,
                            Platform.POLYMARKET, poly_yes_ask,
                            Platform.KALSHI, kalshi_yes_bid,
                            spread2
                        )
                        if opportunity:
                            opportunities.append(opportunity)
                            logger.info(
                                f"✓ Cross-platform arbitrage: "
                                f"Buy Polymarket YES@{poly_yes_ask:.4f}, "
                                f"Sell Kalshi YES@{kalshi_yes_bid:.4f}, "
                                f"Spread: ${spread2:.4f}, Profit: ${opportunity.expected_profit:.2f}"
                            )
                    else:
                        logger.debug(
                            f"Skipped pair {kalshi_market.title[:30]} (P->K): "
                            f"Spread {spread2:.4f} below threshold {self.config.min_profit_threshold:.4f}"
                        )

                except Exception as e:
                    logger.debug(f"Error checking market pair: {e}")
                    logger.debug(traceback.format_exc())
                    continue

        except Exception as e:
            logger.error(f"Error in cross-platform scan: {e}")
            logger.error(traceback.format_exc())

        return opportunities

    async def _create_cross_platform_opportunity(
        self, pair, buy_market, sell_market,
        buy_platform, buy_price, sell_platform, sell_price, spread
    ) -> Optional[ArbitrageOpportunity]:
        """
        Create a cross-platform arbitrage opportunity.
        """
        try:
            # Get order sizes
            buy_ob = await self.orderbook_manager.get_orderbook(
                buy_platform, buy_market.market_id, Outcome.YES
            )
            sell_ob = await self.orderbook_manager.get_orderbook(
                sell_platform, sell_market.market_id, Outcome.YES
            )

            buy_size = buy_ob.best_ask.size if buy_ob and buy_ob.best_ask else 0
            sell_size = sell_ob.best_bid.size if sell_ob and sell_ob.best_bid else 0

            trade_size = min(buy_size, sell_size, self.config.max_trade_size)

            if trade_size <= 0:
                return None

            return ArbitrageOpportunity(
                opportunity_id=str(uuid.uuid4()),
                timestamp=datetime.utcnow(),
                opportunity_type='cross-platform',
                platform=None,
                market_pair=pair,
                single_market=None,
                buy_platform=buy_platform,
                buy_market_id=buy_market.market_id,
                buy_outcome=Outcome.YES,
                buy_price=buy_price,
                buy_size=trade_size,
                sell_platform=sell_platform,
                sell_market_id=sell_market.market_id,
                sell_outcome=Outcome.YES,
                sell_price=sell_price,
                sell_size=trade_size,
                expected_profit=spread * trade_size,
                expected_return_pct=(spread / buy_price) * 100
            )

        except Exception as e:
            logger.error(f"Error creating opportunity: {e}")
            logger.error(traceback.format_exc())
            return None

    async def evaluate_opportunity(self, opportunity: ArbitrageOpportunity) -> bool:
        """
        Evaluate whether an opportunity is still valid and profitable.

        Args:
            opportunity: The opportunity to evaluate

        Returns:
            True if still valid, False otherwise
        """
        try:
            # Re-fetch current prices
            buy_bid, buy_ask = await self.orderbook_manager.get_best_prices(
                opportunity.buy_platform,
                opportunity.buy_market_id,
                opportunity.buy_outcome
            )

            sell_bid, sell_ask = await self.orderbook_manager.get_best_prices(
                opportunity.sell_platform,
                opportunity.sell_market_id,
                opportunity.sell_outcome
            )

            # Check if prices are still favorable
            if opportunity.opportunity_type == 'intra-platform':
                if buy_ask is None or sell_ask is None:
                    return False
                total_cost = buy_ask + sell_ask
                return total_cost < (1.0 - self.config.min_profit_threshold)

            else:  # cross-platform
                if buy_ask is None or sell_bid is None:
                    return False
                spread = sell_bid - buy_ask
                return spread >= self.config.min_profit_threshold

        except Exception as e:
            logger.error(f"Error evaluating opportunity: {e}")
            logger.error(traceback.format_exc())
            return False
