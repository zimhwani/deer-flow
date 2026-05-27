"""
MetaTrader 5 Trading Tools for DeerFlow.

Provides LangChain tools the agent can call to manage positions, execute trades,
analyze history, and calculate risk on any MT5 broker (Deriv, Exness, IC Markets, etc.).
"""

import json
import logging
from datetime import datetime, timezone

from langchain.tools import tool

from deerflow.config import get_app_config

logger = logging.getLogger(__name__)


def _get_client():
    """Create and connect an MT5Client from tool config."""
    from deerflow.community.mt5.client import MT5Client

    config = get_app_config().get_tool_config("mt5_trade")
    account = None
    password = None
    server = None
    path = None

    if config is not None:
        extra = config.model_extra
        acct_raw = extra.get("account", "")
        account = int(acct_raw) if acct_raw else None
        password = extra.get("password", "") or None
        server = extra.get("server", "") or None
        path = extra.get("terminal_path", "") or None

    client = MT5Client(account=account, password=password, server=server, path=path)
    client.connect()
    return client


@tool("mt5_trade", parse_docstring=True)
def mt5_trade_tool(
    action: str,
    symbol: str = "",
    side: str = "",
    volume: float = 0.0,
    price: float = 0.0,
    sl: float = 0.0,
    tp: float = 0.0,
    ticket: int = 0,
    risk_pct: float = 0.0,
    sl_points: float = 0.0,
    days_back: int = 30,
    comment: str = "deerflow",
) -> str:
    """Trade and analyze positions on MetaTrader 5 (Deriv, Exness, IC Markets, etc.). For trade actions (market_order, limit_order, modify, close, close_all), ALWAYS confirm with the user before executing.

    Args:
        action: One of: "account" (balance/equity/margin), "positions" (open positions), "history" (closed trades + analysis), "symbol_info" (spread/contract size), "tick" (bid/ask price), "calculate_lot" (lot size from risk%), "full_report" (everything combined), "market_order" (buy/sell at market), "limit_order" (pending order), "modify" (change SL/TP), "close" (close position), "close_all" (close all positions).
        symbol: Trading pair e.g. "BTCUSD". Required for orders, symbol_info, tick, calculate_lot.
        side: "buy" or "sell". Required for market_order and limit_order.
        volume: Lot size. Required for market_order and limit_order. Optional for partial close.
        price: Entry price. Required for limit_order.
        sl: Stop loss price. Optional for orders and modify.
        tp: Take profit price. Optional for orders and modify.
        ticket: Position ticket number. Required for modify and close.
        risk_pct: Account risk percentage for calculate_lot (e.g. 2.0 means 2%).
        sl_points: Stop loss distance in points for calculate_lot.
        days_back: Days of history to fetch. Default 30.
        comment: Order comment. Default "deerflow".
    """
    try:
        client = _get_client()
    except Exception as e:
        return json.dumps({"error": f"MT5 connection failed: {e}"})

    try:
        result = _dispatch(client, action, symbol, side, volume, price, sl, tp, ticket, risk_pct, sl_points, days_back, comment)
        return json.dumps(result, indent=2, ensure_ascii=False, default=str)
    except Exception as e:
        logger.exception("MT5 tool error")
        return json.dumps({"error": str(e)})
    finally:
        client.disconnect()


