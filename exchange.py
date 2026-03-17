"""
Binance Futures API client wrapper.
Handles all communication with the Binance USDT-M Futures API.
"""

import hashlib
import hmac
import logging
import time
from urllib.parse import urlencode

import requests

from config import APIConfig

logger = logging.getLogger(__name__)


class BinanceFuturesClient:
    """Client for Binance USDT-M Futures API."""

    def __init__(self, config: APIConfig):
        self.config = config
        self.base_url = config.base_url
        self.session = requests.Session()
        self.session.headers.update({
            "X-MBX-APIKEY": config.API_KEY,
        })

    def _sign(self, params: dict) -> dict:
        """Add timestamp and signature to request parameters."""
        params["timestamp"] = int(time.time() * 1000)
        query_string = urlencode(params)
        signature = hmac.new(
            self.config.API_SECRET.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        params["signature"] = signature
        return params

    def _request(self, method: str, path: str, params: dict = None, signed: bool = False, max_retries: int = 3) -> dict | list:
        """Make an API request with automatic retry on network errors."""
        url = f"{self.base_url}{path}"
        params = params or {}

        for attempt in range(1, max_retries + 1):
            request_params = params.copy()
            if signed:
                request_params = self._sign(request_params)

            try:
                if method == "GET":
                    resp = self.session.get(url, params=request_params, timeout=30)
                elif method == "POST":
                    resp = self.session.post(url, params=request_params, timeout=30)
                elif method == "DELETE":
                    resp = self.session.delete(url, params=request_params, timeout=30)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")

                resp.raise_for_status()
                return resp.json()

            except requests.exceptions.HTTPError as e:
                logger.error(f"HTTP error {e.response.status_code}: {e.response.text}")
                raise
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                if attempt < max_retries:
                    wait = attempt * 5
                    logger.warning(f"Network error (attempt {attempt}/{max_retries}): {e}. Retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    logger.error(f"Network error after {max_retries} attempts: {e}")
                    raise
            except requests.exceptions.RequestException as e:
                logger.error(f"Request error: {e}")
                raise

    # ─── Market Data ──────────────────────────────────────────────

    def get_24hr_tickers(self) -> list[dict]:
        """Get 24hr ticker stats for all USDT-M futures symbols."""
        return self._request("GET", "/fapi/v1/ticker/24hr")

    def get_klines(self, symbol: str, interval: str = "1d", limit: int = 5) -> list[list]:
        """
        Get kline/candlestick data.
        Returns list of [open_time, open, high, low, close, volume, close_time, ...].
        """
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        }
        return self._request("GET", "/fapi/v1/klines", params)

    def get_mark_price(self, symbol: str) -> dict:
        """Get current mark price for a symbol."""
        params = {"symbol": symbol}
        return self._request("GET", "/fapi/v1/premiumIndex", params)

    def get_exchange_info(self) -> dict:
        """Get exchange trading rules and symbol info."""
        return self._request("GET", "/fapi/v1/exchangeInfo")

    def get_symbol_info(self, symbol: str) -> dict | None:
        """Get trading rules for a specific symbol."""
        info = self.get_exchange_info()
        for s in info.get("symbols", []):
            if s["symbol"] == symbol:
                return s
        return None

    # ─── Account & Positions ──────────────────────────────────────

    def get_account(self) -> dict:
        """Get current account information."""
        return self._request("GET", "/fapi/v2/account", signed=True)

    def get_balance(self) -> list[dict]:
        """Get futures account balance."""
        return self._request("GET", "/fapi/v2/balance", signed=True)

    def get_positions(self, symbol: str = None) -> list[dict]:
        """Get current position information."""
        params = {}
        if symbol:
            params["symbol"] = symbol
        return self._request("GET", "/fapi/v2/positionRisk", params, signed=True)

    def get_open_orders(self, symbol: str = None) -> list[dict]:
        """Get all open orders."""
        params = {}
        if symbol:
            params["symbol"] = symbol
        return self._request("GET", "/fapi/v1/openOrders", params, signed=True)

    # ─── Trading ──────────────────────────────────────────────────

    def set_leverage(self, symbol: str, leverage: int) -> dict:
        """Set leverage for a symbol."""
        params = {
            "symbol": symbol,
            "leverage": leverage,
        }
        return self._request("POST", "/fapi/v1/leverage", params, signed=True)

    def set_margin_type(self, symbol: str, margin_type: str = "ISOLATED") -> dict:
        """Set margin type (ISOLATED or CROSSED)."""
        params = {
            "symbol": symbol,
            "marginType": margin_type,
        }
        try:
            return self._request("POST", "/fapi/v1/marginType", params, signed=True)
        except requests.exceptions.HTTPError as e:
            # Error -4046 means margin type is already set
            if "4046" in str(e.response.text):
                logger.info(f"Margin type already set to {margin_type} for {symbol}")
                return {"msg": "No need to change margin type."}
            raise

    def place_market_order(self, symbol: str, side: str, quantity: float) -> dict:
        """
        Place a market order.
        side: "BUY" or "SELL"
        """
        params = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": quantity,
        }
        logger.info(f"Placing MARKET {side} order: {symbol} qty={quantity}")
        return self._request("POST", "/fapi/v1/order", params, signed=True)

    def place_limit_order(self, symbol: str, side: str, quantity: float, price: float, time_in_force: str = "GTC") -> dict:
        """Place a limit order."""
        params = {
            "symbol": symbol,
            "side": side,
            "type": "LIMIT",
            "quantity": quantity,
            "price": price,
            "timeInForce": time_in_force,
        }
        logger.info(f"Placing LIMIT {side} order: {symbol} qty={quantity} @ {price}")
        return self._request("POST", "/fapi/v1/order", params, signed=True)

    def place_stop_market_order(self, symbol: str, side: str, quantity: float, stop_price: float) -> dict:
        """Place a stop market order (used for stop loss)."""
        params = {
            "symbol": symbol,
            "side": side,
            "type": "STOP_MARKET",
            "quantity": quantity,
            "stopPrice": stop_price,
        }
        logger.info(f"Placing STOP_MARKET {side} order: {symbol} qty={quantity} stop={stop_price}")
        return self._request("POST", "/fapi/v1/order", params, signed=True)

    def cancel_order(self, symbol: str, order_id: int) -> dict:
        """Cancel a specific order."""
        params = {
            "symbol": symbol,
            "orderId": order_id,
        }
        return self._request("DELETE", "/fapi/v1/order", params, signed=True)

    def cancel_all_orders(self, symbol: str) -> dict:
        """Cancel all open orders for a symbol."""
        params = {"symbol": symbol}
        return self._request("DELETE", "/fapi/v1/allOpenOrders", params, signed=True)

    def close_position(self, symbol: str, side: str, quantity: float) -> dict:
        """
        Close a position by placing an opposite market order.
        If we are LONG, we SELL to close. If SHORT, we BUY to close.
        """
        close_side = "SELL" if side == "BUY" else "BUY"
        params = {
            "symbol": symbol,
            "side": close_side,
            "type": "MARKET",
            "quantity": quantity,
            "reduceOnly": "true",
        }
        logger.info(f"Closing position: {symbol} {close_side} qty={quantity}")
        return self._request("POST", "/fapi/v1/order", params, signed=True)
