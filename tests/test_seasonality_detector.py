"""Tests for SeasonalityDetector (v0.9 phase 4).

Events are stored as UTC inside the StateEventBuffer (production passes
UTC timestamps from HA's state_changed events). Detectors convert to
HA's local timezone before bucketing — so test setup builds events in
LOCAL time (.weekday() / .replace(hour=...)) then converts to UTC for
storage. dt_util.now() returns the test env's local time; helpers walk
back by local weekday so "Friday at 7pm" tests behave identically
regardless of the host's TZ.
"""
from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from unittest.mock import MagicMock

import pytest
from homeassistant.util import dt as dt_util

from custom_components.ha_insights.detectors.base import DetectorContext
from custom_components.ha_insights.detectors.seasonality import SeasonalityDetector
from custom_components.ha_insights.insight import InsightKind
from custom_components.ha_insights.observers.state_event_buffer import (
    StateEvent,
    StateEventBuffer,
)


def _ctx(buf: StateEventBuffer) -> DetectorContext:
    return DetectorContext(hass=MagicMock(), event_buffer=buf)


def _ev(ts: datetime, entity_id: str, new_state: str = "on") -> StateEvent:
    return StateEvent(
        timestamp=ts,
        entity_id=entity_id,
        domain=entity_id.split(".", 1)[0],
        area_id=None,
        old_state="off",
        new_state=new_state,
    )


def _last_n_weekdays(target_weekday: int, n: int, base: datetime) -> list[datetime]:
    """Return the last `n` occurrences of `target_weekday` (0=Mon) prior to base.

    `base` and returned datetimes are in HA's local timezone — callers
    must `.astimezone(UTC)` before passing to buf.add() since the buffer
    stores UTC timestamps just like the production state_changed listener.
    """
    out: list[datetime] = []
    cur = base
    while len(out) < n:
        if cur.weekday() == target_weekday:
            out.append(cur)
        cur -= timedelta(days=1)
    return out


def _to_utc(dt: datetime) -> datetime:
    """Convert a tz-aware local-time datetime to UTC for buffer storage."""
    return dt.astimezone(UTC)


# v1.12.12: deterministic per-event second-jitter. SeasonalityDetector
# now suppresses patterns with stddev <15s (the fingerprint of a Tuya
# weekly schedule), so test fixtures need natural human variance.
# Pattern sums to 0 over each 5-element window so the AVERAGE second
# is 0 — preserves existing "19:30"/"Friday" substring assertions
# regardless of fixture length.
_JITTER_SECONDS = [30, -30, 15, -15, 0]


def _jitter(dt: datetime, i: int) -> datetime:
    """Apply a deterministic per-index second offset so test fixtures
    clear the new robotic-precision gate while staying reproducible."""
    return dt + timedelta(seconds=_JITTER_SECONDS[i % len(_JITTER_SECONDS)])


# --- Empty / no-op ---


@pytest.mark.asyncio
async def test_no_buffer_returns_empty() -> None:
    detector = SeasonalityDetector()
    ctx = DetectorContext(hass=MagicMock(), event_buffer=None)
    assert await detector.scan(ctx) == []


@pytest.mark.asyncio
async def test_too_few_events() -> None:
    """Below MIN_DOMINANT_HITS=3 -> no insight."""
    buf = StateEventBuffer(max_age=timedelta(days=40))
    base = dt_util.now().replace(microsecond=0)
    fridays = _last_n_weekdays(4, 2, base)
    for d in fridays:
        buf.add(_ev(_to_utc(d.replace(hour=19, minute=30)), "media_player.living_room"))
    detector = SeasonalityDetector()
    assert await detector.scan(_ctx(buf)) == []


# --- Detection ---


@pytest.mark.asyncio
async def test_strict_friday_pattern_detected() -> None:
    """4 Fridays at 7pm => strong weekly pattern."""
    buf = StateEventBuffer(max_age=timedelta(days=40))
    base = dt_util.now().replace(microsecond=0)
    fridays = _last_n_weekdays(4, 4, base)  # weekday 4 = Friday
    for i, d in enumerate(fridays):
        buf.add(_ev(_to_utc(_jitter(d.replace(hour=19, minute=30), i)), "media_player.living_room"))
    detector = SeasonalityDetector()
    insights = await detector.scan(_ctx(buf))
    assert len(insights) == 1
    insight = insights[0]
    assert insight.kind is InsightKind.AUTOMATION_PROPOSAL
    assert insight.detector == "seasonality"
    assert insight.payload_format == "automation"
    assert "Friday" in insight.title
    # Time trigger landed within ~5 min of 19:30
    trigger_time = insight.payload["trigger"][0]["at"]
    assert trigger_time.startswith("19:")
    # Weekday condition pinned to Friday
    weekdays = insight.payload["condition"][0]["weekday"]
    assert weekdays == ["fri"]


