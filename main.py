"""
Main entry point for the arbitrage trading bot.
"""

import asyncio
import logging
import sys
from pathlib import Path

from config import get_config
from supervisor import BotSupervisor


def setup_logging():
    """
    Configure logging for the application.
    """
    config = get_config()

    # Create logs directory if it doesn't exist
    log_dir = Path(config.log_file).parent
    if log_dir and not log_dir.exists():
        log_dir.mkdir(parents=True, exist_ok=True)

    # Configure logging format
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    date_format = '%Y-%m-%d %H:%M:%S'

    # Get log level from config
    log_level = getattr(logging, config.log_level.upper(), logging.INFO)

    # Configure root logger
    logging.basicConfig(
        level=log_level,
        format=log_format,
        datefmt=date_format,
        handlers=[
            # Console handler
            logging.StreamHandler(sys.stdout),
            # File handler with rotation
            logging.FileHandler(config.log_file, mode='a')
        ]
    )

    # Set specific log levels for noisy libraries
    logging.getLogger('aiohttp').setLevel(logging.WARNING)
    logging.getLogger('websockets').setLevel(logging.WARNING)

    logger = logging.getLogger(__name__)
    logger.info("Logging configured successfully")


def print_banner():
    """
    Print startup banner.
    """
    banner = """
╔══════════════════════════════════════════════════════════════════════╗
║                                                                      ║
║     High-Frequency Arbitrage Trading Bot                            ║
║     Kalshi ↔ Polymarket                                             ║
║                                                                      ║
║     Status: SIMULATION MODE (No Real Trades)                        ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝
    """
    print(banner)


async def main():
    """
    Main application entry point.
    """
    # Setup logging
    setup_logging()
    logger = logging.getLogger(__name__)

    # Print banner
    print_banner()

    # Load configuration
    config = get_config()
    logger.info("Configuration loaded")
    logger.info(f"Min profit threshold: ${config.min_profit_threshold}")
    logger.info(f"Max trade size: {config.max_trade_size} shares")
    logger.info(f"Update interval: {config.update_interval}s")

    # Create supervisor
    supervisor = BotSupervisor()

    # Setup signal handlers for graceful shutdown
    supervisor.setup_signal_handlers()

    try:
        # Initialize components
        await supervisor.initialize()

        # Start the bot
        await supervisor.start()

    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        return 1
    finally:
        # Ensure cleanup
        if supervisor:
            await supervisor.stop()

    logger.info("Bot shutdown complete")
    return 0


def run():
    """
    Run the bot using uvloop if available for better performance.
    """
    try:
        # Try to use uvloop for better performance on Linux/macOS
        import uvloop
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
        print("Using uvloop for enhanced performance")
    except ImportError:
        # uvloop not available, use default event loop
        pass

    # Run the main coroutine
    exit_code = asyncio.run(main())
    sys.exit(exit_code)


if __name__ == "__main__":
    run()
