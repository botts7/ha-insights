"""Seed synthetic state events that exercise every built-in detector.

Produces (after a scan_now) one insight per detector kind so the dev HA
has a representative gallery for testing the card / panel UX.

Detectors covered:
  schedule       — weekday-22:15 routine on light.morning_demo
  cooccurrence   — front-door-then-porch-light pair
  long_tail      — fan left running 3 hours multiple times
  orphan_device  — sensor that hasn't reported in 12 days
  streak         — 3 consecutive days at ~07:30 on a kitchen light

Run:
  python dev/_seed_all_demos.py
"""
from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import aiohttp

TOKEN_PATH = Path(__file__).parent / "token.txt"
HA_PORT = os.environ.get("HA_PORT", "8125")


async def _inject(ws, *, msg_id, entity_id, domain, area_id, ts, old_state, new_state):
    await ws.send_json({
        "id": msg_id,
        "type": "home_insights/_dev/inject_event",
        "entity_id": entity_id,
        "domain": domain,
        "area_id": area_id,
        "timestamp": ts.isoformat(),
        "old_state": old_state,
        "new_state": new_state,
    })
    return await ws.receive_json()


async def main() -> None:
    token = TOKEN_PATH.read_text(encoding="utf-8").strip()
    end = datetime.now(tz=UTC).replace(microsecond=0)
    msg_id = 0

    async with aiohttp.ClientSession() as s, s.ws_connect(
        f"ws://localhost:{HA_PORT}/api/websocket"
    ) as ws:
        await ws.receive_json()
        await ws.send_json({"type": "auth", "access_token": token})
        await ws.receive_json()

        # --- 1. Schedule: weekday 22:15 light.morning_demo -> off ---
        seeded_schedule = 0
        for offset in range(14):
            when = (end - timedelta(days=offset)).replace(
                hour=22, minute=15, second=0, microsecond=0
            )
            if when.weekday() >= 5:
                continue
            msg_id += 1
            r = await _inject(
                ws,
                msg_id=msg_id,
                entity_id="light.morning_demo",
                domain="light",
                area_id="demo",
                ts=when,
                old_state="on",
                new_state="off",
            )
            if r.get("success"):
                seeded_schedule += 1

        # --- 2. Cooccurrence: door open -> porch light on, 8 times, 5s apart ---
        seeded_cooc = 0
        for i in range(8):
            base = end - timedelta(hours=i + 1)
            for entity, dom, state in [
                ("binary_sensor.front_door_demo", "binary_sensor", "on"),
                ("light.porch_demo", "light", "on"),
            ]:
                msg_id += 1
                r = await _inject(
                    ws,
                    msg_id=msg_id,
                    entity_id=entity,
                    domain=dom,
                    area_id="demo",
                    ts=base if entity.startswith("binary_sensor") else base + timedelta(seconds=5),
                    old_state="off",
                    new_state=state,
                )
                if r.get("success"):
                    seeded_cooc += 1

        # --- 3. Long tail: switch.fan_demo left on 3hrs, 4 times in 14d ---
        seeded_long = 0
        for i in range(4):
            on_at = end - timedelta(days=(i + 1) * 2)
            off_at = on_at + timedelta(hours=3)
            for entity, ts, old_s, new_s in [
                ("switch.fan_demo", on_at, "off", "on"),
                ("switch.fan_demo", off_at, "on", "off"),
            ]:
                msg_id += 1
                r = await _inject(
                    ws,
                    msg_id=msg_id,
                    entity_id=entity,
                    domain="switch",
                    area_id="demo",
                    ts=ts,
                    old_state=old_s,
                    new_state=new_s,
                )
                if r.get("success"):
                    seeded_long += 1

        # --- 4. Orphan device: sensor that last reported 12 days ago ---
        seeded_orphan = 0
        # 5 events all at ~12 days ago, then nothing — qualifies as silent
        for i in range(5):
            when = end - timedelta(days=12, hours=i)
            msg_id += 1
            r = await _inject(
                ws,
                msg_id=msg_id,
                entity_id="sensor.battery_demo",
                domain="sensor",
                area_id="demo",
                ts=when,
                old_state=None,
                new_state="100",
            )
            if r.get("success"):
                seeded_orphan += 1

        # --- 5. Streak: 4 consecutive days at ~07:30, light.kitchen_streak_demo on ---
        seeded_streak = 0
        for i in range(4):
            when = (end - timedelta(days=i + 1)).replace(
                hour=7, minute=30 + (i % 2), second=0, microsecond=0
            )
            msg_id += 1
            r = await _inject(
                ws,
                msg_id=msg_id,
                entity_id="light.kitchen_streak_demo",
                domain="light",
                area_id="demo",
                ts=when,
                old_state="off",
                new_state="on",
            )
            if r.get("success"):
                seeded_streak += 1

        print(f"Seeded {seeded_schedule} schedule events")
        print(f"Seeded {seeded_cooc} cooccurrence events")
        print(f"Seeded {seeded_long} long_tail events")
        print(f"Seeded {seeded_orphan} orphan_device events")
        print(f"Seeded {seeded_streak} streak events")

        msg_id += 1
        await ws.send_json({"id": msg_id, "type": "home_insights/scan_now"})
        r = await ws.receive_json()
        result = r.get("result", {})
        print()
        print(
            f"Scan: detectors_run={result.get('detectors_run')} "
            f"emitted={result.get('insights_emitted')}"
        )

        msg_id += 1
        await ws.send_json({"id": msg_id, "type": "home_insights/list"})
        r = await ws.receive_json()
        insights = r.get("result", {}).get("insights", [])
        print()
        print(f"Visible insights: {len(insights)}")
        for i in insights:
            print(
                f"  [{i['detector']}] {i['title'][:70]} "
                f"(confidence={i['confidence']})"
            )


if __name__ == "__main__":
    asyncio.run(main())
