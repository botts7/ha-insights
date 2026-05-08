#!/usr/bin/env python3
"""Synthetic state-history seeder for HA Insights dev harness.

Generates state events backdated to past timestamps and pushes them
into the integration's StateEventBuffer via the dev-only WS command
home_insights/_dev/inject_event. Used by probe.py end-to-end checks.

Usage:
    python seed.py --pattern weekday-routine \\
        --entity light.kitchen --action turn_on --time 06:47

Reads the long-lived access token from dev/token.txt.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import aiohttp


HA_HOST = "localhost"


def read_token() -> str:
    token_path = Path(__file__).parent / "token.txt"
    if not token_path.exists():
        print(
            "ERROR: dev/token.txt not found. Create a long-lived access token in HA "
            "(Profile -> Security -> Long-Lived Access Tokens) and save it to dev/token.txt.",
            file=sys.stderr,
        )
        sys.exit(2)
    return token_path.read_text(encoding="utf-8").strip()


def parse_time(time_str: str) -> tuple[int, int]:
    """Parse HH:MM into (hour, minute)."""
    parts = time_str.split(":")
    return int(parts[0]), int(parts[1])


def generate_weekday_routine_events(
    *,
    entity_id: str,
    domain: str,
    new_state: str,
    hour: int,
    minute: int,
    days: int,
    end_now: datetime,
) -> list[dict]:
    """Generate one event per weekday in the past `days` days."""
    events: list[dict] = []
    for offset in range(days):
        when = (end_now - timedelta(days=offset)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        if when.weekday() >= 5:
            continue  # skip weekend
        events.append(
            {
                "entity_id": entity_id,
                "domain": domain,
                "area_id": entity_id.split(".", 1)[0],  # tag area same as domain for dev
                "timestamp": when.isoformat(),
                "old_state": "off" if new_state == "on" else "on",
                "new_state": new_state,
            }
        )
    return events


async def inject_events(port: int, token: str, events: list[dict]) -> int:
    """Open WS, auth, fire dev_inject_event for each event. Returns accepted count."""
    url = f"ws://{HA_HOST}:{port}/api/websocket"
    accepted = 0
    async with aiohttp.ClientSession() as session, session.ws_connect(url) as ws:
        # Auth handshake
        msg = await ws.receive_json()
        assert msg["type"] == "auth_required", f"Expected auth_required, got {msg!r}"
        await ws.send_json({"type": "auth", "access_token": token})
        msg = await ws.receive_json()
        if msg["type"] != "auth_ok":
            print(f"ERROR: auth failed: {msg!r}", file=sys.stderr)
            return 0

        # Fire each event
        for i, event in enumerate(events, start=1):
            await ws.send_json(
                {
                    "id": i,
                    "type": "home_insights/_dev/inject_event",
                    **event,
                }
            )
            reply = await ws.receive_json()
            if reply.get("success") and reply.get("result", {}).get("accepted"):
                accepted += 1
            else:
                print(f"WARN: event {i} not accepted: {reply}", file=sys.stderr)
    return accepted


async def main() -> int:
    parser = argparse.ArgumentParser(description="Seed HA with synthetic state history")
    parser.add_argument("--pattern", default="weekday-routine",
                        choices=["weekday-routine"])
    parser.add_argument("--entity", required=True, help="entity_id, e.g. light.kitchen")
    parser.add_argument("--action", default="turn_on",
                        help="HA service like turn_on / turn_off (state inferred)")
    parser.add_argument("--time", default="06:47", help="HH:MM time of day")
    parser.add_argument("--days", type=int, default=14, help="lookback in days")
    parser.add_argument("--port", type=int, default=int(os.environ.get("HA_PORT", "8125")))
    args = parser.parse_args()

    domain = args.entity.split(".", 1)[0]
    new_state = "on" if args.action == "turn_on" else "off"
    hour, minute = parse_time(args.time)

    end_now = datetime.now(tz=UTC).replace(microsecond=0)
    events = generate_weekday_routine_events(
        entity_id=args.entity,
        domain=domain,
        new_state=new_state,
        hour=hour,
        minute=minute,
        days=args.days,
        end_now=end_now,
    )

    token = read_token()
    print(f"Seeding {len(events)} weekday events for {args.entity} at {args.time} via :{args.port}")
    accepted = await inject_events(args.port, token, events)
    print(f"Accepted: {accepted}/{len(events)}")
    print(f"Sample event: {json.dumps(events[0], indent=2) if events else 'none'}")
    return 0 if accepted == len(events) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
