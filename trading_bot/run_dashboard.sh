#!/usr/bin/env bash
# Run the trading bot dashboard
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Load .env if present
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

# Activate venv if present
if [ -f .venv/bin/activate ]; then
  source .venv/bin/activate
fi

PORT="${DASHBOARD_PORT:-8080}"

# The bot runs from the parent deer-flow/ dir so data lands in ../data/
export TRADING_DATA_DIR="${TRADING_DATA_DIR:-../data}"

echo "Starting dashboard on http://localhost:${PORT}"
echo "Reading bot data from: $(cd "$TRADING_DATA_DIR" 2>/dev/null && pwd || echo "$TRADING_DATA_DIR (not found yet)")"

# Run dashboard.py directly (avoids module resolution issues)
python dashboard.py "$@"
