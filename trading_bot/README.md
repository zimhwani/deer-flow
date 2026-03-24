# Deriv.com Automated Trading Bot

A 24/7 trading bot for [Deriv.com](https://deriv.com) that opens and closes positions automatically to build a stable portfolio starting from AU$100.

## Strategy

**RSI Mean-Reversion + Bollinger Band + EMA Trend Filter**

The bot trades **Volatility Synthetic Indices** (not real forex/stocks) — these run 24/7 and are ideal for automated trading with a small account.

| Indicator | Role |
|-----------|------|
| RSI(14) | Detects overbought/oversold momentum |
| Bollinger Bands(20) | Confirms price at extremes |
| EMA(10/20) | Trend direction filter |

**Entry rules (BUY/CALL):**
- RSI < 35 (oversold)
- Price near/below lower Bollinger Band
- EMA trend is bullish (EMA sloping up)

**Entry rules (SELL/PUT):**
- RSI > 65 (overbought)
- Price near/above upper Bollinger Band
- EMA trend is bearish

**No trade** if confidence score < 60%.

## Risk Management

| Rule | Value |
|------|-------|
| Stake per trade | 1.5% of balance (~$1.50 on $100) |
| Max risk per trade | 2% of balance |
| Max open positions | 3 |
| Daily loss limit | 10% ($10 on $100 start) |
| Daily profit target | 3% — bot pauses after hitting this |

The bot **never risks more than $2 per trade** on a $100 account. Positions size up automatically as the portfolio grows.

## Quick Start

### Prerequisites
- Python 3.12+
- A [Deriv.com](https://deriv.com) account with AUD currency
- An API token with **Read** and **Trade** permissions

### 1. Get Your API Token

1. Log in to [app.deriv.com](https://app.deriv.com)
2. Go to **Account Settings → API Token**
3. Create a token with **Read** + **Trade** permissions
4. Copy the token

### 2. Configure

```bash
cd trading_bot
cp .env.example .env
# Edit .env and set your DERIV_API_TOKEN
```

### 3. Run Locally

```bash
chmod +x run.sh
./run.sh
```

### 4. Run with Docker (Recommended for 24/7)

```bash
cd trading_bot

# Set your API token
export DERIV_API_TOKEN="your_token_here"

# Build and start
docker-compose up -d

# Watch logs
docker-compose logs -f

# Stop
docker-compose down
```

## Configuration Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `DERIV_API_TOKEN` | **required** | Your Deriv API token |
| `DERIV_APP_ID` | `1089` | Deriv app ID |
| `TRADING_CURRENCY` | `AUD` | Account currency |
| `TRADING_STARTING_BALANCE` | `100.0` | Starting balance (for risk calculations) |
| `TRADING_SYMBOL` | `R_10` | Symbol to trade |
| `TRADING_DURATION` | `5` | Contract duration (minutes) |
| `TRADING_MAX_RISK_PCT` | `2.0` | Max % of balance per trade |
| `TRADING_MAX_DAILY_LOSS_PCT` | `10.0` | Stop trading if down this % today |
| `TRADING_DAILY_TARGET_PCT` | `3.0` | Pause if up this % today |
| `TRADING_LOG_LEVEL` | `INFO` | Logging verbosity |

## Recommended Symbols

| Symbol | Name | Volatility | Best for |
|--------|------|------------|---------|
| `R_10` | Volatility 10 Index | Lowest | Beginners, $100 accounts |
| `R_25` | Volatility 25 Index | Low-Medium | More trade signals |
| `R_50` | Volatility 50 Index | Medium | Experienced traders |

**Stick with R_10** for your $100 starting account.

## File Structure

```
trading_bot/
├── __init__.py
├── __main__.py        # Entry point
├── bot.py             # Main orchestrator (connect, loop, trade)
├── config.py          # Configuration loading
├── deriv_client.py    # Deriv WebSocket API client
├── risk_manager.py    # Position sizing, daily limits, P&L tracking
├── strategy.py        # RSI + BB + EMA trading signals
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── run.sh
```

## Data & Logs

The bot stores state in `./data/`:
- `bot.log` — full trading log
- `risk_state.json` — daily P&L and trade history (persists across restarts)

## Important Disclaimers

- **This bot trades real money.** Test on a Deriv **demo account** first.
- Synthetic indices are **derivatives** — you can lose your stake on each trade.
- Past performance does not guarantee future results.
- Start with the **demo account** by using a demo API token.
- The 3% daily target and 10% daily stop-loss are conservative defaults — adjust to your risk tolerance.

## Demo Account Testing

Deriv provides free demo accounts with virtual funds. To test:
1. Create a demo account at [app.deriv.com](https://app.deriv.com)
2. Generate an API token for the **demo** account
3. Run the bot — all trades will be virtual until you switch to a real account token
