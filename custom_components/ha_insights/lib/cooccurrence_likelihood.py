"""Co-occurrence-likelihood assessment — distinguish isolated device events from human-context events.

Companion to `lib/timing_likelihood.py`. Where timing analyzes the
variance / range of an entity's events across days, co-occurrence
analyzes the *surrounding context* of each individual event: did
other entities also change state nearby, or did this event happen in
isolation?

The hypothesis (Gad 2026): humans triggering a state change are
typically present in the home, doing other things simultaneously.
Walking through a room triggers motion, opens a door, draws power,
talks to a voice assistant — multimodal. Devices firing on internal
timers do so in isolation; nothing else changes around the event.

So if an entity's "habit" pattern consistently fires with NO
surrounding activity in the rest of the home, that's a strong signal
for device-driven; if every firing is surrounded by 3-5 other state
changes within ±5 seconds, that's a strong signal for human.

---

## Architecture

Sibling to `timing_likelihood`. Same shape:
- pure function over inputs (no HA imports beyond datetime)
- returns a structured `CooccurrenceAssessment` dataclass
- exports `apply_to_confidence(base, assessment)` helper
- detectors compose timing + co-occurrence by multiplying the two
  likelihoods, or via the v1.5.36+ composite `HumanLikelihoodFeatures`
  bundle (planned for v1.5.37 when a third feature lands).

## Inputs

Detectors pass two timestamp lists:
- `cluster_events`: the entity's events that form the candidate
  pattern (same input timing_likelihood gets)
- `nearby_events_per_cluster_event`: for each cluster event, how many
  OTHER entities had state changes within ±window_seconds. This is
  computed by the detector by calling
  `StateEventBuffer.query(since=ev.timestamp - window, until=ev.timestamp + window)`
  and excluding the entity's own events.

We require the detector to do the buffer lookup so the lib stays HA-
core-adoptable (no buffer dependency).

## Thresholds

Reasoning: 0 other entities = isolated device. 1-2 = ambiguous (could
be a sibling sensor of the same device, e.g. battery sensor updating
when the device fires). 3+ = clearly busy context.

Tuned for a ±5s window which catches typical human-action bursts
(motion + door + presence + light) without picking up background
poll cycles (most polling integrations stagger to avoid sync, so
within a 10s window the count is small).
"""
from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class CooccurrenceClass(str, Enum):
    """Coarse classification of surrounding-event density."""

    HUMAN_CONTEXT = "human_context"
    """Median nearby-event count ≥ 3 within ±window_seconds — the home
    was typically busy around each event. Multimodal signature."""

    AMBIGUOUS = "ambiguous"
    """Median nearby-event count of 1-2. Could be a related sensor on
    the same device (battery, signal strength) firing alongside, not
    necessarily human presence."""

    ISOLATED = "isolated"
    """Median nearby-event count < 1 — entity typically fires in
    silence. Consistent with a device internal timer that has no
    human or sibling-sensor activity nearby."""

    INSUFFICIENT_DATA = "insufficient_data"
    """< _MIN_SAMPLES events. Not enough cluster events to assess
    co-occurrence reliably."""


# Need ≥ 3 cluster events for a meaningful mean. v1.5.39 lowered from
# 4 so 3-day streaks get graded (matches StreakDetector's floor).
# Fewer samples means one HA-restart-burst outlier has more leverage,
# but we use median-based classification (robust to single outliers)
# so n=3 stays informative.
_MIN_SAMPLES = 3


# Default window: ±5 seconds. Wide enough to capture human-action
# bursts (walk in → motion → switch → power draw, all in 1-3s).
# Narrow enough to avoid catching unrelated activity (most polling
# integrations stagger to avoid sync, so within 10s the count stays
# small).
DEFAULT_WINDOW_SECONDS = 5.0


