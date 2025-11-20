"""
Market discovery and pairing module.
Identifies matching markets between Kalshi and Polymarket.

================================================================================
PAIRING ALGORITHM OVERVIEW
================================================================================

This module implements a multi-stage market pairing algorithm to find equivalent
prediction markets across Kalshi and Polymarket exchanges.

ALGORITHM STEPS:
1. Category Detection: Classify each market into high-level categories
   (SPORTS, POLITICS, MACRO_ECON, CRYPTO, ENTERTAINMENT, OTHER) based on
   keywords in titles/questions and exchange-provided metadata.

2. Time-Horizon Extraction: Parse resolution/close dates from metadata to
   group markets by when they resolve (same month/year).

3. Pre-filtering: Only compare markets that are in the SAME category AND
   have compatible time horizons. This eliminates cross-category garbage
   matches (e.g., NFL props matched to Fed rate cuts).

4. Token Normalization: Before fuzzy matching, aggressively clean titles:
   - Remove player names and stat thresholds (e.g., "Patrick Mahomes: 300+")
   - Remove generic tokens ("yes", "no", "will", "the", etc.)
   - Extract key semantic tokens for comparison

5. Multi-Component Scoring: Final score combines:
   - text_similarity: Fuzzy match on normalized titles (SequenceMatcher)
   - category_match: 1.0 if same category, 0.0 if not (hard filter)
   - time_window_score: Based on how close resolution dates are

   final_score = text_similarity * category_match * time_window_score

6. Threshold Filtering: Only pairs with final_score >= MIN_FINAL_SCORE are kept.

ASSUMPTIONS:
- Kalshi metadata contains 'close_time' or 'expiration_time' for resolution dates
- Polymarket metadata['event'] contains 'endDate' or 'end_date_iso'
- Sports markets contain team names, player names, and stat thresholds
- Politics markets contain keywords like "election", "president", "vote"
- Macro/econ markets contain keywords like "Fed", "rate", "CPI", "GDP", "inflation"

TUNABLE CONSTANTS (adjust at top of file):
- MIN_FINAL_SCORE: Minimum combined score to accept a pair (default: 0.55)
- MAX_RESOLUTION_DIFF_DAYS: Max days apart for resolution dates (default: 45)
- MIN_TEXT_SIMILARITY: Minimum text similarity before other factors (default: 0.35)
- CATEGORY_KEYWORDS: Keyword lists for each category
- SPORTS_NOISE_PATTERNS: Regex patterns to strip from sports titles

================================================================================
"""

import asyncio
import logging
import re
from typing import List, Dict, Optional, Tuple, Set
from difflib import SequenceMatcher
from datetime import datetime, timedelta
from enum import Enum
from collections import defaultdict

from models import Market, MarketPair, Platform
from kalshi_client import KalshiClient
from polymarket_client import PolymarketClient

logger = logging.getLogger(__name__)


# =============================================================================
# TUNABLE CONSTANTS
# =============================================================================

# Minimum final score to accept a market pair
MIN_FINAL_SCORE = 0.55

# Minimum text similarity before applying other score components
MIN_TEXT_SIMILARITY = 0.35

# Maximum difference in resolution dates (days) to consider markets compatible
MAX_RESOLUTION_DIFF_DAYS = 45

# Time window scoring: markets resolving within this many days get full score
IDEAL_RESOLUTION_DIFF_DAYS = 7

# Number of top candidates to log per category for diagnostics
TOP_CANDIDATES_TO_LOG = 10


# =============================================================================
# CATEGORY DEFINITIONS
# =============================================================================

class MarketCategory(str, Enum):
    """High-level market categories for pre-filtering."""
    SPORTS = "sports"
    POLITICS = "politics"
    MACRO_ECON = "macro_econ"
    CRYPTO = "crypto"
    ENTERTAINMENT = "entertainment"
    WEATHER = "weather"
    OTHER = "other"


