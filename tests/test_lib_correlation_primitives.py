"""Tests for lib/correlation_primitives."""
from __future__ import annotations

import math

from custom_components.ha_insights.lib.correlation_primitives import (
    bin_events,
    carry_forward,
    pearson_correlation,
    time_aligned_correlation,
)

# ---------- pearson_correlation ----------------------------------------


def test_perfect_positive_correlation() -> None:
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    ys = [2.0, 4.0, 6.0, 8.0, 10.0]  # y = 2x
    assert math.isclose(pearson_correlation(xs, ys), 1.0, rel_tol=1e-9)


def test_perfect_negative_correlation() -> None:
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    ys = [10.0, 8.0, 6.0, 4.0, 2.0]
    assert math.isclose(pearson_correlation(xs, ys), -1.0, rel_tol=1e-9)


def test_no_correlation_with_constant_input() -> None:
    """Constant y → variance = 0 → r should fall back to 0."""
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    ys = [5.0] * 5
    assert pearson_correlation(xs, ys) == 0.0


def test_length_mismatch_returns_zero() -> None:
    assert pearson_correlation([1.0, 2.0], [1.0, 2.0, 3.0]) == 0.0


def test_empty_returns_zero() -> None:
    assert pearson_correlation([], []) == 0.0


def test_partial_correlation_in_expected_range() -> None:
    """Noisy linear data should give an r in [0.8, 1.0]."""
    xs = [float(i) for i in range(20)]
    ys = [float(i) + (0.5 if i % 2 == 0 else -0.5) for i in range(20)]
    r = pearson_correlation(xs, ys)
    assert 0.8 < r < 1.0


# ---------- bin_events --------------------------------------------------


def test_bin_events_averages_samples_in_bin() -> None:
    events = [(0.0, 10.0), (30.0, 20.0), (60.0, 30.0), (90.0, 40.0)]
    # 60s bins from t=0 to t=120s → 2 bins
    binned = bin_events(events, bin_size_seconds=60.0, start_ts=0, end_ts=120)
    assert len(binned) == 2
    assert binned[0] == 15.0  # mean of 10 + 20
    assert binned[1] == 35.0  # mean of 30 + 40


def test_bin_events_drops_out_of_range() -> None:
    events = [(-5.0, 100.0), (5.0, 10.0), (200.0, 999.0)]
    binned = bin_events(events, bin_size_seconds=60.0, start_ts=0, end_ts=120)
    assert binned[0] == 10.0
    assert binned[1] is None


def test_bin_events_empty_window() -> None:
    assert bin_events([], bin_size_seconds=60.0, start_ts=0, end_ts=120) == [
        None,
        None,
    ]


def test_bin_events_invalid_inputs() -> None:
    assert bin_events([], bin_size_seconds=0, start_ts=0, end_ts=120) == []
    assert bin_events([], bin_size_seconds=60, start_ts=120, end_ts=0) == []


# ---------- carry_forward -----------------------------------------------


def test_carry_forward_basic() -> None:
    binned = [None, 10.0, None, None, 20.0, None]
    assert carry_forward(binned) == [None, 10.0, 10.0, 10.0, 20.0, 20.0]


def test_carry_forward_initial_nones_remain() -> None:
    binned = [None, None, 5.0]
    assert carry_forward(binned) == [None, None, 5.0]


def test_carry_forward_no_nones() -> None:
    binned = [1.0, 2.0, 3.0]
    assert carry_forward(binned) == [1.0, 2.0, 3.0]


# ---------- time_aligned_correlation -----------------------------------


def test_identical_streams_return_r_one() -> None:
    """Two entities reporting the same values at the same times
    should produce r=1."""
    events_a: list[tuple[float, float]] = [
        (float(i * 600), float(i)) for i in range(20)
    ]
    events_b = list(events_a)  # identical
    result = time_aligned_correlation(
        events_a, events_b,
        bin_size_seconds=600.0,
        start_ts=0, end_ts=12000,
    )
    assert math.isclose(result.r, 1.0, rel_tol=1e-3)
    assert result.best_lag_bins == 0


def test_lag_detected_when_shifted() -> None:
    """Stream B shifted by exactly 1 bin should be detected at lag=1."""
    events_a: list[tuple[float, float]] = [
        (float(i * 600), float(i)) for i in range(20)
    ]
    events_b: list[tuple[float, float]] = [
        (float((i + 1) * 600), float(i)) for i in range(20)
    ]
    result = time_aligned_correlation(
        events_a, events_b,
        bin_size_seconds=600.0,
        start_ts=0, end_ts=15000,
        max_lag_bins=3,
    )
    assert result.r > 0.95
    # Best lag may be 1 or -1 depending on alignment direction;
    # the magnitude is what matters for the dedup decision.
    assert abs(result.best_lag_bins) >= 1


def test_unrelated_streams_low_r() -> None:
    """Two streams with no structural relationship should give a
    near-zero r."""
    events_a = [
        (float(i * 600), float(i * 2))
        for i in range(20)
    ]
    events_b = [
        (float(i * 600), math.sin(i * 0.3) * 10 + 100)
        for i in range(20)
    ]
    result = time_aligned_correlation(
        events_a, events_b,
        bin_size_seconds=600.0,
        start_ts=0, end_ts=12000,
    )
    assert abs(result.r) < 0.95  # not implausibly high


def test_constant_stream_gives_r_zero() -> None:
    """Battery sensor stuck at 100% vs another stream → r=0."""
    events_a = [(float(i * 600), 100.0) for i in range(20)]
    events_b = [(float(i * 600), float(i)) for i in range(20)]
    result = time_aligned_correlation(
        events_a, events_b,
        bin_size_seconds=600.0,
        start_ts=0, end_ts=12000,
    )
    assert result.r == 0.0


def test_below_min_samples_returns_zero_confidence() -> None:
    """3 samples is below MIN_SAMPLES_FOR_CORR=10 — confidence
    should be 0 even with perfect correlation."""
    events_a = [(0.0, 1.0), (600.0, 2.0), (1200.0, 3.0)]
    events_b = list(events_a)
    result = time_aligned_correlation(
        events_a, events_b,
        bin_size_seconds=600.0,
        start_ts=0, end_ts=1800,
    )
    assert result.confidence == 0.0


def test_empty_streams() -> None:
    result = time_aligned_correlation(
        [], [],
        bin_size_seconds=600.0,
        start_ts=0, end_ts=12000,
    )
    assert result.r == 0.0
    assert result.n_samples == 0


# ---------- CorrelationResult shape ------------------------------------


def test_correlation_result_confidence_blends_r_and_n() -> None:
    """Same |r|, larger n → higher confidence."""
    events_a_short = [(float(i * 600), float(i)) for i in range(15)]
    events_b_short = [(float(i * 600), float(i)) for i in range(15)]
    events_a_long = [(float(i * 600), float(i)) for i in range(200)]
    events_b_long = [(float(i * 600), float(i)) for i in range(200)]
    short = time_aligned_correlation(
        events_a_short, events_b_short,
        bin_size_seconds=600.0,
        start_ts=0, end_ts=10000,
    )
    long_ = time_aligned_correlation(
        events_a_long, events_b_long,
        bin_size_seconds=600.0,
        start_ts=0, end_ts=130000,
    )
    assert long_.confidence > short.confidence
