"""
Bitget Copy Trading Analysis Tools for DeerFlow.

Provides LangChain tools that the agent can call to pull account data,
open positions, copy trading history, and trader performance from Bitget.
"""

import json
import logging
from datetime import datetime, timezone

from langchain.tools import tool

from deerflow.config import get_app_config

logger = logging.getLogger(__name__)


def _get_client():
    """Create a BitgetClient from tool config."""
    from deerflow.community.bitget.client import BitgetClient

    config = get_app_config().get_tool_config("bitget_copy_analysis")
    if config is None:
        raise ValueError("bitget_copy_analysis tool not configured in config.yaml. Add api_key, api_secret, and passphrase.")
    extra = config.model_extra
    api_key = extra.get("api_key", "")
    api_secret = extra.get("api_secret", "")
    passphrase = extra.get("passphrase", "")
    if not all([api_key, api_secret, passphrase]):
        raise ValueError("Bitget API credentials incomplete. Set api_key, api_secret, and passphrase in config.yaml or via environment variables ($BITGET_API_KEY, etc.).")
    return BitgetClient(api_key, api_secret, passphrase)


def _ts_to_iso(ts: str | int | None) -> str:
    """Convert millisecond timestamp to ISO date string."""
    if ts is None:
        return "N/A"
    try:
        return datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    except (ValueError, OSError):
        return str(ts)


@tool("bitget_copy_analysis", parse_docstring=True)
def bitget_copy_analysis_tool(action: str, symbol: str = "", trader_id: str = "", page_size: int = 50) -> str:
    """Analyze copy trading performance on Bitget. Use this tool to pull account data, positions,
    copy trading history, and trader stats from the Bitget exchange.

    Args:
        action: The action to perform. One of:
            - "account" — Get futures account balance and margin info
            - "positions" — Get all currently open futures positions
            - "position_detail" — Get position detail for a specific symbol (requires symbol)
            - "copy_current" — Get currently open copy trading orders
            - "copy_history" — Get historical closed copy trading orders
            - "copy_settings" — Get current copy trading follower settings
            - "trader_summary" — Get a trader's public profit summary (requires trader_id)
            - "trader_positions" — Get a trader's current open positions (requires trader_id)
            - "trader_history" — Get a trader's historical orders (requires trader_id)
            - "ticker" — Get current market price for a symbol (requires symbol)
            - "klines" — Get recent candlestick data for a symbol (requires symbol)
            - "full_report" — Generate a comprehensive copy trading analysis report
        symbol: Trading pair symbol, e.g. "BTCUSDT". Required for position_detail, ticker, klines.
        trader_id: The trader's ID on Bitget. Required for trader_summary, trader_positions, trader_history.
        page_size: Number of records to fetch for history queries. Default 50.
    """
    try:
        client = _get_client()
    except ValueError as e:
        return json.dumps({"error": str(e)})

    try:
        result = _dispatch(client, action, symbol, trader_id, page_size)
        return json.dumps(result, indent=2, ensure_ascii=False, default=str)
    except Exception as e:
        logger.exception("Bitget tool error")
        return json.dumps({"error": str(e)})
    finally:
        client.close()


