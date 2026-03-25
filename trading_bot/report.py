"""
Quick performance report — paste output to Claude for analysis.
Usage: python3 report.py
"""
import json
import os
from datetime import datetime

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(_SCRIPT_DIR, "data", "risk_state.json")


def load():
    with open(STATE_FILE) as f:
        return json.load(f)


def report():
    try:
        state = load()
    except FileNotFoundError:
        print("No data file found. Has the bot run yet?")
        return

    trades = state.get("trade_log", [])
    open_pos = state.get("open_positions", [])
    balance = state.get("balance", 0)
    daily_pnl = state.get("daily_pnl", 0)
    date = state.get("date", "unknown")

    wins = [t for t in trades if t.get("profit", 0) > 0]
    losses = [t for t in trades if t.get("profit", 0) <= 0]
    total_profit = sum(t.get("profit", 0) for t in trades)
    win_rate = len(wins) / len(trades) * 100 if trades else 0

    avg_win = sum(t["profit"] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t["profit"] for t in losses) / len(losses) if losses else 0
    best = max((t.get("profit", 0) for t in trades), default=0)
    worst = min((t.get("profit", 0) for t in trades), default=0)
    profit_factor = (
        abs(sum(t["profit"] for t in wins) / sum(t["profit"] for t in losses))
        if losses and sum(t["profit"] for t in losses) != 0
        else float("inf")
    )

    print("=" * 50)
    print(f"  TRADING BOT PERFORMANCE REPORT")
    print(f"  Date: {date}   Generated: {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 50)
    print(f"  Balance:        ${balance:.2f}")
    print(f"  Daily P&L:      ${daily_pnl:+.2f}")
    print(f"  Total Profit:   ${total_profit:+.2f}")
    print("-" * 50)
    print(f"  Total Trades:   {len(trades)}")
    print(f"  Wins:           {len(wins)}")
    print(f"  Losses:         {len(losses)}")
    print(f"  Win Rate:       {win_rate:.1f}%")
    print(f"  Profit Factor:  {profit_factor:.2f}")
    print("-" * 50)
    print(f"  Avg Win:        ${avg_win:+.2f}")
    print(f"  Avg Loss:       ${avg_loss:+.2f}")
    print(f"  Best Trade:     ${best:+.2f}")
    print(f"  Worst Trade:    ${worst:+.2f}")
    print("-" * 50)
    print(f"  Open Positions: {len(open_pos)}")
    for p in open_pos:
        print(f"    #{p.get('contract_id')} {p.get('contract_type')} "
              f"stake={p.get('stake')} opened={p.get('opened_at','')[:19]}")
    print("-" * 50)
    print("  LAST 10 TRADES:")
    for t in trades[-10:][::-1]:
        result = "WIN " if t.get("profit", 0) > 0 else "LOSS"
        print(f"    {result} ${t.get('profit', 0):+.2f}  "
              f"{t.get('contract_type','')}  "
              f"closed={t.get('closed_at','')[:19]}")
    print("=" * 50)


if __name__ == "__main__":
    report()
