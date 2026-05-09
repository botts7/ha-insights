"""Tests for LaggedCorrelationDetector (v0.9 phase 5)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from custom_components.ha_insights.detectors.base import DetectorContext
from custom_components.ha_insights.detectors.lagged_correlation import (
    LaggedCorrelationDetector,
)
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


def _seed_lag_pair(
    buf: StateEventBuffer,
    *,
    times: int,
    delta_seconds: float,
    leader_eid: str = "binary_sensor.garage_door",
    follower_eid: str = "light.driveway",
) -> None:
    """Seed N (leader=on, then follower=on after delta_seconds) pairs."""
    end = datetime.now(tz=UTC).replace(microsecond=0)
    for i in range(times):
        base = end - timedelta(hours=(i + 1) * 2)  # space out 2h apart
        buf.add(_ev(base, leader_eid, "on"))
        buf.add(_ev(base + timedelta(seconds=delta_seconds), follower_eid, "on"))


# --- Empty / no-op ---


@pytest.mark.asyncio
async def test_no_buffer_returns_empty() -> None:
    detector = LaggedCorrelationDetector()
    ctx = DetectorContext(hass=MagicMock(), event_buffer=None)
    assert await detector.scan(ctx) == []


# --- Detection ---


@pytest.mark.asyncio
async def test_detects_3min_lagged_pattern() -> None:
    """Garage opens, driveway light follows ~3 min later, 5 times."""
    buf = StateEventBuffer(max_age=timedelta(days=20))
    _seed_lag_pair(buf, times=5, delta_seconds=180)
    detector = LaggedCorrelationDetector()
    insights = await detector.scan(_ctx(buf))
    assert len(insights) >= 1
    insight = next(
        i
        for i in insights
        if i.fingerprint.get("leader_entity_id") == "binary_sensor.garage_door"
    )
    assert insight.kind is InsightKind.AUTOMATION_PROPOSAL
    assert insight.detector == "lagged_correlation"
    # Title carries minute lag readout
    assert "3m" in insight.title or "180" in insight.title
    # Payload includes a delay step before the action
    actions = insight.payload["action"]
    assert any("delay" in step for step in actions)
    # The action service is in the second slot, after delay
    assert any("service" in step for step in actions)


@pytest.mark.asyncio
async def test_under_min_delta_no_insight() -> None:
    """20 second deltas are cooccurrence territory — lagged detector skips them."""
    buf = StateEventBuffer(max_age=timedelta(days=20))
    _seed_lag_pair(buf, times=5, delta_seconds=20)
    detector = LaggedCorrelationDetector()
    assert await detector.scan(_ctx(buf)) == []


@pytest.mark.asyncio
async def test_over_window_no_insight() -> None:
    """15 minutes is past the 10-min window — not flagged."""
    buf = StateEventBuffer(max_age=timedelta(days=20))
    _seed_lag_pair(buf, times=5, delta_seconds=15 * 60)
    detector = LaggedCorrelationDetector()
    assert await detector.scan(_ctx(buf)) == []


@pytest.mark.asyncio
async def test_below_min_occurrences_no_insight() -> None:
    """3 instances < MIN_OCCURRENCES=4."""
    buf = StateEventBuffer(max_age=timedelta(days=20))
    _seed_lag_pair(buf, times=3, delta_seconds=180)
    detector = LaggedCorrelationDetector()
    assert await detector.scan(_ctx(buf)) == []


# --- Coexistence with CooccurrenceDetector ---


def test_does_not_collide_with_cooccurrence_fingerprint() -> None:
    """Fingerprint includes a scale marker so the same entity pair can fire
    on both detectors without colliding on Insight.compute_id.
    """
    from custom_components.ha_insights.insight import Insight

    base_fingerprint = {
        "leader_entity_id": "binary_sensor.garage_door",
        "leader_state": "on",
        "follower_entity_id": "light.driveway",
        "follower_state": "on",
    }
    lagged_fingerprint = {**base_fingerprint, "scale": "lagged"}
    cooc_id = Insight.compute_id(InsightKind.AUTOMATION_PROPOSAL, base_fingerprint)
    lagged_id = Insight.compute_id(
        InsightKind.AUTOMATION_PROPOSAL, lagged_fingerprint
    )
    assert cooc_id != lagged_id


@pytest.mark.asyncio
async def test_idempotent_rescan() -> None:
    buf = StateEventBuffer(max_age=timedelta(days=20))
    _seed_lag_pair(buf, times=5, delta_seconds=180)
    detector = LaggedCorrelationDetector()
    first = await detector.scan(_ctx(buf))
    second = await detector.scan(_ctx(buf))
    assert {i.id for i in first} == {i.id for i in second}
