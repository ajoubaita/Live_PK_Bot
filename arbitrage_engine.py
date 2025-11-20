"""
Arbitrage detection engine.
Scans for intra-platform and cross-platform arbitrage opportunities.
"""

import asyncio
import logging
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

        # Scan statistics for logging
        self.scan_stats = {
            'markets_checked': 0,
            'markets_skipped_no_data': 0,
            'markets_skipped_low_spread': 0,
            'markets_skipped_no_size': 0,
            'last_summary_time': datetime.utcnow()
        }

        # Profitability tracking
        self.session_stats = {
            'total_opportunities': 0,
            'total_potential_profit': 0.0,
            'best_opportunity_profit': 0.0,
            'best_opportunity_return_pct': 0.0,
            'opportunities_by_type': {'intra-platform': 0, 'cross-platform': 0},
            'session_start': datetime.utcnow()
        }

    def _log_opportunity_details(self, opportunity: ArbitrageOpportunity):
        """Log detailed information about a detected opportunity for profitability analysis."""
        # Update session stats
        self.session_stats['total_opportunities'] += 1
        self.session_stats['total_potential_profit'] += opportunity.expected_profit
        self.session_stats['opportunities_by_type'][opportunity.opportunity_type] += 1

        if opportunity.expected_profit > self.session_stats['best_opportunity_profit']:
            self.session_stats['best_opportunity_profit'] = opportunity.expected_profit
            self.session_stats['best_opportunity_return_pct'] = opportunity.expected_return_pct

        # Log detailed trade information
        if opportunity.opportunity_type == 'intra-platform':
            market_name = opportunity.single_market.title[:50] if opportunity.single_market else 'Unknown'
            logger.info(
                f"\n{'='*60}\n"
                f"💰 ARBITRAGE OPPORTUNITY DETECTED\n"
                f"{'='*60}\n"
                f"Type: {opportunity.opportunity_type.upper()}\n"
                f"Platform: {opportunity.buy_platform.value}\n"
                f"Market: {market_name}\n"
                f"Strategy: Buy YES@${opportunity.buy_price:.4f} + NO@${opportunity.sell_price:.4f}\n"
                f"Total Cost: ${opportunity.buy_price + opportunity.sell_price:.4f}\n"
                f"Trade Size: {opportunity.buy_size} contracts\n"
                f"Expected Profit: ${opportunity.expected_profit:.2f}\n"
                f"Return: {opportunity.expected_return_pct:.2f}%\n"
                f"Time: {opportunity.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
                f"{'='*60}"
            )
        else:  # cross-platform
            kalshi_name = opportunity.market_pair.kalshi_market.title[:40] if opportunity.market_pair else 'Unknown'
            poly_name = opportunity.market_pair.polymarket_market.title[:40] if opportunity.market_pair else 'Unknown'
            logger.info(
                f"\n{'='*60}\n"
                f"💰 ARBITRAGE OPPORTUNITY DETECTED\n"
                f"{'='*60}\n"
                f"Type: {opportunity.opportunity_type.upper()}\n"
                f"Buy: {opportunity.buy_platform.value} @ ${opportunity.buy_price:.4f}\n"
                f"  Market: {kalshi_name if opportunity.buy_platform == Platform.KALSHI else poly_name}\n"
                f"Sell: {opportunity.sell_platform.value} @ ${opportunity.sell_price:.4f}\n"
                f"  Market: {poly_name if opportunity.sell_platform == Platform.POLYMARKET else kalshi_name}\n"
                f"Spread: ${opportunity.sell_price - opportunity.buy_price:.4f}\n"
                f"Trade Size: {opportunity.buy_size} contracts\n"
                f"Expected Profit: ${opportunity.expected_profit:.2f}\n"
                f"Return: {opportunity.expected_return_pct:.2f}%\n"
                f"Time: {opportunity.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
                f"{'='*60}"
            )

    def _log_scan_summary(self):
        """Log periodic summary of scan statistics."""
        now = datetime.utcnow()
        elapsed = (now - self.scan_stats['last_summary_time']).total_seconds()

        # Log summary every 5 minutes
        if elapsed >= 300:
            # Calculate session duration
            session_duration = (now - self.session_stats['session_start']).total_seconds()
            hours = int(session_duration // 3600)
            minutes = int((session_duration % 3600) // 60)

            logger.info(
                f"\n{'='*60}\n"
                f"📊 ARBITRAGE SCAN SUMMARY (last 5 minutes)\n"
                f"{'='*60}\n"
                f"Markets checked: {self.scan_stats['markets_checked']}\n"
                f"Skipped (no data): {self.scan_stats['markets_skipped_no_data']}\n"
                f"Skipped (low spread): {self.scan_stats['markets_skipped_low_spread']}\n"
                f"Skipped (no size): {self.scan_stats['markets_skipped_no_size']}\n"
                f"Opportunities found this period: {self.metrics.opportunities_detected}\n"
                f"{'='*60}\n"
                f"📈 SESSION PROFITABILITY (running {hours}h {minutes}m)\n"
                f"{'='*60}\n"
                f"Total opportunities: {self.session_stats['total_opportunities']}\n"
                f"  - Intra-platform: {self.session_stats['opportunities_by_type']['intra-platform']}\n"
                f"  - Cross-platform: {self.session_stats['opportunities_by_type']['cross-platform']}\n"
                f"Total potential profit: ${self.session_stats['total_potential_profit']:.2f}\n"
                f"Best single opportunity: ${self.session_stats['best_opportunity_profit']:.2f} ({self.session_stats['best_opportunity_return_pct']:.2f}%)\n"
                f"Avg profit per opportunity: ${self.session_stats['total_potential_profit'] / max(1, self.session_stats['total_opportunities']):.2f}\n"
                f"{'='*60}"
            )

            # Reset scan stats (but not session stats)
            self.scan_stats = {
                'markets_checked': 0,
                'markets_skipped_no_data': 0,
                'markets_skipped_low_spread': 0,
                'markets_skipped_no_size': 0,
                'last_summary_time': now
            }

    async def scan_for_opportunities(self) -> List[ArbitrageOpportunity]:
        """
        Scan all markets for arbitrage opportunities.

        Returns:
            List of detected opportunities
        """
        opportunities = []

        try:
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

            if opportunities:
                logger.info(f"Found {len(opportunities)} arbitrage opportunities")
            else:
                # Log suspected cause when no opportunities found
                logger.debug(
                    f"No arbitrage opportunities found. "
                    f"Markets checked: {self.scan_stats['markets_checked']}, "
                    f"Possible reasons: insufficient orderbook data, spreads below threshold ({self.config.min_profit_threshold}), "
                    f"or no available liquidity"
                )

            # Log periodic summary
            self._log_scan_summary()

        except Exception as e:
            logger.error(f"Error scanning for opportunities: {e}")

        return opportunities

    async def _scan_intra_platform(self, platform: Platform) -> List[ArbitrageOpportunity]:
        """
        Scan for intra-platform arbitrage (when YES bid + NO bid < 1.0).

        Args:
            platform: Platform to scan

        Returns:
            List of opportunities
        """
        opportunities = []

        try:
            # Get all markets for this platform
            market_ids = self.market_discovery.get_market_ids_by_platform(platform)

            for market_id in market_ids:
                try:
                    self.scan_stats['markets_checked'] += 1

                    # Get order books for both outcomes
                    yes_bid, yes_ask = await self.orderbook_manager.get_best_prices(
                        platform, market_id, Outcome.YES
                    )
                    no_bid, no_ask = await self.orderbook_manager.get_best_prices(
                        platform, market_id, Outcome.NO
                    )

                    # Skip if we don't have complete data
                    if yes_bid is None or no_bid is None:
                        self.scan_stats['markets_skipped_no_data'] += 1
                        logger.debug(f"Skipped {platform.value}/{market_id}: Missing bid data")
                        continue

                    # Check for arbitrage: Can we buy both YES and NO for < $1.00?
                    # We buy at the ask price, so we need yes_ask + no_ask < 1.0
                    if yes_ask is not None and no_ask is not None:
                        total_cost = yes_ask + no_ask
                        required_spread = 1.0 - self.config.min_profit_threshold

                        # Account for minimum profit threshold
                        if total_cost < required_spread:
                            expected_profit = (1.0 - total_cost)

                            # Get the market object
                            market = self.market_discovery.get_market_by_id(market_id, platform)
                            if not market:
                                logger.debug(f"Skipped {platform.value}/{market_id}: Market not found in discovery")
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
                                self.scan_stats['markets_skipped_no_size'] += 1
                                logger.debug(
                                    f"Skipped {platform.value}/{market_id}: No available size "
                                    f"(yes_size={yes_size}, no_size={no_size})"
                                )
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

                            # Log detailed opportunity for profitability tracking
                            self._log_opportunity_details(opportunity)
                        else:
                            # Spread too low
                            self.scan_stats['markets_skipped_low_spread'] += 1
                            spread = 1.0 - total_cost
                            logger.debug(
                                f"Skipped {platform.value}/{market_id}: "
                                f"Spread {spread:.4f} below threshold {self.config.min_profit_threshold} "
                                f"(yes_ask={yes_ask:.4f}, no_ask={no_ask:.4f})"
                            )
                    else:
                        # Missing ask prices
                        self.scan_stats['markets_skipped_no_data'] += 1
                        logger.debug(f"Skipped {platform.value}/{market_id}: Missing ask data")

                except Exception as e:
                    logger.debug(f"Error checking market {market_id}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error in intra-platform scan for {platform.value}: {e}")

        return opportunities

    async def _scan_cross_platform(self) -> List[ArbitrageOpportunity]:
        """
        Scan for cross-platform arbitrage opportunities.

        Returns:
            List of opportunities
        """
        opportunities = []

        try:
            num_pairs = len(self.market_discovery.market_pairs)
            if num_pairs == 0:
                logger.warning("No market pairs available for cross-platform arbitrage scan")
                return opportunities

            logger.debug(f"Scanning {num_pairs} cross-platform market pairs...")

            # Iterate through all market pairs
            for pair in self.market_discovery.market_pairs:
                try:
                    self.scan_stats['markets_checked'] += 1

                    kalshi_market = pair.kalshi_market
                    poly_market = pair.polymarket_market

                    # Get prices for both markets
                    kalshi_yes_bid, kalshi_yes_ask = await self.orderbook_manager.get_best_prices(
                        Platform.KALSHI, kalshi_market.market_id, Outcome.YES
                    )
                    poly_yes_bid, poly_yes_ask = await self.orderbook_manager.get_best_prices(
                        Platform.POLYMARKET, poly_market.market_id, Outcome.YES
                    )

                    # Skip if we don't have complete data - log which platform is missing
                    has_kalshi = kalshi_yes_bid is not None and kalshi_yes_ask is not None
                    has_poly = poly_yes_bid is not None and poly_yes_ask is not None

                    if not has_kalshi or not has_poly:
                        self.scan_stats['markets_skipped_no_data'] += 1
                        # Log at INFO level for visibility when debugging
                        logger.info(
                            f"Skipped cross-platform pair {kalshi_market.market_id}/{poly_market.market_id}: "
                            f"has_kalshi={has_kalshi}, has_poly={has_poly} "
                            f"(K_bid={kalshi_yes_bid}, K_ask={kalshi_yes_ask}, "
                            f"P_bid={poly_yes_bid}, P_ask={poly_yes_ask})"
                        )
                        continue

                    # Strategy 1: Buy on Kalshi, sell on Polymarket
                    if kalshi_yes_ask < poly_yes_bid:
                        spread = poly_yes_bid - kalshi_yes_ask

                        if spread >= self.config.min_profit_threshold:
                            # Get order sizes
                            kalshi_ob = await self.orderbook_manager.get_orderbook(
                                Platform.KALSHI, kalshi_market.market_id, Outcome.YES
                            )
                            poly_ob = await self.orderbook_manager.get_orderbook(
                                Platform.POLYMARKET, poly_market.market_id, Outcome.YES
                            )

                            kalshi_size = kalshi_ob.best_ask.size if kalshi_ob and kalshi_ob.best_ask else 0
                            poly_size = poly_ob.best_bid.size if poly_ob and poly_ob.best_bid else 0

                            trade_size = min(kalshi_size, poly_size, self.config.max_trade_size)

                            if trade_size > 0:
                                opportunity = ArbitrageOpportunity(
                                    opportunity_id=str(uuid.uuid4()),
                                    timestamp=datetime.utcnow(),
                                    opportunity_type='cross-platform',
                                    platform=None,
                                    market_pair=pair,
                                    single_market=None,
                                    buy_platform=Platform.KALSHI,
                                    buy_market_id=kalshi_market.market_id,
                                    buy_outcome=Outcome.YES,
                                    buy_price=kalshi_yes_ask,
                                    buy_size=trade_size,
                                    sell_platform=Platform.POLYMARKET,
                                    sell_market_id=poly_market.market_id,
                                    sell_outcome=Outcome.YES,
                                    sell_price=poly_yes_bid,
                                    sell_size=trade_size,
                                    expected_profit=spread * trade_size,
                                    expected_return_pct=(spread / kalshi_yes_ask) * 100
                                )

                                opportunities.append(opportunity)

                                # Log detailed opportunity for profitability tracking
                                self._log_opportunity_details(opportunity)
                            else:
                                # No available size
                                self.scan_stats['markets_skipped_no_size'] += 1
                                logger.debug(
                                    f"Skipped cross-platform pair {kalshi_market.market_id}/{poly_market.market_id}: "
                                    f"No size (kalshi_size={kalshi_size}, poly_size={poly_size})"
                                )
                        else:
                            # Spread too low
                            self.scan_stats['markets_skipped_low_spread'] += 1
                            logger.debug(
                                f"Skipped cross-platform pair {kalshi_market.market_id}/{poly_market.market_id}: "
                                f"Spread {spread:.4f} below threshold {self.config.min_profit_threshold} "
                                f"(Buy Kalshi@{kalshi_yes_ask:.4f}, Sell Poly@{poly_yes_bid:.4f})"
                            )

                    # Strategy 2: Buy on Polymarket, sell on Kalshi
                    if poly_yes_ask < kalshi_yes_bid:
                        spread = kalshi_yes_bid - poly_yes_ask

                        if spread >= self.config.min_profit_threshold:
                            # Get order sizes
                            kalshi_ob = await self.orderbook_manager.get_orderbook(
                                Platform.KALSHI, kalshi_market.market_id, Outcome.YES
                            )
                            poly_ob = await self.orderbook_manager.get_orderbook(
                                Platform.POLYMARKET, poly_market.market_id, Outcome.YES
                            )

                            kalshi_size = kalshi_ob.best_bid.size if kalshi_ob and kalshi_ob.best_bid else 0
                            poly_size = poly_ob.best_ask.size if poly_ob and poly_ob.best_ask else 0

                            trade_size = min(kalshi_size, poly_size, self.config.max_trade_size)

                            if trade_size > 0:
                                opportunity = ArbitrageOpportunity(
                                    opportunity_id=str(uuid.uuid4()),
                                    timestamp=datetime.utcnow(),
                                    opportunity_type='cross-platform',
                                    platform=None,
                                    market_pair=pair,
                                    single_market=None,
                                    buy_platform=Platform.POLYMARKET,
                                    buy_market_id=poly_market.market_id,
                                    buy_outcome=Outcome.YES,
                                    buy_price=poly_yes_ask,
                                    buy_size=trade_size,
                                    sell_platform=Platform.KALSHI,
                                    sell_market_id=kalshi_market.market_id,
                                    sell_outcome=Outcome.YES,
                                    sell_price=kalshi_yes_bid,
                                    sell_size=trade_size,
                                    expected_profit=spread * trade_size,
                                    expected_return_pct=(spread / poly_yes_ask) * 100
                                )

                                opportunities.append(opportunity)

                                # Log detailed opportunity for profitability tracking
                                self._log_opportunity_details(opportunity)
                            else:
                                # No available size
                                self.scan_stats['markets_skipped_no_size'] += 1
                                logger.debug(
                                    f"Skipped cross-platform pair {kalshi_market.market_id}/{poly_market.market_id}: "
                                    f"No size (kalshi_size={kalshi_size}, poly_size={poly_size})"
                                )
                        else:
                            # Spread too low
                            self.scan_stats['markets_skipped_low_spread'] += 1
                            logger.debug(
                                f"Skipped cross-platform pair {kalshi_market.market_id}/{poly_market.market_id}: "
                                f"Spread {spread:.4f} below threshold {self.config.min_profit_threshold} "
                                f"(Buy Poly@{poly_yes_ask:.4f}, Sell Kalshi@{kalshi_yes_bid:.4f})"
                            )

                except Exception as e:
                    logger.debug(f"Error checking market pair: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error in cross-platform scan: {e}")

        return opportunities

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
            return False
