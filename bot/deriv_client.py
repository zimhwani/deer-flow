"""
Deriv WebSocket client for the standalone trading bot.

Async client that maintains a persistent connection with automatic
keepalive pings and request/response correlation via req_id.
"""

import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

WS_URL = "wss://ws.derivws.com/websockets/v3"


class DerivBot:
    """Persistent async Deriv WebSocket client for bot trading."""

    def __init__(self, api_token: str, app_id: str = "1089") -> None:
        self.api_token = api_token
        self.app_id = app_id
        self._ws = None
        self._req_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._recv_task = None
        self._ping_task = None
        self._authorized = False

    async def connect(self) -> None:
        try:
            from websockets.asyncio.client import connect
        except ImportError:
            from websockets import connect

        url = f"{WS_URL}?app_id={self.app_id}"
        self._ws = await connect(url)
        self._recv_task = asyncio.create_task(self._recv_loop())
        self._ping_task = asyncio.create_task(self._ping_loop())

        auth_resp = await self._send({"authorize": self.api_token})
        if "error" in auth_resp:
            raise ConnectionError(f"Auth failed: {auth_resp['error'].get('message')}")
        self._authorized = True
        login_id = auth_resp.get("authorize", {}).get("loginid", "unknown")
        balance = auth_resp.get("authorize", {}).get("balance", 0)
        currency = auth_resp.get("authorize", {}).get("currency", "USD")
        logger.info(f"Connected to Deriv: {login_id} | Balance: {balance} {currency}")

    async def disconnect(self) -> None:
        if self._ping_task:
            self._ping_task.cancel()
        if self._recv_task:
            self._recv_task.cancel()
        if self._ws:
            await self._ws.close()
        self._authorized = False

    async def _send(self, payload: dict) -> dict:
        self._req_id += 1
        rid = self._req_id
        payload["req_id"] = rid

        future = asyncio.get_event_loop().create_future()
        self._pending[rid] = future

        await self._ws.send(json.dumps(payload))
        try:
            return await asyncio.wait_for(future, timeout=15)
        except asyncio.TimeoutError:
            self._pending.pop(rid, None)
            raise TimeoutError(f"Request {rid} timed out")

    async def _recv_loop(self) -> None:
        try:
            async for msg in self._ws:
                data = json.loads(msg)
                rid = data.get("req_id")
                if rid and rid in self._pending:
                    self._pending.pop(rid).set_result(data)
        except Exception:
            pass

    async def _ping_loop(self) -> None:
        while True:
            await asyncio.sleep(25)
            try:
                await self._send({"ping": 1})
            except Exception:
                pass

    # ── Account ─────────────────────────────────────────────────────

    async def get_balance(self) -> dict:
        resp = await self._send({"balance": 1})
        b = resp.get("balance", {})
        return {"balance": b.get("balance"), "currency": b.get("currency")}

    # ── Market data ─────────────────────────────────────────────────

    async def get_tick(self, symbol: str) -> dict:
        resp = await self._send({"ticks": symbol})
        t = resp.get("tick", {})
        return {"bid": t.get("bid"), "ask": t.get("ask"), "quote": t.get("quote"), "epoch": t.get("epoch")}

    async def get_candles(self, symbol: str, granularity: int = 60, count: int = 100) -> list[dict]:
        """Get OHLC candle data. granularity in seconds (60=1m, 300=5m, 900=15m, 3600=1h)."""
        resp = await self._send({
            "ticks_history": symbol,
            "adjust_start_time": 1,
            "count": count,
            "end": "latest",
            "granularity": granularity,
            "style": "candles",
        })
        candles = resp.get("candles", [])
        return [
            {"open": float(c["open"]), "high": float(c["high"]), "low": float(c["low"]), "close": float(c["close"]), "epoch": c["epoch"]}
            for c in candles
        ]

    # ── Portfolio ───────────────────────────────────────────────────

    async def get_portfolio(self) -> list[dict]:
        resp = await self._send({"portfolio": 1})
        contracts = resp.get("portfolio", {}).get("contracts", [])
        return [
            {
                "contract_id": c.get("contract_id"),
                "contract_type": c.get("contract_type"),
                "symbol": c.get("symbol"),
                "buy_price": c.get("buy_price"),
                "sell_price": c.get("sell_price") or c.get("bid_price"),
                "payout": c.get("payout"),
                "is_valid_to_sell": c.get("is_valid_to_sell"),
            }
            for c in contracts
        ]

    # ── Trading ─────────────────────────────────────────────────────

    async def buy(self, symbol: str, contract_type: str, amount: float, duration: int, duration_unit: str = "m", barrier: str | None = None) -> dict:
        params: dict[str, Any] = {
            "symbol": symbol,
            "contract_type": contract_type,
            "amount": amount,
            "duration": duration,
            "duration_unit": duration_unit,
            "basis": "stake",
            "currency": "USD",
        }
        if barrier:
            params["barrier"] = barrier

        resp = await self._send({"buy": 1, "price": amount * 5, "parameters": params})
        if "error" in resp:
            raise ValueError(f"Buy failed: {resp['error'].get('message')}")
        b = resp.get("buy", {})
        return {
            "contract_id": b.get("contract_id"),
            "buy_price": b.get("buy_price"),
            "balance_after": b.get("balance_after"),
            "longcode": b.get("longcode"),
        }

    async def sell(self, contract_id: str, price: float = 0) -> dict:
        resp = await self._send({"sell": contract_id, "price": price})
        if "error" in resp:
            raise ValueError(f"Sell failed: {resp['error'].get('message')}")
        s = resp.get("sell", {})
        return {
            "contract_id": contract_id,
            "sell_price": s.get("sold_for") or s.get("sell_price"),
            "balance_after": s.get("balance_after"),
        }

    async def get_active_symbols(self, market: str | None = None) -> list[dict]:
        resp = await self._send({"active_symbols": "brief"})
        symbols = resp.get("active_symbols", [])
        if market:
            symbols = [s for s in symbols if s.get("market") == market]
        return [{"symbol": s["symbol"], "display_name": s.get("display_name", ""), "market": s.get("market", "")} for s in symbols]
