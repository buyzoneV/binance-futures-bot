"""
Multi-step averaging entry strategy for Binance Futures.

Strategy flow:
1. Scan top 10 symbols by 24h volume
2. Select the one with the largest 24h price decline
3. Determine direction (LONG if price dropped = buy dip, SHORT if price rose)
4. Enter with staged scaling based on daily support/resistance levels
5. Exit at 30% profit on total invested capital
"""

import logging
import math
from dataclasses import dataclass, field

from config import TradingConfig
from exchange import BinanceFuturesClient

logger = logging.getLogger(__name__)


@dataclass
class EntryLevel:
    """Represents a staged entry level."""
    level: int  # 1, 2, or 3
    amount_usd: float
    trigger_price: float | None = None
    filled: bool = False
    order_id: int | None = None
    quantity: float = 0.0
    fill_price: float = 0.0


@dataclass
class ActiveTrade:
    """Tracks the current active trade."""
    symbol: str
    direction: str  # "LONG" or "SHORT"
    entries: list[EntryLevel] = field(default_factory=list)
    total_invested: float = 0.0
    total_quantity: float = 0.0
    avg_entry_price: float = 0.0

    @property
    def target_profit_usd(self) -> float:
        """30% of total invested capital."""
        return self.total_invested * 0.30

    @property
    def entry_count(self) -> int:
        return sum(1 for e in self.entries if e.filled)

    @property
    def is_fully_entered(self) -> bool:
        return all(e.filled for e in self.entries)

    def update_averages(self):
        """Recalculate average entry price and totals."""
        self.total_invested = sum(e.amount_usd for e in self.entries if e.filled)
        self.total_quantity = sum(e.quantity for e in self.entries if e.filled)
        if self.total_quantity > 0:
            weighted_sum = sum(e.fill_price * e.quantity for e in self.entries if e.filled)
            self.avg_entry_price = weighted_sum / self.total_quantity


