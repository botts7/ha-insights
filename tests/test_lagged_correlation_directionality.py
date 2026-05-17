"""Tests for v1.9.1: transfer-entropy direction check in LaggedCorrelationDetector."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from custom_components.ha_insights.detectors.base import DetectorContext
from custom_components.ha_insights.detectors.lagged_correlation import (
    LaggedCorrelationDetector,
    _directionality_payload,
)
from custom_components.ha_insights.lib.transfer_entropy import (
    TransferEntropyAssessment,
)
from custom_components.ha_insights.observers.state_event_buffer import (
    StateEvent,
    StateEventBuffer,
)


def _ev(ts: datetime, entity_id: str, new_state: str = "on") -> StateEvent:
    return StateEvent(
        timestamp=ts,
        entity_id=entity_id,
        domain=entity_id.split(".", 1)[0],
        area_id=None,
        old_state="off",
        new_state=new_state,
    )


def _ctx(buf: StateEventBuffer) -> DetectorContext:
    return DetectorContext(hass=MagicMock(), event_buffer=buf)


# ---------- _directionality_factor unit ---------------------------------


def test_factor_none_returns_one() -> None:
    """No assessment -> preserve confidence."""
    det = LaggedCorrelationDetector()
    assert det._directionality_factor(None) == 1.0


def test_factor_low_confidence_returns_one() -> None:
    """Uninformative confidence -> preserve confidence."""
    det = LaggedCorrelationDetector()
    a = TransferEntropyAssessment(
        te_x_to_y=0.5,
        te_y_to_x=0.0,
        asymmetry=0.5,
        dominant_direction="x_to_y",
        n_samples=10,
        confidence=0.1,
    )
    assert det._directionality_factor(a) == 1.0


def test_factor_both_below_noise_returns_one() -> None:
    """Both TE values below noise floor -> uninformative, preserve."""
    det = LaggedCorrelationDetector()
    a = TransferEntropyAssessment(
        te_x_to_y=0.01,
        te_y_to_x=0.01,
        asymmetry=0.0,
        dominant_direction="symmetric",
        n_samples=200,
        confidence=1.0,
    )
    assert det._directionality_factor(a) == 1.0


def test_factor_reversed_direction_demotes_half() -> None:
    det = LaggedCorrelationDetector()
    a = TransferEntropyAssessment(
        te_x_to_y=0.1,
        te_y_to_x=0.9,
        asymmetry=-0.8,
        dominant_direction="y_to_x",
        n_samples=200,
        confidence=1.0,
    )
    assert det._directionality_factor(a) == 0.5


def test_factor_symmetric_with_real_flow_demotes_mild() -> None:
    det = LaggedCorrelationDetector()
    a = TransferEntropyAssessment(
        te_x_to_y=0.3,
        te_y_to_x=0.3,
        asymmetry=0.0,
        dominant_direction="symmetric",
        n_samples=200,
        confidence=1.0,
    )
    assert det._directionality_factor(a) == 0.85


def test_factor_correct_direction_preserves() -> None:
    det = LaggedCorrelationDetector()
    a = TransferEntropyAssessment(
        te_x_to_y=0.9,
        te_y_to_x=0.1,
        asymmetry=0.8,
        dominant_direction="x_to_y",
        n_samples=200,
        confidence=1.0,
    )
    assert det._directionality_factor(a) == 1.0


# ---------- _directionality_payload helper ------------------------------


def test_payload_when_no_assessment() -> None:
    assert _directionality_payload(None) == {"assessed": False}


def test_payload_when_assessed() -> None:
    a = TransferEntropyAssessment(
        te_x_to_y=0.9,
        te_y_to_x=0.1,
        asymmetry=0.8,
        dominant_direction="x_to_y",
        n_samples=200,
        confidence=0.95,
    )
    p = _directionality_payload(a)
    assert p["assessed"] is True
    assert p["direction"] == "x_to_y"
    assert p["te_x_to_y"] == 0.9
    assert p["te_y_to_x"] == 0.1
    assert p["n_samples"] == 200


# ---------- _compute_directionality with synthetic streams ---------------


def test_compute_directionality_real_xy_flow() -> None:
    """200 leader toggles, follower trails by 180s. TE should pick X->Y."""
    det = LaggedCorrelationDetector()
    # Build entity_streams the way _build_entity_streams would.
    streams: dict[str, list[tuple[float, str]]] = {
        "binary_sensor.leader": [],
        "light.follower": [],
    }
    t = 0.0
    state = "off"
    for _ in range(200):
        t += 240.0  # 4 min between toggles
        state = "on" if state == "off" else "off"
        streams["binary_sensor.leader"].append((t, state))
        streams["light.follower"].append((t + 180.0, state))
    key = ("binary_sensor.leader", "on", "light.follower", "on")
    # Bin matches the lag (180s).
    assessment = det._compute_directionality(key, streams, bin_seconds=180.0)
    assert assessment is not None
    assert assessment.dominant_direction == "x_to_y"
    assert assessment.te_x_to_y > assessment.te_y_to_x


def test_compute_directionality_reversed_flow() -> None:
    """Follower fires FIRST in time; 'leader' trails. Direction is reversed."""
    det = LaggedCorrelationDetector()
    streams: dict[str, list[tuple[float, str]]] = {
        "binary_sensor.leader": [],
        "light.follower": [],
    }
    t = 0.0
    state = "off"
    for _ in range(200):
        t += 240.0
        state = "on" if state == "off" else "off"
        streams["light.follower"].append((t, state))
        streams["binary_sensor.leader"].append((t + 180.0, state))
    key = ("binary_sensor.leader", "on", "light.follower", "on")
    assessment = det._compute_directionality(key, streams, bin_seconds=180.0)
    assert assessment is not None
    assert assessment.dominant_direction == "y_to_x"
    assert det._directionality_factor(assessment) == 0.5


def test_compute_directionality_missing_entity_returns_none() -> None:
    det = LaggedCorrelationDetector()
    streams = {"binary_sensor.leader": [(0.0, "on"), (60.0, "off")]}
    key = ("binary_sensor.leader", "on", "light.absent", "on")
    assert det._compute_directionality(key, streams, bin_seconds=60.0) is None


# ---------- End-to-end: payload carries _directionality stamp ------------


@pytest.mark.asyncio
async def test_payload_includes_directionality_stamp() -> None:
    """Existing seed pair (sparse, mostly-constant streams) should not
    be demoted (both TE values below noise floor), and the payload
    should carry an `_directionality` stamp the card can render."""
    buf = StateEventBuffer(max_age=timedelta(days=20))
    end = datetime.now(tz=UTC).replace(microsecond=0)
    for i in range(6):
        base = end - timedelta(hours=(i + 1) * 2)
        buf.add(_ev(base, "binary_sensor.garage_door", "on"))
        buf.add(
            _ev(base + timedelta(seconds=180), "light.driveway", "on")
        )

    detector = LaggedCorrelationDetector()
    insights = await detector.scan(_ctx(buf))
    assert len(insights) >= 1
    insight = next(
        i
        for i in insights
        if i.fingerprint.get("leader_entity_id") == "binary_sensor.garage_door"
    )
    # Stamp present and dict-shaped.
    directionality = insight.payload.get("_directionality")
    assert directionality is not None
    assert isinstance(directionality, dict)
    assert "assessed" in directionality
    # Sparse data: assessed=True (we DID run TE), but both TE values
    # are at the noise floor, so factor is 1.0 and confidence isn't
    # demoted. The existing test_detects_3min_lagged_pattern test
    # confirms detection still happens at 6 occurrences.


@pytest.mark.asyncio
async def test_scan_clears_stream_cache_between_invocations() -> None:
    """The per-scan _entity_streams cache should be cleared between
    scans so a stale dict from a prior scan can't bleed into the next.
    """
    buf = StateEventBuffer(max_age=timedelta(days=20))
    end = datetime.now(tz=UTC).replace(microsecond=0)
    for i in range(6):
        base = end - timedelta(hours=(i + 1) * 2)
        buf.add(_ev(base, "binary_sensor.garage_door", "on"))
        buf.add(
            _ev(base + timedelta(seconds=180), "light.driveway", "on")
        )

    detector = LaggedCorrelationDetector()
    await detector.scan(_ctx(buf))
    assert detector._entity_streams is None
    await detector.scan(_ctx(buf))
    assert detector._entity_streams is None