# Keywords for category detection (lowercase)
CATEGORY_KEYWORDS = {
    MarketCategory.SPORTS: {
        # Team names / leagues
        'nfl', 'nba', 'mlb', 'nhl', 'ncaa', 'football', 'basketball', 'baseball',
        'hockey', 'soccer', 'tennis', 'golf', 'boxing', 'ufc', 'mma',
        'super bowl', 'world series', 'stanley cup', 'playoffs', 'championship',
        # Common sports terms
        'touchdown', 'yards', 'points', 'rebounds', 'assists', 'goals', 'runs',
        'strikeouts', 'rushing', 'passing', 'receiving', 'interceptions',
        'home run', 'field goal', 'three pointer', 'sacks', 'tackles',
        # Team cities (common)
        'patriots', 'chiefs', 'eagles', 'cowboys', 'packers', 'steelers',
        'ravens', 'bills', 'dolphins', 'jets', 'giants', 'commanders',
        '49ers', 'seahawks', 'rams', 'cardinals', 'bears', 'lions', 'vikings',
        'saints', 'falcons', 'panthers', 'buccaneers', 'broncos', 'raiders',
        'chargers', 'browns', 'bengals', 'texans', 'colts', 'titans', 'jaguars',
        'lakers', 'celtics', 'warriors', 'nets', 'knicks', 'heat', 'bulls',
        'yankees', 'dodgers', 'red sox', 'mets', 'cubs', 'astros',
        # Sports betting terms
        'spread', 'over under', 'moneyline', 'parlay', 'sgp', 'prop bet',
        'wins by', 'total points', 'first to score',
    },
    MarketCategory.POLITICS: {
        'election', 'president', 'presidential', 'congress', 'senate', 'house',
        'governor', 'mayor', 'vote', 'ballot', 'democrat', 'republican',
        'biden', 'trump', 'harris', 'desantis', 'newsom', 'pence',
        'primary', 'caucus', 'electoral', 'cabinet', 'secretary',
        'supreme court', 'justice', 'legislation', 'bill', 'law',
        'impeach', 'veto', 'executive order', 'administration',
        'poll', 'approval rating', 'midterm', 'runoff',
        'ukraine', 'russia', 'china', 'taiwan', 'nato', 'war', 'military',
        'foreign policy', 'sanctions', 'diplomacy', 'treaty',
        'prime minister', 'parliament', 'brexit', 'eu',
    },
    MarketCategory.MACRO_ECON: {
        'fed', 'federal reserve', 'fomc', 'interest rate', 'rate cut', 'rate hike',
        'inflation', 'cpi', 'pce', 'gdp', 'unemployment', 'jobs report',
        'nonfarm payroll', 'recession', 'economic', 'economy',
        'treasury', 'bond', 'yield', 'debt ceiling', 'deficit', 'budget',
        'stock market', 's&p', 'dow', 'nasdaq', 'russell',
        'ipo', 'earnings', 'revenue', 'profit',
        'oil price', 'gas price', 'commodity', 'gold price',
        'housing', 'mortgage', 'real estate',
        'tariff', 'trade', 'import', 'export',
    },
    MarketCategory.CRYPTO: {
        'bitcoin', 'btc', 'ethereum', 'eth', 'crypto', 'cryptocurrency',
        'blockchain', 'defi', 'nft', 'token', 'altcoin',
        'binance', 'coinbase', 'ftx', 'sec crypto', 'crypto regulation',
        'solana', 'cardano', 'dogecoin', 'ripple', 'xrp',
        'stablecoin', 'usdt', 'usdc', 'dao',
    },
    MarketCategory.ENTERTAINMENT: {
        'oscar', 'emmy', 'grammy', 'golden globe', 'academy award',
        'movie', 'film', 'box office', 'streaming', 'netflix', 'disney',
        'tv show', 'series', 'album', 'song', 'artist', 'concert',
        'celebrity', 'kardashian', 'swift', 'beyonce',
        'video game', 'gaming', 'esports', 'twitch',
    },
    MarketCategory.WEATHER: {
        'hurricane', 'tornado', 'earthquake', 'flood', 'drought',
        'temperature', 'rainfall', 'snowfall', 'weather', 'climate',
        'wildfire', 'storm', 'typhoon', 'cyclone',
    },
}


