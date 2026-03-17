"""
Configuration for the Binance Futures Averaging Bot.
All settings are loaded from environment variables or .env file.
"""

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class TradingConfig:
    """Trading strategy parameters."""

    # Entry amounts (USD)
    ENTRY_1_AMOUNT: float = 10.0
    ENTRY_2_AMOUNT: float = 20.0
    ENTRY_3_AMOUNT: float = 40.0
    MAX_POSITION_SIZE: float = 70.0

    # Take profit target (30% of total invested)
    TAKE_PROFIT_PCT: float = 0.30

    # Stop loss (10% of total invested)
    STOP_LOSS_PCT: float = 0.10

    # Asset selection
    TOP_VOLUME_COUNT: int = 10

    # Leverage (1x = no leverage)
    LEVERAGE: int = 1

    # Direction: "LONG", "SHORT", or "BOTH"
    DIRECTION: str = "BOTH"

    # Timeframe for daily candle analysis
    KLINE_INTERVAL: str = "1d"

    # How many daily candles to fetch for support analysis
    KLINE_LIMIT: int = 5

    # Polling interval in seconds
    SCAN_INTERVAL_SECONDS: int = 60

    # Minimum price drop percentage to consider entry (24h)
    MIN_DROP_PCT: float = 0.0

    @property
    def entry_amounts(self) -> list[float]:
        return [self.ENTRY_1_AMOUNT, self.ENTRY_2_AMOUNT, self.ENTRY_3_AMOUNT]


@dataclass
class APIConfig:
    """Binance API configuration."""

    API_KEY: str = ""
    API_SECRET: str = ""
    TESTNET: bool = True

    # Base URLs
    MAINNET_REST_URL: str = "https://fapi.binance.com"
    TESTNET_REST_URL: str = "https://demo-fapi.binance.com"

    @property
    def base_url(self) -> str:
        return self.TESTNET_REST_URL if self.TESTNET else self.MAINNET_REST_URL

    @classmethod
    def from_env(cls) -> "APIConfig":
        return cls(
            API_KEY=os.getenv("BINANCE_API_KEY", ""),
            API_SECRET=os.getenv("BINANCE_API_SECRET", ""),
            TESTNET=os.getenv("BINANCE_TESTNET", "true").lower() in ("true", "1", "yes"),
        )


@dataclass
class LogConfig:
    """Logging configuration."""

    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "bot.log"
    LOG_TO_CONSOLE: bool = True
    LOG_TO_FILE: bool = True


def load_config() -> tuple[TradingConfig, APIConfig, LogConfig]:
    """Load all configuration from environment."""
    trading = TradingConfig(
        ENTRY_1_AMOUNT=float(os.getenv("ENTRY_1_AMOUNT", "10")),
        ENTRY_2_AMOUNT=float(os.getenv("ENTRY_2_AMOUNT", "20")),
        ENTRY_3_AMOUNT=float(os.getenv("ENTRY_3_AMOUNT", "40")),
        LEVERAGE=int(os.getenv("LEVERAGE", "1")),
        DIRECTION=os.getenv("DIRECTION", "BOTH").upper(),
        SCAN_INTERVAL_SECONDS=int(os.getenv("SCAN_INTERVAL_SECONDS", "60")),
    )
    api = APIConfig.from_env()
    log = LogConfig(
        LOG_LEVEL=os.getenv("LOG_LEVEL", "INFO"),
    )
    return trading, api, log