def _dispatch(client, action: str, symbol: str, trader_id: str, page_size: int) -> dict:
    """Route to the right API call based on action."""

    if action == "account":
        data = client.get_futures_account()
        return {"action": "account", "data": data}

    elif action == "positions":
        positions = client.get_open_positions()
        return {"action": "positions", "count": len(positions), "positions": _format_positions(positions)}

    elif action == "position_detail":
        if not symbol:
            return {"error": "symbol is required for position_detail"}
        positions = client.get_single_position(symbol)
        return {"action": "position_detail", "symbol": symbol, "positions": _format_positions(positions)}

    elif action == "copy_current":
        orders = client.get_copy_trading_current_orders(page_size=page_size)
        return {"action": "copy_current", "count": len(orders), "orders": _format_copy_orders(orders)}

    elif action == "copy_history":
        orders = client.get_copy_trading_history_orders(page_size=page_size)
        analysis = _analyze_copy_history(orders)
        return {"action": "copy_history", "count": len(orders), "analysis": analysis, "orders": _format_copy_orders(orders)}

    elif action == "copy_settings":
        data = client.get_copy_trading_settings()
        return {"action": "copy_settings", "data": data}

    elif action == "trader_summary":
        if not trader_id:
            return {"error": "trader_id is required for trader_summary"}
        data = client.get_trader_profit_summary(trader_id)
        return {"action": "trader_summary", "trader_id": trader_id, "data": data}

    elif action == "trader_positions":
        if not trader_id:
            return {"error": "trader_id is required for trader_positions"}
        positions = client.get_trader_current_orders(trader_id, page_size=page_size)
        return {"action": "trader_positions", "trader_id": trader_id, "count": len(positions), "positions": _format_copy_orders(positions)}

    elif action == "trader_history":
        if not trader_id:
            return {"error": "trader_id is required for trader_history"}
        orders = client.get_trader_history_orders(trader_id, page_size=page_size)
        analysis = _analyze_copy_history(orders)
        return {"action": "trader_history", "trader_id": trader_id, "count": len(orders), "analysis": analysis, "orders": _format_copy_orders(orders)}

    elif action == "ticker":
        if not symbol:
            return {"error": "symbol is required for ticker"}
        data = client.get_ticker(symbol)
        return {"action": "ticker", "symbol": symbol, "data": data}

    elif action == "klines":
        if not symbol:
            return {"error": "symbol is required for klines"}
        data = client.get_klines(symbol)
        return {"action": "klines", "symbol": symbol, "count": len(data), "candles": data[:20]}

    elif action == "full_report":
        return _generate_full_report(client, trader_id, page_size)

    else:
        return {"error": f"Unknown action: {action}. Valid actions: account, positions, position_detail, copy_current, copy_history, copy_settings, trader_summary, trader_positions, trader_history, ticker, klines, full_report"}


def _format_positions(positions: list[dict]) -> list[dict]:
    """Normalize position data for readability."""
    formatted = []
    for p in positions:
        formatted.append({
            "symbol": p.get("symbol", ""),
            "side": p.get("holdSide", p.get("posSide", "")),
            "size": p.get("total", p.get("holdAmount", "")),
            "leverage": p.get("leverage", ""),
            "entry_price": p.get("openPriceAvg", p.get("averageOpenPrice", "")),
            "mark_price": p.get("markPrice", ""),
            "unrealized_pnl": p.get("unrealizedPL", p.get("unrealizedPnl", "")),
            "margin": p.get("margin", ""),
            "liquidation_price": p.get("liquidationPrice", ""),
            "take_profit": p.get("takeProfitPrice", ""),
            "stop_loss": p.get("stopLossPrice", ""),
            "created": _ts_to_iso(p.get("cTime", p.get("openTime"))),
        })
    return formatted


def _format_copy_orders(orders: list[dict]) -> list[dict]:
    """Normalize copy trading order data."""
    formatted = []
    for o in orders:
        formatted.append({
            "symbol": o.get("symbol", ""),
            "side": o.get("posSide", o.get("holdSide", "")),
            "size": o.get("openSize", o.get("holdAmount", "")),
            "leverage": o.get("leverage", ""),
            "open_price": o.get("openPrice", o.get("openPriceAvg", "")),
            "close_price": o.get("closePrice", ""),
            "pnl": o.get("achievedProfits", o.get("profit", o.get("netProfit", ""))),
            "open_time": _ts_to_iso(o.get("openTime", o.get("cTime"))),
            "close_time": _ts_to_iso(o.get("closeTime", o.get("uTime"))),
            "trader_id": o.get("traderId", ""),
        })
    return formatted


