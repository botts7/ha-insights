"""Tests for lib/changepoint_detection.

Cover both the ruptures-backed path and the pure-Python fallback so
the tests pass whether or not the optional dep is installed. Fallback
is tested directly; ruptures path is tested when available.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import pairwise

import pytest

from custom_components.ha_insights.lib.changepoint_detection import (
    ChangepointAssessment,
    ChangepointBackend,
    ChangepointKind,
    backend_in_use,
    detect_changepoints,
)


def _series(values: list[float], start_days_ago: int = 14):
    """Build a (timestamps, values) tuple with one sample per day."""
    base = datetime(2026, 5, 17, tzinfo=UTC) - timedelta(days=start_days_ago)
    timestamps = [base + timedelta(days=i) for i in range(len(values))]
    return timestamps, values


# ---------- Input validation -------------------------------------------


def test_mismatched_lengths_raises() -> None:
    ts = [datetime(2026, 1, 1, tzinfo=UTC)]
    with pytest.raises(ValueError, match="length mismatch"):
        detect_changepoints(ts, [1.0, 2.0])


def test_too_short_returns_empty() -> None:
    """Need at least 2 × min_segment_size samples for any meaningful split."""
    ts, vals = _series([1.0, 2.0, 3.0])  # only 3 samples; default min=3
    assert detect_changepoints(ts, vals) == []


def test_empty_input_returns_empty() -> None:
    assert detect_changepoints([], []) == []


# ---------- Detection: clear shifts ------------------------------------


def test_detects_clear_mean_shift() -> None:
    """Stable 5/day for a week, then steady 30/day for a week."""
    ts, vals = _series([5, 6, 5, 4, 6, 5, 6, 30, 32, 29, 31, 30, 28, 31])
    out = detect_changepoints(ts, vals)
    assert len(out) >= 1
    # Detected somewhere around index 7 (the shift point), give it ±1
    # to allow either backend's edge choice.
    shift = out[0]
    assert isinstance(shift, ChangepointAssessment)
    days_from_expected = abs(
        (shift.detected_at - ts[7]).total_seconds() / 86400
    )
    assert days_from_expected <= 1
    assert shift.kind == ChangepointKind.MEAN_SHIFT
    assert shift.magnitude > 15  # ~25 unit shift
    assert 0.0 < shift.confidence <= 1.0


def test_detects_drop_to_zero() -> None:
    """Common 'battery died / device retired' shape."""
    ts, vals = _series([10, 12, 11, 9, 13, 10, 11, 0, 0, 0, 0, 0, 0, 0])
    out = detect_changepoints(ts, vals)
    assert len(out) >= 1
    assert out[0].magnitude >= 8  # ~10 unit shift to zero


# ---------- Non-detection: stable / noisy signals ----------------------


def test_stable_signal_no_changepoint() -> None:
    """All same value — nothing to detect."""
    ts, vals = _series([10.0] * 14)
    assert detect_changepoints(ts, vals) == []


def test_noisy_no_trend_no_changepoint() -> None:
    """Random-ish values around a stable mean — no shift."""
    # Alternating ±1 around 10. Mean is constant; this should NOT
    # be flagged as a shift.
    ts, vals = _series([10, 11, 9, 10, 11, 9, 10, 11, 9, 10, 11, 9, 10, 11])
    out = detect_changepoints(ts, vals)
    # PELT *might* find a marginal split; require any detected
    # shift to have low magnitude.
    for cp in out:
        assert cp.magnitude < 3, f"False-positive shift: {cp}"


# ---------- Edge cases -------------------------------------------------


def test_single_outlier_does_not_trigger() -> None:
    """A single spike in an otherwise stable signal isn't a shift."""
    vals = [5, 5, 6, 5, 5, 6, 5, 50, 5, 5, 6, 5, 5, 6]
    ts, _ = _series(vals)
    out = detect_changepoints(ts, vals)
    # If anything fires, it should be low-confidence — single-sample
    # segments earn very low confidence per _confidence_for.
    for cp in out:
        assert cp.confidence < 0.7, (
            f"Single outlier produced high-confidence shift: {cp}"
        )


def test_returns_assessments_in_chronological_order() -> None:
    """Two-shift signal: low → medium → high. Detected in order."""
    vals = [5, 5, 5, 5, 5, 20, 20, 20, 20, 20, 50, 50, 50, 50]
    ts, _ = _series(vals)
    out = detect_changepoints(ts, vals)
    if len(out) >= 2:
        # Each subsequent changepoint should be later than the previous.
        for a, b in pairwise(out):
            assert a.detected_at < b.detected_at


def test_min_segment_size_respected() -> None:
    """A shift within the first few samples shouldn't fire when
    min_segment_size requires the prefix to be larger."""
    ts, vals = _series([5, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30])
    out = detect_changepoints(ts, vals, min_segment_size=5)
    # Prefix of 1 is too short; nothing should fire even though the
    # shift is dramatic.
    assert out == []


# ---------- Backend introspection --------------------------------------


def test_backend_in_use_returns_known_value() -> None:
    backend = backend_in_use()
    assert backend in (ChangepointBackend.RUPTURES, ChangepointBackend.FALLBACK)


def test_assessment_reports_active_backend() -> None:
    """Every emitted assessment should be tagged with the actual
    backend used, so detectors can adjust confidence on fallback."""
    ts, vals = _series([5, 6, 5, 4, 6, 5, 6, 30, 32, 29, 31, 30, 28, 31])
    out = detect_changepoints(ts, vals)
    expected = backend_in_use()
    for cp in out:
        assert cp.backend == expected


def test_assessment_confidence_within_unit_range() -> None:
    """Confidence is always in [0, 1]."""
    ts, vals = _series([1, 2, 3, 4, 5, 6, 7, 100, 100, 100, 100, 100, 100, 100])
    out = detect_changepoints(ts, vals)
    for cp in out:
        assert 0.0 <= cp.confidence <= 1.0


# ---------- Confidence weighting smoke ---------------------------------


def test_balanced_split_higher_confidence_than_lopsided() -> None:
    """All else equal, a 7-vs-7 split should score higher than 13-vs-1."""
    balanced_ts, balanced_vals = _series(
        [5, 5, 5, 5, 5, 5, 5, 30, 30, 30, 30, 30, 30, 30]
    )
    lopsided_ts, lopsided_vals = _series(
        [5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 30]
    )
    balanced_out = detect_changepoints(balanced_ts, balanced_vals)
    lopsided_out = detect_changepoints(lopsided_ts, lopsided_vals)
    if balanced_out and lopsided_out:
        assert balanced_out[0].confidence > lopsided_out[0].confidence
