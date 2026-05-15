"""Timing-likelihood assessment — distinguish human-driven from device-driven event patterns.

Detectors that emit "user habit" insights (schedule, streak, manual_habit,
button_press_habit) all face the same false-positive class: a state
change pattern can be either a human action or a device internal timer
firing on a schedule. The two look identical from a state-machine
perspective but their suitability for "Automate this?" is opposite.

This module centralizes the variance / timing analysis that estimates
how likely a clustered-time event pattern was produced by a human vs a
device timer, returning a structured `TimingAssessment` that detectors
fold into their confidence math.

---

## The signal

Humans have ~1-15 minute natural jitter on routine actions. A user
flipping a switch around 17:25 every day might land at 17:24:30,
17:25:50, 17:24:55, etc — stddev typically 60-180 seconds, range often
spans the minute boundary.

Devices fire at the precise millisecond their timer expires. A
toothbrush BLE OFF event 2 minutes after its ON event has stddev <
0.1 second across hundreds of brushings. Even with network jitter,
local-push devices land within a 1-2 second window.

Cloud-integrated devices add network round-trip and poll-cycle noise:
- `cloud_polling` integrations (Tuya, sems): 0.5-3s jitter typical
- `cloud_push` (Hue, Ecobee): 0.3-2s typical
- `local_polling` / `local_push`: < 200ms typical

So the threshold for "this is a device timer" depends on the
integration's `iot_class`. This module knows about that.

---

## Why a separate module

Pre-v1.5.35 each detector hand-rolled variance math with different
units (minutes vs seconds), different aggregations (stddev vs range),
and different penalty curves. Some applied iot_class awareness, most
didn't. Some emitted the variance to payload, others didn't. Three
detectors, three slightly-different definitions of "tight timing".

Centralizing here:
- One algorithm. Drift-free across detectors.
- `iot_class` aware in one place.
- Pure function — testable without HA, fixturable across detectors.
- Returns structured `TimingAssessment` — easy to put in payload,
  surface to card / LLM, evolve with new fields.
- Future work (paired-event detection, scan_interval awareness, per-
  entity user overrides) plugs in here as additional functions on
  the same datatype. Detectors don't change.

The module is designed to be **liftable into HA core** alongside
`event_filters.py` — no HA imports.

---

## Usage

```python
from ..lib.timing_likelihood import assess_timing

events = [...]  # list of datetimes (local time recommended; DST-fold-free)
assessment = assess_timing(
    timestamps=[ev.timestamp for ev in events],
    iot_class="cloud_polling",
)
confidence *= assessment.human_likelihood
payload["timing_assessment"] = assessment.to_dict()
```
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field, asdict
from datetime import datetime, time
from enum import Enum
from typing import Any


class TimingClass(str, Enum):
    """Coarse classification of an event-timing distribution."""

    HUMAN_LIKELY = "human_likely"
    """Variance consistent with human action (≥ 30s stddev or ≥ 60s range)."""

    TIGHT_PATTERN = "tight_pattern"
    """Tight but plausibly human. Could be alarm-driven, could be device.
    Surfaced but with reduced confidence so the user decides."""

    DEVICE_LIKELY = "device_likely"
    """Variance below what a human can physically produce. Sub-second
    precision is the device-only fingerprint."""

    INSUFFICIENT_DATA = "insufficient_data"
    """Fewer than _MIN_SAMPLES events — no meaningful variance can be
    computed. Detectors should ignore the assessment in this case."""


# Minimum sample size to compute meaningful stddev. With 2 events the
# stddev is the half-range; with 3 it's marginal. 4+ gives a stable
# enough number to trust.
_MIN_SAMPLES = 4


@dataclass(frozen=True)
class TimingAssessment:
    """Structured timing-variance assessment for an event cluster.

    Returned by `assess_timing` so detectors can fold the timing
    signal into confidence math AND ship the same data in payload
    for the card / LLM to consume.

    Fields:
        stddev_seconds: sample stddev of time-of-day in seconds (0 if
            insufficient data).
        range_seconds: max - min of time-of-day in seconds.
        human_likelihood: float in [0, 1]. Detectors multiply their
            confidence by this. 1.0 = no penalty; 0.0 = certainly
            a device timer.
        timing_class: coarse TimingClass enum.
        reason: human-readable explanation. Shown in card tooltips
            on the confidence pill so users see WHY the score is
            what it is.
        sample_count: how many events the assessment is based on.
        iot_class: the integration's iot_class as fed in. Echoed so
            downstream consumers know which thresholds were applied.
    """

    stddev_seconds: float
    range_seconds: float
    human_likelihood: float
    timing_class: TimingClass
    reason: str
    sample_count: int
    iot_class: str | None = None
    # Reserved for future paired-event detection (toothbrush OFF
    # consistently 2 min after toothbrush ON). Empty for now —
    # detectors don't read it yet, but the field is here so payloads
    # in production are forward-compatible.
    paired_with: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Plain dict shape ready for JSON serialization in payloads."""
        d = asdict(self)
        d["timing_class"] = self.timing_class.value
        return d


