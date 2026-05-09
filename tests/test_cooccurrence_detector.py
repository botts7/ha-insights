"""Tests for CooccurrenceDetector."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from custom_components.ha_insights.detectors.base import DetectorContext
from custom_components.ha_insights.detectors.cooccurrence import CooccurrenceDetector
from custom_components.ha_insights.insight import InsightKind
from custom_components.ha_insights.observers.state_event_buffer import (
    StateEvent,
    StateEventBuffer,
)


def _ctx(buf: StateEventBuffer) -> DetectorContext:
    return DetectorContext(hass=MagicMock(), event_buffer=buf)


def _ev(
    timestamp: datetime,
    entity_id: str,
    new_state: str,
    *,
    old_state: str = "off",
    domain: str | None = None,
    area_id: str | None = "kitchen",
) -> StateEvent:
    if domain is None:
        domain = entity_id.split(".", 1)[0]
    return StateEvent(
        timestamp=timestamp,
        entity_id=entity_id,
        domain=domain,
        area_id=area_id,
        old_state=old_state,
        new_state=new_state,
    )


def _seed_door_then_light(
    buf: StateEventBuffer,
    *,
    times: int,
    delta_seconds: float,
    door_eid: str = "binary_sensor.front_door",
    light_eid: str = "light.porch",
    end_now: datetime | None = None,
) -> int:
    """Seed N (door=on, then light=on after delta_seconds) pairs spread out by 1h each."""
    end = end_now or datetime.now(tz=UTC).replace(microsecond=0)
    added = 0
    for i in range(times):
        base = end - timedelta(hours=i + 1)
        buf.add(_ev(base, door_eid, "on"))
        buf.add(_ev(base + timedelta(seconds=delta_seconds), light_eid, "on"))
        added += 2
    return added


@pytest.mark.asyncio
async def test_no_buffer_returns_empty() -> None:
    detector = CooccurrenceDetector()
    ctx = DetectorContext(hass=MagicMock(), event_buffer=None)
    assert await detector.scan(ctx) == []


@pytest.mark.asyncio
async def test_below_min_occurrences_no_insight() -> None:
    buf = StateEventBuffer()
    _seed_door_then_light(buf, times=3, delta_seconds=5)
    detector = CooccurrenceDetector()
    insights = await detector.scan(_ctx(buf))
    assert insights == []


@pytest.mark.asyncio
async def test_consistent_pair_produces_insight() -> None:
    buf = StateEventBuffer()
    _seed_door_then_light(buf, times=8, delta_seconds=5)
    detector = CooccurrenceDetector()
    insights = await detector.scan(_ctx(buf))
    assert len(insights) >= 1
    target = next(
        (
            i
            for i in insights
            if i.fingerprint.get("leader_entity_id") == "binary_sensor.front_door"
        ),
        None,
    )
    assert target is not None
    assert target.kind is InsightKind.AUTOMATION_PROPOSAL
    assert target.detector == "cooccurrence"
    assert "binary_sensor.front_door" in target.title
    assert "light.porch" in target.title


@pytest.mark.asyncio
async def test_payload_has_state_trigger_and_service_action() -> None:
    buf = StateEventBuffer()
    _seed_door_then_light(buf, times=8, delta_seconds=5)
    detector = CooccurrenceDetector()
    insights = await detector.scan(_ctx(buf))
    target = next(
        i for i in insights if i.fingerprint.get("leader_entity_id") == "binary_sensor.front_door"
    )
    payload = target.payload
    assert payload["trigger"] == [
        {
            "platform": "state",
            "entity_id": "binary_sensor.front_door",
            "to": "on",
        }
    ]
    assert payload["action"] == [
        {"service": "light.turn_on", "target": {"entity_id": "light.porch"}}
    ]
    assert payload["mode"] == "single"


@pytest.mark.asyncio
async def test_inconsistent_timing_rejected() -> None:
    """Wildly varying delays should not produce an insight."""
    buf = StateEventBuffer()
    end = datetime.now(tz=UTC).replace(microsecond=0)
    # Varying delays from 1s to 28s (stddev > threshold)
    for i, delta in enumerate([1, 5, 10, 15, 20, 25, 28, 2, 26, 4]):
        base = end - timedelta(hours=i + 1)
        buf.add(_ev(base, "binary_sensor.door", "on"))
        buf.add(_ev(base + timedelta(seconds=delta), "light.porch", "on"))
    detector = CooccurrenceDetector()
    insights = await detector.scan(_ctx(buf))
    assert all(
        i.fingerprint.get("leader_entity_id") != "binary_sensor.door" for i in insights
    )


@pytest.mark.asyncio
async def test_lock_domain_skipped() -> None:
    """Safety-blocked domains never appear as leader or follower."""
    buf = StateEventBuffer()
    end = datetime.now(tz=UTC).replace(microsecond=0)
    for i in range(8):
        base = end - timedelta(hours=i + 1)
        buf.add(_ev(base, "lock.front_door", "unlocked"))
        buf.add(_ev(base + timedelta(seconds=5), "light.porch", "on"))
    detector = CooccurrenceDetector()
    insights = await detector.scan(_ctx(buf))
    assert all(
        i.fingerprint.get("leader_entity_id") != "lock.front_door" for i in insights
    )


@pytest.mark.asyncio
async def test_outside_window_rejected() -> None:
    """Pairs separated by more than WINDOW_SECONDS shouldn't be paired."""
    buf = StateEventBuffer()
    end = datetime.now(tz=UTC).replace(microsecond=0)
    for i in range(8):
        base = end - timedelta(hours=i + 1)
        buf.add(_ev(base, "binary_sensor.door", "on"))
        # 60s delta, way outside the 30s WINDOW
        buf.add(_ev(base + timedelta(seconds=60), "light.porch", "on"))
    detector = CooccurrenceDetector()
    insights = await detector.scan(_ctx(buf))
    assert insights == []


@pytest.mark.asyncio
async def test_same_entity_self_followup_skipped() -> None:
    """An entity can't trigger itself."""
    buf = StateEventBuffer()
    end = datetime.now(tz=UTC).replace(microsecond=0)
    for i in range(8):
        base = end - timedelta(hours=i + 1)
        buf.add(_ev(base, "light.kitchen", "on"))
        buf.add(_ev(base + timedelta(seconds=5), "light.kitchen", "off"))
    detector = CooccurrenceDetector()
    insights = await detector.scan(_ctx(buf))
    # Must not have light.kitchen as both leader and follower
    for ins in insights:
        assert ins.fingerprint.get("leader_entity_id") != ins.fingerprint.get(
            "follower_entity_id"
        )


@pytest.mark.asyncio
async def test_fingerprint_stable_across_scans() -> None:
    buf = StateEventBuffer()
    _seed_door_then_light(buf, times=8, delta_seconds=5)
    detector = CooccurrenceDetector()
    [first] = [
        i
        for i in await detector.scan(_ctx(buf))
        if i.fingerprint.get("leader_entity_id") == "binary_sensor.front_door"
    ]
    [second] = [
        i
        for i in await detector.scan(_ctx(buf))
        if i.fingerprint.get("leader_entity_id") == "binary_sensor.front_door"
    ]
    assert first.id == second.id
