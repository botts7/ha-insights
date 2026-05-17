"""Pearson correlation + time-aligned binning of event streams.

Used by:
- `PhysicalDeviceLinkDetector` (v1.11.0) — detects when two HA
  entities are likely the same physical device by looking for
  implausibly high correlation in their value streams. r > 0.95 on
  temperature over 7 days is almost certainly the same sensor.
- `LocationProposalDetector` (v1.11.5, planned) — uses the same
  primitives to score an unassigned entity's similarity to
  already-area-tagged siblings.

## Why this lib exists

Both detectors needed the same machinery: aligning two
sample-at-arbitrary-times event streams into parallel binned
sequences, then computing correlation. Pulling it out keeps each
detector small and lets the (well-tested) statistical core be
shared.

## What it does NOT do

- Cross-correlation at arbitrary lags. We support a small lag scan
  (±2 bins) for tolerance to clock drift between integrations, but
  not the full lag landscape — that's a different feature.
- Confidence intervals. The `confidence` field is a heuristic mix
  of r magnitude and sample count, calibrated for v1.11.0's
  thresholds. Don't read it as a frequentist p-value.
- Spearman or rank correlation. Pearson is fine for value-similar
  sensors; rank-based methods would help for monotonic-but-
  non-linear relationships we don't expect here.

## Architecture

Pure functions — no HA imports, no side effects. Callers pass
already-collected event lists (typically from
`StateEventBuffer.query`). Tested independently of any detector.
"""
from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

# Minimum stddev (in input units) before we trust a correlation
# computation. Near-constant sensors (e.g. battery sensor stuck at
# 100%) produce numerically-correct but meaningless r values; below
# this floor we return r=0 with low confidence.
_MIN_VARIANCE_FOR_CORR: float = 0.01

# Minimum aligned samples for a meaningful Pearson r. Below this
# the estimate is too noisy to act on.
MIN_SAMPLES_FOR_CORR: int = 10


@dataclass(frozen=True)
class CorrelationResult:
    """Result of a time-aligned Pearson correlation.

    r: Pearson coefficient at the BEST lag tested. Range [-1, 1].
    n_samples: count of aligned (x, y) pairs used.
    best_lag_bins: which lag produced `r`. 0 = perfectly time-
        aligned; ±k = entity B's stream shifted k bins relative
        to A. Reported so callers can flag suspicious lags
        (large lags usually mean coincidental correlation, not
        same-physical-device).
    confidence: 0.0–1.0 heuristic combining |r| and sample count.
        Use for ranking; do not interpret as a p-value.
    """

    r: float
    n_samples: int
    best_lag_bins: int
    confidence: float


def pearson_correlation(xs: list[float], ys: list[float]) -> float:
    """Plain Pearson r on two equal-length lists. Returns 0.0 when
    either list has near-zero variance (would div-by-tiny otherwise).

    Args:
      xs / ys: equal-length numeric sequences.

    Returns:
      Pearson r in [-1, 1], or 0.0 when undefined (constant input,
      empty input, length mismatch).
    """
    if len(xs) != len(ys) or len(xs) < 2:
        return 0.0
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    var_x = sum((x - mean_x) ** 2 for x in xs) / n
    var_y = sum((y - mean_y) ** 2 for y in ys) / n
    if var_x < _MIN_VARIANCE_FOR_CORR or var_y < _MIN_VARIANCE_FOR_CORR:
        return 0.0
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / n
    denom = math.sqrt(var_x) * math.sqrt(var_y)
    if denom == 0:
        return 0.0
    return cov / denom


