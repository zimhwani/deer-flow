"""
Deriv Trading Tools for DeerFlow.

Provides LangChain tools for trading on Deriv via their WebSocket API.
Works on any OS — no MT5 terminal needed.
"""

import json
import logging

from langchain.tools import tool

from deerflow.config import get_app_config

logger = logging.getLogger(__name__)


def _get_client():
    """Create a DerivClient from tool config."""
    from deerflow.community.deriv.client import DerivClient

    config = get_app_config().get_tool_config("deriv_trade")
    if config is None:
        raise ValueError("deriv_trade tool not configured in config.yaml. Add api_token.")
    extra = config.model_extra
    api_token = extra.get("api_token", "")
    app_id = extra.get("app_id", "1089")
    if not api_token:
        raise ValueError("Deriv API token not set. Get one at https://app.deriv.com/account/api-token and set api_token in config.yaml or $DERIV_API_TOKEN.")
    return DerivClient(api_token=api_token, app_id=str(app_id))


@tool("deriv_trade", parse_docstring=True)
def deriv_trade_tool(
    action: str,
    symbol: str = "",
    contract_type: str = "",
    amount: float = 0.0,
    duration: int = 0,
    duration_unit: str = "m",
    contract_id: str = "",
    price: float = 0.0,
    limit: int = 50,
    barrier: str = "",
) -> str:
    """Trade and analyze positions on Deriv. Works on any OS (Linux, Mac, Windows) via WebSocket API. For trade actions (buy, sell, sell_all), ALWAYS confirm with the user first.

    Args:
        action: One of: "balance" (account balance), "portfolio" (open positions), "profit_table" (trade history + analysis), "statement" (transaction log), "tick" (current price), "symbols" (list tradeable symbols), "proposal" (get price quote), "buy" (buy a contract), "sell" (close a position), "sell_all" (close all positions), "full_report" (everything combined).
        symbol: Trading symbol e.g. "R_100" (Volatility 100), "1HZ10V" (Volatility 10). Required for tick, proposal, buy.
        contract_type: Contract type for trading. Common types: "CALL" (rise/up), "PUT" (fall/down), "MULTUP" (multiplier up), "MULTDOWN" (multiplier down), "DIGITOVER", "DIGITUNDER".
        amount: Stake amount in USD for buying contracts.
        duration: Contract duration (e.g. 5 for 5 minutes). Required for proposal and buy.
        duration_unit: Duration unit: "t" (ticks), "s" (seconds), "m" (minutes), "h" (hours), "d" (days).
        contract_id: Contract ID for selling a specific position.
        price: Sell price (0 for market price). Used with sell action.
        limit: Number of records for profit_table and statement. Default 50.
        barrier: Optional barrier for certain contract types (e.g. "+0.5", "-1.0").
    """
    try:
        client = _get_client()
    except ValueError as e:
        return json.dumps({"error": str(e)})

    try:
        result = _dispatch(client, action, symbol, contract_type, amount, duration, duration_unit, contract_id, price, limit, barrier)
        return json.dumps(result, indent=2, ensure_ascii=False, default=str)
    except Exception as e:
        logger.exception("Deriv tool error")
        return json.dumps({"error": str(e)})


