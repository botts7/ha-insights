"""One-shot seed for card demo: backfill an unapplied insight on a fresh entity."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import aiohttp

TOKEN_PATH = Path(__file__).parent / "token.txt"
ENTITY = "light.dashboard_demo"
HOUR = 22
MINUTE = 15


async def main() -> None:
    token = TOKEN_PATH.read_text(encoding="utf-8").strip()
    async with aiohttp.ClientSession() as s, s.ws_connect("ws://localhost:8125/api/websocket") as ws:
        await ws.receive_json()
        await ws.send_json({"type": "auth", "access_token": token})
        await ws.receive_json()

        msg_id = 0
        end = datetime.now(tz=UTC).replace(microsecond=0)
        seeded = 0
        for offset in range(14):
            when = (end - timedelta(days=offset)).replace(
                hour=HOUR, minute=MINUTE, second=0, microsecond=0
            )
            if when.weekday() >= 5:
                continue
            msg_id += 1
            await ws.send_json({
                "id": msg_id,
                "type": "home_insights/_dev/inject_event",
                "entity_id": ENTITY,
                "domain": "light",
                "area_id": "demo",
                "timestamp": when.isoformat(),
                "old_state": "on",
                "new_state": "off",
            })
            r = await ws.receive_json()
            if r.get("success"):
                seeded += 1
        print(f"Seeded {seeded} events for {ENTITY}")

        msg_id += 1
        await ws.send_json({"id": msg_id, "type": "home_insights/scan_now"})
        r = await ws.receive_json()
        result = r.get("result", {})
        print(f"Scan: detectors_run={result.get('detectors_run')} emitted={result.get('insights_emitted')}")

        msg_id += 1
        await ws.send_json({"id": msg_id, "type": "home_insights/list"})
        r = await ws.receive_json()
        insights = r.get("result", {}).get("insights", [])
        print(f"Visible (unapplied, unsdismissed) insights: {len(insights)}")
        for i in insights:
            print(f"  - {i['title']} (confidence={i['confidence']})")


if __name__ == "__main__":
    asyncio.run(main())
