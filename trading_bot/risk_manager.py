"""
Risk Manager
Protects the $100 portfolio with strict position sizing and daily loss limits.
"""

import json
import logging
import os
from datetime import date, datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class RiskManager:
    """
    Controls trading risk to protect capital.

    Key rules for a $100 AU portfolio:
    - Max 2% risk per trade → max $2 stake per trade
    - Max 3 open positions simultaneously
    - Stop trading if daily loss exceeds 10% ($10)
    - Pause trading if daily profit target hit (3% = $3)
    - Never trade with money needed to cover existing positions
    """

    def __init__(
        self,
        starting_balance: float,
        max_risk_per_trade_pct: float = 2.0,
        max_daily_loss_pct: float = 10.0,
        max_open_positions: int = 3,
        daily_profit_target_pct: float = 3.0,
        data_dir: str = "./data",
    ):
        self.starting_balance = starting_balance
        self.max_risk_per_trade_pct = max_risk_per_trade_pct
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_open_positions = max_open_positions
        self.daily_profit_target_pct = daily_profit_target_pct
        self.data_dir = data_dir

        self._open_positions: Dict[int, Dict] = {}  # contract_id → trade info
        self._daily_pnl: float = 0.0
        self._today: date = date.today()
        self._trade_log: List[Dict] = []
        self._session_start_balance: float = starting_balance
        self._current_balance: float = starting_balance
        self._last_cooldown_trigger_losses: int = 0

        os.makedirs(data_dir, exist_ok=True)
        self._load_state()

    # ---- State persistence ----

    def _state_path(self) -> str:
        return os.path.join(self.data_dir, "risk_state.json")

    def _load_state(self) -> None:
        path = self._state_path()
        if os.path.exists(path):
            try:
                with open(path) as f:
                    state = json.load(f)
                saved_date = date.fromisoformat(state.get("date", str(date.today())))
                if saved_date == date.today():
                    self._daily_pnl = state.get("daily_pnl", 0.0)
                    self._trade_log = state.get("trade_log", [])
                    # Restore open positions as a dict keyed by contract_id
                    saved_open = state.get("open_positions", [])
                    self._open_positions = {
                        int(p["contract_id"]): p for p in saved_open
                    }
                    if self._open_positions:
                        logger.info(f"Restored {len(self._open_positions)} open position(s) from state")
                    self._last_cooldown_trigger_losses = state.get("last_cooldown_trigger_losses", 0)
                    logger.info(f"Resumed session | Daily P&L: {self._daily_pnl:+.2f} AUD")
                else:
                    logger.info("New trading day - resetting daily P&L")
            except Exception as e:
                logger.warning(f"Could not load risk state: {e}")

    def update_balance(self, balance: float) -> None:
        """Update the current account balance and persist it."""
        self._current_balance = balance
        self._save_state()

    def _save_state(self) -> None:
        state = {
            "date": str(date.today()),
            "daily_pnl": self._daily_pnl,
            "balance": self._current_balance,
            "trade_log": self._trade_log[-100:],
            "open_positions": list(self._open_positions.values()),
            "last_cooldown_trigger_losses": self._last_cooldown_trigger_losses,
        }
        with open(self._state_path(), "w") as f:
            json.dump(state, f, indent=2)

    # ---- Daily reset ----

    def _check_new_day(self) -> None:
        today = date.today()
        if today != self._today:
            logger.info(f"New day {today} | Yesterday P&L: {self._daily_pnl:+.2f} AUD")
            self._daily_pnl = 0.0
            self._today = today
            self._save_state()

    # ---- Position sizing ----

    def calculate_stake(self, balance: float) -> float:
        """
        Calculate the stake size for a new trade.
        Stakes 1.5% of current balance, minimum $1.00, maximum max_risk_per_trade_pct%.
        """
        max_stake = balance * (self.max_risk_per_trade_pct / 100)
        stake = balance * 0.015
        stake = min(stake, max_stake)
        stake = max(stake, 1.0)  # minimum stake $1
        return round(stake, 2)

    # ---- Trading permission checks ----

    def can_trade(self, balance: float) -> tuple[bool, str]:
        """Check if trading is allowed right now."""
        self._check_new_day()

        # Daily loss limit (based on current balance, not hardcoded starting balance)
        loss_limit = self._current_balance * (self.max_daily_loss_pct / 100)
        if self._daily_pnl <= -loss_limit:
            return False, f"Daily loss limit reached ({self._daily_pnl:.2f} AUD). Stopping for today."

        # Open position limit
        if len(self._open_positions) >= self.max_open_positions:
            return False, f"Max open positions reached ({len(self._open_positions)}/{self.max_open_positions})"

        # Minimum balance check
        if balance < 1.0:
            return False, f"Balance too low: {balance:.2f} AUD"

        return True, "OK"

    # ---- Position tracking ----

    def register_trade(
        self,
        contract_id: int,
        contract_type: str,
        symbol: str,
        stake: float,
        payout: float,
        buy_price: float,
    ) -> None:
        """Record a newly opened trade."""
        self._open_positions[contract_id] = {
            "contract_id": contract_id,
            "contract_type": contract_type,
            "symbol": symbol,
            "stake": stake,
            "payout": payout,
            "buy_price": buy_price,
            "opened_at": datetime.utcnow().isoformat(),
        }
        self._save_state()
        logger.info(
            f"Trade registered #{contract_id} | {contract_type} {symbol} | "
            f"Stake: {stake:.2f} | Payout: {payout:.2f}"
        )

    def close_trade(
        self,
        contract_id: int,
        sell_price: float,
        profit: Optional[float] = None,
    ) -> Optional[float]:
        """Record a closed trade and update P&L."""
        trade = self._open_positions.pop(contract_id, None)
        if not trade:
            return None

        if profit is None:
            profit = sell_price - trade["buy_price"]

        self._daily_pnl += profit
        trade["closed_at"] = datetime.utcnow().isoformat()
        trade["sell_price"] = sell_price
        trade["profit"] = profit
        self._trade_log.append(trade)
        self._save_state()

        result = "WIN" if profit > 0 else "LOSS"
        logger.info(
            f"Trade closed #{contract_id} | {result} | "
            f"Profit: {profit:+.2f} AUD | Daily P&L: {self._daily_pnl:+.2f} AUD"
        )
        return profit

    def get_open_positions(self) -> Dict:
        return dict(self._open_positions)

    def get_daily_pnl(self) -> float:
        return self._daily_pnl

    def get_consecutive_losses(self) -> int:
        """Count how many of the most recent closed trades were losses."""
        count = 0
        for trade in reversed(self._trade_log):
            if trade.get("profit", 0) < 0:
                count += 1
            else:
                break
        return count

    def get_rolling_win_rate(self, n: int = 20) -> Optional[float]:
        """Return win rate over the last n closed trades, or None if fewer than n trades."""
        if len(self._trade_log) < n:
            return None
        window = self._trade_log[-n:]
        wins = sum(1 for t in window if t.get("profit", 0) > 0)
        return wins / n

    def get_last_cooldown_trigger_losses(self) -> int:
        return self._last_cooldown_trigger_losses

    def set_last_cooldown_trigger_losses(self, value: int) -> None:
        self._last_cooldown_trigger_losses = value
        self._save_state()

    def get_last_trade_time(self):
        """Return the opened_at timestamp of the most recent trade, or None."""
        if not self._open_positions and not self._trade_log:
            return None
        # Check most recent open position
        if self._open_positions:
            times = [p.get("opened_at") for p in self._open_positions.values() if p.get("opened_at")]
            if times:
                return max(times)
        # Fall back to last closed trade
        if self._trade_log:
            return self._trade_log[-1].get("opened_at")

    def get_stats(self) -> Dict:
        """Return current session statistics."""
        trades = self._trade_log
        wins = [t for t in trades if t.get("profit", 0) > 0]
        losses = [t for t in trades if t.get("profit", 0) <= 0]
        total_profit = sum(t.get("profit", 0) for t in trades)
        win_rate = len(wins) / len(trades) * 100 if trades else 0

        return {
            "total_trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate_pct": round(win_rate, 1),
            "total_profit_aud": round(total_profit, 2),
            "daily_pnl_aud": round(self._daily_pnl, 2),
            "open_positions": len(self._open_positions),
        }
