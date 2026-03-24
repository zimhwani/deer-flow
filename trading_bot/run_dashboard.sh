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
echo "Starting dashboard on http://localhost:${PORT}"

# Run dashboard.py directly (avoids module resolution issues)
python dashboard.py "$@"