def _analyze_copy_history(orders: list[dict]) -> dict:
    """Compute performance metrics from historical copy orders."""
    if not orders:
        return {"total_trades": 0, "message": "No historical orders found"}

    total = len(orders)
    wins = 0
    losses = 0
    total_pnl = 0.0
    total_profit = 0.0
    total_loss = 0.0
    symbols: dict[str, int] = {}
    sides: dict[str, int] = {}
    holding_times: list[float] = []

    for o in orders:
        pnl_raw = o.get("achievedProfits", o.get("profit", o.get("netProfit", "0")))
        try:
            pnl = float(pnl_raw)
        except (ValueError, TypeError):
            pnl = 0.0

        total_pnl += pnl
        if pnl > 0:
            wins += 1
            total_profit += pnl
        elif pnl < 0:
            losses += 1
            total_loss += abs(pnl)

        sym = o.get("symbol", "UNKNOWN")
        symbols[sym] = symbols.get(sym, 0) + 1

        side = o.get("posSide", o.get("holdSide", "unknown"))
        sides[side] = sides.get(side, 0) + 1

        open_ts = o.get("openTime", o.get("cTime"))
        close_ts = o.get("closeTime", o.get("uTime"))
        if open_ts and close_ts:
            try:
                hold_hours = (int(close_ts) - int(open_ts)) / 3_600_000
                if hold_hours >= 0:
                    holding_times.append(hold_hours)
            except (ValueError, TypeError):
                pass

    win_rate = (wins / total * 100) if total > 0 else 0
    avg_win = (total_profit / wins) if wins > 0 else 0
    avg_loss = (total_loss / losses) if losses > 0 else 0
    profit_factor = (total_profit / total_loss) if total_loss > 0 else float("inf")
    avg_holding_hours = (sum(holding_times) / len(holding_times)) if holding_times else 0

    return {
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "breakeven": total - wins - losses,
        "win_rate_pct": round(win_rate, 2),
        "total_pnl_usdt": round(total_pnl, 4),
        "total_profit_usdt": round(total_profit, 4),
        "total_loss_usdt": round(total_loss, 4),
        "avg_win_usdt": round(avg_win, 4),
        "avg_loss_usdt": round(avg_loss, 4),
        "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else "inf",
        "avg_holding_hours": round(avg_holding_hours, 2),
        "symbols_traded": symbols,
        "side_distribution": sides,
        "estimated_30pct_profit_share_usdt": round(total_profit * 0.30, 4) if total_profit > 0 else 0,
    }


def _generate_full_report(client, trader_id: str, page_size: int) -> dict:
    """Pull everything and produce a comprehensive analysis report."""
    report: dict = {"action": "full_report"}

    # Account overview
    try:
        report["account"] = client.get_futures_account()
    except Exception as e:
        report["account_error"] = str(e)

    # Current positions
    try:
        positions = client.get_open_positions()
        report["open_positions"] = {"count": len(positions), "positions": _format_positions(positions)}
    except Exception as e:
        report["positions_error"] = str(e)

    # Copy trading current orders
    try:
        current = client.get_copy_trading_current_orders(page_size=page_size)
        report["copy_current"] = {"count": len(current), "orders": _format_copy_orders(current)}
    except Exception as e:
        report["copy_current_error"] = str(e)

    # Copy trading history + analysis
    try:
        history = client.get_copy_trading_history_orders(page_size=page_size)
        report["copy_history"] = {
            "count": len(history),
            "analysis": _analyze_copy_history(history),
            "orders": _format_copy_orders(history),
        }
    except Exception as e:
        report["copy_history_error"] = str(e)

    # Copy settings
    try:
        report["copy_settings"] = client.get_copy_trading_settings()
    except Exception as e:
        report["copy_settings_error"] = str(e)

    # Trader info (if provided)
    if trader_id:
        try:
            report["trader_summary"] = client.get_trader_profit_summary(trader_id)
        except Exception as e:
            report["trader_summary_error"] = str(e)

        try:
            trader_hist = client.get_trader_history_orders(trader_id, page_size=page_size)
            report["trader_analysis"] = {
                "count": len(trader_hist),
                "analysis": _analyze_copy_history(trader_hist),
            }
        except Exception as e:
            report["trader_analysis_error"] = str(e)

    return report