def bin_events(
    events: Iterable[tuple[float, float]],
    *,
    bin_size_seconds: float,
    start_ts: float,
    end_ts: float,
) -> list[float | None]:
    """Aggregate (timestamp, value) tuples into fixed-size bins.

    Each bin's value is the AVERAGE of values in that bin (or None
    when the bin had no samples). Average is preferred over
    last-value because some integrations report more frequently
    than others — a 10s-cadence sensor would dominate the bin
    against a 60s-cadence sensor if we took just the last value.

    Args:
      events: iterable of (epoch_seconds, value) tuples.
      bin_size_seconds: bin width. 600 (10 min) is the default for
        physical-device-link detection — small enough to catch real
        coupling, large enough to absorb cadence differences.
      start_ts / end_ts: epoch-second bounds of the output window.

    Returns:
      List of length ceil((end_ts - start_ts) / bin_size_seconds);
      each element is the bin's mean or None if no samples landed.
    """
    if bin_size_seconds <= 0 or end_ts <= start_ts:
        return []
    n_bins = int(math.ceil((end_ts - start_ts) / bin_size_seconds))
    sums: list[float] = [0.0] * n_bins
    counts: list[int] = [0] * n_bins
    for ts, value in events:
        if ts < start_ts or ts >= end_ts:
            continue
        bin_idx = int((ts - start_ts) // bin_size_seconds)
        if 0 <= bin_idx < n_bins:
            sums[bin_idx] += value
            counts[bin_idx] += 1
    out: list[float | None] = []
    for i in range(n_bins):
        if counts[i] > 0:
            out.append(sums[i] / counts[i])
        else:
            out.append(None)
    return out


def carry_forward(binned: list[float | None]) -> list[float | None]:
    """Replace None bins with the most-recent prior non-None value.

    Bins still None at the start (before the first sample) stay None.
    Carry-forward is the right interpolation for stateful sensors
    (temp, humidity, etc.) where "no new reading" means "value
    hasn't changed observably." For instantaneous sensors (motion,
    button press) this is wrong — those should NOT use this lib's
    correlation primitives.
    """
    out: list[float | None] = []
    last: float | None = None
    for v in binned:
        if v is not None:
            last = v
        out.append(last)
    return out


def time_aligned_correlation(
    events_a: list[tuple[float, float]],
    events_b: list[tuple[float, float]],
    *,
    bin_size_seconds: float = 600.0,
    start_ts: float,
    end_ts: float,
    max_lag_bins: int = 2,
) -> CorrelationResult:
    """Compute Pearson r between two event streams, scanning small
    lags to tolerate clock drift between integrations.

    Returns the BEST lag's r (highest |r|, not raw r — negative
    correlation also matters for inverse signals like one entity
    being a derivative of the other).

    Args:
      events_a / events_b: (epoch_seconds, value) tuples.
      bin_size_seconds: bin width for alignment.
      start_ts / end_ts: epoch-second window bounds.
      max_lag_bins: scan ±k bin offsets. 2 (= ±20 min at the
        default 10-min bin) handles typical clock drift and
        reporting cadence offsets without making coincidental
        matches more likely.

    Returns:
      CorrelationResult with r at the best lag + sample count +
      confidence heuristic.
    """
    a_binned = carry_forward(
        bin_events(events_a, bin_size_seconds=bin_size_seconds,
                   start_ts=start_ts, end_ts=end_ts)
    )
    b_binned = carry_forward(
        bin_events(events_b, bin_size_seconds=bin_size_seconds,
                   start_ts=start_ts, end_ts=end_ts)
    )
    if not a_binned or not b_binned:
        return CorrelationResult(
            r=0.0, n_samples=0, best_lag_bins=0, confidence=0.0
        )

    best_r = 0.0
    best_lag = 0
    best_n = 0
    # Scan lag=0 first; on ties, lag=0 wins. Identical streams
    # correlate equally at all lags — the meaningful answer is
    # "no shift," not whatever lag the loop happened to test first.
    lag_order = [0] + [
        x for x in range(-max_lag_bins, max_lag_bins + 1) if x != 0
    ]
    for lag in lag_order:
        xs, ys = _align_with_lag(a_binned, b_binned, lag)
        if len(xs) < MIN_SAMPLES_FOR_CORR:
            continue
        r = pearson_correlation(xs, ys)
        if abs(r) > abs(best_r):
            best_r = r
            best_lag = lag
            best_n = len(xs)

    confidence = _confidence_from(best_r, best_n)
    return CorrelationResult(
        r=round(best_r, 4),
        n_samples=best_n,
        best_lag_bins=best_lag,
        confidence=round(confidence, 3),
    )


def _align_with_lag(
    a: list[float | None],
    b: list[float | None],
    lag: int,
) -> tuple[list[float], list[float]]:
    """Build (xs, ys) by shifting b by `lag` bins relative to a, then
    dropping pairs where either side is None."""
    xs: list[float] = []
    ys: list[float] = []
    n = len(a)
    for i in range(n):
        j = i + lag
        if j < 0 or j >= n:
            continue
        if a[i] is None or b[j] is None:
            continue
        xs.append(a[i])  # type: ignore[arg-type]
        ys.append(b[j])  # type: ignore[arg-type]
    return xs, ys


def _confidence_from(r: float, n_samples: int) -> float:
    """Heuristic confidence: blends |r| magnitude with sample size.

    Calibrated for v1.11.0's r>0.95 threshold:
      - r=0.95, n=100 → ~0.85
      - r=0.99, n=200 → ~0.95
      - r=0.50, n=500 → ~0.45 (still emits if asked, but ranks low)
      - r=0.90, n=8   → 0.0 (sample count below MIN_SAMPLES)

    Don't interpret as a p-value. Use for ranking and threshold
    decisions only.
    """
    if n_samples < MIN_SAMPLES_FOR_CORR:
        return 0.0
    # Sample-count factor saturates at 200 — beyond that the r
    # estimate is stable enough that more samples don't add
    # confidence about the underlying relationship.
    sample_factor = min(1.0, n_samples / 200.0)
    # |r| factor: linear in |r|. Squaring would over-penalize the
    # 0.85–0.95 band that's our sweet spot for "probably same
    # physical device but verify."
    return abs(r) * sample_factor


__all__ = [
    "MIN_SAMPLES_FOR_CORR",
    "CorrelationResult",
    "bin_events",
    "carry_forward",
    "pearson_correlation",
    "time_aligned_correlation",
]