def _dispatch(client, action, symbol, contract_type, amount, duration, duration_unit, contract_id, price, limit, barrier) -> dict:
    barrier_val = barrier if barrier else None

    if action == "balance":
        return {"action": "balance", "data": client.get_balance()}

    elif action == "portfolio":
        positions = client.get_portfolio()
        total_profit = sum(p.get("profit") or 0 for p in positions)
        return {"action": "portfolio", "count": len(positions), "total_unrealized_pnl": round(total_profit, 2), "positions": positions}

    elif action == "profit_table":
        trades = client.get_profit_table(limit=limit)
        analysis = _analyze_profit_table(trades)
        return {"action": "profit_table", "count": len(trades), "analysis": analysis, "trades": trades}

    elif action == "statement":
        txns = client.get_statement(limit=limit)
        return {"action": "statement", "count": len(txns), "transactions": txns}

    elif action == "tick":
        if not symbol:
            return {"error": "symbol is required for tick"}
        return {"action": "tick", "data": client.get_tick(symbol)}

    elif action == "symbols":
        symbols = client.get_active_symbols()
        return {"action": "symbols", "count": len(symbols), "symbols": symbols}

    elif action == "proposal":
        if not symbol or not contract_type or amount <= 0 or duration <= 0:
            return {"error": "symbol, contract_type, amount (>0), and duration (>0) are required"}
        return {"action": "proposal", "data": client.get_proposal(symbol, contract_type, amount, duration, duration_unit, barrier=barrier_val)}

    elif action == "buy":
        if not symbol or not contract_type or amount <= 0 or duration <= 0:
            return {"error": "symbol, contract_type, amount (>0), and duration (>0) are required"}
        return {"action": "buy", "result": client.buy_contract(symbol, contract_type, amount, duration, duration_unit, barrier=barrier_val)}

    elif action == "sell":
        if not contract_id:
            return {"error": "contract_id is required for sell"}
        return {"action": "sell", "result": client.sell(contract_id, price=price)}

    elif action == "sell_all":
        results = client.sell_all()
        return {"action": "sell_all", "closed": len(results), "results": results}

    elif action == "full_report":
        return _generate_full_report(client, limit)

    else:
        return {"error": f"Unknown action: {action}. Use: balance, portfolio, profit_table, statement, tick, symbols, proposal, buy, sell, sell_all, full_report"}


def _analyze_profit_table(trades: list[dict]) -> dict:
    """Compute performance metrics from trade history."""
    if not trades:
        return {"total_trades": 0, "message": "No trades found"}

    total = len(trades)
    wins = 0
    losses = 0
    total_pnl = 0.0
    total_profit = 0.0
    total_loss = 0.0
    total_stake = 0.0

    for t in trades:
        pnl = t.get("profit_loss") or 0
        buy = t.get("buy_price") or 0
        total_pnl += pnl
        total_stake += buy

        if pnl > 0:
            wins += 1
            total_profit += pnl
        elif pnl < 0:
            losses += 1
            total_loss += abs(pnl)

    win_rate = (wins / total * 100) if total > 0 else 0
    avg_win = (total_profit / wins) if wins > 0 else 0
    avg_loss = (total_loss / losses) if losses > 0 else 0
    profit_factor = (total_profit / total_loss) if total_loss > 0 else float("inf")
    roi = (total_pnl / total_stake * 100) if total_stake > 0 else 0

    return {
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "breakeven": total - wins - losses,
        "win_rate_pct": round(win_rate, 2),
        "total_pnl": round(total_pnl, 2),
        "total_profit": round(total_profit, 2),
        "total_loss": round(total_loss, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else "inf",
        "total_staked": round(total_stake, 2),
        "roi_pct": round(roi, 2),
        "savings_vs_30pct_copy": round(total_profit * 0.30, 2) if total_profit > 0 else 0,
    }


def _generate_full_report(client, limit: int) -> dict:
    """Pull balance, portfolio, and history into one report."""
    report: dict = {"action": "full_report"}

    try:
        report["balance"] = client.get_balance()
    except Exception as e:
        report["balance_error"] = str(e)

    try:
        positions = client.get_portfolio()
        total_profit = sum(p.get("profit") or 0 for p in positions)
        report["portfolio"] = {"count": len(positions), "total_unrealized_pnl": round(total_profit, 2), "positions": positions}
    except Exception as e:
        report["portfolio_error"] = str(e)

    try:
        trades = client.get_profit_table(limit=limit)
        report["profit_table"] = {"count": len(trades), "analysis": _analyze_profit_table(trades)}
    except Exception as e:
        report["profit_table_error"] = str(e)

    return report
