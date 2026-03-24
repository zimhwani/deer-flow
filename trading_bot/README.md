# Deriv.com Automated Trading Bot

A 24/7 trading bot for [Deriv.com](https://deriv.com) that opens and closes positions automatically to build a stable portfolio starting from AU$100. No Docker required — runs with plain Python.

## Strategy

**RSI Mean-Reversion + Bollinger Band + EMA Trend Filter**

The bot trades **Volatility Synthetic Indices** (not real forex/stocks) — these run 24/7 and are ideal for automated trading with a small account.

| Indicator | Role |
|-----------|------|
| RSI(14) | Detects overbought/oversold momentum |
| Bollinger Bands(20) | Confirms price at extremes |
| EMA(10/20) | Trend direction filter |

**BUY (CALL):** RSI < 35 + price near lower BB + bullish EMA slope
**SELL (PUT):** RSI > 65 + price near upper BB + bearish EMA slope
No trade if confidence score < 60%.

## Risk Management

| Rule | Value |
|------|-------|
| Stake per trade | ~$1.50 (1.5% of balance) |
| Max stake | $2.00 (2% cap) |
| Max open positions | 3 |
| Daily stop-loss | 10% — stops trading for the day if hit |

Stakes grow automatically as the portfolio grows.

---

## Quick Start

### Requirements
- Python 3.12+ (check with `python3 --version`)
- A [Deriv.com](https://deriv.com) account set to **AUD** currency

### Step 1 — Get your API token

1. Log in to [app.deriv.com](https://app.deriv.com)
2. Go to **Account Settings → API Token**
3. Create a token with **Read** + **Trade** permissions
4. Copy the token

> **Tip:** Create a **demo account** first and use its token — the bot will trade with virtual money so you can test safely.

### Step 2 — Configure

```bash
cd trading_bot
cp .env.example .env
```

Open `.env` in any text editor and set:
```
DERIV_API_TOKEN=your_token_here
```

### Step 3 — Run

```bash
chmod +x run.sh
./run.sh
```

The script automatically creates a virtual environment, installs dependencies, and starts the bot. Press **Ctrl+C** to stop.

---

## Running 24/7 (without Docker)

### Option A — systemd service (Linux, recommended)

Installs the bot as a background service that starts on boot and restarts if it crashes:

```bash
chmod +x install_service.sh
./install_service.sh
```

Then manage it with:
```bash
journalctl -u deriv-trading-bot -f   # live logs
systemctl status deriv-trading-bot   # check status
sudo systemctl stop deriv-trading-bot    # stop
sudo systemctl disable deriv-trading-bot # remove from startup
```

### Option B — tmux (any Linux/Mac, no sudo needed)

```bash
# Install tmux if needed: sudo apt install tmux
tmux new-session -d -s trading './run.sh'

# Reconnect to see logs
tmux attach -t trading

# Detach (leave running): Ctrl+B then D
```

### Option C — screen

```bash
screen -S trading ./run.sh
# Detach: Ctrl+A then D
# Reattach: screen -r trading
```

### Option D — Windows

On Windows, run in a normal terminal:
```
trading_bot\run.bat
```
Or keep the terminal open and minimise it. To auto-start on login, add a shortcut to `run.bat` in your Startup folder (`Win+R` → `shell:startup`).

---

## Configuration Reference

All settings go in `trading_bot/.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `DERIV_API_TOKEN` | **required** | Your Deriv API token |
| `DERIV_APP_ID` | `1089` | Deriv app ID |
| `TRADING_CURRENCY` | `AUD` | Account currency |
| `TRADING_STARTING_BALANCE` | `100.0` | Starting balance (for risk sizing) |
| `TRADING_SYMBOL` | `R_10` | Symbol to trade |
| `TRADING_DURATION` | `5` | Contract duration (minutes) |
| `TRADING_MAX_RISK_PCT` | `2.0` | Max % of balance per trade |
| `TRADING_MAX_DAILY_LOSS_PCT` | `10.0` | Stop trading if down this % today |
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
├── __main__.py          # Entry point
├── bot.py               # Main orchestrator
├── config.py            # Configuration loading
├── deriv_client.py      # Deriv WebSocket API client
├── risk_manager.py      # Position sizing, daily limits, P&L tracking
├── strategy.py          # RSI + BB + EMA trading signals
├── requirements.txt     # Python dependencies
├── run.sh               # Start script (Linux/Mac)
├── install_service.sh   # Install as systemd service (Linux)
├── .env.example         # Config template
└── data/                # Created automatically
    ├── bot.log          # Full trade log
    └── risk_state.json  # Daily P&L (persists across restarts)
```

## Disclaimers

- **This bot trades real money.** Always test on a demo account first.
- Synthetic indices are derivatives — you can lose your stake on each trade.
- Past performance does not guarantee future results.
