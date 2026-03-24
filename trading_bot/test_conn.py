"""
Quick connection diagnostic — run this to debug 401 errors.

Usage:
    cd trading_bot
    python test_conn.py
"""
import asyncio
import json
import os
import sys
from urllib.parse import urlparse

try:
    import aiohttp
    import websockets
except ImportError:
    sys.exit("Missing deps — run:  pip install aiohttp websockets")


def load_env():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        sys.exit(".env file not found. Copy .env.example to .env and fill in values.")
    for line in open(env_path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


async def main():
    load_env()
    token = os.environ.get("DERIV_API_TOKEN", "")
    app_id = os.environ.get("DERIV_APP_ID", "")
    account_id = os.environ.get("DERIV_ACCOUNT_ID", "")

    print(f"App ID    : {app_id}")
    print(f"Account   : {account_id}")
    print(f"Token     : {token[:8]}...{token[-4:] if len(token) > 12 else '(short)'}")
    print()

    # Step 1: OTP REST call
    otp_url = f"https://api.derivws.com/trading/v1/options/accounts/{account_id}/otp"
    print(f"[1] POST {otp_url}")
    async with aiohttp.ClientSession() as session:
        async with session.post(
            otp_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Deriv-App-ID": app_id,
            },
        ) as resp:
            body = await resp.text()
            print(f"    Status : {resp.status}")
            print(f"    Body   : {body[:400]}")
            if resp.status != 200:
                print("\n  FAIL — OTP request was rejected.")
                print("  Check: token is a PAT from developers.deriv.com, and account_id is correct.")
                return

            try:
                ws_url = json.loads(body)["data"]["url"]
            except (KeyError, json.JSONDecodeError) as e:
                print(f"\n  FAIL — Could not parse OTP response: {e}")
                return

    parsed = urlparse(ws_url)
    print(f"\n[2] Connecting to WebSocket: {parsed.scheme}://{parsed.netloc}{parsed.path}?otp=<redacted>")
    try:
        async with websockets.connect(ws_url) as ws:
            print("    Status : CONNECTED")
            print("\n  SUCCESS — WebSocket handshake completed.")
    except Exception as e:
        print(f"    Error  : {e}")
        print("\n  FAIL — WebSocket connection rejected.")
        print("  The OTP URL was obtained but the connection was refused.")
        print("  This usually means the PAT token doesn't have trading scope,")
        print("  or it belongs to a different account than DERIV_ACCOUNT_ID.")


asyncio.run(main())
