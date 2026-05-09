"""Probe the home_insights/refine endpoint against the live integration.

Lists insights, picks the first one, calls refine, prints the full result.
Used to debug "not seeing a refine response" — surfaces what the server
actually returns, vs what the card chooses to render.
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
    url = f"ws://localhost:{HA_PORT}/api/websocket"
    async with aiohttp.ClientSession() as s, s.ws_connect(url) as ws:
        await ws.receive_json()
        await ws.send_json({"type": "auth", "access_token": token})
        await ws.receive_json()

        msg_id = 1
        await ws.send_json({"id": msg_id, "type": "home_insights/list"})
        r = await ws.receive_json()
        insights = r.get("result", {}).get("insights", [])
        if not insights:
            print("No insights to refine. Run _cooccurrence_seed.py first.")
            return
        # Honor a CLI selector: --detector cooccurrence
        import sys
        prefer = None
        if "--detector" in sys.argv:
            prefer = sys.argv[sys.argv.index("--detector") + 1]
        target = (
            next((i for i in insights if i["detector"] == prefer), insights[0])
            if prefer
            else insights[0]
        )
        print(f"Refining: {target['title']}")
        print(f"  id={target['id']}  detector={target['detector']}")
        print()

        msg_id += 1
        await ws.send_json({
            "id": msg_id,
            "type": "home_insights/refine",
            "insight_id": target["id"],
        })
        r = await ws.receive_json()
        print(json.dumps(r, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
