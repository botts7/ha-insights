"""Tests for StreakDetector."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from homeassistant.util import dt as dt_util

from custom_components.ha_insights.detectors.base import DetectorContext
from custom_components.ha_insights.detectors.streak import StreakDetector
from custom_components.ha_insights.insight import InsightKind
from custom_components.ha_insights.observers.state_event_buffer import (
    StateEvent,
    StateEventBuffer,
)


def _ctx(buf: StateEventBuffer) -> DetectorContext:
    return DetectorContext(hass=MagicMock(), event_buffer=buf)


def _ev(timestamp: datetime, entity_id: str, new_state: str) -> StateEvent:
    return StateEvent(
        timestamp=timestamp,
        entity_id=entity_id,
        domain=entity_id.split(".", 1)[0],
        area_id=None,
        old_state="off",
        new_state=new_state,
    )


def _seed_streak(
    buf: StateEventBuffer,
    entity_id: str,
    state: str,
    *,
    days: int,
    at_hour: int = 22,
    at_minute: int = 15,
    jitter_minutes: int = 0,
    end_now: datetime | None = None,
) -> None:
    """Seed `days` consecutive-day events at roughly the same time-of-day.

    Times are constructed in HA's local timezone so `at_hour`/`at_minute`
    describe the wall-clock value the detector will read (it uses
    `dt_util.as_local`). Stored as UTC to mirror the production
    state_changed listener.
    """
    end = end_now or dt_util.now().replace(microsecond=0)
    for i in range(days):
        when_local = (end - timedelta(days=i + 1)).replace(
            hour=at_hour,
            minute=at_minute + (i % 2) * jitter_minutes,
            second=0,
            microsecond=0,
        )
        buf.add(_ev(when_local.astimezone(UTC), entity_id, state))


@pytest.mark.asyncio
async def test_no_buffer_returns_empty() -> None:
    detector = StreakDetector()
    ctx = DetectorContext(hass=MagicMock(), event_buffer=None)
    assert await detector.scan(ctx) == []


@pytest.mark.asyncio
async def test_below_min_streak_no_insight() -> None:
    """2 consecutive days (< MIN_STREAK=3) doesn't fire."""
    buf = StateEventBuffer(max_age=timedelta(days=30))
    _seed_streak(buf, "light.kitchen", "on", days=2)
    detector = StreakDetector()
    insights = await detector.scan(_ctx(buf))
    assert insights == []


@pytest.mark.asyncio
async def test_three_day_streak_produces_insight() -> None:
    buf = StateEventBuffer(max_age=timedelta(days=30))
    _seed_streak(buf, "light.kitchen", "on", days=3)
    detector = StreakDetector()
    insights = await detector.scan(_ctx(buf))
    assert len(insights) == 1
    insight = insights[0]
    assert insight.kind is InsightKind.AUTOMATION_PROPOSAL
    assert insight.detector == "streak"
    assert "light.kitchen" in insight.title
    assert "3 days in a row" in insight.title


@pytest.mark.asyncio
async def test_payload_has_time_trigger_and_service() -> None:
    buf = StateEventBuffer(max_age=timedelta(days=30))
    _seed_streak(buf, "light.kitchen", "on", days=4, at_hour=22, at_minute=15)
    detector = StreakDetector()
    [insight] = await detector.scan(_ctx(buf))
    payload = insight.payload
    trigger = payload["trigger"][0]
    assert trigger["platform"] == "time"
    assert trigger["at"].startswith("22:1")  # ~22:15 (allow small drift)
    action = payload["action"][0]
    assert action["service"] == "light.turn_on"
    assert action["target"]["entity_id"] == "light.kitchen"


@pytest.mark.asyncio
async def test_strong_schedule_handed_off() -> None:
    """If the data is strong enough for ScheduleDetector, Streak skips it."""
    buf = StateEventBuffer(max_age=timedelta(days=30))
    # 10+ consecutive days, very tight time clustering — meets Schedule's bar
    _seed_streak(
        buf,
        "light.kitchen",
        "on",
        days=10,
        at_hour=22,
        at_minute=15,
        jitter_minutes=1,
    )
    detector = StreakDetector()
    insights = await detector.scan(_ctx(buf))
    # Streak hands this off to Schedule — we should NOT fire
    assert insights == []


@pytest.mark.asyncio
async def test_inconsistent_time_no_insight() -> None:
    """4-day streak but wildly varying time-of-day shouldn't fire."""
    buf = StateEventBuffer(max_age=timedelta(days=30))
    end = datetime.now(tz=UTC).replace(microsecond=0)
    # Days 1-4 with hours 6, 12, 18, 23 — too spread to be a routine
    for i, hour in enumerate([6, 12, 18, 23]):
        when = (end - timedelta(days=i + 1)).replace(
            hour=hour, minute=0, second=0, microsecond=0
        )
        buf.add(_ev(when, "light.kitchen", "on"))
    detector = StreakDetector()
    insights = await detector.scan(_ctx(buf))
    assert insights == []


@pytest.mark.asyncio
async def test_non_consecutive_days_no_streak() -> None:
    """3 events on days 1, 3, 5 — not a consecutive streak."""
    buf = StateEventBuffer(max_age=timedelta(days=30))
    end = datetime.now(tz=UTC).replace(microsecond=0)
    for offset in [1, 3, 5]:
        when = (end - timedelta(days=offset)).replace(
            hour=22, minute=15, second=0, microsecond=0
        )
        buf.add(_ev(when, "light.kitchen", "on"))
    detector = StreakDetector()
    insights = await detector.scan(_ctx(buf))
    assert insights == []


@pytest.mark.asyncio
async def test_blocked_domain_skipped() -> None:
    buf = StateEventBuffer(max_age=timedelta(days=30))
    _seed_streak(buf, "lock.front_door", "unlocked", days=4)
    detector = StreakDetector()
    insights = await detector.scan(_ctx(buf))
    assert insights == []


@pytest.mark.asyncio
async def test_fingerprint_stable() -> None:
    buf = StateEventBuffer(max_age=timedelta(days=30))
    _seed_streak(buf, "light.kitchen", "on", days=4)
    detector = StreakDetector()
    [first] = await detector.scan(_ctx(buf))
    [second] = await detector.scan(_ctx(buf))
    assert first.id == second.id
