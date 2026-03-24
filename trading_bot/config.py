"""
Deriv.com Trading Bot - Configuration
All settings are controlled via environment variables or config.json.
"""

import os
import json
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TradingConfig:
    # Deriv API settings
    api_token: str = ""
    app_id: str = "1089"                # Deriv default app_id for testing
    ws_url: str = "wss://ws.derivws.com/websockets/v3"

    # Account settings
    currency: str = "AUD"
    starting_balance: float = 100.0

    # Risk management
    max_risk_per_trade_pct: float = 2.0     # Max 2% of balance per trade
    max_daily_loss_pct: float = 10.0        # Stop trading if down 10% today
    max_open_positions: int = 3             # Max concurrent trades
    risk_reward_ratio: float = 2.0          # Target 1:2 risk/reward

    # Strategy settings
    symbol: str = "R_10"                    # Volatility 10 Index (low volatility synthetic)
    contract_type: str = "CALL"             # CALL/PUT
    duration: int = 5                       # Contract duration in minutes
    duration_unit: str = "m"               # m=minutes, t=ticks, s=seconds, h=hours, d=days

    # Portfolio targets
    daily_profit_target_pct: float = 3.0   # Take a break if up 3% today
    weekly_profit_target_pct: float = 10.0 # Weekly target

    # Operational settings
    polling_interval_seconds: float = 30.0  # How often to check for signals
    reconnect_delay_seconds: float = 5.0
    max_reconnect_attempts: int = 20
    log_level: str = "INFO"
    data_dir: str = "./data"


def load_config(config_path: Optional[str] = None) -> TradingConfig:
    """Load configuration from environment variables and optional JSON file."""
    cfg = TradingConfig()

    # Load from JSON file if provided
    if config_path and os.path.exists(config_path):
        with open(config_path) as f:
            data = json.load(f)
        for key, val in data.items():
            if hasattr(cfg, key):
                setattr(cfg, key, val)

    # Environment variables override file settings
    env_map = {
        "DERIV_API_TOKEN": "api_token",
        "DERIV_APP_ID": "app_id",
        "DERIV_WS_URL": "ws_url",
        "TRADING_CURRENCY": "currency",
        "TRADING_STARTING_BALANCE": "starting_balance",
        "TRADING_SYMBOL": "symbol",
        "TRADING_DURATION": "duration",
        "TRADING_MAX_RISK_PCT": "max_risk_per_trade_pct",
        "TRADING_MAX_DAILY_LOSS_PCT": "max_daily_loss_pct",
        "TRADING_DAILY_TARGET_PCT": "daily_profit_target_pct",
        "TRADING_LOG_LEVEL": "log_level",
        "TRADING_DATA_DIR": "data_dir",
    }

    for env_var, attr in env_map.items():
        val = os.environ.get(env_var)
        if val is not None:
            current = getattr(cfg, attr)
            if isinstance(current, float):
                setattr(cfg, attr, float(val))
            elif isinstance(current, int):
                setattr(cfg, attr, int(val))
            else:
                setattr(cfg, attr, val)

    return cfg
