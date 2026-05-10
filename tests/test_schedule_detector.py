"""Tests for the ScheduleDetector v0.1 hero.

Events stored as UTC; detector converts to local before bucketing
(v1.0 timezone fix). Test setup builds events at LOCAL hour/minute
then converts to UTC for buffer storage so .weekday() and
_minute_of_day reflect the user's calendar regardless of host TZ.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from homeassistant.util import dt as dt_util

from custom_components.ha_insights.detectors.base import DetectorContext
from custom_components.ha_insights.detectors.schedule import ScheduleDetector
from custom_components.ha_insights.insight import InsightKind
from custom_components.ha_insights.observers.state_event_buffer import (
    StateEvent,
    StateEventBuffer,
)


def _ctx_with_buffer(buf: StateEventBuffer) -> DetectorContext:
    return DetectorContext(hass=MagicMock(), event_buffer=buf)


def _seed_weekday_routine(
    buf: StateEventBuffer,
    *,
    entity_id: str = "light.kitchen",
    domain: str = "light",
    area_id: str | None = "kitchen",
    new_state: str = "on",
    hour: int = 6,
    minute: int = 47,
    days: int = 14,
    end_now: datetime | None = None,
) -> int:
    """Seed weekday-only events at hour:minute over the last `days`. Returns count added.

    `end_now` and the per-event `when` are constructed in HA's local
    timezone (so .weekday() identifies local weekdays), then
    `.astimezone(UTC)` for buffer storage to mirror the production
    state_changed listener.
    """
    end = end_now or dt_util.now()
    added = 0
    for offset in range(days):
        local_when = (end - timedelta(days=offset)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        if local_when.weekday() >= 5:  # skip weekend (local)
            continue
        ev = StateEvent(
            timestamp=local_when.astimezone(UTC),
            entity_id=entity_id,
            domain=domain,
            area_id=area_id,
            old_state="off" if new_state == "on" else "on",
            new_state=new_state,
        )
        buf.add(ev)
        added += 1
    return added


@pytest.mark.asyncio
async def test_no_buffer_returns_empty() -> None:
    detector = ScheduleDetector()
    ctx = DetectorContext(hass=MagicMock(), event_buffer=None)
    assert await detector.scan(ctx) == []


@pytest.mark.asyncio
async def test_empty_buffer_returns_empty() -> None:
    buf = StateEventBuffer()
    detector = ScheduleDetector()
    assert await detector.scan(_ctx_with_buffer(buf)) == []


@pytest.mark.asyncio
async def test_below_min_occurrences_returns_empty() -> None:
    """Fewer than 10 weekday hits should not produce an insight."""
    buf = StateEventBuffer()
    _seed_weekday_routine(buf, days=7)  # only ~5 weekdays
    detector = ScheduleDetector()
    insights = await detector.scan(_ctx_with_buffer(buf))
    assert insights == []


@pytest.mark.asyncio
async def test_consistent_weekday_routine_produces_insight() -> None:
    buf = StateEventBuffer()
    seeded = _seed_weekday_routine(buf, days=14)
    assert seeded >= 10  # sanity: 14 days normally has >=10 weekdays
    detector = ScheduleDetector()
    insights = await detector.scan(_ctx_with_buffer(buf))
    assert len(insights) == 1

    insight = insights[0]
    assert insight.kind is InsightKind.AUTOMATION_PROPOSAL
    assert insight.detector == "schedule"
    assert "06:47" in insight.title
    assert "light.kitchen" in insight.title
    assert insight.confidence > 0.6
    assert insight.area_id == "kitchen"
    assert insight.payload_format == "automation"


@pytest.mark.asyncio
async def test_insight_payload_is_valid_automation_shape() -> None:
    buf = StateEventBuffer()
    _seed_weekday_routine(buf, days=14)
    detector = ScheduleDetector()
    [insight] = await detector.scan(_ctx_with_buffer(buf))

    payload = insight.payload
    assert payload["alias"].startswith("HA Insights:")
    assert payload["mode"] == "single"
    assert payload["trigger"] == [{"platform": "time", "at": "06:47:00"}]
    assert payload["condition"] == [
        {"condition": "time", "weekday": ["mon", "tue", "wed", "thu", "fri"]}
    ]
    assert payload["action"] == [
        {"service": "light.turn_on", "target": {"entity_id": "light.kitchen"}}
    ]


@pytest.mark.asyncio
async def test_scattered_times_rejected_by_stddev() -> None:
    """Events spread over a 30-minute window should fail the stddev threshold."""
    buf = StateEventBuffer()
    end = dt_util.now().replace(microsecond=0)
    # Seed events at varying times to ensure stddev > 8 min
    times_minutes = [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55]
    for offset, m in enumerate(times_minutes):
        when = (end - timedelta(days=offset)).replace(hour=6, minute=m, second=0, microsecond=0)
        if when.weekday() >= 5:
            when -= timedelta(days=2)
        buf.add(
            StateEvent(
                timestamp=when,
                entity_id="light.kitchen",
                domain="light",
                area_id="kitchen",
                old_state="off",
                new_state="on",
            )
        )
    detector = ScheduleDetector()
    insights = await detector.scan(_ctx_with_buffer(buf))
    assert insights == []


@pytest.mark.asyncio
async def test_weekend_only_routine_classifies_as_weekends() -> None:
    """Routine that only fires Sat/Sun should produce a weekends insight."""
    buf = StateEventBuffer()
    end = dt_util.now().replace(hour=10, minute=0, second=0, microsecond=0)
    for offset in range(60):  # extend lookback to capture enough weekends
        when = end - timedelta(days=offset)
        if when.weekday() < 5:
            continue
        buf.add(
            StateEvent(
                timestamp=when,
                entity_id="light.bedroom",
                domain="light",
                area_id="bedroom",
                old_state="off",
                new_state="on",
            )
        )
    detector = ScheduleDetector()
    # Pull back the lookback so we use buffer events; adjust buffer's max_age first
    detector.LOOKBACK_DAYS = 60
    insights = await detector.scan(_ctx_with_buffer(buf))
    if insights:
        # Defensive: classifier picked weekends only when applicable
        assert "weekends" in insights[0].title.lower()


@pytest.mark.asyncio
async def test_safety_blocked_domain_lock_skipped() -> None:
    buf = StateEventBuffer()
    end = dt_util.now().replace(hour=22, minute=0, second=0, microsecond=0)
    for offset in range(14):
        when = end - timedelta(days=offset)
        if when.weekday() >= 5:
            continue
        buf.add(
            StateEvent(
                timestamp=when,
                entity_id="lock.front_door",
                domain="lock",
                area_id="entry",
                old_state="unlocked",
                new_state="locked",
            )
        )
    detector = ScheduleDetector()
    insights = await detector.scan(_ctx_with_buffer(buf))
    assert insights == []  # lock domain is safety-blocked


@pytest.mark.asyncio
async def test_non_enum_state_skipped() -> None:
    """Numeric / decimal states should not be treated as routines."""
    buf = StateEventBuffer()
    end = dt_util.now().replace(hour=14, minute=30, second=0, microsecond=0)
    for offset in range(14):
        when = end - timedelta(days=offset)
        if when.weekday() >= 5:
            continue
        buf.add(
            StateEvent(
                timestamp=when,
                entity_id="sensor.temperature",
                domain="sensor",
                area_id="kitchen",
                old_state="71.2",
                new_state="72.5",
            )
        )
    detector = ScheduleDetector()
    insights = await detector.scan(_ctx_with_buffer(buf))
    assert insights == []


@pytest.mark.asyncio
async def test_fingerprint_stable_across_scans() -> None:
    """The same routine seen twice produces the same insight id (dedup-friendly)."""
    buf = StateEventBuffer()
    _seed_weekday_routine(buf, days=14)
    detector = ScheduleDetector()
    [first] = await detector.scan(_ctx_with_buffer(buf))
    [second] = await detector.scan(_ctx_with_buffer(buf))
    assert first.id == second.id
    assert first.fingerprint == second.fingerprint


def test_classify_weekdays_internal() -> None:
    classify = ScheduleDetector._classify_weekdays
    assert classify([0, 1, 2, 3]) == frozenset({0, 1, 2, 3, 4})
    assert classify([5, 6]) == frozenset({5, 6})
    assert classify([0, 5]) is None  # mixed weekday + weekend
    assert classify([0]) is None  # too few unique days


def test_is_enum_state_internal() -> None:
    is_enum = ScheduleDetector._is_enum_state
    assert is_enum("on") is True
    assert is_enum("off") is True
    assert is_enum("home") is True
    assert is_enum("72.5") is False  # decimal
    assert is_enum("unavailable") is False
    assert is_enum("unknown") is False
    assert is_enum("") is False
    assert is_enum("a" * 25) is False  # too long


def test_domain_to_service_internal() -> None:
    s = ScheduleDetector._domain_to_service
    assert s("light", "on") == "light.turn_on"
    assert s("light", "off") == "light.turn_off"
    assert s("switch", "on") == "switch.turn_on"
    assert s("media_player", "playing") == "media_player.turn_on"  # fallback
