"""Single source of truth for "is this insight device-managed?".

Pre-v1.12.12, the card's `_renderDeviceManagedPill` computed this
verdict in TypeScript across 6 signal classes (3 strong, 4 soft) and
v1.12.10's filler-filter computed it in Python checking only 1 signal.
That divergence caused real-install false positives: a low-confidence
streak with `persistence_class=fixed_cycle` rendered the
🤖 device-managed badge in the card but escaped the Python filter
(which only checked `timing_class=device_likely`).

This module is the canonical Python verdict. Detectors call
`is_device_managed_from_assessments()` at emit time and stamp the
boolean result onto `payload["_is_device_managed"]`. The card and the
filler-filter both read the same field — no re-computation, no
language drift.

Pure function — no HA imports. Mirrors the canonical rule from
`ha-insights-card/src/ha-insights-card.ts::_renderDeviceManagedPill`:

    strong = (timing_class == "device_likely")
           + (cooccurrence_class == "isolated")
           + (persistence_class == "fixed_cycle")
    soft   = (timing_class == "tight_pattern")
           + (cooccurrence_class == "ambiguous")
           + (persistence_class == "tight_duration")
           + (transition_entropy_class == "novel_context")
    is_device_managed = (strong >= 1) or (strong + soft >= 3)
"""
from __future__ import annotations

from typing import Any

# Strong device-managed signals — any one of these means the pattern
# is almost certainly device-internal logic, not a user habit.
_STRONG_SIGNALS: dict[str, str] = {
    "_timing_assessment": "device_likely",
    "_cooccurrence_assessment": "isolated",
    "_persistence_assessment": "fixed_cycle",
}

# Soft signals — each one nudges the verdict but only matters when
# 3+ stack together (covers "looks managed from several angles" cases
# without false-positive on any single weak signal).
_SOFT_SIGNALS: dict[str, str] = {
    "_timing_assessment": "tight_pattern",
    "_cooccurrence_assessment": "ambiguous",
    "_persistence_assessment": "tight_duration",
    "_transition_entropy_assessment": "novel_context",
}

# Which class-name key to read inside each assessment dict.
_CLASS_KEY: dict[str, str] = {
    "_timing_assessment": "timing_class",
    "_cooccurrence_assessment": "cooccurrence_class",
    "_persistence_assessment": "persistence_class",
    "_transition_entropy_assessment": "transition_entropy_class",
}


def is_device_managed(payload: dict[str, Any] | None) -> bool:
    """Verdict computed from an insight payload's assessment blocks.

    Reads `payload["_timing_assessment"]["timing_class"]` (and the
    parallel cooccurrence/persistence/entropy blocks). Returns False if
    the payload is missing, malformed, or none of the signals fire.

    Detectors should prefer the typed dataclass entrypoint
    (`is_device_managed_from_assessments`) which avoids the dict round-
    trip; this version exists so callers operating on stored insights
    (post-emit, e.g. the filler filter) can decide without re-parsing.
    """
    if not isinstance(payload, dict):
        return False
    strong = 0
    soft = 0
    for assessment_key, class_value in _STRONG_SIGNALS.items():
        block = payload.get(assessment_key)
        if not isinstance(block, dict):
            continue
        if block.get(_CLASS_KEY[assessment_key]) == class_value:
            strong += 1
    for assessment_key, class_value in _SOFT_SIGNALS.items():
        block = payload.get(assessment_key)
        if not isinstance(block, dict):
            continue
        if block.get(_CLASS_KEY[assessment_key]) == class_value:
            soft += 1
    return strong >= 1 or (strong + soft) >= 3


def is_device_managed_from_assessments(
    *,
    timing_class: str | None = None,
    cooccurrence_class: str | None = None,
    persistence_class: str | None = None,
    transition_entropy_class: str | None = None,
) -> bool:
    """Same verdict, computed from already-parsed class strings.

    Used inside `HumanLikelihoodFeatures.payload_keys()` so we don't
    have to serialise → re-parse the dict we just built.
    """
    strong = sum([
        timing_class == "device_likely",
        cooccurrence_class == "isolated",
        persistence_class == "fixed_cycle",
    ])
    soft = sum([
        timing_class == "tight_pattern",
        cooccurrence_class == "ambiguous",
        persistence_class == "tight_duration",
        transition_entropy_class == "novel_context",
    ])
    return strong >= 1 or (strong + soft) >= 3
