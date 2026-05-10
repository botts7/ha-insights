"""Tests for FrequencyAnomalyDetector (v0.9 phase 2).

Detector buckets by HA-local midnight (v1.0 timezone fix). Test setup
builds today_start as a LOCAL midnight, then converts to UTC for
buffer storage so the today/baseline split aligns with what the
detector computes.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from homeassistant.util import dt as dt_util

from custom_components.ha_insights.detectors.base import DetectorContext
from custom_components.ha_insights.detectors.frequency_anomaly import (
    FrequencyAnomalyDetector,
)
from custom_components.ha_insights.insight import InsightKind
from custom_components.ha_insights.observers.state_event_buffer import (
    StateEvent,
    StateEventBuffer,
)


def _ctx(buf: StateEventBuffer) -> DetectorContext:
    return DetectorContext(hass=MagicMock(), event_buffer=buf)


def _ev(timestamp: datetime, entity_id: str, new_state: str = "on") -> StateEvent:
    return StateEvent(
        timestamp=timestamp,
        entity_id=entity_id,
        domain=entity_id.split(".", 1)[0],
        area_id=None,
        old_state=None,
        new_state=new_state,
    )


def _seed_baseline(
    buf: StateEventBuffer,
    *,
    entity_id: str,
    today_start: datetime,
    daily: int,
    days: int,
) -> None:
    """Seed `daily` events on each of the prior `days` days (excluding today)."""
    for d in range(1, days + 1):
        day_anchor = today_start - timedelta(days=d)
        for k in range(daily):
            buf.add(_ev(day_anchor + timedelta(hours=k % 24, minutes=k), entity_id))


def _seed_today(
    buf: StateEventBuffer,
    *,
    entity_id: str,
    today_start: datetime,
    count: int,
) -> None:
    for k in range(count):
        buf.add(_ev(today_start + timedelta(minutes=k * 2), entity_id))


def _today_start(now: datetime) -> datetime:
    """Return today's local midnight as a UTC datetime for buffer comparison.

    Detector computes today_start_local then `.astimezone(UTC)`; tests
    must do the same so seeded events land on the right side of the
    today/baseline cut.
    """
    local_now = dt_util.as_local(now) if now.tzinfo else now
    today_start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return today_start_local.astimezone(UTC)


# --- Empty / no-op ---


@pytest.mark.asyncio
async def test_no_buffer_returns_empty() -> None:
    detector = FrequencyAnomalyDetector()
    ctx = DetectorContext(hass=MagicMock(), event_buffer=None)
    assert await detector.scan(ctx) == []


@pytest.mark.asyncio
async def test_empty_buffer_returns_empty() -> None:
    buf = StateEventBuffer(max_age=timedelta(days=30))
    detector = FrequencyAnomalyDetector()
    assert await detector.scan(_ctx(buf)) == []


# --- Detection ---


@pytest.mark.asyncio
async def test_detects_clear_spike() -> None:
    """Today fired 50x with a 2/day baseline => spike."""
    buf = StateEventBuffer(max_age=timedelta(days=30))
    today_start = _today_start(datetime.now(tz=UTC))
    _seed_baseline(
        buf,
        entity_id="binary_sensor.front_door",
        today_start=today_start,
        daily=2,
        days=13,
    )
    _seed_today(
        buf, entity_id="binary_sensor.front_door", today_start=today_start, count=50
    )
    detector = FrequencyAnomalyDetector()
    insights = await detector.scan(_ctx(buf))
    assert len(insights) == 1
    insight = insights[0]
    assert insight.kind is InsightKind.ANOMALY
    assert insight.detector == "frequency_anomaly"
    assert "binary_sensor.front_door" in insight.title
    assert insight.payload_format == "card"
    assert insight.payload["type"] == "history-graph"
    assert insight.payload["entities"] == ["binary_sensor.front_door"]
    # 50/2 = 25x ratio, well past the 10x ceiling for confidence
    assert insight.confidence == pytest.approx(1.0, abs=0.001)


@pytest.mark.asyncio
async def test_three_x_ratio_is_threshold() -> None:
    """3x baseline lands at confidence ~0.6 — the floor."""
    buf = StateEventBuffer(max_age=timedelta(days=30))
    today_start = _today_start(datetime.now(tz=UTC))
    # baseline 5/day => today needs >= 15 to clear 3x
    _seed_baseline(
        buf,
        entity_id="binary_sensor.motion",
        today_start=today_start,
        daily=5,
        days=13,
    )
    _seed_today(
        buf, entity_id="binary_sensor.motion", today_start=today_start, count=15
    )
    detector = FrequencyAnomalyDetector()
    insights = await detector.scan(_ctx(buf))
    assert len(insights) == 1
    assert insights[0].confidence == pytest.approx(0.6, abs=0.01)


# --- Filtering ---


@pytest.mark.asyncio
async def test_below_threshold_no_insight() -> None:
    """2x baseline doesn't cross the 3x bar."""
    buf = StateEventBuffer(max_age=timedelta(days=30))
    today_start = _today_start(datetime.now(tz=UTC))
    _seed_baseline(
        buf,
        entity_id="sensor.thermostat_a",
        today_start=today_start,
        daily=10,
        days=13,
    )
    _seed_today(
        buf, entity_id="sensor.thermostat_a", today_start=today_start, count=20
    )
    detector = FrequencyAnomalyDetector()
    assert await detector.scan(_ctx(buf)) == []


