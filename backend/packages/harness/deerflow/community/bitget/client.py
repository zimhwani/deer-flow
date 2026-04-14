"""
Bitget API Client for copy trading analysis.

Handles authentication (HMAC-SHA256 signing) and provides methods for
account info, positions, copy trading history, and trader order tracking.

API Docs: https://www.bitget.com/api-doc/common/intro
"""

import hashlib
import hmac
import json
import logging
import time
from base64 import b64encode
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.bitget.com"


class BitgetClient:
    """Authenticated Bitget REST API client."""

    def __init__(self, api_key: str, api_secret: str, passphrase: str) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self._http = httpx.Client(base_url=BASE_URL, timeout=15)

    # ── Auth helpers ────────────────────────────────────────────────

    def _sign(self, timestamp: str, method: str, request_path: str, body: str = "") -> str:
        message = timestamp + method.upper() + request_path + body
        mac = hmac.new(self.api_secret.encode(), message.encode(), hashlib.sha256)
        return b64encode(mac.digest()).decode()

    def _headers(self, method: str, request_path: str, body: str = "") -> dict[str, str]:
        timestamp = str(int(time.time() * 1000))
        sign = self._sign(timestamp, method, request_path, body)
        return {
            "ACCESS-KEY": self.api_key,
            "ACCESS-SIGN": sign,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
            "locale": "en-US",
        }

    def _get(self, path: str, params: dict | None = None) -> dict:
        request_path = path
        if params:
            request_path = f"{path}?{urlencode(params)}"
        headers = self._headers("GET", request_path)
        resp = self._http.get(request_path, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != "00000":
            raise ValueError(f"Bitget API error: {data.get('msg', 'unknown')} (code={data.get('code')})")
        return data.get("data", {})

    def _post(self, path: str, body: dict | None = None) -> dict:
        body_str = json.dumps(body) if body else ""
        headers = self._headers("POST", path, body_str)
        resp = self._http.post(path, headers=headers, content=body_str)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != "00000":
            raise ValueError(f"Bitget API error: {data.get('msg', 'unknown')} (code={data.get('code')})")
        return data.get("data", {})

    # ── Account ─────────────────────────────────────────────────────

    def get_futures_account(self, product_type: str = "USDT-FUTURES") -> dict:
        """Get futures account balance and margin info."""
        return self._get("/api/v2/mix/account/account", {"productType": product_type, "marginCoin": "USDT"})

    # ── Positions ───────────────────────────────────────────────────

    def get_open_positions(self, product_type: str = "USDT-FUTURES") -> list[dict]:
        """Get all currently open futures positions."""
        data = self._get("/api/v2/mix/position/all-position", {"productType": product_type, "marginCoin": "USDT"})
        if isinstance(data, list):
            return data
        return data.get("list", []) if isinstance(data, dict) else []

    def get_single_position(self, symbol: str, product_type: str = "USDT-FUTURES") -> list[dict]:
        """Get position details for a specific symbol."""
        data = self._get("/api/v2/mix/position/single-position", {"symbol": symbol, "productType": product_type, "marginCoin": "USDT"})
        if isinstance(data, list):
            return data
        return data.get("list", []) if isinstance(data, dict) else []

    # ── Order history ───────────────────────────────────────────────

    def get_order_history(self, product_type: str = "USDT-FUTURES", page_size: int = 50) -> list[dict]:
        """Get historical closed orders."""
        data = self._get("/api/v2/mix/order/orders-history", {"productType": product_type, "pageSize": str(page_size)})
        if isinstance(data, list):
            return data
        return data.get("entrustedList", data.get("list", [])) if isinstance(data, dict) else []

    # ── Copy trading ────────────────────────────────────────────────

    def get_copy_trading_current_orders(self, product_type: str = "USDT-FUTURES", page_size: int = 50) -> list[dict]:
        """Get currently open copy trading orders (follower perspective)."""
        data = self._get("/api/v2/copy/mix-follower/query-current-orders", {"productType": product_type, "pageSize": str(page_size)})
        if isinstance(data, list):
            return data
        return data.get("list", []) if isinstance(data, dict) else []

    def get_copy_trading_history_orders(self, product_type: str = "USDT-FUTURES", page_size: int = 50) -> list[dict]:
        """Get historical closed copy trading orders (follower perspective)."""
        data = self._get("/api/v2/copy/mix-follower/query-history-orders", {"productType": product_type, "pageSize": str(page_size)})
        if isinstance(data, list):
            return data
        return data.get("list", []) if isinstance(data, dict) else []

    def get_copy_trading_settings(self) -> dict:
        """Get current copy trading follower settings."""
        return self._get("/api/v2/copy/mix-follower/query-settings")

    # ── Trader info (public) ────────────────────────────────────────

    def get_trader_profit_summary(self, trader_id: str) -> dict:
        """Get a trader's public profit summary (PnL, win rate, etc.)."""
        return self._get("/api/v2/copy/mix-trader/query-profit-summary", {"traderId": trader_id})

    def get_trader_current_orders(self, trader_id: str, product_type: str = "USDT-FUTURES", page_size: int = 50) -> list[dict]:
        """Get a trader's currently open positions (public)."""
        data = self._get("/api/v2/copy/mix-trader/query-current-orders", {"traderId": trader_id, "productType": product_type, "pageSize": str(page_size)})
        if isinstance(data, list):
            return data
        return data.get("list", []) if isinstance(data, dict) else []

    def get_trader_history_orders(self, trader_id: str, product_type: str = "USDT-FUTURES", page_size: int = 50) -> list[dict]:
        """Get a trader's historical closed orders (public)."""
        data = self._get("/api/v2/copy/mix-trader/query-history-orders", {"traderId": trader_id, "productType": product_type, "pageSize": str(page_size)})
        if isinstance(data, list):
            return data
        return data.get("list", []) if isinstance(data, dict) else []

    # ── Market data (public, no auth needed) ────────────────────────

    def get_ticker(self, symbol: str, product_type: str = "USDT-FUTURES") -> dict:
        """Get current market ticker for a symbol."""
        return self._get("/api/v2/mix/market/ticker", {"symbol": symbol, "productType": product_type})

    def get_klines(self, symbol: str, granularity: str = "1H", limit: int = 100, product_type: str = "USDT-FUTURES") -> list:
        """Get candlestick data for a symbol."""
        data = self._get("/api/v2/mix/market/candles", {"symbol": symbol, "productType": product_type, "granularity": granularity, "limit": str(limit)})
        return data if isinstance(data, list) else []

    def close(self) -> None:
        self._http.close()
