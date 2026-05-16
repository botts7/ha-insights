"""Persistence likelihood — fixed device cycles vs variable human sessions.

Third signal-grader sibling to `lib/timing_likelihood.py` and
`lib/cooccurrence_likelihood.py`. Same architecture, same return-
type shape, same `apply_to_confidence` signature so detectors chain
all three penalties together.

---

## The signal (Gad 2026, feature #2)

Devices flip state and revert on fixed internal cycles. A toothbrush
ON event is followed by an OFF event almost exactly 2:00.000 later
every time. A POE camera reboots on a 4-hour cron. A robot vacuum
runs for 47 minutes whenever it docks.

Humans hold state for variable durations. Light ON: maybe 2 minutes
(grabbed something from the room), maybe 4 hours (watching TV), maybe
3 days (forgot it was on). Variance is the fingerprint.

So given a cluster of "entity → state S" events, look up how long the
entity stayed in S each time before transitioning out. If the durations
are nearly identical (coefficient of variation < 5%), that's a device
cycle. If they span orders of magnitude, that's a human.

---

## What this catches that timing + cooccurrence don't

- **Toothbrush OFF every weekday at 08:54**: timing analysis flags
  the OFF event tight-pattern. Co-occurrence flags it isolated (no
  other activity at 08:54). But it's persistence that nails the
  smoking gun: every brushing session is exactly 2:00.005 long. No
  human brushes for *exactly* 120 seconds and zero microseconds.

- **NVR profile cycling**: a "switch.nvr_profile_3 → on" event
  has ~variable timing across days, surrounded by other camera
  activity (so cooccurrence sees human context). But each session
  is exactly 3600.000 seconds — clear device cycle.

This is the third lens; the three are mostly orthogonal.

---

## Architecture

Pure function over a list of durations (seconds). Detectors compute
the durations by looking up the next-state-change-for-this-entity
in the event buffer after each cluster event.
"""
from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


class PersistenceClass(StrEnum):
    """Coarse classification of duration-in-state distribution."""

    HUMAN_VARIABLE = "human_variable"
    """Durations span ≥ 1 order of magnitude OR have CV > 30%. Variable
    enough to be human-controlled — different brushing sessions, TV
    watching of different shows, etc."""

    TIGHT_DURATION = "tight_duration"
    """CV between 5% and 30%. Consistent but not robotic — could be an
    alarm-driven routine ('wake up, immediately start coffee' has
    tight delay) or a polite device that varies slightly."""

    FIXED_CYCLE = "fixed_cycle"
    """CV < 5% across ≥ 3 sessions (the `_MIN_SAMPLES` floor lowered
    from 4 in v1.5.39 so 3-day streaks get graded). The entity holds
    state for the same duration every time within sub-second
    precision — definitive device internal timer."""

    INSUFFICIENT_DATA = "insufficient_data"
    """< _MIN_SAMPLES durations available. Some cluster events haven't
    transitioned out yet (still in the new state at the end of the
    buffer); detector should pass the original count and let the lib
    handle the sample-size guard."""


_MIN_SAMPLES = 3


# Coefficient-of-variation thresholds for classification.
# CV = stddev / mean — unitless, scale-invariant, perfect for comparing
# 2-minute toothbrush cycles vs 4-hour TV sessions on the same axis.
_FIXED_CYCLE_CV = 0.05  # < 5% → robotic precision
_TIGHT_DURATION_CV = 0.30  # 5-30% → consistent but not robotic


# Multipliers per class. Symmetric with the timing + cooccurrence libs.
# Fixed cycles drop confidence by 75% (a touch less aggressive than
# timing's device_likely 80%, because persistence is sensitive to
# polling intervals that mask shorter durations); tight-duration drops
# 15%; human-variable is neutral.
_LIKELIHOOD_BY_CLASS: dict[PersistenceClass, float] = {
    PersistenceClass.HUMAN_VARIABLE: 1.0,
    PersistenceClass.TIGHT_DURATION: 0.85,
    PersistenceClass.FIXED_CYCLE: 0.25,
    PersistenceClass.INSUFFICIENT_DATA: 1.0,
}


@dataclass(frozen=True)
class PersistenceAssessment:
    """Structured result from `assess_persistence`.

    Fields:
        mean_duration_seconds: average duration in state.
        stddev_duration_seconds: sample stddev across sessions.
        coefficient_of_variation: stddev / mean — scale-invariant
            measure of duration consistency.
        persistence_class: coarse classification.
        human_likelihood: confidence multiplier in [0, 1].
        reason: human-readable explanation for card tooltip.
        sample_count: how many durations were analyzed.
    """

    mean_duration_seconds: float
    stddev_duration_seconds: float
    coefficient_of_variation: float
    persistence_class: PersistenceClass
    human_likelihood: float
    reason: str
    sample_count: int

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["persistence_class"] = self.persistence_class.value
        return d


