"""
Run the trading bot:
    python -m trading_bot
    python -m trading_bot --config config.json
"""

import asyncio
import argparse
import os
import sys

# Ensure parent dir is on path when run directly
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from trading_bot.bot import main

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deriv.com Trading Bot")
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to JSON config file (optional, env vars take precedence)",
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default=None,
        help="Trading symbol to use, e.g. R_25, R_50, R_75, R_100 (overrides config and env var)",
    )
    args = parser.parse_args()
    asyncio.run(main(args.config, symbol=args.symbol))
