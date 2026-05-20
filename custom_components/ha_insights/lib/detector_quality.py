"""Pure functions for the apply-rate detector-quality penalty.

v1.14.7 (May 2026). Closes the v1.14 batch — turns the verdict-history
timeline into actionable confidence adjustments. Detectors whose
suggestions users consistently reject (low apply-rate) get their
emitted insights demoted in confidence; detectors with no opinion
yet are untouched.

## The rule

For each detector, compute the apply-rate across ALL its insights'
decisive verdicts (apply / dismiss / retire). Map the rate to a
confidence multiplier:

  - `apply_rate < 0.20` → factor 0.60  (heavy demotion: 4 of 5
    suggestions rejected = visibly less prominent)
  - `apply_rate < 0.50` → factor 0.85  (light demotion)
  - `apply_rate >= 0.50` → factor 1.0  (neutral — user finds the
    detector useful enough)

Below `MIN_DECISIVE_VERDICTS` (5) the factor stays at 1.0 — too
little signal to penalize. Snoozes and undos are ignored: they
don't represent a user decision about the *value* of the
suggestion (snooze = "later"; undo = "I tried it, didn't love
the implementation").

## Why we don't boost above 1.0

Confidence is a per-insight signal the *detector* set based on its
own evidence. Inflating it post-hoc would lie to the rest of the
pipeline (notification thresholds, repairs dual-emit, audit hooks
all gate on confidence). Penalty-only stays honest.

## Architecture

Same pattern as `lib/user_verdict_history.py`, `lib/changepoint_detection.py`,
etc.: pure stdlib, zero HA imports, trivially testable. The store
layer (`get_decisive_verdicts_by_detector`) supplies the inputs;
this module is the rule.
"""
from __future__ import annotations

from collections.abc import Iterable

# Minimum decisive verdicts before the penalty kicks in. Below this,
# the standard error on apply_rate is too high to penalize on. With
# the v1.14.3a `dismiss_rate` etc. analysis: 5 samples → ~22%
# margin on a 50% rate; 10 samples → ~15%; 20 samples → ~10%.
# Choose 5 as the floor where the penalty distinguishes "really
# low" from "small sample".
MIN_DECISIVE_VERDICTS: int = 5

# Verdict kinds that count toward apply_rate. Mirrors the lib's
# `VerdictKind` set but kept as plain strings so this module stays
# stdlib-only.
_DECISIVE_KINDS: frozenset[str] = frozenset({"applied", "dismissed", "retired"})

# Penalty factor bands.
_PENALTY_HEAVY: float = 0.60
_PENALTY_LIGHT: float = 0.85
_PENALTY_NEUTRAL: float = 1.0


def apply_rate_from_kinds(
    kinds: Iterable[str],
) -> tuple[float, int]:
    """Compute (apply_rate, decisive_count) from a sequence of
    verdict-kind strings.

    Snoozes / undos / clear_applied are ignored — they don't reflect
    a user opinion about the suggestion's value. Returns (0.0, 0)
    when no decisive verdicts.
    """
    decisive = [k for k in kinds if k in _DECISIVE_KINDS]
    if not decisive:
        return (0.0, 0)
    applies = sum(1 for k in decisive if k == "applied")
    return (applies / len(decisive), len(decisive))


def compute_penalty_factor(
    apply_rate: float,
    decisive_count: int,
) -> float:
    """Map (apply_rate, decisive_count) → confidence multiplier in (0, 1.0].

    Below ``MIN_DECISIVE_VERDICTS`` the factor is neutral (1.0).
    Above that, three bands:
      - apply_rate < 0.20 → 0.60 (heavy demotion)
      - apply_rate < 0.50 → 0.85 (light demotion)
      - apply_rate >= 0.50 → 1.0 (neutral)
    """
    if decisive_count < MIN_DECISIVE_VERDICTS:
        return _PENALTY_NEUTRAL
    if apply_rate < 0.20:
        return _PENALTY_HEAVY
    if apply_rate < 0.50:
        return _PENALTY_LIGHT
    return _PENALTY_NEUTRAL


def compute_penalties_by_detector(
    kinds_by_detector: dict[str, list[str]],
) -> dict[str, float]:
    """Bulk variant. Returns ``{detector_name: penalty_factor}`` for every
    detector in the input. Detectors not in the input (no verdict
    history) are simply omitted — the caller's default-to-1.0 lookup
    handles them."""
    out: dict[str, float] = {}
    for det, kinds in kinds_by_detector.items():
        rate, count = apply_rate_from_kinds(kinds)
        out[det] = compute_penalty_factor(rate, count)
    return out


# v1.22 — detector-level rejection signal. Distinct from the
# penalty system: the penalty quietly demotes individual insights;
# this signal proposes disabling the whole detector via a meta-
# insight the user can action. Higher bar (n >= 20 vs n >= 5,
# apply_rate < 0.10 vs < 0.20) because the proposed action is
# louder and harder to undo. Memory:
# [[ha_insights_v2_presence_and_adaptive]] §v1.16 Detector-level.
MIN_DECISIVE_VERDICTS_FOR_DISABLE_HINT: int = 20
APPLY_RATE_DISABLE_THRESHOLD: float = 0.10


def find_rejection_signals(
    kinds_by_detector: dict[str, list[str]],
    *,
    min_decisive: int = MIN_DECISIVE_VERDICTS_FOR_DISABLE_HINT,
    apply_rate_threshold: float = APPLY_RATE_DISABLE_THRESHOLD,
) -> list[dict[str, float | int | str]]:
    """For v1.22 AdaptiveFeedback detector-level emission.

    Returns the list of detectors whose suggestions the user has been
    rejecting consistently enough to warrant a "consider disabling
    this detector" prompt. Each entry:

      {
        "detector": "schedule",
        "n_decisive": 22,
        "n_applies": 1,
        "n_rejections": 21,
        "apply_rate": 0.045,
      }

    Sorted ascending by apply_rate so the most-rejected detector
    leads. Detectors with insufficient data (n_decisive < min_decisive)
    are filtered out — small samples have wide error bars and we
    don't want to suggest disabling a detector that's only emitted
    five things.

    Caller is responsible for time-windowing the input. The store's
    ``get_decisive_verdict_kinds_by_detector_since(ts)`` returns
    last-N-days data; passing all-time kinds here would treat
    historical rejections as fresh, which is what the cooldown +
    re-suggest layer is supposed to prevent.
    """
    out: list[dict[str, float | int | str]] = []
    for detector, kinds in kinds_by_detector.items():
        decisive = [k for k in kinds if k in _DECISIVE_KINDS]
        n_decisive = len(decisive)
        if n_decisive < min_decisive:
            continue
        n_applies = sum(1 for k in decisive if k == "applied")
        rate = n_applies / n_decisive if n_decisive else 0.0
        if rate >= apply_rate_threshold:
            continue
        out.append({
            "detector": detector,
            "n_decisive": n_decisive,
            "n_applies": n_applies,
            "n_rejections": n_decisive - n_applies,
            "apply_rate": round(rate, 3),
        })
    out.sort(key=lambda r: float(r["apply_rate"]))
    return out


__all__ = [
    "APPLY_RATE_DISABLE_THRESHOLD",
    "MIN_DECISIVE_VERDICTS",
    "MIN_DECISIVE_VERDICTS_FOR_DISABLE_HINT",
    "apply_rate_from_kinds",
    "compute_penalties_by_detector",
    "compute_penalty_factor",
    "find_rejection_signals",
]
