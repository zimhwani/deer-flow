---
name: copy-trading-analysis
description: Analyze copy trading performance and execute independent trades on MT5 (Deriv). Use this skill when the user asks about their trading, wants to manage positions, analyze trade history, calculate risk, or transition from copy trading to independent trading. Also covers Bitget copy trade analysis for evaluating traders and profit share costs.
allowed-tools:
  - mt5_trade
  - bitget_copy_analysis
  - web_search
  - web_fetch
  - bash
  - write_file
  - read_file
---

# Copy Trading Analysis & MT5 Trading Skill

## Overview

This skill provides two integrated capabilities:
1. **MT5 Trading** — Trade independently on MetaTrader 5 (Deriv, Exness, IC Markets) with full position management, risk calculation, and performance analysis
2. **Bitget Copy Trade Analysis** — Pull and analyze copy trading data to understand what you're paying and whether the strategy is replicable

## When to Use This Skill

- User wants to place trades, check positions, or manage orders on MT5
- User asks about their trading performance or account status
- User wants to calculate position sizes based on risk percentage
- User asks about their copy trading costs on Bitget
- User wants to evaluate whether to keep following a trader vs trading independently
- User wants a breakdown of profit share fees vs independent trading savings

---

## MT5 Trading Tool

Use the `mt5_trade` tool. **Always confirm with the user before executing trade actions.**

### Read Actions (safe)

| Action | What It Does | Required Params |
|--------|-------------|-----------------|
| `account` | Balance, equity, margin, leverage | — |
| `positions` | All open positions | `symbol` (optional filter) |
| `history` | Closed trade history + analysis | `days_back` (default 30) |
| `symbol_info` | Symbol details (spread, min lot, contract size) | `symbol` |
| `tick` | Current bid/ask price | `symbol` |
| `calculate_lot` | Position size from risk % and SL | `symbol`, `risk_pct`, `sl_points` |
| `full_report` | Account + positions + history combined | `days_back` (optional) |

### Trade Actions (require user confirmation)

| Action | What It Does | Required Params |
|--------|-------------|-----------------|
| `market_order` | Place market buy/sell | `symbol`, `side`, `volume` + optional `sl`, `tp` |
| `limit_order` | Place pending limit order | `symbol`, `side`, `volume`, `price` + optional `sl`, `tp` |
| `modify` | Change SL/TP on position | `ticket`, `sl` and/or `tp` |
| `close` | Close position (full or partial) | `ticket`, `volume` (optional for partial) |
| `close_all` | Close all positions | `symbol` (optional filter) |

### Risk Management Workflow

Before placing any trade, calculate the proper lot size:

```
1. mt5_trade(action="tick", symbol="BTCUSD")           → Get current price
2. mt5_trade(action="symbol_info", symbol="BTCUSD")    → Get contract specs
3. mt5_trade(action="calculate_lot", symbol="BTCUSD", risk_pct=2.0, sl_points=500)  → Get lot size for 2% risk
4. Confirm with user: "Place sell 0.05 BTCUSD at market with SL at 75,000?"
5. mt5_trade(action="market_order", symbol="BTCUSD", side="sell", volume=0.05, sl=75000, tp=73000)
```

### Performance Analysis

Use `full_report` to get a comprehensive breakdown:

```
mt5_trade(action="full_report", days_back=30)
```

Key metrics returned in the analysis:
- **Win Rate** — Percentage of profitable closed trades
- **Profit Factor** — Total profit / Total loss (>1.5 is good, >2.0 is strong)
- **Expectancy** — Average profit per trade
- **Net PnL** — Gross PnL after commissions and swap
- **Savings vs 30% Copy** — How much you saved by trading independently vs paying 30% profit share

---

## Bitget Copy Trade Analysis Tool

Use the `bitget_copy_analysis` tool to evaluate your copy trading.

### Available Actions

| Action | What It Does | Required Params |
|--------|-------------|-----------------|
| `account` | Futures account balance & margin | — |
| `positions` | All open futures positions | — |
| `copy_current` | Open copy trading orders | — |
| `copy_history` | Historical copy orders + analysis | — |
| `copy_settings` | Copy trading configuration | — |
| `trader_summary` | Trader's public profit stats | `trader_id` |
| `trader_positions` | Trader's current open positions | `trader_id` |
| `trader_history` | Trader's historical orders + analysis | `trader_id` |
| `full_report` | Everything combined | `trader_id` (optional) |

---

## Combined Analysis Workflow

### Phase 1: Gather Data from Both Platforms

```
# MT5 independent trading performance
mt5_trade(action="full_report", days_back=30)

# Bitget copy trading performance (if still active)
bitget_copy_analysis(action="full_report", trader_id="<if known>")
```

### Phase 2: Compare Performance

Side-by-side comparison of:
1. **MT5 independent**: Net PnL, win rate, profit factor (100% profit retention)
2. **Bitget copy trading**: Gross PnL minus 30% profit share

### Phase 3: Strategy Assessment

From the copy trading history, assess replicability:
- **Entry Patterns** — Support/resistance, trend following, mean reversion?
- **Exit Patterns** — Fixed TP/SL, dynamic exits, scaling in/out?
- **Risk Management** — Position sizing, max concurrent positions, drawdown behavior?

### Phase 4: Recommendation

| Replicability | Recommendation |
|--------------|----------------|
| **High** (rule-based entries/exits) | Trade independently on MT5, save the 30% |
| **Medium** (discretionary with patterns) | Hybrid — copy trade + practice on MT5 demo |
| **Low** (pure discretion, news-based) | Keep copy trading — the 30% buys expertise |

## Output Format

```markdown
## Trading Analysis Report

### MT5 Account
- Balance, equity, leverage, free margin

### Open Positions
- Symbol, side, volume, entry, current PnL, TP/SL status

### Performance (Last 30 Days)
- Win rate, profit factor, net PnL, expectancy
- Commission + swap costs
- Savings vs 30% copy trading profit share

### Copy Trading Comparison (if applicable)
- Bitget gross PnL vs profit share paid
- MT5 net PnL (no share)
- Monthly savings from independent trading

### Risk Assessment
- Current exposure, margin usage
- Largest winning/losing trades
- Suggestions for improvement
```

## Important Notes

- MT5 tool requires MetaTrader 5 terminal running (Windows) with configured account
- Always use `calculate_lot` before placing trades to ensure proper risk management
- Never risk more than 2% per trade unless the user explicitly requests otherwise
- For Deriv MT5: symbol format is usually "BTCUSD" not "BTCUSDT"
- `savings_vs_30pct_copy` in the history analysis shows what 30% of gross profit would have been
