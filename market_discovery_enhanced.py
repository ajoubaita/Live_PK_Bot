"""
Market discovery and pairing module - ENHANCED VERSION
Identifies matching markets between Kalshi and Polymarket.

FIXES:
- Logs sample matched pairs at startup
- Better logging of pairing process
- Stack traces for errors
- Detailed matching statistics
"""

import asyncio
import logging
import traceback
from typing import List, Dict, Optional
from difflib import SequenceMatcher
import re

from models import Market, MarketPair, Platform
from kalshi_client import KalshiClient
from polymarket_client import PolymarketClient

logger = logging.getLogger(__name__)


class MarketDiscovery:
    """
    Discovers and pairs markets from Kalshi and Polymarket.
    Uses fuzzy matching to identify equivalent markets across platforms.
    """

    def __init__(self, kalshi_client: KalshiClient, polymarket_client: PolymarketClient):
        """
        Initialize market discovery.

        Args:
            kalshi_client: Kalshi API client
            polymarket_client: Polymarket API client
        """
        self.kalshi_client = kalshi_client
        self.polymarket_client = polymarket_client
        self.kalshi_markets: Dict[str, Market] = {}
        self.polymarket_markets: Dict[str, Market] = {}
        self.market_pairs: List[MarketPair] = []

    async def discover_all_markets(self) -> tuple[List[Market], List[Market]]:
        """
        Fetch all markets from both platforms concurrently.

        Returns:
            Tuple of (kalshi_markets, polymarket_markets)
        """
        logger.info("Starting market discovery...")

        try:
            # Fetch markets from both platforms concurrently
            kalshi_markets_task = self.kalshi_client.fetch_markets()
            polymarket_markets_task = self.polymarket_client.fetch_markets()

            kalshi_markets, polymarket_markets = await asyncio.gather(
                kalshi_markets_task,
                polymarket_markets_task,
                return_exceptions=True
            )

            # Handle exceptions
            if isinstance(kalshi_markets, Exception):
                logger.error(f"Error fetching Kalshi markets: {kalshi_markets}")
                logger.error(traceback.format_exc())
                kalshi_markets = []

            if isinstance(polymarket_markets, Exception):
                logger.error(f"Error fetching Polymarket markets: {polymarket_markets}")
                logger.error(traceback.format_exc())
                polymarket_markets = []

            # Store markets in dictionaries for quick lookup
            self.kalshi_markets = {m.market_id: m for m in kalshi_markets}
            self.polymarket_markets = {m.market_id: m for m in polymarket_markets}

            logger.info(
                f"✓ Discovered {len(kalshi_markets)} Kalshi markets and "
                f"{len(polymarket_markets)} Polymarket markets"
            )

            # Log sample markets for debugging
            if kalshi_markets:
                logger.info(f"Sample Kalshi markets:")
                for market in kalshi_markets[:5]:
                    logger.info(f"  - {market.title} (ID: {market.market_id})")

            if polymarket_markets:
                logger.info(f"Sample Polymarket markets:")
                for market in polymarket_markets[:5]:
                    logger.info(f"  - {market.title} (ID: {market.market_id})")

            return kalshi_markets, polymarket_markets

        except Exception as e:
            logger.error(f"Error during market discovery: {e}")
            logger.error(traceback.format_exc())
            return [], []

    def normalize_text(self, text: str) -> str:
        """
        Normalize market text for comparison.

        Args:
            text: Raw market title or question

        Returns:
            Normalized text
        """
        # Convert to lowercase
        text = text.lower()

        # Remove special characters and extra whitespace
        text = re.sub(r'[^\w\s]', ' ', text)
        text = ' '.join(text.split())

        # Remove common words that don't add semantic value
        stop_words = {'will', 'the', 'be', 'in', 'on', 'at', 'to', 'for', 'of', 'a', 'an'}
        words = [w for w in text.split() if w not in stop_words]

        return ' '.join(words)

    def calculate_similarity(self, text1: str, text2: str) -> float:
        """
        Calculate similarity score between two text strings.

        Args:
            text1: First text
            text2: Second text

        Returns:
            Similarity score between 0 and 1
        """
        # Normalize both texts
        norm1 = self.normalize_text(text1)
        norm2 = self.normalize_text(text2)

        # Use SequenceMatcher for fuzzy matching
        return SequenceMatcher(None, norm1, norm2).ratio()

    def find_market_pairs(self, similarity_threshold: float = 0.6) -> List[MarketPair]:
        """
        Find matching market pairs between platforms.

        Args:
            similarity_threshold: Minimum similarity score to consider a match (0-1)

        Returns:
            List of MarketPair objects
        """
        pairs = []

        logger.info(f"Pairing markets across platforms (threshold={similarity_threshold})...")

        # Track pairing statistics
        comparisons = 0
        high_confidence_pairs = 0
        medium_confidence_pairs = 0

        # Compare each Kalshi market with each Polymarket market
        for kalshi_id, kalshi_market in self.kalshi_markets.items():
            best_match = None
            best_score = 0.0

            for poly_id, poly_market in self.polymarket_markets.items():
                comparisons += 1

                # Calculate similarity between titles and questions
                title_similarity = self.calculate_similarity(
                    kalshi_market.title,
                    poly_market.title
                )
                question_similarity = self.calculate_similarity(
                    kalshi_market.question,
                    poly_market.question
                )

                # Use the maximum similarity score
                similarity = max(title_similarity, question_similarity)

                if similarity > best_score:
                    best_score = similarity
                    best_match = poly_market

            # If we found a match above threshold, create a pair
            if best_match and best_score >= similarity_threshold:
                pair = MarketPair(
                    kalshi_market=kalshi_market,
                    polymarket_market=best_match,
                    confidence=best_score
                )
                pairs.append(pair)

                # Track confidence levels
                if best_score >= 0.8:
                    high_confidence_pairs += 1
                elif best_score >= 0.7:
                    medium_confidence_pairs += 1

                logger.debug(
                    f"Paired (confidence={best_score:.2f}): "
                    f"'{kalshi_market.title}' <-> '{best_match.title}'"
                )

        self.market_pairs = pairs

        # Log pairing summary
        logger.info("=" * 80)
        logger.info("MARKET PAIRING SUMMARY")
        logger.info("-" * 80)
        logger.info(f"Total comparisons: {comparisons:,}")
        logger.info(f"Market pairs found: {len(pairs)}")
        logger.info(f"  - High confidence (≥0.8): {high_confidence_pairs}")
        logger.info(f"  - Medium confidence (0.7-0.8): {medium_confidence_pairs}")
        logger.info(f"  - Lower confidence (<0.7): {len(pairs) - high_confidence_pairs - medium_confidence_pairs}")

        # Log sample pairs for verification
        if pairs:
            logger.info("")
            logger.info("Sample Market Pairs:")
            for i, pair in enumerate(pairs[:10]):  # Show first 10 pairs
                logger.info(
                    f"  {i+1}. [{pair.confidence:.2f}] "
                    f"Kalshi: '{pair.kalshi_market.title[:40]}...' <-> "
                    f"Polymarket: '{pair.polymarket_market.title[:40]}...'"
                )
            if len(pairs) > 10:
                logger.info(f"  ... and {len(pairs) - 10} more pairs")

        logger.info("=" * 80)

        return pairs

    def get_all_markets(self) -> List[Market]:
        """
        Get all discovered markets from both platforms.

        Returns:
            Combined list of all markets
        """
        return list(self.kalshi_markets.values()) + list(self.polymarket_markets.values())

    def get_market_by_id(self, market_id: str, platform: Platform) -> Optional[Market]:
        """
        Get a specific market by ID and platform.

        Args:
            market_id: Market identifier
            platform: Platform (KALSHI or POLYMARKET)

        Returns:
            Market object or None if not found
        """
        if platform == Platform.KALSHI:
            return self.kalshi_markets.get(market_id)
        elif platform == Platform.POLYMARKET:
            return self.polymarket_markets.get(market_id)
        return None

    async def refresh_markets(self):
        """
        Refresh market data and re-pair markets.
        Should be called periodically to catch new markets.
        """
        logger.info("Refreshing market data...")

        try:
            # Discover markets
            await self.discover_all_markets()

            # Re-pair markets
            self.find_market_pairs()

            logger.info("✓ Market refresh completed")

        except Exception as e:
            logger.error(f"Error refreshing markets: {e}")
            logger.error(traceback.format_exc())

    def get_market_ids_by_platform(self, platform: Platform) -> List[str]:
        """
        Get list of market IDs for a specific platform.

        Args:
            platform: Platform to get IDs for

        Returns:
            List of market IDs
        """
        if platform == Platform.KALSHI:
            return list(self.kalshi_markets.keys())
        elif platform == Platform.POLYMARKET:
            return list(self.polymarket_markets.keys())
        return []
