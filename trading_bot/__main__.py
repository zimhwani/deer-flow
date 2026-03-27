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

# Load .env from the trading_bot directory (if present)
_env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_env_path):
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_path)
    except ImportError:
        # Fallback: parse manually if python-dotenv not installed
        with open(_env_path) as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _, _v = _line.partition("=")
                    os.environ.setdefault(_k.strip(), _v.strip())

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
