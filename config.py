"""
Configuration module for the arbitrage trading bot.
Loads settings from environment variables with validation.
"""

import os
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field, validator
from dotenv import load_dotenv

# Load .env file if it exists
load_dotenv()


class BotConfig(BaseSettings):
    """
    Main configuration class for the trading bot.
    All settings are loaded from environment variables.
    """

    # Kalshi API Configuration
    kalshi_api_base: str = Field(
        default="https://api.elections.kalshi.com",
        description="Kalshi API base URL"
    )
    kalshi_ws_url: str = Field(
        default="wss://api.elections.kalshi.com/trade-api/ws/v2",
        description="Kalshi WebSocket URL"
    )
    kalshi_email: Optional[str] = Field(
        default=None,
        description="Kalshi account email"
    )
    kalshi_password: Optional[str] = Field(
        default=None,
        description="Kalshi account password"
    )
    kalshi_api_key: Optional[str] = Field(
        default=None,
        description="Kalshi API key"
    )

    # Polymarket API Configuration
    polymarket_api_base: str = Field(
        default="https://gamma-api.polymarket.com",
        description="Polymarket Gamma API base URL"
    )
    polymarket_ws_url: str = Field(
        default="wss://ws-subscriptions-clob.polymarket.com/ws/market",
        description="Polymarket WebSocket URL"
    )
    polymarket_api_key: Optional[str] = Field(
        default=None,
        description="Polymarket API key"
    )
    polymarket_secret: Optional[str] = Field(
        default=None,
        description="Polymarket secret"
    )

    # Bot Configuration
    min_profit_threshold: float = Field(
        default=0.01,
        description="Minimum profit per share to trigger arbitrage"
    )
    max_trade_size: int = Field(
        default=100,
        description="Maximum shares to simulate per trade"
    )
    update_interval: float = Field(
        default=0.1,
        description="Seconds between arbitrage checks"
    )
    market_refresh_interval: int = Field(
        default=300,
        description="Seconds between market discovery refreshes"
    )

    # Logging Configuration
    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR)"
    )
    log_file: str = Field(
        default="trading_bot.log",
        description="Main log file path"
    )
    trade_log_file: str = Field(
        default="trades.jsonl",
        description="Trade log file path (JSON Lines format)"
    )
    db_file: str = Field(
        default="trading_bot.db",
        description="SQLite database file path"
    )

    # Performance Configuration
    max_reconnect_attempts: int = Field(
        default=10,
        description="Maximum reconnection attempts before giving up"
    )
    reconnect_base_delay: int = Field(
        default=2,
        description="Base delay for exponential backoff (seconds)"
    )
    websocket_timeout: int = Field(
        default=30,
        description="Seconds before considering WebSocket dead"
    )
    heartbeat_interval: int = Field(
        default=15,
        description="Seconds between heartbeat checks"
    )

    @validator('log_level')
    def validate_log_level(cls, v):
        """Validate that log level is one of the standard levels."""
        valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        v = v.upper()
        if v not in valid_levels:
            raise ValueError(f"log_level must be one of {valid_levels}")
        return v

    @validator('min_profit_threshold')
    def validate_min_profit(cls, v):
        """Ensure minimum profit threshold is positive."""
        if v <= 0:
            raise ValueError("min_profit_threshold must be positive")
        return v

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# Global configuration instance
config = BotConfig()


def get_config() -> BotConfig:
    """
    Get the global configuration instance.

    Returns:
        BotConfig: The configuration object
    """
    return config