# Patterns to strip from sports titles (player names, stat thresholds)
SPORTS_NOISE_PATTERNS = [
    r'\b[A-Z][a-z]+\s+[A-Z][a-z]+\s*:\s*\d+\+?\b',  # "Patrick Mahomes: 300+"
    r'\b[A-Z][a-z]+\s+[A-Z][a-z]+\s+[A-Z]+\b',  # "Travis Kelce III"
    r'\b\d+\+?\s*(yards?|points?|rebounds?|assists?|goals?|tds?|ints?)\b',
    r'\bover\s+\d+\.?\d*\s*(points?|yards?)?\b',
    r'\bunder\s+\d+\.?\d*\s*(points?|yards?)?\b',
    r'\bwins?\s+by\s+(over\s+)?\d+\.?\d*\s*(points?)?\b',
    r'\bfirst\s+to\s+\d+\b',
    r'\b(yes|no)\s*,?\s*',
]


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def detect_category(market: Market) -> MarketCategory:
    """
    Detect the category of a market based on title, question, and metadata.

    Args:
        market: Market object to categorize

    Returns:
        MarketCategory enum value
    """
    # Combine title and question for keyword matching
    text = f"{market.title} {market.question}".lower()

    # Also check metadata for exchange-provided category hints
    metadata = market.metadata or {}

    # Kalshi often has series_ticker or category field
    if market.platform == Platform.KALSHI:
        series = metadata.get('series_ticker', '').lower()
        event_ticker = metadata.get('event_ticker', '').lower()
        category_field = metadata.get('category', '').lower()
        text = f"{text} {series} {event_ticker} {category_field}"

    # Polymarket has tags in event
    elif market.platform == Platform.POLYMARKET:
        event = metadata.get('event', {})
        tags = event.get('tags', [])
        if isinstance(tags, list):
            text = f"{text} {' '.join(str(t).lower() for t in tags)}"
        slug = event.get('slug', '').lower()
        text = f"{text} {slug}"

    # Score each category by keyword matches
    category_scores = {}
    for category, keywords in CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text)
        # Weight multi-word keywords higher
        score += sum(2 for kw in keywords if ' ' in kw and kw in text)
        category_scores[category] = score

    # Find the category with highest score
    best_category = max(category_scores, key=category_scores.get)
    best_score = category_scores[best_category]

    # If no strong signal, classify as OTHER
    if best_score < 2:
        return MarketCategory.OTHER

    return best_category


def extract_resolution_date(market: Market) -> Optional[datetime]:
    """
    Extract the resolution/close date from market metadata.

    Args:
        market: Market object

    Returns:
        datetime or None if not found
    """
    metadata = market.metadata or {}

    # Try various field names
    date_fields = [
        'close_time', 'expiration_time', 'end_time', 'end_date',
        'resolution_time', 'expiry', 'settlement_time'
    ]

    if market.platform == Platform.KALSHI:
        for field in date_fields:
            value = metadata.get(field)
            if value:
                return _parse_date(value)

    elif market.platform == Platform.POLYMARKET:
        event = metadata.get('event', {})
        for field in date_fields + ['endDate', 'end_date_iso']:
            value = event.get(field) or metadata.get('market', {}).get(field)
            if value:
                return _parse_date(value)

    return None


def _parse_date(value) -> Optional[datetime]:
    """Parse various date formats into datetime."""
    if isinstance(value, datetime):
        return value

    if isinstance(value, (int, float)):
        # Unix timestamp (seconds or milliseconds)
        if value > 1e12:  # Milliseconds
            return datetime.utcfromtimestamp(value / 1000)
        return datetime.utcfromtimestamp(value)

    if isinstance(value, str):
        # Try various formats
        formats = [
            '%Y-%m-%dT%H:%M:%S.%fZ',
            '%Y-%m-%dT%H:%M:%SZ',
            '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%d',
        ]
        for fmt in formats:
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue

        # Try ISO format parsing
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00').replace('+00:00', ''))
        except:
            pass

    return None