class TradingStrategy:
    """Implements the multi-step averaging entry strategy."""

    def __init__(self, client: BinanceFuturesClient, config: TradingConfig):
        self.client = client
        self.config = config
        self.active_trade: ActiveTrade | None = None
        self._symbol_filters: dict = {}

    # ─── Symbol Selection ─────────────────────────────────────────

    def _get_tradeable_symbols(self) -> set[str]:
        """Get the set of symbols that are currently tradeable (TRADING status)."""
        try:
            info = self.client.get_exchange_info()
            return {
                s["symbol"] for s in info.get("symbols", [])
                if s.get("status") == "TRADING"
            }
        except Exception as e:
            logger.warning(f"Could not fetch exchange info: {e}")
            return set()

    def scan_and_select(self) -> tuple[str, str] | None:
        """
        Scan the market and select the best trading candidate.
        Returns (symbol, direction) or None if no suitable asset found.
        """
        tickers = self.client.get_24hr_tickers()

        # Get tradeable symbols
        tradeable = self._get_tradeable_symbols()
        if tradeable:
            logger.info(f"Found {len(tradeable)} tradeable symbols")

        # Filter to USDT-margined pairs that are actively trading
        usdt_tickers = [
            t for t in tickers
            if t["symbol"].endswith("USDT")
            and (not tradeable or t["symbol"] in tradeable)
        ]

        # Sort by 24h quote volume (descending) and take top N
        usdt_tickers.sort(key=lambda t: float(t.get("quoteVolume", 0)), reverse=True)
        top_by_volume = usdt_tickers[: self.config.TOP_VOLUME_COUNT]

        if not top_by_volume:
            logger.warning("No USDT futures tickers found")
            return None

        logger.info(f"Top {len(top_by_volume)} by volume: {[t['symbol'] for t in top_by_volume]}")

        # Find the one with the largest absolute price change
        # For BOTH mode: pick the largest |priceChangePercent|
        # For LONG only: pick the most negative (biggest drop)
        # For SHORT only: pick the most positive (biggest rise)

        if self.config.DIRECTION == "LONG":
            # Biggest drop → go LONG (buy the dip)
            candidate = min(top_by_volume, key=lambda t: float(t.get("priceChangePercent", 0)))
            pct = float(candidate.get("priceChangePercent", 0))
            if pct >= -self.config.MIN_DROP_PCT:
                logger.info(f"No sufficient drop found. Best: {candidate['symbol']} at {pct}%")
                return None
            direction = "LONG"

        elif self.config.DIRECTION == "SHORT":
            # Biggest rise → go SHORT
            candidate = max(top_by_volume, key=lambda t: float(t.get("priceChangePercent", 0)))
            pct = float(candidate.get("priceChangePercent", 0))
            if pct <= self.config.MIN_DROP_PCT:
                logger.info(f"No sufficient rise found. Best: {candidate['symbol']} at {pct}%")
                return None
            direction = "SHORT"

        else:  # BOTH
            # Pick the asset with the largest absolute change
            candidate = max(top_by_volume, key=lambda t: abs(float(t.get("priceChangePercent", 0))))
            pct = float(candidate.get("priceChangePercent", 0))
            direction = "SHORT" if pct > 0 else "LONG"

        symbol = candidate["symbol"]
        logger.info(
            f"Selected: {symbol} | 24h change: {pct:.2f}% | Direction: {direction} | "
            f"Volume: {float(candidate.get('quoteVolume', 0)):,.0f} USDT"
        )
        return symbol, direction

    # ─── Price Level Calculation ──────────────────────────────────

    def get_daily_levels(self, symbol: str) -> dict:
        """
        Fetch daily klines and compute entry trigger levels.
        Returns dict with previous day's OHLC and computed support/resistance zones.
        """
        klines = self.client.get_klines(symbol, self.config.KLINE_INTERVAL, self.config.KLINE_LIMIT)

        if len(klines) < 2:
            logger.warning(f"Insufficient kline data for {symbol}")
            return {}

        # Previous completed daily candle (index -2, since -1 is the current incomplete candle)
        prev_candle = klines[-2]
        current_candle = klines[-1]

        prev_open = float(prev_candle[1])
        prev_high = float(prev_candle[2])
        prev_low = float(prev_candle[3])
        prev_close = float(prev_candle[4])

        current_price = float(current_candle[4])  # latest close as proxy

        # Daily range for computing lower support zone
        daily_range = prev_high - prev_low

        # If daily range is 0 (no price movement), use 1% of current price as fallback
        if daily_range <= 0:
            daily_range = current_price * 0.01
            logger.info(f"Daily range is 0 for {symbol}, using 1% fallback: {daily_range:.6f}")

        levels = {
            "current_price": current_price,
            "prev_open": prev_open,
            "prev_high": prev_high,
            "prev_low": prev_low,
            "prev_close": prev_close,
            "daily_range": daily_range,
        }

        logger.info(
            f"{symbol} daily levels: price={current_price:.6f}, "
            f"prev_low={prev_low:.6f}, prev_high={prev_high:.6f}, "
            f"range={daily_range:.6f}"
        )
        return levels

    def compute_entry_triggers(self, levels: dict, direction: str) -> list[float]:
        """
        Compute the 3 entry trigger prices based on daily levels.

        LONG entries (buying the dip):
          1st: Market price (immediate)
          2nd: Previous daily low
          3rd: Previous daily low - 0.5 * daily range (deeper support)

        SHORT entries (selling the rip):
          1st: Market price (immediate)
          2nd: Previous daily high
          3rd: Previous daily high + 0.5 * daily range (higher resistance)
        """
        if direction == "LONG":
            trigger_1 = None  # Market order, no trigger
            trigger_2 = levels["prev_low"]
            trigger_3 = levels["prev_low"] - 0.5 * levels["daily_range"]
        else:  # SHORT
            trigger_1 = None
            trigger_2 = levels["prev_high"]
            trigger_3 = levels["prev_high"] + 0.5 * levels["daily_range"]

        return [trigger_1, trigger_2, trigger_3]

    # ─── Symbol Precision ─────────────────────────────────────────

    def _get_symbol_filters(self, symbol: str) -> dict:
        """Get and cache symbol trading filters (tick size, lot size, etc.)."""
        if symbol not in self._symbol_filters:
            info = self.client.get_symbol_info(symbol)
            if not info:
                raise ValueError(f"Symbol {symbol} not found in exchange info")

            filters = {}
            for f in info.get("filters", []):
                filters[f["filterType"]] = f

            self._symbol_filters[symbol] = {
                "price_precision": info.get("pricePrecision", 8),
                "quantity_precision": info.get("quantityPrecision", 8),
                "tick_size": float(filters.get("PRICE_FILTER", {}).get("tickSize", "0.01")),
                "step_size": float(filters.get("LOT_SIZE", {}).get("stepSize", "0.001")),
                "min_qty": float(filters.get("LOT_SIZE", {}).get("minQty", "0.001")),
                "min_notional": float(filters.get("MIN_NOTIONAL", {}).get("notional", "5")),
            }
        return self._symbol_filters[symbol]

    def _round_quantity(self, symbol: str, quantity: float) -> float:
        """Round quantity to the symbol's step size."""
        filters = self._get_symbol_filters(symbol)
        step = filters["step_size"]
        precision = filters["quantity_precision"]
        rounded = math.floor(quantity / step) * step
        return round(rounded, precision)

    def _round_price(self, symbol: str, price: float) -> float:
        """Round price to the symbol's tick size."""
        filters = self._get_symbol_filters(symbol)
        tick = filters["tick_size"]
        precision = filters["price_precision"]
        rounded = round(round(price / tick) * tick, precision)
        return rounded

    def _calculate_quantity(self, symbol: str, amount_usd: float, price: float) -> float:
        """Calculate order quantity from USD amount and price."""
        raw_qty = amount_usd / price
        qty = self._round_quantity(symbol, raw_qty)

        filters = self._get_symbol_filters(symbol)
        if qty < filters["min_qty"]:
            logger.warning(
                f"Calculated qty {qty} below min {filters['min_qty']} for {symbol}. "
                f"Using min qty."
            )
            qty = filters["min_qty"]
        return qty

    # ─── Trade Setup ──────────────────────────────────────────────

    def setup_trade(self, symbol: str, direction: str) -> ActiveTrade | None:
        """
        Set up a new trade: configure leverage, compute levels, prepare entries.
        """
        try:
            # Set leverage
            self.client.set_leverage(symbol, self.config.LEVERAGE)
            logger.info(f"Leverage set to {self.config.LEVERAGE}x for {symbol}")

            # Set margin type to ISOLATED
            self.client.set_margin_type(symbol, "ISOLATED")

        except Exception as e:
            logger.error(f"Failed to configure {symbol}: {e}")
            return None

        # Get daily levels
        levels = self.get_daily_levels(symbol)
        if not levels:
            return None

        # Compute entry triggers
        triggers = self.compute_entry_triggers(levels, direction)

        # Create entry levels
        entries = []
        for i, (amount, trigger) in enumerate(
            zip(self.config.entry_amounts, triggers), start=1
        ):
            entries.append(
                EntryLevel(
                    level=i,
                    amount_usd=amount,
                    trigger_price=trigger,
                )
            )

        trade = ActiveTrade(symbol=symbol, direction=direction, entries=entries)
        self.active_trade = trade

        logger.info(f"Trade setup for {symbol} ({direction}):")
        for entry in entries:
            trigger_str = f"${entry.trigger_price:.6f}" if entry.trigger_price else "MARKET"
            logger.info(f"  Entry {entry.level}: ${entry.amount_usd} @ {trigger_str}")

        return trade

    # ─── Order Execution ──────────────────────────────────────────

    def execute_entry(self, entry: EntryLevel, price: float) -> bool:
        """Execute a single entry order."""
        trade = self.active_trade
        if not trade:
            return False

        symbol = trade.symbol
        side = "BUY" if trade.direction == "LONG" else "SELL"
        quantity = self._calculate_quantity(symbol, entry.amount_usd, price)

        if quantity <= 0:
            logger.error(f"Invalid quantity for entry {entry.level}")
            return False

        try:
            result = self.client.place_market_order(symbol, side, quantity)
            entry.filled = True
            entry.order_id = result.get("orderId")
            entry.quantity = quantity

            # Get fill price — fallback to mark price if avgPrice is 0 or missing
            fill_price = float(result.get("avgPrice", 0))
            if fill_price <= 0:
                try:
                    mark = self.client.get_mark_price(symbol)
                    fill_price = float(mark.get("markPrice", price))
                except Exception:
                    fill_price = price
            entry.fill_price = fill_price

            trade.update_averages()

            logger.info(
                f"Entry {entry.level} FILLED: {symbol} {side} {quantity} @ {entry.fill_price:.6f} | "
                f"Total invested: ${trade.total_invested:.2f} | "
                f"Avg price: {trade.avg_entry_price:.6f}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to execute entry {entry.level}: {e}")
            return False

    def execute_initial_entry(self) -> bool:
        """Execute the first (market) entry."""
        trade = self.active_trade
        if not trade or not trade.entries:
            return False

        entry = trade.entries[0]
        if entry.filled:
            logger.info("Initial entry already filled")
            return True

        # Get current price
        mark = self.client.get_mark_price(trade.symbol)
        current_price = float(mark.get("markPrice", 0))

        if current_price <= 0:
            logger.error("Invalid mark price")
            return False

        return self.execute_entry(entry, current_price)

    # ─── Monitoring & Additional Entries ──────────────────────────

    def check_additional_entries(self) -> bool:
        """
        Check if price has reached trigger levels for entries 2 and 3.
        Returns True if any new entry was executed.
        """
        trade = self.active_trade
        if not trade:
            return False

        mark = self.client.get_mark_price(trade.symbol)
        current_price = float(mark.get("markPrice", 0))
        if current_price <= 0:
            return False

        executed = False
        for entry in trade.entries:
            if entry.filled or entry.trigger_price is None:
                continue

            # Check if trigger condition is met
            if trade.direction == "LONG":
                # For LONG: price must drop to or below trigger
                if current_price <= entry.trigger_price:
                    logger.info(
                        f"Entry {entry.level} trigger hit: price {current_price:.6f} <= {entry.trigger_price:.6f}"
                    )
                    if self.execute_entry(entry, current_price):
                        executed = True
            else:
                # For SHORT: price must rise to or above trigger
                if current_price >= entry.trigger_price:
                    logger.info(
                        f"Entry {entry.level} trigger hit: price {current_price:.6f} >= {entry.trigger_price:.6f}"
                    )
                    if self.execute_entry(entry, current_price):
                        executed = True

        return executed

    def check_take_profit(self) -> bool:
        """
        Check if unrealized profit has reached 30% of total invested.
        Uses the exchange's reported unrealized PnL for accuracy.
        Returns True if position was closed.
        """
        trade = self.active_trade
        if not trade or trade.total_quantity <= 0:
            return False

        # Use the exchange's own PnL calculation (most reliable)
        try:
            positions = self.client.get_positions(trade.symbol)
            unrealized_pnl = None
            for pos in positions:
                if pos["symbol"] == trade.symbol:
                    pos_amt = float(pos.get("positionAmt", 0))
                    if pos_amt != 0:
                        unrealized_pnl = float(pos.get("unRealizedProfit", 0))
                        break

            if unrealized_pnl is None:
                logger.debug("No position found on exchange for PnL check")
                return False

        except Exception as e:
            logger.warning(f"Could not fetch position for PnL check: {e}")
            return False

        target = trade.target_profit_usd
        pnl_pct = (unrealized_pnl / trade.total_invested * 100) if trade.total_invested > 0 else 0

        logger.info(
            f"PnL check: ${unrealized_pnl:.2f} / ${target:.2f} target ({pnl_pct:.1f}%) | "
            f"Invested: ${trade.total_invested:.2f} | Entries: {trade.entry_count}/3"
        )

        if unrealized_pnl >= target:
            logger.info(
                f"TAKE PROFIT HIT! PnL: ${unrealized_pnl:.2f} >= target ${target:.2f} ({pnl_pct:.1f}%)"
            )
            return self._close_position()

        return False

    def _close_position(self) -> bool:
        """Close the entire position."""
        trade = self.active_trade
        if not trade:
            return False

        try:
            side = "BUY" if trade.direction == "LONG" else "SELL"
            self.client.close_position(trade.symbol, side, trade.total_quantity)
            logger.info(
                f"Position CLOSED: {trade.symbol} | "
                f"Total invested: ${trade.total_invested:.2f} | "
                f"Entries: {trade.entry_count}/3"
            )

            # Cancel any remaining open orders
            try:
                self.client.cancel_all_orders(trade.symbol)
            except Exception:
                pass

            self.active_trade = None
            return True

        except Exception as e:
            logger.error(f"Failed to close position: {e}")
            return False

    def get_status(self) -> dict:
        """Get current strategy status for logging/monitoring."""
        trade = self.active_trade
        if not trade:
            return {"status": "IDLE", "message": "No active trade"}

        return {
            "status": "ACTIVE",
            "symbol": trade.symbol,
            "direction": trade.direction,
            "entries_filled": trade.entry_count,
            "total_invested": trade.total_invested,
            "total_quantity": trade.total_quantity,
            "avg_entry_price": trade.avg_entry_price,
            "target_profit": trade.target_profit_usd,
        }