# Threshold table indexed by iot_class. `range_drop_seconds` is the
# max time-of-day spread (max - min) that still counts as "device-
# tight" — events tighter than this almost certainly came from a
# device timer rather than a human action. `stddev_tag_seconds` is
# the looser "this is suspicious but possibly human" band that
# triggers a confidence cut but not a near-zero score.
#
# Local integrations: tight thresholds because local devices have
# < 200ms typical jitter and even slow Zigbee mesh hops stay under
# 1s most of the time.
#
# Cloud integrations: 5-10x looser to absorb network round-trip,
# cloud-side queuing, and HA poll-cycle delays.
_THRESHOLDS: dict[str, dict[str, float]] = {
    "local_push": {"range_drop_seconds": 2.0, "stddev_tag_seconds": 30.0},
    "local_polling": {"range_drop_seconds": 2.0, "stddev_tag_seconds": 30.0},
    "calculated": {"range_drop_seconds": 2.0, "stddev_tag_seconds": 30.0},
    "cloud_push": {"range_drop_seconds": 10.0, "stddev_tag_seconds": 30.0},
    "cloud_polling": {"range_drop_seconds": 10.0, "stddev_tag_seconds": 30.0},
    "assumed_state": {"range_drop_seconds": 10.0, "stddev_tag_seconds": 30.0},
}

# Fallback when iot_class is unknown / missing. Conservative: 5s
# range threshold — wider than local (so we don't false-positive on
# integrations with manifest gaps), tighter than cloud (so we still
# catch obvious device timers).
_DEFAULT_THRESHOLDS = {"range_drop_seconds": 5.0, "stddev_tag_seconds": 30.0}


# Confidence multipliers applied per timing class. Values chosen so
# a device-likely insight with a base confidence of 0.7 drops to
# 0.14 — comfortably below the default min_confidence filter so the
# user doesn't see it unless they explicitly browse low-confidence
# rows. Tight-pattern insights drop by ~15% — visible but demoted.
_LIKELIHOOD_BY_CLASS: dict[TimingClass, float] = {
    TimingClass.HUMAN_LIKELY: 1.0,
    TimingClass.TIGHT_PATTERN: 0.85,
    TimingClass.DEVICE_LIKELY: 0.20,
    TimingClass.INSUFFICIENT_DATA: 1.0,  # don't penalize what we can't measure
}


def assess_timing(
    timestamps: list[datetime],
    iot_class: str | None = None,
) -> TimingAssessment:
    """Score a cluster of event timestamps for device-vs-human likelihood.

    All time-of-day analysis is done modulo 24 hours, so events
    spanning midnight (23:59 vs 00:01) are correctly two minutes
    apart not 23h58m. Inputs should be timezone-aware datetimes;
    we work entirely in their tz-local time-of-day.

    Pure function. No HA imports, no I/O. Caller is responsible for
    DST normalization if needed — but for time-of-day modulo 86400,
    DST jumps appear as a one-hour outlier which the robust stddev
    naturally tolerates (we don't trim, since one DST event a year
    in a 14-day window has negligible weight).

    Args:
        timestamps: datetimes of the events being assessed. Order
            doesn't matter; duplicates allowed.
        iot_class: HA integration `iot_class` from manifest.json
            (e.g. "local_push", "cloud_polling"). None or unrecognized
            falls back to conservative defaults.

    Returns:
        TimingAssessment dataclass with the classification + the
        numeric inputs (stddev, range, sample_count) so downstream
        consumers can run their own logic if needed.
    """
    n = len(timestamps)
    if n < _MIN_SAMPLES:
        return TimingAssessment(
            stddev_seconds=0.0,
            range_seconds=0.0,
            human_likelihood=_LIKELIHOOD_BY_CLASS[
                TimingClass.INSUFFICIENT_DATA
            ],
            timing_class=TimingClass.INSUFFICIENT_DATA,
            reason=f"only {n} events — need ≥ {_MIN_SAMPLES} for variance.",
            sample_count=n,
            iot_class=iot_class,
        )

    # Convert each event to seconds-of-day. We do this in two steps so
    # midnight-crossing patterns (e.g. nightly 23:55 + occasional
    # 00:05) are treated correctly: shift everything to the same wall-
    # clock window before computing stddev.
    seconds_of_day = sorted(_to_seconds_of_day(ts) for ts in timestamps)
    seconds_of_day = _unwrap_around_midnight(seconds_of_day)

    range_s = seconds_of_day[-1] - seconds_of_day[0]
    stddev_s = statistics.stdev(seconds_of_day)

    thresholds = _THRESHOLDS.get(iot_class or "", _DEFAULT_THRESHOLDS)
    drop_range = thresholds["range_drop_seconds"]
    tag_stddev = thresholds["stddev_tag_seconds"]

    if range_s < drop_range:
        cls = TimingClass.DEVICE_LIKELY
        reason = (
            f"every event lands within a {range_s:.1f}s window across "
            f"{n} days — tighter than humans can physically produce. "
            f"Most likely a device internal timer or platform schedule."
        )
    elif stddev_s < tag_stddev:
        cls = TimingClass.TIGHT_PATTERN
        reason = (
            f"timing is consistent to within ±{stddev_s:.0f}s across "
            f"{n} days. Plausibly human (alarm-driven routine) but "
            f"tight enough that a device timer is also possible."
        )
    else:
        cls = TimingClass.HUMAN_LIKELY
        reason = (
            f"natural jitter (±{stddev_s:.0f}s across {n} days) is "
            f"consistent with a human-driven routine."
        )

    return TimingAssessment(
        stddev_seconds=round(stddev_s, 2),
        range_seconds=round(range_s, 2),
        human_likelihood=_LIKELIHOOD_BY_CLASS[cls],
        timing_class=cls,
        reason=reason,
        sample_count=n,
        iot_class=iot_class,
    )


