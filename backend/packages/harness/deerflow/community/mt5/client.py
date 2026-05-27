"""
MetaTrader 5 client wrapper for DeerFlow.

Wraps the MetaTrader5 Python package into a clean interface for
account info, position management, trade execution, and history.

Requires: pip install MetaTrader5  (Windows only — needs MT5 terminal running)
"""

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _ensure_mt5():
    """Lazy-import MetaTrader5 so the module can be loaded on any OS for testing."""
    try:
        import MetaTrader5 as mt5
        return mt5
    except ImportError:
        raise ImportError("MetaTrader5 package not installed. Run: pip install MetaTrader5 (Windows only)")


class MT5Client:
    """Wrapper around the MetaTrader5 Python package."""

    def __init__(self, account: int | None = None, password: str | None = None, server: str | None = None, path: str | None = None) -> None:
        self.account = account
        self.password = password
        self.server = server
        self.path = path
        self._connected = False

    def connect(self) -> bool:
        mt5 = _ensure_mt5()
        kwargs: dict[str, Any] = {}
        if self.path:
            kwargs["path"] = self.path
        if not mt5.initialize(**kwargs):
            raise ConnectionError(f"MT5 initialize failed: {mt5.last_error()}")

        if self.account and self.password and self.server:
            if not mt5.login(self.account, password=self.password, server=self.server):
                mt5.shutdown()
                raise ConnectionError(f"MT5 login failed: {mt5.last_error()}")

        self._connected = True
        return True

    def disconnect(self) -> None:
        if self._connected:
            mt5 = _ensure_mt5()
            mt5.shutdown()
            self._connected = False

    # ── Account ─────────────────────────────────────────────────────

    def get_account_info(self) -> dict:
        mt5 = _ensure_mt5()
        info = mt5.account_info()
        if info is None:
            raise ValueError(f"Failed to get account info: {mt5.last_error()}")
        return {
            "login": info.login,
            "name": info.name,
            "server": info.server,
            "balance": info.balance,
            "equity": info.equity,
            "margin": info.margin,
            "free_margin": info.margin_free,
            "leverage": info.leverage,
            "profit": info.profit,
            "currency": info.currency,
        }

    # ── Positions ───────────────────────────────────────────────────

    def get_positions(self, symbol: str | None = None) -> list[dict]:
        mt5 = _ensure_mt5()
        if symbol:
            positions = mt5.positions_get(symbol=symbol)
        else:
            positions = mt5.positions_get()

        if positions is None:
            return []

        return [
            {
                "ticket": p.ticket,
                "symbol": p.symbol,
                "type": "buy" if p.type == 0 else "sell",
                "volume": p.volume,
                "open_price": p.price_open,
                "current_price": p.price_current,
                "sl": p.sl,
                "tp": p.tp,
                "profit": p.profit,
                "swap": p.swap,
                "comment": p.comment,
                "magic": p.magic,
                "open_time": datetime.fromtimestamp(p.time, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            }
            for p in positions
        ]

    # ── Trade history ───────────────────────────────────────────────

    def get_deals(self, days_back: int = 30) -> list[dict]:
        mt5 = _ensure_mt5()
        from_date = datetime.now(tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        from_date = from_date.replace(day=max(1, from_date.day - 1))

        import datetime as dt_module
        from_ts = from_date - dt_module.timedelta(days=days_back)
        to_ts = datetime.now(tz=timezone.utc)

        deals = mt5.history_deals_get(from_ts, to_ts)
        if deals is None:
            return []

        return [
            {
                "ticket": d.ticket,
                "order": d.order,
                "symbol": d.symbol,
                "type": _deal_type_str(d.type),
                "volume": d.volume,
                "price": d.price,
                "profit": d.profit,
                "commission": d.commission,
                "swap": d.swap,
                "fee": d.fee,
                "comment": d.comment,
                "magic": d.magic,
                "entry": _deal_entry_str(d.entry),
                "time": datetime.fromtimestamp(d.time, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            }
            for d in deals
        ]

    # ── Market data ─────────────────────────────────────────────────

    def get_symbol_info(self, symbol: str) -> dict:
        mt5 = _ensure_mt5()
        info = mt5.symbol_info(symbol)
        if info is None:
            raise ValueError(f"Symbol {symbol} not found: {mt5.last_error()}")
        return {
            "name": info.name,
            "description": info.description,
            "bid": info.bid,
            "ask": info.ask,
            "spread": info.spread,
            "digits": info.digits,
            "volume_min": info.volume_min,
            "volume_max": info.volume_max,
            "volume_step": info.volume_step,
            "trade_contract_size": info.trade_contract_size,
            "point": info.point,
        }

    def get_tick(self, symbol: str) -> dict:
        mt5 = _ensure_mt5()
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise ValueError(f"No tick for {symbol}: {mt5.last_error()}")
        return {
            "symbol": symbol,
            "bid": tick.bid,
            "ask": tick.ask,
            "last": tick.last,
            "volume": tick.volume,
            "time": datetime.fromtimestamp(tick.time, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        }

    # ── Trade execution ─────────────────────────────────────────────

    def market_order(self, symbol: str, side: str, volume: float, sl: float | None = None, tp: float | None = None, comment: str = "deerflow") -> dict:
        """Place a market order (buy or sell)."""
        mt5 = _ensure_mt5()

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise ValueError(f"Cannot get price for {symbol}: {mt5.last_error()}")

        order_type = mt5.ORDER_TYPE_BUY if side.lower() == "buy" else mt5.ORDER_TYPE_SELL
        price = tick.ask if side.lower() == "buy" else tick.bid

        request: dict[str, Any] = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "deviation": 20,
            "magic": 202506,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        if sl is not None:
            request["sl"] = sl
        if tp is not None:
            request["tp"] = tp

        result = mt5.order_send(request)
        return _parse_order_result(result)

    def limit_order(self, symbol: str, side: str, volume: float, price: float, sl: float | None = None, tp: float | None = None, comment: str = "deerflow") -> dict:
        """Place a pending limit order."""
        mt5 = _ensure_mt5()

        order_type = mt5.ORDER_TYPE_BUY_LIMIT if side.lower() == "buy" else mt5.ORDER_TYPE_SELL_LIMIT

        request: dict[str, Any] = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "deviation": 20,
            "magic": 202506,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        if sl is not None:
            request["sl"] = sl
        if tp is not None:
            request["tp"] = tp

        result = mt5.order_send(request)
        return _parse_order_result(result)

    def modify_position(self, ticket: int, sl: float | None = None, tp: float | None = None) -> dict:
        """Modify SL/TP on an existing position."""
        mt5 = _ensure_mt5()

        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            raise ValueError(f"Position {ticket} not found")

        pos = positions[0]
        request: dict[str, Any] = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": pos.symbol,
            "position": ticket,
            "sl": sl if sl is not None else pos.sl,
            "tp": tp if tp is not None else pos.tp,
        }

        result = mt5.order_send(request)
        return _parse_order_result(result)

    def close_position(self, ticket: int, volume: float | None = None, comment: str = "deerflow close") -> dict:
        """Close an open position (full or partial)."""
        mt5 = _ensure_mt5()

        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            raise ValueError(f"Position {ticket} not found")

        pos = positions[0]
        close_volume = volume if volume is not None else pos.volume
        close_type = mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY
        tick = mt5.symbol_info_tick(pos.symbol)
        price = tick.bid if pos.type == 0 else tick.ask

        request: dict[str, Any] = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": pos.symbol,
            "volume": close_volume,
            "type": close_type,
            "position": ticket,
            "price": price,
            "deviation": 20,
            "magic": 202506,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        return _parse_order_result(result)

    def close_all(self, symbol: str | None = None, comment: str = "deerflow close all") -> list[dict]:
        """Close all open positions, optionally filtered by symbol."""
        positions = self.get_positions(symbol=symbol)
        results = []
        for pos in positions:
            try:
                r = self.close_position(pos["ticket"], comment=comment)
                results.append(r)
            except Exception as e:
                results.append({"ticket": pos["ticket"], "error": str(e)})
        return results

    # ── Risk calculator ─────────────────────────────────────────────

    def calculate_lot_size(self, symbol: str, risk_pct: float, sl_points: float) -> dict:
        """Calculate position size based on account risk percentage and SL distance."""
        mt5 = _ensure_mt5()
        account = self.get_account_info()
        sym_info = self.get_symbol_info(symbol)

        balance = account["balance"]
        risk_amount = balance * (risk_pct / 100)
        point_value = sym_info["trade_contract_size"] * sym_info["point"]

        if point_value <= 0 or sl_points <= 0:
            return {"error": "Cannot calculate: point_value or sl_points is zero"}

        raw_lots = risk_amount / (sl_points * point_value)
        step = sym_info["volume_step"]
        lots = max(sym_info["volume_min"], min(sym_info["volume_max"], round(raw_lots / step) * step))
        lots = round(lots, 2)

        return {
            "symbol": symbol,
            "account_balance": balance,
            "risk_pct": risk_pct,
            "risk_amount": round(risk_amount, 2),
            "sl_points": sl_points,
            "calculated_lots": lots,
            "volume_min": sym_info["volume_min"],
            "volume_max": sym_info["volume_max"],
            "volume_step": sym_info["volume_step"],
        }


# ── Helpers ─────────────────────────────────────────────────────────


def _deal_type_str(deal_type: int) -> str:
    types = {0: "buy", 1: "sell", 2: "balance", 3: "credit", 4: "charge", 5: "correction", 6: "bonus"}
    return types.get(deal_type, f"unknown({deal_type})")


def _deal_entry_str(entry: int) -> str:
    entries = {0: "in", 1: "out", 2: "in_out", 3: "out_by"}
    return entries.get(entry, f"unknown({entry})")


def _parse_order_result(result) -> dict:
    if result is None:
        return {"success": False, "error": "order_send returned None"}
    retcode = result.retcode
    success = retcode == 10009  # TRADE_RETCODE_DONE
    return {
        "success": success,
        "retcode": retcode,
        "retcode_description": _retcode_str(retcode),
        "deal": result.deal,
        "order": result.order,
        "volume": result.volume,
        "price": result.price,
        "comment": result.comment,
    }


def _retcode_str(code: int) -> str:
    codes = {
        10004: "REQUOTE", 10006: "REJECT", 10007: "CANCEL",
        10008: "PLACED", 10009: "DONE", 10010: "DONE_PARTIAL",
        10011: "ERROR", 10012: "TIMEOUT", 10013: "INVALID",
        10014: "INVALID_VOLUME", 10015: "INVALID_PRICE",
        10016: "INVALID_STOPS", 10017: "TRADE_DISABLED",
        10018: "MARKET_CLOSED", 10019: "NO_MONEY",
        10020: "PRICE_CHANGED", 10021: "PRICE_OFF",
        10022: "INVALID_EXPIRATION", 10023: "ORDER_CHANGED",
        10024: "TOO_MANY_REQUESTS", 10025: "NO_CHANGES",
        10026: "AUTOTRADING_DISABLED", 10027: "LOCKED",
        10028: "FROZEN", 10029: "INVALID_FILL",
        10030: "CONNECTION", 10031: "ONLY_REAL",
        10032: "LIMIT_ORDERS", 10033: "LIMIT_VOLUME",
    }
    return codes.get(code, f"UNKNOWN({code})")