def assess_persistence(
    durations_seconds: list[float],
    previous_state_durations_seconds: list[float] | None = None,
) -> PersistenceAssessment:
    """Classify a duration-in-state distribution as fixed-cycle vs human.

    v1.5.39 extends the assessment to look in BOTH directions:

    - **Forward direction** (`durations_seconds`): how long the entity
      STAYS in the new state after the cluster event. Catches things
      like "switch turns ON, then auto-OFF after exactly 5:00.001".

    - **Backward direction** (`previous_state_durations_seconds`):
      how long the entity WAS in the previous state before flipping
      at the cluster event. Catches the toothbrush case — the OFF
      event's brushing-session length is the fingerprint, not how
      long it stays off afterward.

    A device-cycle event has tight CV in ONE direction even when the
    other direction is human-variable. So we compute CV in both
    directions when both are provided and use whichever is MORE
    conclusive (lower CV) for classification. The `reason` text
    cites which direction won so the user can verify.

    Pre-v1.5.39 callers passed only `durations_seconds` (forward).
    That path still works — backward direction is opt-in via the new
    optional parameter; existing callers see identical output.

    Args:
        durations_seconds: forward-direction (next-state) durations
            for each cluster event. Sessions still open at the buffer
            edge should be OMITTED — the sample-size guard handles
            the sparsity.
        previous_state_durations_seconds: backward-direction
            (previous-state) durations. None means "skip backward
            analysis"; an empty list means "tried but no data
            available" (treated as None for classification).

    Returns:
        PersistenceAssessment with CV from the more-conclusive
        direction. `reason` includes the direction marker.

    Pure function; no I/O, no HA imports.
    """
    fwd = _summarize(durations_seconds)
    bwd = _summarize(previous_state_durations_seconds)

    # Pick the more conclusive direction (lower CV among those with
    # enough samples). When neither direction has enough samples,
    # return INSUFFICIENT_DATA citing the better-populated direction.
    if fwd is None and bwd is None:
        # Use the larger sample count for the error message.
        fwd_n = len(durations_seconds)
        bwd_n = len(previous_state_durations_seconds or [])
        n = max(fwd_n, bwd_n)
        return PersistenceAssessment(
            mean_duration_seconds=0.0,
            stddev_duration_seconds=0.0,
            coefficient_of_variation=0.0,
            persistence_class=PersistenceClass.INSUFFICIENT_DATA,
            human_likelihood=_LIKELIHOOD_BY_CLASS[
                PersistenceClass.INSUFFICIENT_DATA
            ],
            reason=(
                f"only {n} completed sessions in either direction — "
                f"need ≥ {_MIN_SAMPLES} to assess persistence."
            ),
            sample_count=n,
        )

    # Choose the direction with the lower CV (tighter = more likely
    # to be the device fingerprint). If only one direction has data,
    # use it.
    if bwd is None or (fwd is not None and fwd.cv <= bwd.cv):
        chosen = fwd
        direction_label = "next-state duration"
        assert chosen is not None  # narrow for type checker
    else:
        chosen = bwd
        direction_label = "previous-state duration"

    if chosen.cv < _FIXED_CYCLE_CV:
        cls = PersistenceClass.FIXED_CYCLE
        reason = (
            f"every {direction_label} lasts ~{_fmt_seconds(chosen.mean)} "
            f"with CV {chosen.cv * 100:.1f}% across {chosen.n} events — "
            f"robotic precision, consistent with a device internal timer "
            f"(no human varies a session length below ±5%)."
        )
    elif chosen.cv < _TIGHT_DURATION_CV:
        cls = PersistenceClass.TIGHT_DURATION
        reason = (
            f"{direction_label}s average {_fmt_seconds(chosen.mean)} with "
            f"CV {chosen.cv * 100:.0f}% — consistent but not robotic. "
            f"Could be an alarm-driven routine or a polite device."
        )
    else:
        cls = PersistenceClass.HUMAN_VARIABLE
        reason = (
            f"{direction_label}s span {_fmt_seconds(chosen.min_v)} to "
            f"{_fmt_seconds(chosen.max_v)} (mean "
            f"{_fmt_seconds(chosen.mean)}, CV {chosen.cv * 100:.0f}%) — "
            f"variable enough to be human-controlled."
        )

    return PersistenceAssessment(
        mean_duration_seconds=round(chosen.mean, 3),
        stddev_duration_seconds=round(chosen.stddev, 3),
        coefficient_of_variation=round(chosen.cv, 4),
        persistence_class=cls,
        human_likelihood=_LIKELIHOOD_BY_CLASS[cls],
        reason=reason,
        sample_count=chosen.n,
    )


@dataclass(frozen=True)
class _DurationSummary:
    """Internal summary of one direction's duration distribution."""

    n: int
    mean: float
    stddev: float
    cv: float
    min_v: float
    max_v: float


def _summarize(
    durations: list[float] | None,
) -> _DurationSummary | None:
    """Compute CV summary for one direction; None if not enough data."""
    if durations is None:
        return None
    n = len(durations)
    if n < _MIN_SAMPLES:
        return None
    mean_v = statistics.fmean(durations)
    stddev_v = statistics.stdev(durations)
    cv = (stddev_v / mean_v) if mean_v > 0 else 0.0
    return _DurationSummary(
        n=n,
        mean=mean_v,
        stddev=stddev_v,
        cv=cv,
        min_v=min(durations),
        max_v=max(durations),
    )


def apply_to_confidence(
    base_confidence: float,
    assessment: PersistenceAssessment,
) -> float:
    """clamp(base * assessment.human_likelihood). Matches the
    timing_likelihood + cooccurrence_likelihood helper signature so
    detectors can chain all three:

        c = base
        c = timing_likelihood.apply_to_confidence(c, timing_a)
        c = cooccurrence_likelihood.apply_to_confidence(c, coocc_a)
        c = persistence_likelihood.apply_to_confidence(c, pers_a)
    """
    out = base_confidence * assessment.human_likelihood
    return max(0.0, min(1.0, out))


# ----- helpers -----

def _fmt_seconds(seconds: float) -> str:
    """Pretty-format a duration for the tooltip reason string.
    Sub-minute → seconds; sub-hour → minutes; otherwise hours."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    if seconds < 3600:
        return f"{seconds / 60:.1f}min"
    return f"{seconds / 3600:.1f}h"