def calculate_time_window_score(date1: Optional[datetime], date2: Optional[datetime]) -> float:
    """
    Calculate score based on how close two resolution dates are.

    Args:
        date1: First resolution date (or None)
        date2: Second resolution date (or None)

    Returns:
        Score between 0.0 and 1.0
    """
    # If either date is missing, give partial credit
    if date1 is None or date2 is None:
        return 0.7  # Moderate penalty for missing dates

    # Calculate difference in days
    diff_days = abs((date1 - date2).days)

    if diff_days <= IDEAL_RESOLUTION_DIFF_DAYS:
        return 1.0
    elif diff_days <= MAX_RESOLUTION_DIFF_DAYS:
        # Linear decay from 1.0 to 0.5
        decay = (diff_days - IDEAL_RESOLUTION_DIFF_DAYS) / (MAX_RESOLUTION_DIFF_DAYS - IDEAL_RESOLUTION_DIFF_DAYS)
        return 1.0 - (decay * 0.5)
    else:
        return 0.0  # Too far apart


def normalize_title_for_matching(text: str, category: MarketCategory) -> str:
    """
    Aggressively normalize title for fuzzy matching.
    Strips noise specific to the category.

    Args:
        text: Raw title/question
        category: Market category

    Returns:
        Normalized text
    """
    text = text.lower()

    # Category-specific noise removal
    if category == MarketCategory.SPORTS:
        # Remove player names, stat thresholds, yes/no prefixes
        for pattern in SPORTS_NOISE_PATTERNS:
            text = re.sub(pattern, ' ', text, flags=re.IGNORECASE)

    # General cleanup
    # Remove special characters
    text = re.sub(r'[^\w\s]', ' ', text)

    # Remove common stop words
    stop_words = {
        'will', 'the', 'be', 'in', 'on', 'at', 'to', 'for', 'of', 'a', 'an',
        'is', 'are', 'was', 'were', 'been', 'being', 'have', 'has', 'had',
        'do', 'does', 'did', 'this', 'that', 'these', 'those', 'it', 'its',
        'by', 'from', 'with', 'as', 'or', 'and', 'but', 'if', 'than', 'so',
        'yes', 'no', 'true', 'false',
    }

    words = [w for w in text.split() if w not in stop_words and len(w) > 1]

    return ' '.join(words)


def extract_key_terms(text: str, category: MarketCategory) -> Set[str]:
    """
    Extract key semantic terms from text based on category.

    Args:
        text: Normalized text
        category: Market category

    Returns:
        Set of key terms
    """
    words = set(text.lower().split())

    # For certain categories, prioritize specific terms
    if category == MarketCategory.POLITICS:
        important = {'election', 'president', 'vote', 'senate', 'house',
                    'governor', 'trump', 'biden', 'harris', 'democrat',
                    'republican', 'ukraine', 'russia', 'china', 'war'}
        return words & important if words & important else words

    if category == MarketCategory.MACRO_ECON:
        important = {'fed', 'rate', 'cut', 'hike', 'inflation', 'cpi', 'gdp',
                    'recession', 'unemployment', 'fomc', 'treasury', 'bond'}
        return words & important if words & important else words

    return words


# =============================================================================
# MAIN CLASS
# =============================================================================

