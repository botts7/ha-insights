"""Tests for RebootLoopDetector — v1.14.1.

Covers:
  - CV bucket boundaries (tight / clear / moderate / random)
  - The <48h median-gap sanity gate
  - The ≥5 transition minimum
  - Skip rules (blocked / excluded domain / wrong transition)
  - Payload structure (median_gap_human, observations, suggested_actions)
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from custom_components.ha_insights.detectors.base import DetectorContext
from custom_components.ha_insights.detectors.reboot_loop import (
    RebootLoopDetector,
    _format_duration,
    _suggested_actions,
)
from custom_components.ha_insights.insight import InsightKind
from custom_components.ha_insights.observers.state_event_buffer import (
    StateEvent,
    StateEventBuffer,
)


def _ctx(buf: StateEventBuffer | None) -> DetectorContext:
    """Build a context with a MagicMock hass + the given buffer.

    hass.states.get(entity_id) returns a MagicMock with .attributes={};
    that's enough for the detector's friendly_name fallback.
    """
    hass = MagicMock()
    # state.attributes is a real dict so .get("friendly_name") returns None.
    fake_state = MagicMock()
    fake_state.attributes = {}
    hass.states.get.return_value = fake_state
    return DetectorContext(hass=hass, event_buffer=buf)


def _flip_into_unavailable(
    timestamp: datetime,
    entity_id: str = "sensor.flaky",
    old_state: str = "on",
) -> StateEvent:
    return StateEvent(
        timestamp=timestamp,
        entity_id=entity_id,
        domain=entity_id.split(".", 1)[0],
        area_id=None,
        old_state=old_state,
        new_state="unavailable",
    )


def _seed_regular_flips(
    buf: StateEventBuffer,
    *,
    entity_id: str = "sensor.flaky",
    interval: timedelta,
    count: int,
    end: datetime | None = None,
) -> list[datetime]:
    """Add `count` flips spaced exactly `interval` apart."""
    if end is None:
        end = datetime.now(tz=UTC).replace(microsecond=0)
    times: list[datetime] = []
    for i in range(count):
        t = end - (count - 1 - i) * interval
        times.append(t)
        buf.add(_flip_into_unavailable(t, entity_id=entity_id))
    return times


def _seed_flips_with_gaps(
    buf: StateEventBuffer,
    *,
    entity_id: str = "sensor.flaky",
    gap_seconds: list[float],
    end: datetime | None = None,
) -> list[datetime]:
    """Add flips with explicit (potentially varying) gaps between them.

    Useful when a test needs the resulting CV to land in a specific
    band. `gap_seconds[i]` is the spacing between flip i and i+1.
    """
    if end is None:
        end = datetime.now(tz=UTC).replace(microsecond=0)
    times: list[datetime] = [end]
    for g in reversed(gap_seconds):
        times.append(times[-1] - timedelta(seconds=g))
    times.reverse()
    for t in times:
        buf.add(_flip_into_unavailable(t, entity_id=entity_id))
    return times


# ---------- Empty / null cases ---------------------------------------


@pytest.mark.asyncio
async def test_no_buffer_returns_empty() -> None:
    assert await RebootLoopDetector().scan(_ctx(None)) == []


@pytest.mark.asyncio
async def test_empty_buffer_returns_empty() -> None:
    buf = StateEventBuffer(max_age=timedelta(days=14))
    assert await RebootLoopDetector().scan(_ctx(buf)) == []


@pytest.mark.asyncio
async def test_below_min_transitions_returns_empty() -> None:
    """4 transitions isn't enough to trust a CV — skip."""
    buf = StateEventBuffer(max_age=timedelta(days=14))
    _seed_regular_flips(buf, interval=timedelta(hours=3), count=4)
    assert await RebootLoopDetector().scan(_ctx(buf)) == []


# ---------- Regularity buckets ---------------------------------------


