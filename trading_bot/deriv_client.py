"""
Deriv.com WebSocket API Client
Handles connection, authentication, and API calls.
"""

import asyncio
import json
import logging
import time
from typing import Any, Callable, Dict, Optional

import aiohttp
import websockets
from websockets.exceptions import ConnectionClosed

_REST_BASE = "https://api.derivws.com"

logger = logging.getLogger(__name__)


class DerivClient:
    """Async WebSocket client for Deriv.com API."""

    def __init__(self, api_token: str, app_id: str, account_id: str):
        self.api_token = api_token
        self.app_id = app_id
        self.account_id = account_id
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self._req_id = 0
        self._pending: Dict[int, asyncio.Future] = {}
        self._subscriptions: Dict[str, Callable] = {}
        self._listener_task: Optional[asyncio.Task] = None
        self.is_authorized = False
        self.account_info: Dict[str, Any] = {}

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    async def _get_otp_url(self) -> str:
        """Call REST API to get an authenticated WebSocket URL (OTP)."""
        url = f"{_REST_BASE}/trading/v1/options/accounts/{self.account_id}/otp"
        logger.debug(f"OTP request: POST {url}")
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Deriv-App-ID": self.app_id,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers) as resp:
                text = await resp.text()
                logger.debug(f"OTP response ({resp.status}): {text[:300]}")
                if resp.status != 200:
                    raise RuntimeError(
                        f"OTP request failed (HTTP {resp.status}) for account "
                        f"'{self.account_id}' with app '{self.app_id}': {text}"
                    )
                try:
                    data = json.loads(text)
                    ws_url = data["data"]["url"]
                except (KeyError, json.JSONDecodeError) as e:
                    raise RuntimeError(
                        f"Unexpected OTP response format: {e} — body: {text[:300]}"
                    )
                return ws_url

    async def connect(self) -> None:
        """Establish WebSocket connection via OTP-authenticated URL."""
        logger.info("Requesting authenticated WebSocket URL...")
        ws_url = await self._get_otp_url()
        # Log the host only (strip the OTP token from the URL for security)
        from urllib.parse import urlparse
        parsed = urlparse(ws_url)
        logger.info(f"Connecting to Deriv API ({parsed.scheme}://{parsed.netloc}{parsed.path})...")
        self.ws = await websockets.connect(
            ws_url,
            ping_interval=30,
            ping_timeout=10,
        )
        self._listener_task = asyncio.create_task(self._listen())
        logger.info("Connected to Deriv API")

    async def disconnect(self) -> None:
        """Close WebSocket connection."""
        if self._listener_task:
            self._listener_task.cancel()
        if self.ws:
            await self.ws.close()
        self.is_authorized = False
        logger.info("Disconnected from Deriv API")

    async def authorize(self) -> Dict[str, Any]:
        """Auth is handled via OTP URL; fetch account info from balance."""
        self.is_authorized = True
        balance = await self.get_balance()
        self.account_info = {
            "balance": balance.get("balance", 0),
            "currency": balance.get("currency", ""),
        }
        logger.info(
            f"Connected to account {self.account_id} "
            f"| Balance: {self.account_info.get('balance', 0)} "
            f"{self.account_info.get('currency', '')}"
        )
        return self.account_info

    async def send(self, payload: Dict[str, Any], timeout: float = 30.0) -> Dict[str, Any]:
        """Send a request and wait for the response."""
        req_id = self._next_id()
        payload["req_id"] = req_id
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = future

        await self.ws.send(json.dumps(payload))
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise TimeoutError(f"Request timed out: {payload}")

    async def _listen(self) -> None:
        """Background task to receive messages from the WebSocket."""
        try:
            async for raw in self.ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                req_id = msg.get("req_id")

                # Resolve pending futures
                if req_id and req_id in self._pending:
                    future = self._pending.pop(req_id)
                    if not future.done():
                        future.set_result(msg)

                # Handle subscription callbacks
                msg_type = msg.get("msg_type")
                if msg_type in self._subscriptions:
                    try:
                        await self._subscriptions[msg_type](msg)
                    except Exception as e:
                        logger.error(f"Subscription callback error ({msg_type}): {e}")

        except ConnectionClosed as e:
            logger.warning(f"WebSocket connection closed: {e}")
            # Fail any pending requests
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(ConnectionError("WebSocket closed"))
            self._pending.clear()
        except asyncio.CancelledError:
            pass

    def on(self, msg_type: str, callback: Callable) -> None:
        """Register a callback for a subscription message type."""
        self._subscriptions[msg_type] = callback

    # ---- Account Methods ----

    async def get_balance(self) -> Dict[str, Any]:
        """Get current account balance."""
        resp = await self.send({"balance": 1, "subscribe": 0})
        return resp.get("balance", {})

    async def get_portfolio(self) -> Dict[str, Any]:
        """Get open contracts."""
        resp = await self.send({"portfolio": 1})
        return resp.get("portfolio", {})

    async def get_statement(self, limit: int = 50) -> Dict[str, Any]:
        """Get account statement."""
        resp = await self.send({"statement": 1, "limit": limit})
        return resp.get("statement", {})

    # ---- Market Data Methods ----

    async def get_active_symbols(self, market_type: str = "synthetic_index") -> list:
        """Get list of active trading symbols."""
        resp = await self.send({
            "active_symbols": "brief",
            "product_type": "basic",
        })
        symbols = resp.get("active_symbols", [])
        if market_type:
            symbols = [s for s in symbols if s.get("market") == market_type]
        return symbols

    async def get_ticks(self, symbol: str, count: int = 100) -> list:
        """Get historical tick data."""
        resp = await self.send({
            "ticks_history": symbol,
            "count": count,
            "end": "latest",
            "style": "ticks",
        })
        history = resp.get("history", {})
        prices = history.get("prices", [])
        times = history.get("times", [])
        return [{"price": p, "time": t} for p, t in zip(prices, times)]

    async def get_candles(self, symbol: str, granularity: int = 60, count: int = 100) -> list:
        """Get OHLC candle data. granularity in seconds (60=1min, 300=5min)."""
        resp = await self.send({
            "ticks_history": symbol,
            "count": count,
            "end": "latest",
            "style": "candles",
            "granularity": granularity,
        })
        return resp.get("candles", [])

    async def subscribe_ticks(self, symbol: str, callback: Callable) -> str:
        """Subscribe to live tick stream. Returns subscription ID."""
        self.on("tick", callback)
        resp = await self.send({
            "ticks": symbol,
            "subscribe": 1,
        })
        if "error" in resp:
            raise RuntimeError(f"Tick subscription failed: {resp['error']['message']}")
        return resp.get("subscription", {}).get("id", "")

    async def forget(self, subscription_id: str) -> None:
        """Cancel a subscription."""
        await self.send({"forget": subscription_id})

    # ---- Trading Methods ----

    async def buy_contract(
        self,
        symbol: str,
        contract_type: str,
        duration: int,
        duration_unit: str,
        amount: float,
        basis: str = "stake",
    ) -> Dict[str, Any]:
        """
        Buy a contract (open a position).

        contract_type: CALL (up) or PUT (down)
        basis: 'stake' (amount you pay) or 'payout' (amount you receive if win)
        """
        # First get a price proposal
        proposal = await self.send({
            "proposal": 1,
            "amount": amount,
            "basis": basis,
            "contract_type": contract_type,
            "currency": "AUD",
            "duration": duration,
            "duration_unit": duration_unit,
            "underlying_symbol": symbol,
        })

        if "error" in proposal:
            raise RuntimeError(f"Proposal failed: {proposal['error']['message']}")

        proposal_id = proposal["proposal"]["id"]
        payout = proposal["proposal"].get("payout", 0)
        ask_price = proposal["proposal"].get("ask_price", amount)

        logger.info(
            f"Proposal: {contract_type} {symbol} | Stake: {ask_price:.2f} AUD | "
            f"Payout: {payout:.2f} AUD | Duration: {duration}{duration_unit}"
        )

        # Buy the proposal
        buy_resp = await self.send({"buy": proposal_id, "price": ask_price})

        if "error" in buy_resp:
            raise RuntimeError(f"Buy failed: {buy_resp['error']['message']}")

        contract = buy_resp.get("buy", {})
        logger.info(
            f"Contract opened: {contract.get('contract_id')} | "
            f"Buy price: {contract.get('buy_price')} | "
            f"Payout: {contract.get('payout')}"
        )
        return contract

    async def sell_contract(self, contract_id: int, price: float = 0) -> Dict[str, Any]:
        """Sell/close an open contract early."""
        resp = await self.send({"sell": contract_id, "price": price})
        if "error" in resp:
            raise RuntimeError(f"Sell failed: {resp['error']['message']}")
        return resp.get("sell", {})

    async def get_contract(self, contract_id: int) -> Dict[str, Any]:
        """Get details of a specific contract."""
        resp = await self.send({
            "proposal_open_contract": 1,
            "contract_id": contract_id,
        })
        return resp.get("proposal_open_contract", {})
