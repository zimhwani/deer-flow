"""
Standalone Deriv trading bot.

Connects to Deriv via WebSocket, runs a trend-following EMA crossover
strategy, and manages trades automatically. No LLM or DeerFlow needed.

Usage:
    export DERIV_API_TOKEN="your_token"
    python3 bot.py                          # demo mode (default)
    python3 bot.py --live                   # live trading (real money)
    python3 bot.py --symbol R_100           # trade Volatility 100 Index
    python3 bot.py --stake 5 --duration 15  # $5 stake, 15-min contracts
"""

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone

from deriv_client import DerivBot
from strategy import get_signal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("bot")

# ── Defaults ────────────────────────────────────────────────────────

DEFAULT_SYMBOL = "R_100"        # Volatility 100 Index (24/7 synthetic)
DEFAULT_STAKE = 1.0             # $1 per trade
DEFAULT_DURATION = 5            # 5 minutes
DEFAULT_DURATION_UNIT = "m"     # minutes
DEFAULT_CANDLE_INTERVAL = 60    # 1-minute candles (seconds)
DEFAULT_CHECK_INTERVAL = 60     # check for signals every 60 seconds
DEFAULT_FAST_EMA = 8
DEFAULT_SLOW_EMA = 21


async def run_bot(
    api_token: str,
    app_id: str,
    symbol: str,
    stake: float,
    duration: int,
    duration_unit: str,
    candle_interval: int,
    check_interval: int,
    fast_ema: int,
    slow_ema: int,
    max_trades: int,
    dry_run: bool,
) -> None:
    bot = DerivBot(api_token=api_token, app_id=app_id)

    try:
        await bot.connect()
    except Exception as e:
        logger.error(f"Failed to connect: {e}")
        return

    balance = await bot.get_balance()
    logger.info(f"Balance: {balance['balance']} {balance['currency']}")
    logger.info(f"Strategy: EMA({fast_ema}/{slow_ema}) crossover on {symbol}")
    logger.info(f"Stake: ${stake} | Duration: {duration}{duration_unit} | Candle: {candle_interval}s")

    if dry_run:
        logger.info("*** DRY RUN MODE — no real trades will be placed ***")

    trades_taken = 0
    wins = 0
    losses = 0
    total_pnl = 0.0

    try:
        while max_trades == 0 or trades_taken < max_trades:
            # Check if we already have an open position
            portfolio = await bot.get_portfolio()
            has_open = any(p["symbol"] == symbol for p in portfolio)

            if has_open:
                logger.info(f"Position open on {symbol}, waiting...")
                await asyncio.sleep(check_interval)
                continue

            # Get candles and check for signal
            try:
                candles = await bot.get_candles(symbol, granularity=candle_interval, count=slow_ema + 10)
            except Exception as e:
                logger.warning(f"Failed to get candles: {e}")
                await asyncio.sleep(check_interval)
                continue

            signal = get_signal(candles, fast_period=fast_ema, slow_period=slow_ema)

            if signal is None:
                tick = await bot.get_tick(symbol)
                logger.info(f"No signal | {symbol} @ {tick.get('quote', 'N/A')} | Trades: {trades_taken} | PnL: ${total_pnl:.2f}")
                await asyncio.sleep(check_interval)
                continue

            # Execute trade
            logger.info(f"*** SIGNAL: {signal} on {symbol} — stake ${stake} for {duration}{duration_unit} ***")

            if dry_run:
                logger.info(f"[DRY RUN] Would buy {signal} on {symbol}")
                trades_taken += 1
                await asyncio.sleep(check_interval)
                continue

            try:
                result = await bot.buy(symbol, signal, stake, duration, duration_unit)
                contract_id = result["contract_id"]
                buy_price = result.get("buy_price", stake)
                logger.info(f"Bought: contract_id={contract_id} | buy_price={buy_price}")
                trades_taken += 1

                # Wait for contract to expire
                wait_seconds = _duration_to_seconds(duration, duration_unit) + 5
                logger.info(f"Waiting {wait_seconds}s for contract to settle...")
                await asyncio.sleep(wait_seconds)

                # Check result
                new_balance = await bot.get_balance()
                new_bal = new_balance["balance"]
                pnl = new_bal - (balance["balance"] + total_pnl)
                total_pnl += pnl

                if pnl > 0:
                    wins += 1
                    logger.info(f"WIN +${pnl:.2f} | Balance: {new_bal} | Record: {wins}W-{losses}L | Total PnL: ${total_pnl:.2f}")
                else:
                    losses += 1
                    logger.info(f"LOSS ${pnl:.2f} | Balance: {new_bal} | Record: {wins}W-{losses}L | Total PnL: ${total_pnl:.2f}")

            except Exception as e:
                logger.error(f"Trade failed: {e}")
                await asyncio.sleep(check_interval)

            await asyncio.sleep(check_interval)

    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    finally:
        logger.info(f"Session summary: {trades_taken} trades | {wins}W-{losses}L | PnL: ${total_pnl:.2f}")
        win_rate = (wins / trades_taken * 100) if trades_taken > 0 else 0
        logger.info(f"Win rate: {win_rate:.1f}%")
        saved = total_pnl * 0.30 if total_pnl > 0 else 0
        logger.info(f"Saved vs 30% copy trading fee: ${saved:.2f}")
        await bot.disconnect()