@pytest.mark.asyncio
async def test_tightly_regular_high_confidence() -> None:
    """Exactly-regular cadence → CV ≈ 0 → tight bucket."""
    buf = StateEventBuffer(max_age=timedelta(days=14))
    _seed_regular_flips(buf, interval=timedelta(hours=3), count=10)
    insights = await RebootLoopDetector().scan(_ctx(buf))
    assert len(insights) == 1
    assert insights[0].kind == InsightKind.ANOMALY
    assert insights[0].confidence == pytest.approx(0.92)
    assert insights[0].payload["flips_count"] == 10
    assert insights[0].payload["cv"] == pytest.approx(0.0, abs=0.01)


@pytest.mark.asyncio
async def test_clearly_regular_medium_confidence() -> None:
    """CV in the 0.10–0.20 band → clear bucket → 0.80.

    Hand-crafted gaps so the CV lands precisely in-range. Gaps of
    [12000, 14400, 16800, 14400, 12000, 16800] s have mean 14400
    and pstdev ≈ 1960 → CV ≈ 0.136.
    """
    buf = StateEventBuffer(max_age=timedelta(days=14))
    _seed_flips_with_gaps(
        buf,
        gap_seconds=[12000, 14400, 16800, 14400, 12000, 16800],
    )
    insights = await RebootLoopDetector().scan(_ctx(buf))
    assert len(insights) == 1
    assert insights[0].confidence == pytest.approx(0.80)


@pytest.mark.asyncio
async def test_moderately_regular_low_confidence() -> None:
    """CV in the 0.20–0.30 band → moderate bucket → 0.65.

    Larger gap dispersion: [8000, 14400, 20800, 14400, 8000, 20800] s
    has mean 14400 and pstdev ≈ 5380 → CV ≈ 0.373 (too random).
    Tune down to [10000, 14400, 18800, 14400, 10000, 18800] which
    gives pstdev ≈ 3580 → CV ≈ 0.249.
    """
    buf = StateEventBuffer(max_age=timedelta(days=14))
    _seed_flips_with_gaps(
        buf,
        gap_seconds=[10000, 14400, 18800, 14400, 10000, 18800],
    )
    insights = await RebootLoopDetector().scan(_ctx(buf))
    assert len(insights) == 1
    assert insights[0].confidence == pytest.approx(0.65)


@pytest.mark.asyncio
async def test_random_spacing_not_flagged() -> None:
    """Non-regular Poisson-like spacing → CV > 0.30 → skip."""
    buf = StateEventBuffer(max_age=timedelta(days=14))
    end = datetime.now(tz=UTC).replace(microsecond=0)
    # Wildly-spaced flips to push CV above 0.30.
    offsets_minutes = [10, 60, 90, 300, 1200, 1800, 3000]
    for off in offsets_minutes:
        buf.add(_flip_into_unavailable(end - timedelta(minutes=off)))
    insights = await RebootLoopDetector().scan(_ctx(buf))
    assert insights == []


# ---------- Median-gap sanity gate -----------------------------------


@pytest.mark.asyncio
async def test_weekly_reboot_not_flagged_as_loop() -> None:
    """Regular but spaced >48h apart → intentional weekly maintenance."""
    buf = StateEventBuffer(max_age=timedelta(days=30))
    _seed_regular_flips(buf, interval=timedelta(days=3), count=6)
    insights = await RebootLoopDetector().scan(_ctx(buf))
    assert insights == []


# ---------- Skip rules -----------------------------------------------


@pytest.mark.asyncio
async def test_blocked_entity_not_flagged() -> None:
    buf = StateEventBuffer(max_age=timedelta(days=14))
    _seed_regular_flips(buf, interval=timedelta(hours=3), count=10, entity_id="sensor.private")
    hass = MagicMock()
    fake_state = MagicMock()
    fake_state.attributes = {}
    hass.states.get.return_value = fake_state
    ctx = DetectorContext(
        hass=hass,
        event_buffer=buf,
        blocked_entities=frozenset({"sensor.private"}),
    )
    assert await RebootLoopDetector().scan(ctx) == []


