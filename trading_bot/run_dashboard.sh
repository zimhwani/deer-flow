#!/usr/bin/env bash
# Run the trading bot dashboard
set -e
cd "$(dirname "$0")"

# Load .env if present
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi

# Activate venv if present
if [ -f .venv/bin/activate ]; then
  source .venv/bin/activate
fi

PORT="${DASHBOARD_PORT:-8080}"
echo "Starting dashboard on http://localhost:${PORT}"
python -m trading_bot.dashboard "$@"