@pytest.mark.asyncio
async def test_min_today_count_floor() -> None:
    """A sleepy entity that suddenly fires 5x (still below MIN_TODAY_COUNT) is ignored."""
    buf = StateEventBuffer(max_age=timedelta(days=30))
    today_start = _today_start(datetime.now(tz=UTC))
    # 14 baseline events spread (1/day), today fires 5 (5x ratio but below floor)
    _seed_baseline(
        buf, entity_id="sensor.foo", today_start=today_start, daily=2, days=13
    )
    _seed_today(buf, entity_id="sensor.foo", today_start=today_start, count=5)
    detector = FrequencyAnomalyDetector()
    assert await detector.scan(_ctx(buf)) == []


@pytest.mark.asyncio
async def test_brand_new_entity_skipped() -> None:
    """New entity with no baseline shouldn't be flagged. Its ratio is undefined."""
    buf = StateEventBuffer(max_age=timedelta(days=30))
    today_start = _today_start(datetime.now(tz=UTC))
    _seed_today(
        buf,
        entity_id="binary_sensor.brand_new",
        today_start=today_start,
        count=100,
    )
    detector = FrequencyAnomalyDetector()
    assert await detector.scan(_ctx(buf)) == []


@pytest.mark.asyncio
async def test_blocked_domain_skipped() -> None:
    """device_tracker is in domains_default_blocked — privacy floor."""
    buf = StateEventBuffer(max_age=timedelta(days=30))
    today_start = _today_start(datetime.now(tz=UTC))
    _seed_baseline(
        buf,
        entity_id="device_tracker.phone",
        today_start=today_start,
        daily=2,
        days=13,
    )
    _seed_today(
        buf, entity_id="device_tracker.phone", today_start=today_start, count=50
    )
    detector = FrequencyAnomalyDetector()
    # device_tracker isn't even in _DEFAULT_DOMAINS for this detector
    assert await detector.scan(_ctx(buf)) == []


# --- Idempotency ---


@pytest.mark.asyncio
async def test_same_day_rescan_dedupes() -> None:
    """Two scans on the same data produce the same insight id."""
    buf = StateEventBuffer(max_age=timedelta(days=30))
    today_start = _today_start(datetime.now(tz=UTC))
    _seed_baseline(
        buf,
        entity_id="switch.basement_lights",
        today_start=today_start,
        daily=2,
        days=13,
    )
    _seed_today(
        buf, entity_id="switch.basement_lights", today_start=today_start, count=40
    )
    detector = FrequencyAnomalyDetector()
    first = await detector.scan(_ctx(buf))
    second = await detector.scan(_ctx(buf))
    assert len(first) == 1
    assert len(second) == 1
    assert first[0].id == second[0].id