# ----- helpers -----

_SECONDS_PER_DAY = 86400


def _to_seconds_of_day(ts: datetime) -> float:
    """Time-of-day in seconds, including sub-second fraction.

    Uses local time iff `ts` is timezone-aware; otherwise naive
    behavior matches the system tz. Caller is expected to feed
    consistently-zoned datetimes (the detector pipeline normalizes
    to HA's configured tz already)."""
    t: time = ts.time()
    return (
        t.hour * 3600
        + t.minute * 60
        + t.second
        + t.microsecond / 1_000_000
    )


def _unwrap_around_midnight(
    sorted_seconds: list[float],
) -> list[float]:
    """Rotate the seconds-of-day list so a midnight-crossing pattern
    has a small range. Without this, an event at 23:55:00 and another
    at 00:05:00 register as 86100 vs 300 — range ~85800 seconds, when
    the actual cluster span is 600 seconds (10 min).

    Heuristic: find the LARGEST gap between consecutive sorted
    times. If that gap is > 12 hours, "fold" the list at that point
    by adding 86400 to the values BEFORE it. The unwrapped values
    are still monotone; stddev computation is unaffected by absolute
    offset.

    For most patterns (no midnight crossing) the largest gap is just
    the gap between the last event of the day and the first of the
    next, with no other gap > 12h — folding is a no-op.

    Returns a NEW list — caller's input is unchanged.
    """
    if len(sorted_seconds) < 2:
        return list(sorted_seconds)

    biggest_gap = 0.0
    biggest_gap_index = 0
    for i in range(1, len(sorted_seconds)):
        gap = sorted_seconds[i] - sorted_seconds[i - 1]
        if gap > biggest_gap:
            biggest_gap = gap
            biggest_gap_index = i
    # Also consider the wrap-around gap (last → first + 86400)
    wrap_gap = (sorted_seconds[0] + _SECONDS_PER_DAY) - sorted_seconds[-1]
    if wrap_gap > biggest_gap:
        # Wrap is the biggest gap; events are already in the right
        # order (no unwrap needed). This is the normal case.
        return list(sorted_seconds)
    # The biggest gap is interior — events cluster around midnight.
    # Move the trailing chunk (after the gap) back by 24h so the
    # cluster is contiguous.
    out = list(sorted_seconds)
    for i in range(biggest_gap_index, len(out)):
        out[i] -= _SECONDS_PER_DAY
    # Re-sort so the assessment caller's max/min are still meaningful.
    out.sort()
    return out


def apply_to_confidence(
    base_confidence: float,
    assessment: TimingAssessment,
) -> float:
    """Convenience: clamp(base_confidence * assessment.human_likelihood).

    Detectors can call this rather than inlining the multiply +
    clamp themselves, so the formula stays in one place. Future
    changes to the curve (e.g. switching to a non-linear penalty)
    only need to land here.
    """
    out = base_confidence * assessment.human_likelihood
    return max(0.0, min(1.0, out))
