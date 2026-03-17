"""
Main bot loop for the Binance Futures Averaging Bot.
Orchestrates scanning, entry, monitoring, and exit.
"""

import logging
import signal
import sys
import time
from datetime import datetime, timezone

from config import load_config, TradingConfig, APIConfig, LogConfig
from exchange import BinanceFuturesClient
from strategy import TradingStrategy

logger = logging.getLogger("bot")


def setup_logging(log_config: LogConfig):
    """Configure logging handlers."""
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_config.LOG_LEVEL, logging.INFO))

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)-12s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if log_config.LOG_TO_CONSOLE:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    if log_config.LOG_TO_FILE:
        file_handler = logging.FileHandler(log_config.LOG_FILE)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)


class TradingBot:
    """Main trading bot orchestrator."""

    def __init__(self):
        self.running = False
        self.trading_config: TradingConfig | None = None
        self.api_config: APIConfig | None = None
        self.client: BinanceFuturesClient | None = None
        self.strategy: TradingStrategy | None = None

    def initialize(self):
        """Initialize the bot with configuration and API client."""
        trading_config, api_config, log_config = load_config()
        setup_logging(log_config)

        self.trading_config = trading_config
        self.api_config = api_config

        if not api_config.API_KEY or not api_config.API_SECRET:
            logger.error("API key and secret are required. Set BINANCE_API_KEY and BINANCE_API_SECRET.")
            sys.exit(1)

        self.client = BinanceFuturesClient(api_config)
        self.strategy = TradingStrategy(self.client, trading_config)

        env = "TESTNET" if api_config.TESTNET else "MAINNET"
        logger.info("=" * 60)
        logger.info(f"Binance Futures Averaging Bot")
        logger.info(f"Environment: {env}")
        logger.info(f"Base URL: {api_config.base_url}")
        logger.info(f"Direction: {trading_config.DIRECTION}")
        logger.info(f"Leverage: {trading_config.LEVERAGE}x")
        logger.info(f"Entry structure: ${trading_config.ENTRY_1_AMOUNT} → ${trading_config.ENTRY_2_AMOUNT} → ${trading_config.ENTRY_3_AMOUNT}")
        logger.info(f"Max position: ${trading_config.MAX_POSITION_SIZE}")
        logger.info(f"Take profit: {trading_config.TAKE_PROFIT_PCT * 100:.0f}%")
        logger.info(f"Scan interval: {trading_config.SCAN_INTERVAL_SECONDS}s")
        logger.info("=" * 60)

        # Verify connectivity
        try:
            balance = self.client.get_balance()
            usdt_balance = next((b for b in balance if b["asset"] == "USDT"), None)
            if usdt_balance:
                available = float(usdt_balance.get("availableBalance", 0))
                logger.info(f"USDT balance: ${available:.2f}")
            else:
                logger.warning("No USDT balance found")
        except Exception as e:
            logger.error(f"Failed to connect to Binance: {e}")
            sys.exit(1)

    def run(self):
        """Main bot loop."""
        self.running = True

        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        logger.info("Bot started. Press Ctrl+C to stop.")

        consecutive_errors = 0

        while self.running:
            try:
                self._tick()
                consecutive_errors = 0
            except KeyboardInterrupt:
                break
            except Exception as e:
                consecutive_errors += 1
                logger.error(f"Error in main loop ({consecutive_errors}): {e}", exc_info=True)

                # Back off on repeated errors (max 5 min wait)
                if consecutive_errors > 1:
                    backoff = min(consecutive_errors * 30, 300)
                    logger.warning(f"Backing off for {backoff}s due to repeated errors")
                    time.sleep(backoff)
                    continue

            # Sleep between ticks
            if self.running:
                time.sleep(self.trading_config.SCAN_INTERVAL_SECONDS)

        self._shutdown()

    def _tick(self):
        """Single iteration of the bot logic."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        logger.debug(f"--- Tick at {now} ---")

        if self.strategy.active_trade is None:
            # No active trade → scan for new opportunity
            self._scan_and_enter()
        else:
            # Active trade → monitor entries and exit
            self._monitor_trade()

    def _scan_and_enter(self):
        """Scan the market and open a new trade if conditions are met."""
        logger.info("Scanning market for trading opportunities...")

        result = self.strategy.scan_and_select()
        if result is None:
            logger.info("No suitable trading candidate found this cycle.")
            return

        symbol, direction = result

        # Check if we already have a position on this symbol
        try:
            positions = self.client.get_positions(symbol)
            for pos in positions:
                if pos["symbol"] == symbol and float(pos.get("positionAmt", 0)) != 0:
                    logger.info(f"Already have an open position on {symbol}, skipping.")
                    return
        except Exception as e:
            logger.warning(f"Could not check existing positions: {e}")

        # Set up the trade
        trade = self.strategy.setup_trade(symbol, direction)
        if not trade:
            logger.warning("Failed to set up trade")
            return

        # Execute initial entry (market order)
        success = self.strategy.execute_initial_entry()
        if success:
            logger.info(f"Initial entry executed for {symbol} ({direction})")
            status = self.strategy.get_status()
            logger.info(f"Status: {status}")
        else:
            logger.error("Initial entry failed. Resetting trade.")
            self.strategy.active_trade = None

    def _monitor_trade(self):
        """Monitor active trade for additional entries and exit conditions."""
        trade = self.strategy.active_trade
        if not trade:
            return

        logger.debug(f"Monitoring {trade.symbol} ({trade.direction}) | Entries: {trade.entry_count}/3")

        # Check for additional entries (if not fully entered)
        if not trade.is_fully_entered:
            self.strategy.check_additional_entries()

        # Check take profit condition (this also logs the PnL)
        closed = self.strategy.check_take_profit()
        if closed:
            logger.info("Trade closed with profit target reached!")
            logger.info("Will scan for new opportunity on next cycle.")

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        logger.info(f"Received signal {signum}. Shutting down...")
        self.running = False

    def _shutdown(self):
        """Clean shutdown."""
        logger.info("Shutting down bot...")

        if self.strategy and self.strategy.active_trade:
            trade = self.strategy.active_trade
            logger.warning(
                f"Active trade on shutdown: {trade.symbol} ({trade.direction}) | "
                f"Invested: ${trade.total_invested:.2f} | Entries: {trade.entry_count}/3"
            )
            logger.warning("Position will remain open. Close manually if needed.")

        logger.info("Bot stopped.")


def main():
    bot = TradingBot()
    bot.initialize()
    bot.run()


if __name__ == "__main__":
    main()
