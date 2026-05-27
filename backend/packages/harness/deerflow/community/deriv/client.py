"""
Deriv WebSocket API client.

Connects to wss://ws.derivws.com/websockets/v3 for trading, account info,
portfolio management, and market data. Works on any OS (Linux, Mac, Windows).

Requires: pip install websockets
"""

import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

WS_URL = "wss://ws.derivws.com/websockets/v3"


class DerivClient:
    """Synchronous wrapper around Deriv's async WebSocket API."""

    def __init__(self, api_token: str, app_id: str = "1089") -> None:
        self.api_token = api_token
        self.app_id = app_id
        self._req_id = 0

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    def _run(self, coro):
        """Run an async coroutine synchronously."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result(timeout=30)
        return asyncio.run(coro)

    async def _request(self, payload: dict) -> dict:
        """Open connection, authenticate, send one request, return response."""
        try:
            from websockets.asyncio.client import connect
        except ImportError:
            try:
                from websockets import connect as connect
            except ImportError:
                raise ImportError("websockets package not installed. Run: pip install websockets")

        url = f"{WS_URL}?app_id={self.app_id}"
        async with connect(url) as ws:
            auth_msg = json.dumps({"authorize": self.api_token, "req_id": self._next_id()})
            await ws.send(auth_msg)
            auth_resp = json.loads(await ws.recv())

            if "error" in auth_resp:
                raise ValueError(f"Auth failed: {auth_resp['error'].get('message', auth_resp['error'])}")

            payload["req_id"] = self._next_id()
            await ws.send(json.dumps(payload))

            while True:
                resp = json.loads(await ws.recv())
                if resp.get("req_id") == payload["req_id"]:
                    if "error" in resp:
                        raise ValueError(f"API error: {resp['error'].get('message', resp['error'])}")
                    return resp
                if resp.get("msg_type") == "authorize":
                    continue

    def _call(self, payload: dict) -> dict:
        return self._run(self._request(payload))

    # ── Account ─────────────────────────────────────────────────────

    def get_balance(self) -> dict:
        resp = self._call({"balance": 1})
        bal = resp.get("balance", {})
        return {
            "balance": bal.get("balance"),
            "currency": bal.get("currency"),
            "login_id": bal.get("loginid"),
        }

    # ── Portfolio (open positions) ──────────────────────────────────

    def get_portfolio(self) -> list[dict]:
        resp = self._call({"portfolio": 1})
        contracts = resp.get("portfolio", {}).get("contracts", [])
        return [
            {
                "contract_id": c.get("contract_id"),
                "contract_type": c.get("contract_type"),
                "symbol": c.get("symbol"),
                "buy_price": c.get("buy_price"),
                "sell_price": c.get("sell_price", c.get("bid_price")),
                "payout": c.get("payout"),
                "profit": round((c.get("sell_price") or c.get("bid_price", 0)) - (c.get("buy_price") or 0), 2) if c.get("buy_price") else None,
                "is_valid_to_sell": c.get("is_valid_to_sell"),
                "purchase_time": c.get("purchase_time"),
                "longcode": c.get("longcode"),
            }
            for c in contracts
        ]

    # ── Profit table (trade history) ────────────────────────────────

    def get_profit_table(self, limit: int = 50, sort: str = "DESC") -> list[dict]:
        resp = self._call({"profit_table": 1, "description": 1, "limit": limit, "sort": sort})
        txns = resp.get("profit_table", {}).get("transactions", [])
        return [
            {
                "contract_id": t.get("contract_id"),
                "transaction_id": t.get("transaction_id"),
                "symbol": t.get("shortcode", "").split("_")[0] if t.get("shortcode") else t.get("app_id", ""),
                "buy_price": t.get("buy_price"),
                "sell_price": t.get("sell_price"),
                "profit_loss": t.get("profit_loss"),
                "purchase_time": t.get("purchase_time"),
                "sell_time": t.get("sell_time"),
                "longcode": t.get("longcode"),
            }
            for t in txns
        ]

    # ── Statement (full transaction log) ────────────────────────────

    def get_statement(self, limit: int = 50) -> list[dict]:
        resp = self._call({"statement": 1, "description": 1, "limit": limit})
        txns = resp.get("statement", {}).get("transactions", [])
        return [
            {
                "transaction_id": t.get("transaction_id"),
                "action_type": t.get("action_type"),
                "amount": t.get("amount"),
                "balance_after": t.get("balance_after"),
                "transaction_time": t.get("transaction_time"),
                "longcode": t.get("longcode"),
            }
            for t in txns
        ]

    # ── Market data ─────────────────────────────────────────────────

    def get_tick(self, symbol: str) -> dict:
        resp = self._call({"ticks": symbol})
        tick = resp.get("tick", {})
        return {
            "symbol": tick.get("symbol", symbol),
            "bid": tick.get("bid"),
            "ask": tick.get("ask"),
            "quote": tick.get("quote"),
            "epoch": tick.get("epoch"),
        }

    def get_active_symbols(self, product_type: str = "basic") -> list[dict]:
        resp = self._call({"active_symbols": product_type})
        symbols = resp.get("active_symbols", [])
        return [
            {
                "symbol": s.get("symbol"),
                "display_name": s.get("display_name"),
                "market": s.get("market"),
                "submarket": s.get("submarket"),
                "pip_size": s.get("pip"),
                "is_trading_suspended": s.get("is_trading_suspended"),
            }
            for s in symbols
        ]

    # ── Trading ─────────────────────────────────────────────────────

    def get_proposal(self, symbol: str, contract_type: str, amount: float, duration: int, duration_unit: str = "m", basis: str = "stake", barrier: str | None = None) -> dict:
        """Get a price quote before buying."""
        payload: dict[str, Any] = {
            "proposal": 1,
            "symbol": symbol,
            "contract_type": contract_type,
            "amount": amount,
            "duration": duration,
            "duration_unit": duration_unit,
            "basis": basis,
            "currency": "USD",
        }
        if barrier is not None:
            payload["barrier"] = barrier

        resp = self._call(payload)
        prop = resp.get("proposal", {})
        return {
            "proposal_id": prop.get("id"),
            "ask_price": prop.get("ask_price"),
            "spot": prop.get("spot"),
            "spot_time": prop.get("spot_time"),
            "payout": prop.get("payout"),
            "longcode": prop.get("longcode"),
        }

    def buy(self, proposal_id: str, price: float) -> dict:
        """Buy a contract using a proposal ID."""
        resp = self._call({"buy": proposal_id, "price": price})
        buy_data = resp.get("buy", {})
        return {
            "contract_id": buy_data.get("contract_id"),
            "buy_price": buy_data.get("buy_price"),
            "balance_after": buy_data.get("balance_after"),
            "payout": buy_data.get("payout"),
            "spot": buy_data.get("start_time"),
            "transaction_id": buy_data.get("transaction_id"),
            "longcode": buy_data.get("longcode"),
        }

    def buy_contract(self, symbol: str, contract_type: str, amount: float, duration: int, duration_unit: str = "m", basis: str = "stake", barrier: str | None = None) -> dict:
        """Get proposal and buy in one step."""
        payload: dict[str, Any] = {
            "buy": 1,
            "price": amount * 2,
            "parameters": {
                "symbol": symbol,
                "contract_type": contract_type,
                "amount": amount,
                "duration": duration,
                "duration_unit": duration_unit,
                "basis": basis,
                "currency": "USD",
            },
        }
        if barrier is not None:
            payload["parameters"]["barrier"] = barrier

        resp = self._call(payload)
        buy_data = resp.get("buy", {})
        return {
            "contract_id": buy_data.get("contract_id"),
            "buy_price": buy_data.get("buy_price"),
            "balance_after": buy_data.get("balance_after"),
            "payout": buy_data.get("payout"),
            "transaction_id": buy_data.get("transaction_id"),
            "longcode": buy_data.get("longcode"),
        }

    def sell(self, contract_id: str, price: float = 0) -> dict:
        """Sell/close an open contract. Price=0 means sell at market."""
        resp = self._call({"sell": contract_id, "price": price})
        sell_data = resp.get("sell", {})
        return {
            "contract_id": sell_data.get("contract_id") or contract_id,
            "sell_price": sell_data.get("sold_for") or sell_data.get("sell_price"),
            "balance_after": sell_data.get("balance_after"),
            "transaction_id": sell_data.get("transaction_id"),
        }

    def sell_all(self) -> list[dict]:
        """Close all open positions."""
        portfolio = self.get_portfolio()
        results = []
        for pos in portfolio:
            if pos.get("is_valid_to_sell"):
                try:
                    r = self.sell(pos["contract_id"])
                    results.append(r)
                except Exception as e:
                    results.append({"contract_id": pos["contract_id"], "error": str(e)})
        return results
