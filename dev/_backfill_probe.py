"""Verify the home_insights.backfill service runs and reports a summary.

Calls the service via REST, then waits a moment and lists current insights.
The dev HA typically has no recorder data; this probe just confirms the
endpoint is wired and doesn't crash.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import aiohttp

TOKEN_PATH = Path(__file__).parent / "token.txt"
HA_PORT = os.environ.get("HA_PORT", "8125")


async def main() -> None:
    token = TOKEN_PATH.read_text(encoding="utf-8").strip()

    async with aiohttp.ClientSession() as s:
        # Call the service via REST
        async with s.post(
            f"http://localhost:{HA_PORT}/api/services/home_insights/backfill",
            headers={"Authorization": f"Bearer {token}"},
            json={"lookback_days": 14},
        ) as r:
            text = await r.text()
            print(f"backfill service: HTTP {r.status}")
            try:
                data = json.loads(text)
                print(json.dumps(data, indent=2))
            except json.JSONDecodeError:
                print(text)

    # The service log line should be visible at INFO level. We surface it
    # via WS instead in v0.4 phase 1C.


if __name__ == "__main__":
    asyncio.run(main())
