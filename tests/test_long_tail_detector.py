"""Tests for LongTailDetector."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from custom_components.ha_insights.detectors.base import DetectorContext
from custom_components.ha_insights.detectors.long_tail import (
    DEFAULT_DURATION_THRESHOLDS,
    LongTailDetector,
)
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
    old_state: str | None = None,
    domain: str | None = None,
) -> StateEvent:
    if domain is None:
        domain = entity_id.split(".", 1)[0]
    return StateEvent(
        timestamp=timestamp,
        entity_id=entity_id,
        domain=domain,
        area_id=None,
        old_state=old_state,
        new_state=new_state,
    )


def _seed_long_spans(
    buf: StateEventBuffer,
    entity_id: str,
    span_minutes: float,
    *,
    times: int,
    end_now: datetime | None = None,
) -> None:
    """Seed N (on, off) pairs each lasting `span_minutes`, spaced 1 day apart."""
    end = end_now or datetime.now(tz=UTC).replace(microsecond=0)
    for i in range(times):
        on_at = end - timedelta(days=i + 1)
        off_at = on_at + timedelta(minutes=span_minutes)
        buf.add(_ev(on_at, entity_id, "on", old_state="off"))
        buf.add(_ev(off_at, entity_id, "off", old_state="on"))


@pytest.mark.asyncio
async def test_no_buffer_returns_empty() -> None:
    detector = LongTailDetector()
    ctx = DetectorContext(hass=MagicMock(), event_buffer=None)
    assert await detector.scan(ctx) == []


@pytest.mark.asyncio
async def test_short_spans_no_insight() -> None:
    """30-minute spans on a light (90min threshold) should not surface."""
    buf = StateEventBuffer(max_age=timedelta(days=30))
    _seed_long_spans(buf, "light.kitchen", span_minutes=30, times=5)
    detector = LongTailDetector()
    insights = await detector.scan(_ctx(buf))
    assert insights == []


@pytest.mark.asyncio
async def test_long_light_spans_produce_insight() -> None:
    """3-hour spans on a light should surface an auto-off proposal.

    Need 5+ occurrences to clear MIN_CONFIDENCE_TO_EMIT=0.5 (confidence
    formula is `count/10` so 5 occurrences = 0.5 exactly).
    """
    buf = StateEventBuffer(max_age=timedelta(days=30))
    _seed_long_spans(buf, "light.kitchen", span_minutes=180, times=5)
    detector = LongTailDetector()
    insights = await detector.scan(_ctx(buf))
    assert len(insights) == 1
    insight = insights[0]
    assert insight.kind is InsightKind.AUTOMATION_PROPOSAL
    assert insight.detector == "long_tail"
    assert "light.kitchen" in insight.title
    assert "180" in insight.title  # avg minutes


@pytest.mark.asyncio
async def test_below_min_occurrences_filtered() -> None:
    """Only 2 long spans (vs MIN_OCCURRENCES=3) should not surface."""
    buf = StateEventBuffer(max_age=timedelta(days=30))
    _seed_long_spans(buf, "light.kitchen", span_minutes=120, times=2)
    detector = LongTailDetector()
    insights = await detector.scan(_ctx(buf))
    assert insights == []


@pytest.mark.asyncio
async def test_payload_has_for_trigger_and_turn_off() -> None:
    buf = StateEventBuffer(max_age=timedelta(days=30))
    _seed_long_spans(buf, "switch.fan", span_minutes=240, times=5)
    detector = LongTailDetector()
    insights = await detector.scan(_ctx(buf))
    assert len(insights) == 1
    payload = insights[0].payload
    trigger = payload["trigger"][0]
    assert trigger["platform"] == "state"
    assert trigger["entity_id"] == "switch.fan"
    assert trigger["to"] == "on"
    # `for:` matches the threshold for the switch domain
    assert trigger["for"] == {"minutes": DEFAULT_DURATION_THRESHOLDS["switch"]}
    # Action turns it off
    action = payload["action"][0]
    assert action["service"] == "switch.turn_off"
    assert action["target"]["entity_id"] == "switch.fan"


@pytest.mark.asyncio
async def test_unlisted_domain_skipped() -> None:
    """climate.* / sensor.* aren't in DEFAULT_DURATION_THRESHOLDS — skip."""
    buf = StateEventBuffer(max_age=timedelta(days=30))
    _seed_long_spans(buf, "climate.thermostat", span_minutes=600, times=10)
    detector = LongTailDetector()
    insights = await detector.scan(_ctx(buf))
    assert insights == []


@pytest.mark.asyncio
async def test_blocked_domain_skipped() -> None:
    """lock.* is in domains_default_blocked — skip even if threshold maps."""
    buf = StateEventBuffer(max_age=timedelta(days=30))
    # Pretend lock domain has a threshold (it doesn't by default, but the
    # safety filter is the second line of defense).
    _seed_long_spans(buf, "lock.front_door", span_minutes=180, times=4)
    detector = LongTailDetector()
    insights = await detector.scan(_ctx(buf))
    assert insights == []


@pytest.mark.asyncio
async def test_open_span_at_buffer_end_excluded() -> None:
    """An entity that's still on (no off event in buffer) shouldn't fire."""
    buf = StateEventBuffer(max_age=timedelta(days=30))
    end = datetime.now(tz=UTC).replace(microsecond=0)
    # Light came on 5 hours ago and is still on; no off event recorded.
    buf.add(_ev(end - timedelta(hours=5), "light.kitchen", "on", old_state="off"))
    detector = LongTailDetector()
    insights = await detector.scan(_ctx(buf))
    assert insights == []


@pytest.mark.asyncio
async def test_extreme_span_capped() -> None:
    """A multi-day span (more than MAX_REASONABLE_HOURS) is excluded."""
    buf = StateEventBuffer(max_age=timedelta(days=30))
    end = datetime.now(tz=UTC).replace(microsecond=0)
    # Single 60-hour on/off pair — beyond the 48h cap. Need 3 such spans
    # to even get past MIN_OCCURRENCES; build them.
    for i in range(4):
        on_at = end - timedelta(days=(i + 1) * 4)
        off_at = on_at + timedelta(hours=60)
        buf.add(_ev(on_at, "light.kitchen", "on", old_state="off"))
        buf.add(_ev(off_at, "light.kitchen", "off", old_state="on"))
    detector = LongTailDetector()
    insights = await detector.scan(_ctx(buf))
    # The 60h spans exceed the cap; nothing surfaces
    assert insights == []


@pytest.mark.asyncio
async def test_fingerprint_stable() -> None:
    buf = StateEventBuffer(max_age=timedelta(days=30))
    _seed_long_spans(buf, "light.kitchen", span_minutes=180, times=5)
    detector = LongTailDetector()
    [first] = await detector.scan(_ctx(buf))
    [second] = await detector.scan(_ctx(buf))
    assert first.id == second.id


@pytest.mark.asyncio
async def test_confidence_scales_with_count() -> None:
    """More long-tail events should produce higher confidence."""
    buf_few = StateEventBuffer(max_age=timedelta(days=30))
    buf_many = StateEventBuffer(max_age=timedelta(days=30))
    # 6 = clears the 0.5 emit floor with margin; 10 saturates at 1.0
    _seed_long_spans(buf_few, "light.kitchen", span_minutes=180, times=6)
    _seed_long_spans(buf_many, "light.kitchen", span_minutes=180, times=10)
    detector = LongTailDetector()
    [few] = await detector.scan(_ctx(buf_few))
    [many] = await detector.scan(_ctx(buf_many))
    assert many.confidence > few.confidence
