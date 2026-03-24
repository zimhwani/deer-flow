#!/usr/bin/env bash
# Quick-start script for the Deriv Trading Bot

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Load .env if it exists
if [[ -f ".env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
    echo "✓ Loaded .env"
else
    echo "⚠ No .env file found. Copy .env.example → .env and fill in your API token."
    echo "  cp .env.example .env"
    exit 1
fi

if [[ -z "${DERIV_API_TOKEN:-}" ]]; then
    echo "✗ DERIV_API_TOKEN is not set in .env"
    exit 1
fi

mkdir -p ./data

echo "Starting Deriv Trading Bot..."
echo "  Symbol:   ${TRADING_SYMBOL:-R_10}"
echo "  Balance:  ${TRADING_STARTING_BALANCE:-100} AUD"
echo "  Max Risk: ${TRADING_MAX_RISK_PCT:-2}% per trade"
echo ""

pip install -q -r requirements.txt

cd ..
python -m trading_bot "$@"