@pytest.mark.asyncio
async def test_excluded_domain_not_flagged() -> None:
    buf = StateEventBuffer(max_age=timedelta(days=14))
    _seed_regular_flips(buf, interval=timedelta(hours=3), count=10, entity_id="automation.flaky")
    assert await RebootLoopDetector().scan(_ctx(buf)) == []


@pytest.mark.asyncio
async def test_recovery_transitions_not_counted() -> None:
    """unavailable → on isn't a flip into unavailable; only count INTO."""
    buf = StateEventBuffer(max_age=timedelta(days=14))
    end = datetime.now(tz=UTC).replace(microsecond=0)
    # 10 recovery events — should NOT trigger.
    for i in range(10):
        buf.add(
            StateEvent(
                timestamp=end - timedelta(hours=3 * i),
                entity_id="sensor.x",
                domain="sensor",
                area_id=None,
                old_state="unavailable",
                new_state="on",
            )
        )
    assert await RebootLoopDetector().scan(_ctx(buf)) == []


@pytest.mark.asyncio
async def test_bootstrap_transition_not_counted() -> None:
    """old_state=None (boot fan-out / first-seen) doesn't count."""
    buf = StateEventBuffer(max_age=timedelta(days=14))
    end = datetime.now(tz=UTC).replace(microsecond=0)
    for i in range(10):
        buf.add(
            StateEvent(
                timestamp=end - timedelta(hours=3 * i),
                entity_id="sensor.x",
                domain="sensor",
                area_id=None,
                old_state=None,  # first observation, not a flip
                new_state="unavailable",
            )
        )
    assert await RebootLoopDetector().scan(_ctx(buf)) == []


# ---------- Payload structure ----------------------------------------


@pytest.mark.asyncio
async def test_payload_has_diagnostic_fields() -> None:
    buf = StateEventBuffer(max_age=timedelta(days=14))
    _seed_regular_flips(buf, interval=timedelta(hours=3), count=8)
    insights = await RebootLoopDetector().scan(_ctx(buf))
    assert len(insights) == 1
    p = insights[0].payload
    assert p["kind"] == "reboot_loop"
    assert p["flips_count"] == 8
    assert p["lookback_days"] == 7
    assert p["median_gap_minutes"] == pytest.approx(180, abs=1)
    assert "median_gap_human" in p
    assert isinstance(p["suggested_actions"], list)
    assert len(p["suggested_actions"]) >= 4
    assert p["observations"][0]["kind"] == "reboot_cadence"


@pytest.mark.asyncio
async def test_fingerprint_stable_across_scans() -> None:
    buf = StateEventBuffer(max_age=timedelta(days=14))
    _seed_regular_flips(buf, interval=timedelta(hours=3), count=10)
    first = await RebootLoopDetector().scan(_ctx(buf))
    second = await RebootLoopDetector().scan(_ctx(buf))
    assert first[0].id == second[0].id


# ---------- Helpers --------------------------------------------------


def test_format_duration_minutes() -> None:
    assert _format_duration(timedelta(minutes=45)) == "45 min"


def test_format_duration_hours() -> None:
    assert _format_duration(timedelta(hours=3)) == "3 h"
    assert _format_duration(timedelta(hours=3, minutes=15)) == "3 h 15 min"


def test_format_duration_days() -> None:
    assert _format_duration(timedelta(days=2)) == "2 d"
    assert _format_duration(timedelta(days=2, hours=6)) == "2 d 6 h"


def test_suggested_actions_includes_integration_log_hint() -> None:
    actions = _suggested_actions("shelly")
    assert any("shelly" in a for a in actions)


def test_suggested_actions_without_integration() -> None:
    actions = _suggested_actions(None)
    assert any("Settings" in a for a in actions)