@pytest.mark.asyncio
async def test_dominance_ratio_filter() -> None:
    """If non-Friday firings are >30% of total, skip — not a clean weekly pattern."""
    buf = StateEventBuffer(max_age=timedelta(days=40))
    base = dt_util.now().replace(microsecond=0)
    # 3 Fridays + 3 random other days (50/50)
    fridays = _last_n_weekdays(4, 3, base)
    for d in fridays:
        buf.add(_ev(_to_utc(d.replace(hour=19)), "switch.party"))
    # 3 Tuesdays
    tuesdays = _last_n_weekdays(1, 3, base)
    for d in tuesdays:
        buf.add(_ev(_to_utc(d.replace(hour=19)), "switch.party"))
    detector = SeasonalityDetector()
    assert await detector.scan(_ctx(buf)) == []


@pytest.mark.asyncio
async def test_loose_time_drift_within_30min() -> None:
    """Saturday 7pm, 7:15, 7:30, 8pm => stddev ~22 min, still emits."""
    buf = StateEventBuffer(max_age=timedelta(days=40))
    base = dt_util.now().replace(microsecond=0)
    saturdays = _last_n_weekdays(5, 4, base)
    times = [time(19, 0), time(19, 15), time(19, 30), time(20, 0)]
    for d, t in zip(saturdays, times, strict=True):
        buf.add(_ev(_to_utc(d.replace(hour=t.hour, minute=t.minute)), "switch.bbq"))
    detector = SeasonalityDetector()
    insights = await detector.scan(_ctx(buf))
    assert len(insights) == 1
    assert "Saturday" in insights[0].title


@pytest.mark.asyncio
async def test_excessive_time_drift_rejected() -> None:
    """Sunday 9am, 12pm, 3pm, 9pm => stddev > 30 min, no pattern."""
    buf = StateEventBuffer(max_age=timedelta(days=40))
    base = dt_util.now().replace(microsecond=0)
    sundays = _last_n_weekdays(6, 4, base)
    hours = [9, 12, 15, 21]
    for d, h in zip(sundays, hours, strict=True):
        buf.add(_ev(_to_utc(d.replace(hour=h, minute=0)), "light.porch"))
    detector = SeasonalityDetector()
    assert await detector.scan(_ctx(buf)) == []


@pytest.mark.asyncio
async def test_blocked_domain_skipped() -> None:
    """device_tracker is in domains_default_blocked => never emit."""
    buf = StateEventBuffer(max_age=timedelta(days=40))
    base = dt_util.now().replace(microsecond=0)
    fridays = _last_n_weekdays(4, 4, base)
    for d in fridays:
        buf.add(_ev(_to_utc(d.replace(hour=18)), "device_tracker.car", "home"))
    detector = SeasonalityDetector()
    assert await detector.scan(_ctx(buf)) == []


@pytest.mark.asyncio
async def test_idempotent_rescan() -> None:
    """Two scans on the same data => same insight id."""
    buf = StateEventBuffer(max_age=timedelta(days=40))
    base = dt_util.now().replace(microsecond=0)
    fridays = _last_n_weekdays(4, 4, base)
    for i, d in enumerate(fridays):
        buf.add(_ev(_to_utc(_jitter(d.replace(hour=19, minute=30), i)), "switch.movie_lights"))
    detector = SeasonalityDetector()
    first = await detector.scan(_ctx(buf))
    second = await detector.scan(_ctx(buf))
    assert len(first) == 1 and len(second) == 1
    assert first[0].id == second[0].id


@pytest.mark.asyncio
async def test_scheduledetector_overlap_skipped() -> None:
    """Daily 7pm event triggers ScheduleDetector but not Seasonality.

    SeasonalityDetector should only fire on patterns where ONE weekday
    dominates. Daily firings have all 7 weekdays equally represented;
    no dominance, no insight.
    """
    buf = StateEventBuffer(max_age=timedelta(days=40))
    base = dt_util.now().replace(microsecond=0)
    # 14 daily events at LOCAL 19:00, stored as UTC
    for i in range(14):
        local_ts = (base - timedelta(days=i)).replace(hour=19, minute=0)
        buf.add(_ev(_to_utc(local_ts), "light.evening"))
    detector = SeasonalityDetector()
    assert await detector.scan(_ctx(buf)) == []
