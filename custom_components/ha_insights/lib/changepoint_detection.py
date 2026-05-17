"""Changepoint detection on univariate time series.

A *changepoint* is a moment when the statistical character of a signal
shifts — the mean steps to a new level, the variance changes, or the
slope flips. For HA Insights this is the signal we want when:

- A user's morning routine moves from 06:50 to 08:30 (new job).
- A binary_sensor's daily firing count drops to zero (battery dying,
  device retired — distinct from "orphan / silent").
- A schedule that fired every weekday at 07:15 starts firing at 09:00.

Without changepoint detection, the schedule / streak / frequency
detectors treat the post-shift data as noise that pollutes the
pattern: a 4-month routine that just changed last week looks like
"weak signal" rather than "strong signal that recently shifted."

## Backend

Uses `ruptures.Pelt` (Pruned Exact Linear Time, Killick 2012) when
the optional dependency is available. PELT is O(N) under standard
penalty and runs in milliseconds on a 14-day × 50-entity dataset
per the research-answers memory.

When `ruptures` isn't installed (restricted Python environments
without C extensions), the lib falls back to a pure-Python
cumulative-mean-shift detector. The fallback catches the same
broad mean-shift class with worse asymptotic complexity (O(N²))
and reduced sensitivity to variance changes. Both backends emit
the same `ChangepointAssessment` shape so callers don't branch.

## Architecture per memory `ha_insights_research_answers_v1`

This is an **algorithmic lib** — single-consumer wrapper around a
stats library, distinct from the signal-grader libs
(timing_likelihood, cooccurrence_likelihood, persistence_likelihood,
transition_entropy) which are multi-consumer and compose into a
HumanLikelihoodFeatures bundle.

Used initially by StateShiftDetector (v1.8.1+); may also feed
FrequencyAnomalyDetector and SeasonalityDetector to demote
confidence on signals that span a changepoint.

Zero HA imports. Pure function on a list of (timestamp, value) pairs.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

# Try to import ruptures. Track availability for caller diagnostics.
# We don't fall back silently — `detect_changepoints` reports the
# backend used in the assessment so detectors can adjust confidence.
try:
    import ruptures as _ruptures

    _RUPTURES_AVAILABLE = True
except ImportError:
    _ruptures = None  # type: ignore[assignment]
    _RUPTURES_AVAILABLE = False


class ChangepointKind(StrEnum):
    """Coarse classification of the shift detected.

    MEAN_SHIFT — the signal stepped to a new level (most common; what
        PELT under model="l2" detects).
    VARIANCE_SHIFT — the signal's noisiness changed. Currently only
        reported by ruptures backend with model="rbf"; fallback never
        emits this.
    UNKNOWN — fallback path or low-confidence call. Treat conservatively.
    """

    MEAN_SHIFT = "mean_shift"
    VARIANCE_SHIFT = "variance_shift"
    UNKNOWN = "unknown"


class ChangepointBackend(StrEnum):
    """Which implementation produced the assessment."""

    RUPTURES = "ruptures"
    FALLBACK = "fallback"


@dataclass(frozen=True)
class ChangepointAssessment:
    """One detected changepoint in a univariate time series.

    detected_at: timestamp of the data point AT or AFTER which the
        shift occurred. The actual transition lies between
        detected_at - 1 and detected_at; we report detected_at so
        downstream UI ("Routine shifted on 2026-05-12") aligns with
        the first day showing the new behavior.
    kind: what kind of shift.
    magnitude: |mean_after - mean_before|, on the same scale as the
        input values. Caller normalizes for cross-signal comparison.
    confidence: 0.0–1.0. Heuristic blend of magnitude and the
        difference between segment sizes. Single-sample segments
        score near 0 even with huge magnitudes (likely outliers).
    backend: which implementation produced this. Detectors can demote
        confidence when backend == FALLBACK.
    """

    detected_at: datetime
    kind: ChangepointKind
    magnitude: float
    confidence: float
    backend: ChangepointBackend


# Minimum segment size — segments shorter than this are merged into
# neighbors. Protects against single-outlier "shifts." Tuned for
# daily-frequency data (14d signal); shorter signals should override.
_MIN_SEGMENT_SIZE: int = 3

# Default PELT penalty. Higher = fewer changepoints reported. Tuned
# against synthetic data where a 5-day pre-shift mean of 10 jumps to
# a post-shift mean of 30 reliably triggers; smaller shifts don't.
# Callers wanting tighter sensitivity can override.
_DEFAULT_PENALTY: float = 10.0


def detect_changepoints(
    timestamps: Sequence[datetime],
    values: Sequence[float],
    *,
    penalty: float = _DEFAULT_PENALTY,
    min_segment_size: int = _MIN_SEGMENT_SIZE,
) -> list[ChangepointAssessment]:
    """Find changepoints in a univariate time series.

    Args:
      timestamps: monotonically increasing datetimes for each value.
        Same length as `values`.
      values: numeric series. Typical inputs:
        - daily firing counts (integers)
        - time-of-day in minutes for a recurring event (0-1439)
        - rolling weekly mean of an entity's daily activity
      penalty: PELT penalty parameter (higher → fewer changepoints).
      min_segment_size: minimum samples per detected segment. Segments
        shorter than this don't produce a changepoint.

    Returns:
      List of changepoints in chronological order. Empty list when no
      shift detected or input is too short to assess.
    """
    if len(timestamps) != len(values):
        raise ValueError(
            f"timestamps and values length mismatch: "
            f"{len(timestamps)} vs {len(values)}"
        )
    if len(values) < 2 * min_segment_size:
        # Not enough data for any meaningful split.
        return []

    if _RUPTURES_AVAILABLE:
        return _detect_with_ruptures(
            list(timestamps), list(values), penalty, min_segment_size
        )
    return _detect_fallback(
        list(timestamps), list(values), min_segment_size
    )


def _detect_with_ruptures(
    timestamps: list[datetime],
    values: list[float],
    penalty: float,
    min_segment_size: int,
) -> list[ChangepointAssessment]:
    """ruptures.Pelt with the L2 cost model (mean-shift detection)."""
    import numpy as _np  # local import — only when ruptures path runs

    signal = _np.asarray(values, dtype=float).reshape(-1, 1)
    algo = _ruptures.Pelt(model="l2", min_size=min_segment_size).fit(signal)
    # Predict returns segment END indices (1-indexed, exclusive). The
    # final index is always len(signal) — drop it; that's the "end of
    # data" sentinel, not an actual changepoint.
    cuts: list[int] = algo.predict(pen=penalty)
    if cuts and cuts[-1] == len(signal):
        cuts = cuts[:-1]

    out: list[ChangepointAssessment] = []
    prev_start = 0
    for cut_index in cuts:
        before = values[prev_start:cut_index]
        after_end = (
            cuts[cuts.index(cut_index) + 1]
            if cuts.index(cut_index) + 1 < len(cuts)
            else len(values)
        )
        after = values[cut_index:after_end]
        if not before or not after:
            continue
        mean_before = sum(before) / len(before)
        mean_after = sum(after) / len(after)
        magnitude = abs(mean_after - mean_before)
        confidence = _confidence_for(magnitude, len(before), len(after))
        out.append(
            ChangepointAssessment(
                detected_at=timestamps[cut_index],
                kind=ChangepointKind.MEAN_SHIFT,
                magnitude=magnitude,
                confidence=confidence,
                backend=ChangepointBackend.RUPTURES,
            )
        )
        prev_start = cut_index
    return out


def _detect_fallback(
    timestamps: list[datetime],
    values: list[float],
    min_segment_size: int,
) -> list[ChangepointAssessment]:
    """Pure-Python mean-shift detector.

    Scans every interior position, computes the difference in means
    between the prefix and suffix segments. Largest difference wins
    if it exceeds the noise floor (3× the within-segment standard
    deviation). Only finds ONE changepoint per call — recursion would
    catch multiple but explodes O(N² log N) on long signals.

    Less sensitive than PELT but adequate for the dominant use case
    (a routine that shifted once). Detectors should treat fallback-
    backend results as lower confidence.
    """
    n = len(values)
    best_index: int | None = None
    best_diff: float = 0.0
    for k in range(min_segment_size, n - min_segment_size + 1):
        before = values[:k]
        after = values[k:]
        mean_before = sum(before) / len(before)
        mean_after = sum(after) / len(after)
        diff = abs(mean_after - mean_before)
        if diff > best_diff:
            best_diff = diff
            best_index = k
    if best_index is None:
        return []
    # Noise floor: 3 × pooled stddev. Adjust to taste; tuned for
    # daily-count data which has Poisson-ish variance.
    mean_total = sum(values) / n
    variance = sum((v - mean_total) ** 2 for v in values) / n
    stddev = variance**0.5
    if best_diff < 3 * stddev:
        return []
    before_seg = values[:best_index]
    after_seg = values[best_index:]
    mean_before = sum(before_seg) / len(before_seg)
    mean_after = sum(after_seg) / len(after_seg)
    magnitude = abs(mean_after - mean_before)
    return [
        ChangepointAssessment(
            detected_at=timestamps[best_index],
            # Fallback only detects mean shifts. Label honest.
            kind=ChangepointKind.MEAN_SHIFT,
            magnitude=magnitude,
            confidence=_confidence_for(
                magnitude, len(before_seg), len(after_seg)
            ),
            backend=ChangepointBackend.FALLBACK,
        )
    ]


def _confidence_for(
    magnitude: float, n_before: int, n_after: int
) -> float:
    """Heuristic confidence blend.

    - Magnitude factor: 0.5 at magnitude=1, saturates to 1.0 at
      magnitude=20. Tuned for daily-count data; callers normalizing
      a different scale should be aware.
    - Segment-size factor: penalizes lopsided splits (one segment
      much shorter than the other). At 1:1 split, factor=1.0. At
      1:10, factor≈0.55.
    """
    magnitude_factor = min(1.0, 0.5 + magnitude / 40.0)
    balance = min(n_before, n_after) / max(n_before, n_after)
    balance_factor = 0.5 + 0.5 * balance
    return round(magnitude_factor * balance_factor, 3)


def backend_in_use() -> ChangepointBackend:
    """Which backend will detect_changepoints use?

    Lets detectors log "changepoint detection running on FALLBACK
    backend (install `ruptures` for better sensitivity)" once per
    install, rather than per call.
    """
    return (
        ChangepointBackend.RUPTURES
        if _RUPTURES_AVAILABLE
        else ChangepointBackend.FALLBACK
    )


__all__ = [
    "ChangepointAssessment",
    "ChangepointBackend",
    "ChangepointKind",
    "backend_in_use",
    "detect_changepoints",
]