class MarketDiscovery:
    """
    Discovers and pairs markets from Kalshi and Polymarket.
    Uses category-based pre-filtering and multi-component scoring.
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

        # Category caches
        self._kalshi_by_category: Dict[MarketCategory, List[Market]] = defaultdict(list)
        self._poly_by_category: Dict[MarketCategory, List[Market]] = defaultdict(list)

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
                kalshi_markets = []

            if isinstance(polymarket_markets, Exception):
                logger.error(f"Error fetching Polymarket markets: {polymarket_markets}")
                polymarket_markets = []

            # Store markets in dictionaries for quick lookup
            self.kalshi_markets = {m.market_id: m for m in kalshi_markets}
            self.polymarket_markets = {m.market_id: m for m in polymarket_markets}

            # Categorize markets
            self._categorize_markets()

            logger.info(
                f"Discovered {len(kalshi_markets)} Kalshi markets and "
                f"{len(polymarket_markets)} Polymarket markets"
            )

            return kalshi_markets, polymarket_markets

        except Exception as e:
            logger.error(f"Error during market discovery: {e}")
            return [], []

    def _categorize_markets(self):
        """Categorize all markets into buckets for efficient pairing."""
        self._kalshi_by_category = defaultdict(list)
        self._poly_by_category = defaultdict(list)

        kalshi_category_counts = defaultdict(int)
        poly_category_counts = defaultdict(int)

        for market in self.kalshi_markets.values():
            category = detect_category(market)
            self._kalshi_by_category[category].append(market)
            kalshi_category_counts[category] += 1

        for market in self.polymarket_markets.values():
            category = detect_category(market)
            self._poly_by_category[category].append(market)
            poly_category_counts[category] += 1

        # Log category distribution
        logger.info("Market category distribution:")
        for category in MarketCategory:
            k_count = kalshi_category_counts.get(category, 0)
            p_count = poly_category_counts.get(category, 0)
            if k_count > 0 or p_count > 0:
                logger.info(f"  {category.value}: Kalshi={k_count}, Polymarket={p_count}")

    def calculate_similarity(self, text1: str, text2: str) -> float:
        """
        Calculate similarity score between two text strings.

        Args:
            text1: First text
            text2: Second text

        Returns:
            Similarity score between 0 and 1
        """
        return SequenceMatcher(None, text1, text2).ratio()

    def find_market_pairs(self, similarity_threshold: float = None) -> List[MarketPair]:
        """
        Find matching market pairs between platforms using category-based
        pre-filtering and multi-component scoring.

        Args:
            similarity_threshold: Ignored (uses MIN_FINAL_SCORE constant)

        Returns:
            List of MarketPair objects
        """
        pairs = []
        all_candidates = []  # For diagnostic logging

        logger.info(f"Pairing markets across platforms...")
        logger.info(f"  MIN_FINAL_SCORE={MIN_FINAL_SCORE}")
        logger.info(f"  MIN_TEXT_SIMILARITY={MIN_TEXT_SIMILARITY}")
        logger.info(f"  MAX_RESOLUTION_DIFF_DAYS={MAX_RESOLUTION_DIFF_DAYS}")

        # Ensure markets are categorized
        if not self._kalshi_by_category:
            self._categorize_markets()

        # Process each category separately
        for category in MarketCategory:
            kalshi_in_category = self._kalshi_by_category.get(category, [])
            poly_in_category = self._poly_by_category.get(category, [])

            if not kalshi_in_category or not poly_in_category:
                continue

            logger.info(f"\nProcessing category: {category.value}")
            logger.info(f"  Comparing {len(kalshi_in_category)} Kalshi vs {len(poly_in_category)} Polymarket")

            category_candidates = []

            # Compare each Kalshi market with each Polymarket market in same category
            for kalshi_market in kalshi_in_category:
                kalshi_date = extract_resolution_date(kalshi_market)
                kalshi_normalized = normalize_title_for_matching(
                    f"{kalshi_market.title} {kalshi_market.question}",
                    category
                )

                best_match = None
                best_score = 0.0
                best_components = {}

                for poly_market in poly_in_category:
                    poly_date = extract_resolution_date(poly_market)

                    # Calculate time window score (hard filter if too far apart)
                    time_score = calculate_time_window_score(kalshi_date, poly_date)
                    if time_score == 0.0:
                        continue  # Skip - resolution dates too far apart

                    # Normalize Polymarket title
                    poly_normalized = normalize_title_for_matching(
                        f"{poly_market.title} {poly_market.question}",
                        category
                    )

                    # Calculate text similarity
                    text_sim = self.calculate_similarity(kalshi_normalized, poly_normalized)

                    if text_sim < MIN_TEXT_SIMILARITY:
                        continue  # Skip - text not similar enough

                    # Category match score (always 1.0 since we pre-filtered)
                    category_score = 1.0

                    # Calculate final combined score
                    final_score = text_sim * category_score * time_score

                    if final_score > best_score:
                        best_score = final_score
                        best_match = poly_market
                        best_components = {
                            'text_sim': text_sim,
                            'category_score': category_score,
                            'time_score': time_score,
                            'kalshi_date': kalshi_date,
                            'poly_date': poly_date,
                        }

                # Track candidate for logging
                if best_match and best_score > 0.3:
                    candidate = {
                        'kalshi_title': kalshi_market.title[:60],
                        'poly_title': best_match.title[:60],
                        'final_score': best_score,
                        'category': category.value,
                        **best_components
                    }
                    category_candidates.append(candidate)
                    all_candidates.append(candidate)

                # If above threshold, create pair
                if best_match and best_score >= MIN_FINAL_SCORE:
                    pair = MarketPair(
                        kalshi_market=kalshi_market,
                        polymarket_market=best_match,
                        confidence=best_score
                    )
                    pairs.append(pair)

            # Log top candidates for this category
            if category_candidates:
                category_candidates.sort(key=lambda x: x['final_score'], reverse=True)
                logger.info(f"\n  Top {min(TOP_CANDIDATES_TO_LOG, len(category_candidates))} candidates in {category.value}:")
                for i, c in enumerate(category_candidates[:TOP_CANDIDATES_TO_LOG]):
                    status = "✓" if c['final_score'] >= MIN_FINAL_SCORE else "✗"
                    date_info = ""
                    if c.get('kalshi_date') and c.get('poly_date'):
                        diff = abs((c['kalshi_date'] - c['poly_date']).days)
                        date_info = f" [Δ{diff}d]"
                    elif c.get('kalshi_date') or c.get('poly_date'):
                        date_info = " [partial dates]"

                    logger.info(
                        f"    {status} {c['final_score']:.3f} "
                        f"(text={c['text_sim']:.2f}, time={c['time_score']:.2f}){date_info}"
                    )
                    logger.info(f"       K: {c['kalshi_title']}")
                    logger.info(f"       P: {c['poly_title']}")

        # Log summary
        logger.info(f"\n{'='*60}")
        logger.info(f"PAIRING SUMMARY")
        logger.info(f"{'='*60}")
        logger.info(f"Total pairs found: {len(pairs)}")

        # Break down by category
        pairs_by_category = defaultdict(int)
        for pair in pairs:
            cat = detect_category(pair.kalshi_market)
            pairs_by_category[cat] += 1

        for category, count in sorted(pairs_by_category.items(), key=lambda x: -x[1]):
            logger.info(f"  {category.value}: {count} pairs")

        # Log some actual pairs
        if pairs:
            logger.info(f"\nSample pairs (first {min(5, len(pairs))}):")
            for pair in pairs[:5]:
                logger.info(f"  [{pair.confidence:.3f}] {pair.kalshi_market.title[:40]} <-> {pair.polymarket_market.title[:40]}")
        else:
            logger.warning("No pairs found! Check category detection and scoring thresholds.")
            # Log best overall candidates for debugging
            if all_candidates:
                all_candidates.sort(key=lambda x: x['final_score'], reverse=True)
                logger.info("Best candidates that didn't make threshold:")
                for c in all_candidates[:5]:
                    logger.info(f"  {c['final_score']:.3f}: {c['kalshi_title'][:35]} <-> {c['poly_title'][:35]}")

        self.market_pairs = pairs
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

            logger.info("Market refresh completed")

        except Exception as e:
            logger.error(f"Error refreshing markets: {e}")

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
