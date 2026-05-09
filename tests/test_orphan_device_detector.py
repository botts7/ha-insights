"""Tests for OrphanDeviceDetector."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from custom_components.ha_insights.detectors.base import DetectorContext
from custom_components.ha_insights.detectors.orphan_device import OrphanDeviceDetector
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
) -> StateEvent:
    return StateEvent(
        timestamp=timestamp,
        entity_id=entity_id,
        domain=entity_id.split(".", 1)[0],
        area_id=None,
        old_state=None,
        new_state=new_state,
    )


@pytest.mark.asyncio
async def test_no_buffer_returns_empty() -> None:
    detector = OrphanDeviceDetector()
    ctx = DetectorContext(hass=MagicMock(), event_buffer=None)
    assert await detector.scan(ctx) == []


@pytest.mark.asyncio
async def test_recent_entity_not_orphaned() -> None:
    """Entity reporting today is fine."""
    buf = StateEventBuffer(max_age=timedelta(days=30))
    end = datetime.now(tz=UTC).replace(microsecond=0)
    for i in range(5):
        buf.add(_ev(end - timedelta(hours=i), "binary_sensor.door", "off"))
    detector = OrphanDeviceDetector()
    insights = await detector.scan(_ctx(buf))
    assert insights == []


@pytest.mark.asyncio
async def test_stale_entity_surfaces_orphan() -> None:
    """Entity that last reported >7 days ago is an orphan."""
    buf = StateEventBuffer(max_age=timedelta(days=30))
    end = datetime.now(tz=UTC).replace(microsecond=0)
    # 5 events all clustered 10 days ago — entity has been silent since
    for i in range(5):
        buf.add(
            _ev(
                end - timedelta(days=10, hours=i),
                "binary_sensor.battery_door",
                "off",
            )
        )
    detector = OrphanDeviceDetector()
    insights = await detector.scan(_ctx(buf))
    assert len(insights) == 1
    insight = insights[0]
    assert insight.kind is InsightKind.ANOMALY
    assert insight.detector == "orphan_device"
    assert "binary_sensor.battery_door" in insight.title
    assert "10d" in insight.title or "days" in insight.title


@pytest.mark.asyncio
async def test_too_few_prior_events_skipped() -> None:
    """Entity with only 2 events (< MIN_PRIOR_EVENTS=3) is not an orphan."""
    buf = StateEventBuffer(max_age=timedelta(days=30))
    end = datetime.now(tz=UTC).replace(microsecond=0)
    for i in range(2):
        buf.add(_ev(end - timedelta(days=10, hours=i), "sensor.new", "1"))
    detector = OrphanDeviceDetector()
    insights = await detector.scan(_ctx(buf))
    assert insights == []


@pytest.mark.asyncio
async def test_payload_has_unavailable_trigger_and_notify_action() -> None:
    buf = StateEventBuffer(max_age=timedelta(days=30))
    end = datetime.now(tz=UTC).replace(microsecond=0)
    for i in range(5):
        buf.add(
            _ev(end - timedelta(days=12, hours=i), "switch.garage", "on")
        )
    detector = OrphanDeviceDetector()
    insights = await detector.scan(_ctx(buf))
    assert len(insights) == 1
    payload = insights[0].payload
    trigger = payload["trigger"][0]
    assert trigger["platform"] == "state"
    assert trigger["entity_id"] == "switch.garage"
    assert trigger["from"] == "unavailable"
    action = payload["action"][0]
    assert action["service"] == "persistent_notification.create"
    assert "switch.garage" in action["data"]["message"]


@pytest.mark.asyncio
async def test_blocked_domain_not_flagged() -> None:
    """camera.* / lock.* / person.* — blocked domains never surface orphans."""
    buf = StateEventBuffer(max_age=timedelta(days=30))
    end = datetime.now(tz=UTC).replace(microsecond=0)
    for i in range(5):
        buf.add(_ev(end - timedelta(days=10, hours=i), "lock.front_door", "locked"))
        buf.add(_ev(end - timedelta(days=10, hours=i), "person.alice", "home"))
    detector = OrphanDeviceDetector()
    insights = await detector.scan(_ctx(buf))
    assert insights == []


@pytest.mark.asyncio
async def test_unlisted_domain_skipped() -> None:
    """sun.* / scene.* / weather.* aren't in the allowlist — skipped."""
    buf = StateEventBuffer(max_age=timedelta(days=30))
    end = datetime.now(tz=UTC).replace(microsecond=0)
    for i in range(5):
        buf.add(_ev(end - timedelta(days=10, hours=i), "sun.sun", "above_horizon"))
        buf.add(_ev(end - timedelta(days=10, hours=i), "scene.movie_night", "scening"))
    detector = OrphanDeviceDetector()
    insights = await detector.scan(_ctx(buf))
    assert insights == []


@pytest.mark.asyncio
async def test_confidence_scales_with_silence() -> None:
    buf_short = StateEventBuffer(max_age=timedelta(days=30))
    buf_long = StateEventBuffer(max_age=timedelta(days=30))
    end = datetime.now(tz=UTC).replace(microsecond=0)
    for i in range(5):
        # 8 days silent
        buf_short.add(
            _ev(end - timedelta(days=8, hours=i), "sensor.short", "1")
        )
        # 13 days silent
        buf_long.add(
            _ev(end - timedelta(days=13, hours=i), "sensor.long", "1")
        )
    detector = OrphanDeviceDetector()
    [short] = await detector.scan(_ctx(buf_short))
    [long_orphan] = await detector.scan(_ctx(buf_long))
    assert long_orphan.confidence > short.confidence


@pytest.mark.asyncio
async def test_fingerprint_stable_within_a_day() -> None:
    """Same buffer, two scans on the same day produce the same insight id."""
    buf = StateEventBuffer(max_age=timedelta(days=30))
    end = datetime.now(tz=UTC).replace(microsecond=0)
    for i in range(5):
        buf.add(_ev(end - timedelta(days=10, hours=i), "sensor.x", "1"))
    detector = OrphanDeviceDetector()
    [first] = await detector.scan(_ctx(buf))
    [second] = await detector.scan(_ctx(buf))
    assert first.id == second.id
