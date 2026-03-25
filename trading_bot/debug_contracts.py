"""
Debug script - queries Deriv directly for stuck open positions.
Usage: python3 debug_contracts.py
"""
import asyncio
import json
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_SCRIPT_DIR))

# Load .env file if present
_env_path = os.path.join(_SCRIPT_DIR, ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

from trading_bot.deriv_client import DerivClient
from trading_bot.config import load_config


async def main():
    config = load_config()
    if not config.api_token:
        print("ERROR: No API token set. Check your config/env vars.")
        return

    state_file = os.path.join(_SCRIPT_DIR, "data", "risk_state.json")
    with open(state_file) as f:
        state = json.load(f)
    open_positions = state.get("open_positions", [])
    contract_ids = [int(p["contract_id"]) for p in open_positions]
    print(f"Open positions to resolve: {contract_ids}\n")

    client = DerivClient(api_token=config.api_token, app_id=config.app_id)
    await client.connect()

    print("--- ACCOUNT STATEMENT (last 20) ---")
    statement = await client.get_statement(limit=20)
    for txn in statement.get("transactions", []):
        cid = txn.get("contract_id")
        action = txn.get("action_type")
        amount = txn.get("amount")
        if cid in contract_ids or cid in [str(c) for c in contract_ids]:
            print(f"  ** MATCH ** contract_id={cid} action={action} amount={amount}")
        else:
            print(f"  contract_id={cid} action={action} amount={amount}")

    print("\n--- PROFIT TABLE (last 20) ---")
    profit_table = await client.get_profit_table(limit=20)
    for txn in profit_table.get("transactions", []):
        cid = txn.get("contract_id")
        buy = txn.get("buy_price")
        sell = txn.get("sell_price")
        if int(cid) in contract_ids:
            print(f"  ** MATCH ** contract_id={cid} buy={buy} sell={sell}")
        else:
            print(f"  contract_id={cid} buy={buy} sell={sell}")

    print("\n--- PROPOSAL_OPEN_CONTRACT for each ---")
    for cid in contract_ids:
        result = await client.get_contract(cid)
        print(f"  contract {cid}: {result}")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
