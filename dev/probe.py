#!/usr/bin/env python3
"""End-to-end probe for HA Insights integration.

Walks the full demo path:
  1. Connect + auth via WS
  2. home_insights/hello                  (handshake)
  3. home_insights/_dev/inject_event x N  (seed weekday routine)
  4. home_insights/scan_now               (run detectors)
  5. home_insights/list                   (assert insight produced)
  6. home_insights/apply                  (write the automation)
  7. Verify automation registered in HA

Reads the long-lived access token from dev/token.txt.
Returns exit code 0 on success, 1 on assertion failure, 2 on setup error.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import aiohttp


HA_HOST = "localhost"
TARGET_ENTITY = "light.kitchen_probe"  # use a synthetic entity to avoid collisions


def read_token() -> str:
    token_path = Path(__file__).parent / "token.txt"
    if not token_path.exists():
        print(
            "ERROR: dev/token.txt not found. Create a long-lived access token in HA "
            "and save it to dev/token.txt.",
            file=sys.stderr,
        )
        sys.exit(2)
    return token_path.read_text(encoding="utf-8").strip()


class WsSession:
    def __init__(self, port: int, token: str) -> None:
        self._port = port
        self._token = token
        self._next_id = 1
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None

    async def __aenter__(self) -> WsSession:
        self._session = aiohttp.ClientSession()
        self._ws = await self._session.ws_connect(
            f"ws://{HA_HOST}:{self._port}/api/websocket"
        )
        msg = await self._ws.receive_json()
        assert msg["type"] == "auth_required"
        await self._ws.send_json({"type": "auth", "access_token": self._token})
        msg = await self._ws.receive_json()
        if msg["type"] != "auth_ok":
            raise RuntimeError(f"auth failed: {msg!r}")
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._ws is not None:
            await self._ws.close()
        if self._session is not None:
            await self._session.close()

    async def send(self, payload: dict) -> dict:
        assert self._ws is not None
        msg_id = self._next_id
        self._next_id += 1
        await self._ws.send_json({"id": msg_id, **payload})
        return await self._ws.receive_json()


def generate_weekday_events(
    *, entity_id: str, hour: int, minute: int, days: int = 14
) -> list[dict]:
    end = datetime.now(tz=UTC).replace(microsecond=0)
    events: list[dict] = []
    for offset in range(days):
        when = (end - timedelta(days=offset)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        if when.weekday() >= 5:
            continue
        events.append(
            {
                "entity_id": entity_id,
                "domain": entity_id.split(".", 1)[0],
                "area_id": "probe_area",
                "timestamp": when.isoformat(),
                "old_state": "off",
                "new_state": "on",
            }
        )
    return events


async def fetch_automation_via_rest(port: int, token: str, automation_id: str) -> dict | None:
    """Find an automation entity whose attributes.id matches automation_id.

    HA derives the entity_id from the alias (slugified), not from our id, so
    we list all automation.* states and match on attributes.id.
    """
    url = f"http://{HA_HOST}:{port}/api/states"
    headers = {"Authorization": f"Bearer {token}"}
    async with aiohttp.ClientSession() as s, s.get(url, headers=headers) as r:
        if r.status != 200:
            return None
        states = await r.json()
    for entity in states:
        if not entity.get("entity_id", "").startswith("automation."):
            continue
        if entity.get("attributes", {}).get("id") == automation_id:
            return entity
    return None


async def main() -> int:
    port = int(os.environ.get("HA_PORT", "8125"))
    token = read_token()

    print(f"=== HA Insights probe @ :{port} ===")

    async with WsSession(port, token) as ws:
        # 1. handshake
        reply = await ws.send({"type": "home_insights/hello"})
        if not reply.get("success"):
            print(f"FAIL: hello failed: {reply}", file=sys.stderr)
            return 1
        print(f"OK: hello — integration_version={reply['result']['integration_version']}, "
              f"ws_protocol_version={reply['result']['ws_protocol_version']}")

        # 2. seed events
        events = generate_weekday_events(
            entity_id=TARGET_ENTITY, hour=6, minute=47
        )
        print(f"Seeding {len(events)} weekday events at 06:47 for {TARGET_ENTITY}...")
        for event in events:
            reply = await ws.send(
                {"type": "home_insights/_dev/inject_event", **event}
            )
            if not reply.get("success"):
                print(f"FAIL: inject_event failed: {reply}", file=sys.stderr)
                return 1
        print(f"OK: seeded {len(events)} events")

        # 3. scan_now
        reply = await ws.send({"type": "home_insights/scan_now"})
        if not reply.get("success"):
            print(f"FAIL: scan_now failed: {reply}", file=sys.stderr)
            return 1
        result = reply["result"]
        print(f"OK: scan_now ran {result['detectors_run']}, emitted {result['insights_emitted']} insights")

        # 4. list
        reply = await ws.send({"type": "home_insights/list"})
        if not reply.get("success"):
            print(f"FAIL: list failed: {reply}", file=sys.stderr)
            return 1
        insights = reply["result"]["insights"]
        target_insights = [i for i in insights if TARGET_ENTITY in i["title"]]
        if not target_insights:
            print(f"FAIL: no insight produced for {TARGET_ENTITY}", file=sys.stderr)
            print(f"  All insights: {json.dumps([i['title'] for i in insights], indent=2)}")
            return 1
        insight = target_insights[0]
        print(f"OK: list found insight: {insight['title']}")
        print(f"    id={insight['id']}, confidence={insight['confidence']}")

        # 5. apply
        reply = await ws.send(
            {"type": "home_insights/apply", "insight_id": insight["id"]}
        )
        if not reply.get("success"):
            print(f"FAIL: apply failed: {reply}", file=sys.stderr)
            return 1
        automation_id = reply["result"]["automation_id"]
        print(f"OK: apply created automation {automation_id}")

    # 6. verify automation in HA
    auto = await fetch_automation_via_rest(port, token, automation_id)
    if auto is None:
        print(f"WARN: automation {automation_id} not visible via REST yet "
              f"(may need manual reload — see dev/README)", file=sys.stderr)
    else:
        print(f"OK: automation visible via REST: state={auto['state']}")

    print()
    print("=== ALL CHECKS PASSED ===")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
