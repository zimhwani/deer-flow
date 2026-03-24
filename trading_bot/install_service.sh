#!/usr/bin/env bash
# Install the trading bot as a systemd service so it runs 24/7 and
# restarts automatically after reboots or crashes.
#
# Usage:
#   chmod +x install_service.sh
#   ./install_service.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="deriv-trading-bot"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
PYTHON="$SCRIPT_DIR/.venv/bin/python"

# ── Ensure .env exists ──────────────────────────────────────────────────────
if [[ ! -f "$SCRIPT_DIR/.env" ]]; then
    echo "ERROR: $SCRIPT_DIR/.env not found."
    echo "Run: cp .env.example .env  and set your DERIV_API_TOKEN first."
    exit 1
fi

# ── Ensure venv + deps are installed ────────────────────────────────────────
if [[ ! -f "$PYTHON" ]]; then
    echo "Setting up virtual environment..."
    python3 -m venv "$SCRIPT_DIR/.venv"
fi
"$PYTHON" -m pip install -q -r "$SCRIPT_DIR/requirements.txt"

mkdir -p "$SCRIPT_DIR/data"

# ── Write systemd service file ───────────────────────────────────────────────
echo "Writing $SERVICE_FILE (requires sudo)..."
sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=Deriv.com Automated Trading Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$(dirname "$SCRIPT_DIR")
EnvironmentFile=$SCRIPT_DIR/.env
ExecStart=$PYTHON -m trading_bot
Restart=always
RestartSec=15
StandardOutput=append:$SCRIPT_DIR/data/bot.log
StandardError=append:$SCRIPT_DIR/data/bot.log

[Install]
WantedBy=multi-user.target
EOF

# ── Enable and start ─────────────────────────────────────────────────────────
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

echo ""
echo "Service installed and started!"
echo ""
echo "Useful commands:"
echo "  View live logs:  journalctl -u $SERVICE_NAME -f"
echo "  Check status:    systemctl status $SERVICE_NAME"
echo "  Stop bot:        sudo systemctl stop $SERVICE_NAME"
echo "  Disable on boot: sudo systemctl disable $SERVICE_NAME"
