"""
Trade logging module.
Handles persistent logging of simulated trades and bot events.
"""

import asyncio
import logging
import json
from typing import Optional, List
from datetime import datetime
import aiofiles
import aiosqlite

from models import ArbitrageOpportunity, BotMetrics
from config import get_config

logger = logging.getLogger(__name__)


class TradeLogger:
    """
    Logs simulated trades and bot metrics to persistent storage.
    Uses both JSON Lines files and SQLite database for redundancy.
    """

    def __init__(self):
        """Initialize the trade logger."""
        self.config = get_config()
        self.trade_log_file = self.config.trade_log_file
        self.db_file = self.config.db_file
        self.db_conn: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

    async def initialize(self):
        """
        Initialize database and create tables if needed.
        """
        try:
            # Create SQLite database connection
            self.db_conn = await aiosqlite.connect(self.db_file)

            # Create tables
            await self.db_conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    opportunity_id TEXT UNIQUE NOT NULL,
                    timestamp TEXT NOT NULL,
                    opportunity_type TEXT NOT NULL,
                    buy_platform TEXT NOT NULL,
                    buy_market_id TEXT NOT NULL,
                    buy_outcome TEXT NOT NULL,
                    buy_price REAL NOT NULL,
                    buy_size INTEGER NOT NULL,
                    sell_platform TEXT NOT NULL,
                    sell_market_id TEXT NOT NULL,
                    sell_outcome TEXT NOT NULL,
                    sell_price REAL NOT NULL,
                    sell_size INTEGER NOT NULL,
                    expected_profit REAL NOT NULL,
                    expected_return_pct REAL NOT NULL,
                    simulated_at TEXT NOT NULL
                )
            """)

            await self.db_conn.execute("""
                CREATE TABLE IF NOT EXISTS metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    uptime_seconds REAL NOT NULL,
                    markets_tracked INTEGER NOT NULL,
                    opportunities_detected INTEGER NOT NULL,
                    trades_simulated INTEGER NOT NULL,
                    total_simulated_profit REAL NOT NULL,
                    kalshi_connected INTEGER NOT NULL,
                    polymarket_connected INTEGER NOT NULL,
                    last_error TEXT
                )
            """)

            await self.db_conn.commit()

            logger.info("Trade logger initialized successfully")

        except Exception as e:
            logger.error(f"Error initializing trade logger: {e}")
            raise

    async def close(self):
        """
        Close database connection.
        """
        if self.db_conn:
            await self.db_conn.close()
            self.db_conn = None
            logger.info("Trade logger closed")

    async def log_simulated_trade(self, opportunity: ArbitrageOpportunity):
        """
        Log a simulated trade.

        Args:
            opportunity: The arbitrage opportunity that was simulated
        """
        async with self._lock:
            try:
                # Mark as simulated
                opportunity.simulated = True
                opportunity.simulation_timestamp = datetime.utcnow()

                # Convert to dictionary
                trade_data = opportunity.to_dict()

                # Log to JSON Lines file
                await self._log_to_jsonl(trade_data)

                # Log to database
                await self._log_to_db(opportunity)

                logger.info(
                    f"Logged simulated trade: {opportunity.opportunity_type} "
                    f"profit=${opportunity.expected_profit:.2f}"
                )

            except Exception as e:
                logger.error(f"Error logging trade: {e}")

    async def _log_to_jsonl(self, trade_data: dict):
        """
        Append trade data to JSON Lines file.

        Args:
            trade_data: Trade data dictionary
        """
        try:
            async with aiofiles.open(self.trade_log_file, mode='a') as f:
                await f.write(json.dumps(trade_data) + '\n')

        except Exception as e:
            logger.error(f"Error writing to JSON Lines file: {e}")

    async def _log_to_db(self, opportunity: ArbitrageOpportunity):
        """
        Insert trade into SQLite database.

        Args:
            opportunity: The arbitrage opportunity
        """
        try:
            await self.db_conn.execute("""
                INSERT OR REPLACE INTO trades (
                    opportunity_id, timestamp, opportunity_type,
                    buy_platform, buy_market_id, buy_outcome, buy_price, buy_size,
                    sell_platform, sell_market_id, sell_outcome, sell_price, sell_size,
                    expected_profit, expected_return_pct, simulated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                opportunity.opportunity_id,
                opportunity.timestamp.isoformat(),
                opportunity.opportunity_type,
                opportunity.buy_platform.value,
                opportunity.buy_market_id,
                opportunity.buy_outcome.value,
                opportunity.buy_price,
                opportunity.buy_size,
                opportunity.sell_platform.value,
                opportunity.sell_market_id,
                opportunity.sell_outcome.value,
                opportunity.sell_price,
                opportunity.sell_size,
                opportunity.expected_profit,
                opportunity.expected_return_pct,
                opportunity.simulation_timestamp.isoformat()
            ))

            await self.db_conn.commit()

        except Exception as e:
            logger.error(f"Error inserting trade into database: {e}")

    async def log_metrics(self, metrics: BotMetrics):
        """
        Log bot metrics to database.

        Args:
            metrics: Bot metrics object
        """
        async with self._lock:
            try:
                await self.db_conn.execute("""
                    INSERT INTO metrics (
                        timestamp, uptime_seconds, markets_tracked,
                        opportunities_detected, trades_simulated,
                        total_simulated_profit, kalshi_connected,
                        polymarket_connected, last_error
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    datetime.utcnow().isoformat(),
                    metrics.uptime(),
                    metrics.markets_tracked,
                    metrics.opportunities_detected,
                    metrics.trades_simulated,
                    metrics.total_simulated_profit,
                    1 if metrics.kalshi_connected else 0,
                    1 if metrics.polymarket_connected else 0,
                    metrics.last_error
                ))

                await self.db_conn.commit()

            except Exception as e:
                logger.error(f"Error logging metrics: {e}")

    async def get_recent_trades(self, limit: int = 100) -> List[dict]:
        """
        Retrieve recent simulated trades from database.

        Args:
            limit: Maximum number of trades to retrieve

        Returns:
            List of trade dictionaries
        """
        try:
            async with self.db_conn.execute("""
                SELECT * FROM trades
                ORDER BY timestamp DESC
                LIMIT ?
            """, (limit,)) as cursor:
                rows = await cursor.fetchall()

                trades = []
                for row in rows:
                    trades.append({
                        'id': row[0],
                        'opportunity_id': row[1],
                        'timestamp': row[2],
                        'opportunity_type': row[3],
                        'buy_platform': row[4],
                        'buy_market_id': row[5],
                        'buy_outcome': row[6],
                        'buy_price': row[7],
                        'buy_size': row[8],
                        'sell_platform': row[9],
                        'sell_market_id': row[10],
                        'sell_outcome': row[11],
                        'sell_price': row[12],
                        'sell_size': row[13],
                        'expected_profit': row[14],
                        'expected_return_pct': row[15],
                        'simulated_at': row[16]
                    })

                return trades

        except Exception as e:
            logger.error(f"Error retrieving trades: {e}")
            return []

    async def get_total_simulated_profit(self) -> float:
        """
        Calculate total simulated profit from all trades.

        Returns:
            Total profit
        """
        try:
            async with self.db_conn.execute("""
                SELECT SUM(expected_profit) FROM trades
            """) as cursor:
                row = await cursor.fetchone()
                return row[0] if row[0] is not None else 0.0

        except Exception as e:
            logger.error(f"Error calculating total profit: {e}")
            return 0.0

    async def get_trade_count(self) -> int:
        """
        Get total number of simulated trades.

        Returns:
            Trade count
        """
        try:
            async with self.db_conn.execute("""
                SELECT COUNT(*) FROM trades
            """) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

        except Exception as e:
            logger.error(f"Error counting trades: {e}")
            return 0
