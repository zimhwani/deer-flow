#!/usr/bin/env bash
# Quick-start script for the Deriv Trading Bot (no Docker required)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Load .env if it exists
if [[ -f ".env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
    echo "Loaded .env"
else
    echo "No .env file found. Copy .env.example to .env and fill in your API token."
    echo "  cp .env.example .env"
    exit 1
fi

if [[ -z "${DERIV_API_TOKEN:-}" ]]; then
    echo "DERIV_API_TOKEN is not set in .env"
    exit 1
fi

mkdir -p ./data

# Install dependencies into a virtual environment
if [[ ! -d ".venv" ]]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

echo "Installing dependencies..."
.venv/bin/pip install -q -r requirements.txt

echo ""
echo "Starting Deriv Trading Bot..."
echo "  Symbol:   ${TRADING_SYMBOL:-R_10}"
echo "  Balance:  ${TRADING_STARTING_BALANCE:-100} AUD"
echo "  Max Risk: ${TRADING_MAX_RISK_PCT:-2}% per trade"
echo "  Logs:     ./data/bot.log"
echo ""
echo "Press Ctrl+C to stop."
echo ""

cd ..
"$SCRIPT_DIR/.venv/bin/python" -m trading_bot "$@"