def _duration_to_seconds(duration: int, unit: str) -> int:
    multipliers = {"t": 2, "s": 1, "m": 60, "h": 3600, "d": 86400}
    return duration * multipliers.get(unit, 60)


def main() -> None:
    parser = argparse.ArgumentParser(description="Deriv Trading Bot — Trend Following EMA Crossover")
    parser.add_argument("--token", default=os.environ.get("DERIV_API_TOKEN", ""), help="Deriv API token (or set DERIV_API_TOKEN env var)")
    parser.add_argument("--app-id", default=os.environ.get("DERIV_APP_ID", "1089"), help="Deriv app ID")
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL, help=f"Trading symbol (default: {DEFAULT_SYMBOL})")
    parser.add_argument("--stake", type=float, default=DEFAULT_STAKE, help=f"Stake per trade in USD (default: {DEFAULT_STAKE})")
    parser.add_argument("--duration", type=int, default=DEFAULT_DURATION, help=f"Contract duration (default: {DEFAULT_DURATION})")
    parser.add_argument("--duration-unit", default=DEFAULT_DURATION_UNIT, choices=["t", "s", "m", "h", "d"], help="Duration unit")
    parser.add_argument("--candle-interval", type=int, default=DEFAULT_CANDLE_INTERVAL, help="Candle granularity in seconds (default: 60)")
    parser.add_argument("--check-interval", type=int, default=DEFAULT_CHECK_INTERVAL, help="Seconds between signal checks (default: 60)")
    parser.add_argument("--fast-ema", type=int, default=DEFAULT_FAST_EMA, help=f"Fast EMA period (default: {DEFAULT_FAST_EMA})")
    parser.add_argument("--slow-ema", type=int, default=DEFAULT_SLOW_EMA, help=f"Slow EMA period (default: {DEFAULT_SLOW_EMA})")
    parser.add_argument("--max-trades", type=int, default=0, help="Max trades before stopping (0 = unlimited)")
    parser.add_argument("--live", action="store_true", help="Live trading mode (default is dry run)")
    args = parser.parse_args()

    if not args.token:
        logger.error("No API token. Set DERIV_API_TOKEN or use --token")
        sys.exit(1)

    dry_run = not args.live

    asyncio.run(run_bot(
        api_token=args.token,
        app_id=args.app_id,
        symbol=args.symbol,
        stake=args.stake,
        duration=args.duration,
        duration_unit=args.duration_unit,
        candle_interval=args.candle_interval,
        check_interval=args.check_interval,
        fast_ema=args.fast_ema,
        slow_ema=args.slow_ema,
        max_trades=args.max_trades,
        dry_run=dry_run,
    ))


if __name__ == "__main__":
    main()
