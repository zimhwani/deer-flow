---
name: copy-trading-analysis
description: Analyze copy trading performance on Bitget. Use this skill when the user asks about their copy trading, wants to evaluate a trader they're following, or wants to understand if they could replicate a trader's strategy independently. Triggers on queries about copy trading, trader analysis, profit share costs, position tracking, or building independent trading strategies.
allowed-tools:
  - bitget_copy_analysis
  - web_search
  - web_fetch
  - bash
  - write_file
  - read_file
---

# Copy Trading Analysis Skill

## Overview

This skill uses the Bitget API to pull copy trading data and produce actionable analysis. It helps users understand what they're paying in profit share, whether the trader's strategy is replicable, and what patterns the trader follows.

## When to Use This Skill

- User asks about their copy trading performance or costs
- User wants to evaluate whether to keep following a trader
- User wants to analyze a trader's strategy, win rate, or patterns
- User asks about replicating a copy trading strategy independently
- User wants a breakdown of profit share fees vs returns

## Available Tool Actions

Use the `bitget_copy_analysis` tool with these actions:

| Action | What It Does | Required Params |
|--------|-------------|-----------------|
| `account` | Futures account balance & margin | — |
| `positions` | All open futures positions | — |
| `position_detail` | Specific symbol position | `symbol` |
| `copy_current` | Open copy trading orders | — |
| `copy_history` | Historical copy orders + analysis | — |
| `copy_settings` | Copy trading configuration | — |
| `trader_summary` | Trader's public profit stats | `trader_id` |
| `trader_positions` | Trader's current open positions | `trader_id` |
| `trader_history` | Trader's historical orders + analysis | `trader_id` |
| `ticker` | Current market price | `symbol` |
| `klines` | Recent candlestick data | `symbol` |
| `full_report` | Everything combined | `trader_id` (optional) |

## Analysis Workflow

### Phase 1: Data Collection

Start by pulling a full report to get the big picture:

```
bitget_copy_analysis(action="full_report", trader_id="<if known>")
```

This returns account info, open positions, copy trade history with analysis, and trader stats.

### Phase 2: Performance Metrics

From the copy history analysis, examine these key metrics:

1. **Win Rate** — Percentage of profitable trades
2. **Profit Factor** — Total profit / Total loss (>1.5 is good, >2.0 is strong)
3. **Average Win vs Average Loss** — Is the trader cutting losses and letting winners run?
4. **Holding Time** — Average duration of trades (scalper vs swing trader)
5. **Symbol Distribution** — Is the trader focused on one pair or diversified?
6. **Side Distribution** — Long-biased, short-biased, or balanced?

### Phase 3: Profit Share Cost Analysis

Calculate the real cost of the 30% profit share:

```
Total profit from copy trading: $X
30% profit share paid: $Y
Net profit after share: $X - $Y
Effective return vs gross: (X - Y) / X * 100%
```

Compare against:
- What the user would earn trading independently (100% retention, but higher risk)
- Whether the profit share is worth the convenience
- Break-even analysis: how much independent trading skill would offset the share

### Phase 4: Strategy Pattern Recognition

Analyze the trader's behavior to determine if their strategy is replicable:

1. **Entry Patterns**
   - Does the trader enter at specific price levels (support/resistance)?
   - Are entries correlated with market conditions (trend following vs mean reversion)?
   - What leverage does the trader consistently use?

2. **Exit Patterns**
   - Does the trader use fixed TP/SL or dynamic exits?
   - Average holding time — is this a scalping or swing strategy?
   - Does the trader scale in/out of positions?

3. **Risk Management**
   - Position sizing relative to account
   - Maximum concurrent positions
   - Drawdown behavior — does the trader add to losing positions?

4. **Replicability Assessment**
   - Simple (rule-based entries/exits) → High replicability
   - Moderate (discretionary with clear patterns) → Medium replicability  
   - Complex (pure discretion, news-based) → Low replicability

### Phase 5: Recommendations

Based on the analysis, provide:

1. **Continue Copy Trading** — If the strategy is complex, the trader has a strong edge, and the profit share is small relative to returns
2. **Build Your Own Bot** — If the strategy follows clear patterns that can be automated
3. **Hybrid Approach** — Continue copying while learning the patterns, gradually transition to independent trading
4. **Stop Copying** — If the trader's metrics are poor or deteriorating

## Output Format

Present findings in a structured report:

```markdown
## Copy Trading Analysis Report

### Account Overview
- Balance, margin, equity

### Active Copy Trades
- Current positions with entry, size, PnL

### Historical Performance
- Win rate, profit factor, PnL breakdown
- Profit share costs to date

### Trader Strategy Profile
- Entry/exit patterns identified
- Risk management approach
- Consistency metrics

### Replicability Assessment
- Score: High / Medium / Low
- Key patterns that could be automated
- What would be lost without the trader

### Recommendation
- Action: Continue / Build Bot / Hybrid / Stop
- Reasoning
- Next steps
```

## Important Notes

- Always present PnL in USDT with clear labels
- Account for funding fees and trading fees in cost analysis
- The `estimated_30pct_profit_share_usdt` field in history analysis shows the total profit share cost
- Trader IDs can be found in the Bitget app or web UI under the trader's profile
- This tool requires Bitget API credentials (api_key, api_secret, passphrase) configured in config.yaml