def _dispatch(client, action, symbol, side, volume, price, sl, tp, ticket, risk_pct, sl_points, days_back, comment) -> dict:
    sl_val = sl if sl != 0.0 else None
    tp_val = tp if tp != 0.0 else None

    if action == "account":
        return {"action": "account", "data": client.get_account_info()}

    elif action == "positions":
        sym = symbol or None
        positions = client.get_positions(symbol=sym)
        total_profit = sum(p["profit"] for p in positions)
        return {"action": "positions", "count": len(positions), "total_unrealized_pnl": round(total_profit, 2), "positions": positions}

    elif action == "history":
        deals = client.get_deals(days_back=days_back)
        analysis = _analyze_deals(deals)
        return {"action": "history", "days_back": days_back, "count": len(deals), "analysis": analysis, "deals": deals[:100]}

    elif action == "symbol_info":
        if not symbol:
            return {"error": "symbol is required"}
        return {"action": "symbol_info", "data": client.get_symbol_info(symbol)}

    elif action == "tick":
        if not symbol:
            return {"error": "symbol is required"}
        return {"action": "tick", "data": client.get_tick(symbol)}

    elif action == "calculate_lot":
        if not symbol or risk_pct <= 0 or sl_points <= 0:
            return {"error": "symbol, risk_pct (>0), and sl_points (>0) are required"}
        return {"action": "calculate_lot", "data": client.calculate_lot_size(symbol, risk_pct, sl_points)}

    elif action == "market_order":
        if not symbol or not side or volume <= 0:
            return {"error": "symbol, side (buy/sell), and volume (>0) are required"}
        return {"action": "market_order", "result": client.market_order(symbol, side, volume, sl=sl_val, tp=tp_val, comment=comment)}

    elif action == "limit_order":
        if not symbol or not side or volume <= 0 or price <= 0:
            return {"error": "symbol, side, volume (>0), and price (>0) are required"}
        return {"action": "limit_order", "result": client.limit_order(symbol, side, volume, price, sl=sl_val, tp=tp_val, comment=comment)}

    elif action == "modify":
        if ticket <= 0:
            return {"error": "ticket is required for modify"}
        if sl_val is None and tp_val is None:
            return {"error": "at least one of sl or tp must be set"}
        return {"action": "modify", "result": client.modify_position(ticket, sl=sl_val, tp=tp_val)}

    elif action == "close":
        if ticket <= 0:
            return {"error": "ticket is required for close"}
        vol = volume if volume > 0 else None
        return {"action": "close", "result": client.close_position(ticket, volume=vol, comment=comment)}

    elif action == "close_all":
        sym = symbol or None
        results = client.close_all(symbol=sym, comment=comment)
        return {"action": "close_all", "results": results}

    elif action == "full_report":
        return _generate_full_report(client, days_back)

    else:
        return {"error": f"Unknown action: {action}. Use: account, positions, history, symbol_info, tick, calculate_lot, market_order, limit_order, modify, close, close_all, full_report"}


def _analyze_deals(deals: list[dict]) -> dict:
    """Compute performance metrics from closed deals."""
    trade_deals = [d for d in deals if d["entry"] == "out" and d["type"] in ("buy", "sell")]

    if not trade_deals:
        return {"total_closed_trades": 0, "message": "No closed trades in this period"}

    total = len(trade_deals)
    wins = 0
    losses = 0
    total_pnl = 0.0
    total_profit = 0.0
    total_loss = 0.0
    total_commission = 0.0
    total_swap = 0.0
    symbols: dict[str, int] = {}
    sides: dict[str, int] = {}

    for d in trade_deals:
        pnl = d["profit"]
        total_pnl += pnl
        total_commission += d.get("commission", 0)
        total_swap += d.get("swap", 0)

        if pnl > 0:
            wins += 1
            total_profit += pnl
        elif pnl < 0:
            losses += 1
            total_loss += abs(pnl)

        symbols[d["symbol"]] = symbols.get(d["symbol"], 0) + 1
        sides[d["type"]] = sides.get(d["type"], 0) + 1

    win_rate = (wins / total * 100) if total > 0 else 0
    avg_win = (total_profit / wins) if wins > 0 else 0
    avg_loss = (total_loss / losses) if losses > 0 else 0
    profit_factor = (total_profit / total_loss) if total_loss > 0 else float("inf")
    expectancy = total_pnl / total if total > 0 else 0

    net_pnl = total_pnl + total_commission + total_swap

    return {
        "total_closed_trades": total,
        "wins": wins,
        "losses": losses,
        "breakeven": total - wins - losses,
        "win_rate_pct": round(win_rate, 2),
        "gross_pnl": round(total_pnl, 2),
        "total_commission": round(total_commission, 2),
        "total_swap": round(total_swap, 2),
        "net_pnl": round(net_pnl, 2),
        "total_profit": round(total_profit, 2),
        "total_loss": round(total_loss, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else "inf",
        "expectancy_per_trade": round(expectancy, 2),
        "symbols_traded": symbols,
        "side_distribution": sides,
        "savings_vs_30pct_copy": round(total_profit * 0.30, 2) if total_profit > 0 else 0,
    }


def _generate_full_report(client, days_back: int) -> dict:
    """Pull account, positions, and history into one analysis."""
    report: dict = {"action": "full_report"}

    try:
        report["account"] = client.get_account_info()
    except Exception as e:
        report["account_error"] = str(e)

    try:
        positions = client.get_positions()
        total_profit = sum(p["profit"] for p in positions)
        report["positions"] = {"count": len(positions), "total_unrealized_pnl": round(total_profit, 2), "positions": positions}
    except Exception as e:
        report["positions_error"] = str(e)

    try:
        deals = client.get_deals(days_back=days_back)
        report["history"] = {"days_back": days_back, "count": len(deals), "analysis": _analyze_deals(deals)}
    except Exception as e:
        report["history_error"] = str(e)

    return report
