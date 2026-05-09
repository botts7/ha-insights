"""Quick lister: dump current insights including applied ones."""
from __future__ import annotations

import asyncio
from pathlib import Path

import aiohttp


async def main() -> None:
    token = Path(__file__).parent.joinpath("token.txt").read_text(encoding="utf-8").strip()
    async with aiohttp.ClientSession() as s, s.ws_connect(
        "ws://localhost:8125/api/websocket"
    ) as ws:
        await ws.receive_json()
        await ws.send_json({"type": "auth", "access_token": token})
        await ws.receive_json()
        await ws.send_json({
            "id": 1,
            "type": "home_insights/list",
            "include_applied": True,
        })
        r = await ws.receive_json()
        insights = r.get("result", {}).get("insights", [])
        print(f"== {len(insights)} insights ==")
        for i in insights:
            applied = " (APPLIED)" if i.get("applied_at") else ""
            print(
                f"  [{i['detector']}] {i['title'][:70]}"
                f" conf={i['confidence']}{applied}"
            )


if __name__ == "__main__":
    asyncio.run(main())
