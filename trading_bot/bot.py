"""
Deriv.com Trading Bot - Main Orchestrator
Runs 24/7, opening and closing positions based on strategy signals.
"""

import asyncio
import logging
import signal
import sys
from datetime import datetime
from typing import Optional

from websockets.exceptions import ConnectionClosed

from .config import TradingConfig, load_config
from .deriv_client import DerivClient
from .risk_manager import RiskManager
from .strategy import Signal, generate_signal

logger = logging.getLogger(__name__)


class TradingBot:
    """
    Main trading bot that:
    1. Connects to Deriv.com API
    2. Fetches market data on each cycle
    3. Runs strategy analysis
    4. Opens/closes positions based on signals + risk rules
    5. Reconnects automatically on disconnection
    """

    def __init__(self, config: TradingConfig):
        self.config = config
        self.client = DerivClient(
            api_token=config.api_token,
            app_id=config.app_id,
            account_id=config.account_id,
        )
        self.risk = RiskManager(
            starting_balance=config.starting_balance,
            max_risk_per_trade_pct=config.max_risk_per_trade_pct,
            max_daily_loss_pct=config.max_daily_loss_pct,
            max_open_positions=config.max_open_positions,
            daily_profit_target_pct=config.daily_profit_target_pct,
            data_dir=config.data_dir,
        )
        self._running = False
        self._balance: float = config.starting_balance
        self._cycle_count: int = 0

    async def start(self) -> None:
        """Start the bot with automatic reconnection."""
        self._running = True
        reconnect_attempts = 0

        logger.info("=" * 60)
        logger.info("  Deriv.com Trading Bot Starting")
        logger.info(f"  Symbol:    {self.config.symbol}")
        logger.info(f"  Currency:  {self.config.currency}")
        logger.info(f"  Max risk:  {self.config.max_risk_per_trade_pct}% per trade")
        logger.info(f"  Interval:  {self.config.polling_interval_seconds}s")
        logger.info("=" * 60)

        while self._running:
            try:
                await self._connect_and_run()
                reconnect_attempts = 0
            except Exception as e:
                if not self._running:
                    break
                reconnect_attempts += 1
                if reconnect_attempts > self.config.max_reconnect_attempts:
                    logger.error("Max reconnect attempts reached. Stopping bot.")
                    break
                delay = min(self.config.reconnect_delay_seconds * (2 ** min(reconnect_attempts, 5)), 300)
                logger.warning(
                    f"Connection error: {e}. "
                    f"Reconnecting in {delay:.0f}s (attempt {reconnect_attempts})"
                )
                await asyncio.sleep(delay)

    async def stop(self) -> None:
        """Gracefully stop the bot."""
        logger.info("Stopping trading bot...")
        self._running = False
        await self.client.disconnect()

    async def _on_contract_update(self, msg: dict) -> None:
        """Handle real-time contract settlement notifications."""
        data = msg.get("proposal_open_contract", {})
        contract_id = data.get("contract_id")
        status = data.get("status")

        if not contract_id or status not in ("won", "lost", "sold"):
            return

        if contract_id not in self.risk.get_open_positions():
            return

        sell_price = float(data.get("sell_price", 0))
        profit = float(data.get("profit", 0))
        self.risk.close_trade(contract_id, sell_price, profit)

        try:
            balance_info = await self.client.get_balance()
            self._balance = float(balance_info.get("balance", self._balance))
            self.risk.update_balance(self._balance)
        except Exception as e:
            logger.warning(f"Balance refresh failed after contract close: {e}")

    async def _connect_and_run(self) -> None:
        """Connect to Deriv and run the main trading loop."""
        await self.client.connect()

        if not self.config.api_token:
            raise ValueError(
                "DERIV_API_TOKEN is not set. "
                "Get your API token from https://app.deriv.com/account/api-token"
            )

        self.client.on("proposal_open_contract", self._on_contract_update)
        await self.client.authorize()
        balance_info = await self.client.get_balance()
        self._balance = float(balance_info.get("balance", self.config.starting_balance))
        self.risk.update_balance(self._balance)
        logger.info(f"Account balance: {self._balance:.2f} {self.config.currency}")

        # Start the main loop
        await self._trading_loop()

    async def _trading_loop(self) -> None:
        """Main trading loop - runs continuously."""
        logger.info("Entering trading loop...")

        while self._running and self.client.is_authorized:
            self._cycle_count += 1
            cycle_start = datetime.utcnow()

            try:
                await self._run_cycle()
            except (ConnectionClosed, ConnectionError, OSError) as e:
                logger.warning(f"Cycle {self._cycle_count}: connection lost ({e}), triggering reconnect")
                raise
            except Exception as e:
                logger.error(f"Cycle {self._cycle_count} error: {e}", exc_info=True)

            # Refresh balance periodically
            if self._cycle_count % 5 == 0:
                try:
                    balance_info = await self.client.get_balance()
                    self._balance = float(balance_info.get("balance", self._balance))
                    self.risk.update_balance(self._balance)
                except (ConnectionClosed, ConnectionError, OSError) as e:
                    logger.warning(f"Balance refresh: connection lost ({e}), triggering reconnect")
                    raise
                except Exception as e:
                    logger.warning(f"Balance refresh failed: {e}")

            # Print status every 10 cycles
            if self._cycle_count % 10 == 0:
                self._print_status()

            # Wait for next cycle
            elapsed = (datetime.utcnow() - cycle_start).total_seconds()
            wait = max(0, self.config.polling_interval_seconds - elapsed)
            await asyncio.sleep(wait)

    async def _run_cycle(self) -> None:
        """Single analysis and trade cycle."""
        # 1. Always check open positions first so expired contracts are settled
        await self._check_open_positions()

        # 2. Check if trading is permitted
        can_trade, reason = self.risk.can_trade(self._balance)
        if not can_trade:
            logger.info(f"Cycle {self._cycle_count}: Skipping - {reason}")
            return

        # 3. Fetch market data (5-minute candles, last 50)
        candles = await self.client.get_candles(
            symbol=self.config.symbol,
            granularity=300,   # 5-minute candles
            count=50,
        )

        if len(candles) < 30:
            logger.info(f"Cycle {self._cycle_count}: Insufficient candle data ({len(candles)})")
            return

        # 4. Generate signal
        signal = generate_signal(candles, self.config.symbol)
        logger.info(
            f"Cycle {self._cycle_count}: Signal={signal.signal.name} "
            f"Confidence={signal.confidence:.0%} | {signal.reason}"
        )

        # 5. Execute trade if signal is strong enough
        if signal.signal == Signal.HOLD or signal.confidence < 0.65:
            return

        # 6. Consecutive loss cooldown — skip 2 cycles after 2 losses in a row
        consecutive_losses = self.risk.get_consecutive_losses()
        if consecutive_losses >= 2:
            cooldown_cycles = consecutive_losses  # 2 losses → skip 2 cycles, 3 → skip 3, etc.
            if not hasattr(self, "_loss_cooldown_until"):
                self._loss_cooldown_until = 0
            if self._cycle_count <= self._loss_cooldown_until:
                logger.info(
                    f"Cycle {self._cycle_count}: Loss cooldown active "
                    f"({consecutive_losses} consecutive losses, cooling until cycle {self._loss_cooldown_until})"
                )
                return
            else:
                self._loss_cooldown_until = self._cycle_count + cooldown_cycles
                logger.info(f"Cycle {self._cycle_count}: {consecutive_losses} consecutive losses — cooldown set for {cooldown_cycles} cycles")
                return

        # 7. Minimum gap between trades — don't open if a trade was opened < 2 min ago
        last_trade_time = self.risk.get_last_trade_time()
        if last_trade_time:
            try:
                last_dt = datetime.fromisoformat(last_trade_time)
                gap_seconds = (datetime.utcnow() - last_dt).total_seconds()
                if gap_seconds < 120:
                    logger.info(f"Cycle {self._cycle_count}: Trade gap too short ({gap_seconds:.0f}s < 120s), skipping")
                    return
            except Exception:
                pass

        stake = self.risk.calculate_stake(self._balance)
        currency = self.client.account_info.get("currency", self.config.currency)
        logger.info(f"Placing {signal.signal.name} trade | Stake: {stake:.2f} {currency}")

        try:
            contract = await self.client.buy_contract(
                symbol=self.config.symbol,
                contract_type=signal.signal.value,
                duration=self.config.duration,
                duration_unit=self.config.duration_unit,
                amount=stake,
            )

            self.risk.register_trade(
                contract_id=contract["contract_id"],
                contract_type=signal.signal.value,
                symbol=self.config.symbol,
                stake=stake,
                payout=float(contract.get("payout", 0)),
                buy_price=float(contract.get("buy_price", stake)),
            )

            # Subscribe to real-time settlement updates
            try:
                await self.client.subscribe_contract_updates(contract["contract_id"])
            except Exception as e:
                logger.warning(f"Contract subscription failed, will fall back to polling: {e}")

        except Exception as e:
            logger.error(f"Failed to place trade: {e}")

    async def _check_open_positions(self) -> None:
        """Detect settled contracts via account statement (primary) and contract poll (fallback)."""
        open_positions = self.risk.get_open_positions()
        if not open_positions:
            return

        closed_ids: set = set()

        # --- Primary: account statement ---
        try:
            statement = await self.client.get_statement(limit=50)
            transactions = statement.get("transactions", [])
            logger.debug(f"Statement: {len(transactions)} transactions")

            for txn in transactions:
                cid = txn.get("contract_id")
                if cid is None:
                    continue
                cid = int(cid)
                if cid not in open_positions or cid in closed_ids:
                    continue
                action = txn.get("action_type", "")
                logger.debug(f"Statement txn for open contract {cid}: action={action} txn={txn}")
                if action in ("sell", "payout"):
                    trade = open_positions[cid]
                    buy_price = float(trade.get("buy_price", trade.get("stake", 0)))
                    payout = float(txn.get("amount", 0))
                    profit = round(payout - buy_price, 2)
                    self.risk.close_trade(cid, payout, profit)
                    closed_ids.add(cid)
                    try:
                        balance_info = await self.client.get_balance()
                        self._balance = float(balance_info.get("balance", self._balance))
                        self.risk.update_balance(self._balance)
                    except Exception as e:
                        logger.warning(f"Balance refresh failed: {e}")
        except Exception as e:
            logger.warning(f"Statement check failed: {e}")

        # --- Fallback 1: profit_table (covers expired contracts) ---
        remaining = {cid: pos for cid, pos in open_positions.items() if cid not in closed_ids}
        if remaining:
            try:
                profit_table = await self.client.get_profit_table(limit=50)
                for txn in profit_table.get("transactions", []):
                    cid = txn.get("contract_id")
                    if cid is None:
                        continue
                    cid = int(cid)
                    if cid not in remaining:
                        continue
                    buy_price = float(txn.get("buy_price", 0))
                    sell_price = float(txn.get("sell_price", 0))
                    profit = round(sell_price - buy_price, 2)
                    self.risk.close_trade(cid, sell_price, profit)
                    closed_ids.add(cid)
                    logger.info(f"Contract {cid} closed via profit_table | profit={profit:+.2f}")
                    try:
                        balance_info = await self.client.get_balance()
                        self._balance = float(balance_info.get("balance", self._balance))
                        self.risk.update_balance(self._balance)
                    except Exception as e:
                        logger.warning(f"Balance refresh failed: {e}")
            except Exception as e:
                logger.warning(f"Profit table check failed: {e}")

        # --- Fallback 2: proposal_open_contract poll (for very recently expired) ---
        remaining = {cid: pos for cid, pos in open_positions.items() if cid not in closed_ids}
        for contract_id in remaining:
            try:
                details = await self.client.get_contract(contract_id)
                status = details.get("status")
                logger.debug(f"Contract {contract_id} poll: status={status} keys={list(details.keys())}")
                if status in ("won", "lost", "sold"):
                    sell_price = float(details.get("sell_price", 0))
                    profit = float(details.get("profit", 0))
                    self.risk.close_trade(contract_id, sell_price, profit)
                    try:
                        balance_info = await self.client.get_balance()
                        self._balance = float(balance_info.get("balance", self._balance))
                        self.risk.update_balance(self._balance)
                    except Exception as e:
                        logger.warning(f"Balance refresh failed: {e}")
            except Exception as e:
                logger.warning(f"Contract poll failed for {contract_id}: {e}")

    def _print_status(self) -> None:
        """Print a status summary."""
        stats = self.risk.get_stats()
        currency = self.client.account_info.get("currency", self.config.currency)
        logger.info(
            f"\n{'─'*50}\n"
            f"  Balance:      {self._balance:.2f} {currency}\n"
            f"  Daily P&L:    {stats['daily_pnl_aud']:+.2f} {currency}\n"
            f"  Total Trades: {stats['total_trades']} "
            f"(W:{stats['wins']} / L:{stats['losses']} | {stats['win_rate_pct']:.0f}%)\n"
            f"  Open:         {stats['open_positions']}/{self.config.max_open_positions}\n"
            f"{'─'*50}"
        )


async def main(config_path: Optional[str] = None) -> None:
    """Entry point for the trading bot."""
    config = load_config(config_path)

    # Ensure data directory exists before opening log file
    import os
    os.makedirs(config.data_dir, exist_ok=True)

    # Set up logging
    log_level = getattr(logging, config.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(
                f"{config.data_dir}/bot.log",
                mode="a",
                encoding="utf-8",
            ) if config.data_dir else logging.StreamHandler(),
        ],
    )

    bot = TradingBot(config)

    # Handle graceful shutdown
    loop = asyncio.get_event_loop()

    def _shutdown(sig):
        logger.info(f"Received {sig.name}. Shutting down...")
        loop.create_task(bot.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown, sig)

    await bot.start()
    logger.info("Bot stopped.")