@dataclass(frozen=True)
class CooccurrenceAssessment:
    """Per-cluster co-occurrence analysis.

    Fields:
        mean_nearby: average count of other-entity state changes
            within ±window of each cluster event.
        median_nearby: median; robust to occasional outliers (e.g.
            HA restart bursts).
        cooccurrence_class: coarse classification.
        human_likelihood: confidence multiplier in [0, 1].
        reason: human-readable explanation for tooltips.
        sample_count: how many cluster events were analyzed.
        window_seconds: the lookup window used.
    """

    mean_nearby: float
    median_nearby: float
    cooccurrence_class: CooccurrenceClass
    human_likelihood: float
    reason: str
    sample_count: int
    window_seconds: float = DEFAULT_WINDOW_SECONDS

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready dict for payload storage."""
        d = asdict(self)
        d["cooccurrence_class"] = self.cooccurrence_class.value
        return d


# Confidence multipliers per class. Symmetric with timing_likelihood:
# ISOLATED penalizes about as much as DEVICE_LIKELY does on the
# timing side, AMBIGUOUS is the soft middle, HUMAN_CONTEXT is a small
# CONFIRMATION boost (not >1.0 — we never inflate beyond the
# detector's own confidence; we only ratify it). INSUFFICIENT_DATA
# is neutral.
_LIKELIHOOD_BY_CLASS: dict[CooccurrenceClass, float] = {
    CooccurrenceClass.HUMAN_CONTEXT: 1.0,
    CooccurrenceClass.AMBIGUOUS: 0.90,
    CooccurrenceClass.ISOLATED: 0.40,
    CooccurrenceClass.INSUFFICIENT_DATA: 1.0,
}


def assess_cooccurrence(
    nearby_counts: list[int],
    window_seconds: float = DEFAULT_WINDOW_SECONDS,
) -> CooccurrenceAssessment:
    """Classify a cluster of events by their surrounding-event density.

    Args:
        nearby_counts: for each cluster event, the count of other
            entities' state changes within ±window_seconds. Detector
            computes this via StateEventBuffer.query() + exclude-self.
        window_seconds: echoed in the assessment for downstream
            consumers; doesn't affect the math (caller did the
            window query already).

    Returns:
        CooccurrenceAssessment with mean / median / class / multiplier.

    The function is pure — no I/O, no HA imports. Liftable into HA
    core helpers alongside `event_filters.py` and
    `timing_likelihood.py`.
    """
    n = len(nearby_counts)
    if n < _MIN_SAMPLES:
        return CooccurrenceAssessment(
            mean_nearby=0.0,
            median_nearby=0.0,
            cooccurrence_class=CooccurrenceClass.INSUFFICIENT_DATA,
            human_likelihood=_LIKELIHOOD_BY_CLASS[
                CooccurrenceClass.INSUFFICIENT_DATA
            ],
            reason=f"only {n} events — need ≥ {_MIN_SAMPLES} for context analysis.",
            sample_count=n,
            window_seconds=window_seconds,
        )

    mean_v = statistics.fmean(nearby_counts)
    median_v = statistics.median(nearby_counts)

    # Median > 2 → robustly busy context (≥ half the time, ≥ 3 other
    # entities flickered nearby). Use median for the band threshold
    # because one HA restart can inflate the mean.
    if median_v >= 3:
        cls = CooccurrenceClass.HUMAN_CONTEXT
        reason = (
            f"each event has a median of {median_v:.0f} other entity "
            f"state changes within ±{window_seconds:.0f}s — the home "
            f"was busy. Consistent with a human-driven action."
        )
    elif median_v >= 1:
        cls = CooccurrenceClass.AMBIGUOUS
        reason = (
            f"median {median_v:.0f} nearby event(s) — could be a sibling "
            f"sensor on the same device (battery, signal) firing alongside, "
            f"or partial human context."
        )
    else:
        cls = CooccurrenceClass.ISOLATED
        reason = (
            f"events fire in isolation (median {median_v:.0f} nearby, "
            f"mean {mean_v:.1f}). No other entity activity within ±"
            f"{window_seconds:.0f}s — consistent with a device internal "
            f"timer."
        )

    return CooccurrenceAssessment(
        mean_nearby=round(mean_v, 2),
        median_nearby=round(median_v, 2),
        cooccurrence_class=cls,
        human_likelihood=_LIKELIHOOD_BY_CLASS[cls],
        reason=reason,
        sample_count=n,
        window_seconds=window_seconds,
    )


def apply_to_confidence(
    base_confidence: float,
    assessment: CooccurrenceAssessment,
) -> float:
    """Clamp(base * assessment.human_likelihood). Matches the
    timing_likelihood helper signature so detectors can chain:

        c = base
        c = timing_likelihood.apply_to_confidence(c, timing_assessment)
        c = cooccurrence_likelihood.apply_to_confidence(c, coocc_assessment)

    Future composite type (v1.5.37) will collapse this into one call
    over a HumanLikelihoodFeatures bundle. Until then, chaining is
    the explicit pattern.
    """
    out = base_confidence * assessment.human_likelihood
    return max(0.0, min(1.0, out))
