"""Coupling strength — distinguish device-internal logic from user habit.

When a B-follows-A pair shows sub-second deterministic timing across many
occurrences, that's almost always device-side wiring (ESPHome on_press,
Z-Wave central scene, Zigbee binding, vendor scene) — NOT a user pressing
two buttons in quick succession. From HA's event-bus perspective these
look indistinguishable from real user habits, but the latency signature
gives them away:

- Direct device binding / on-device automation: typically <500 ms,
  near-zero stddev (it's just the device's CPU + radio link)
- HA-side automation on a healthy install: typically 100-500 ms,
  small but nonzero stddev (event loop dispatch + service call)
- User habit (two manual actions): typically >2 s, high stddev
  (humans are slow and inconsistent)

This module surfaces the signature on each pair as a `CouplingScore` so
the detector can stamp it onto the Insight payload. The card can then
render a 🔗 "looks coupled" badge AND the scan pipeline can demote
TIGHT-coupled insights' confidence — the user shouldn't be nagged to
add an automation that does what their device binding already does.

The badge is recommendation, not classification. We don't *prove* the
pair is device-internal vs HA-automation vs habit; we surface the
timing evidence and let the user judge. See
`reference_device_internal_logic_problem` in agent memory for the full
rationale on why HA event metadata alone can't classify these.

Zero HA imports. Pure function operating on the per-pair `deltas`
(seconds between leader and follower) and `leader_count` (total times
the leader fired during the lookback window) the detectors already
compute.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Literal

CouplingTier = Literal["TIGHT", "LOOSE", "NONE"]


@dataclass(frozen=True)
class CouplingScore:
    """Summary of how tightly two entities co-fire in time.

    median_lag_ms: median delta between leader and follower (ms)
    consistency:   fraction of leader fires that produced a follower
                   (0.0–1.0). Detectors compute this as
                   len(deltas) / leader_count.
    tier:          TIGHT (sub-half-second + ≥90% consistency — almost
                   certainly device-internal or pre-existing automation),
                   LOOSE (≤2 s + ≥70% — could be HA automation, could
                   be a fast user habit), NONE (slower or inconsistent
                   — looks like a real user habit worth surfacing).
    """

    median_lag_ms: float
    consistency: float
    tier: CouplingTier


# Tier thresholds. Tunable from field feedback; encoded as module
# constants rather than detector class attrs so the card can reference
# the same numbers if it ever wants to render explanatory text.
TIGHT_MEDIAN_LAG_MS: float = 500.0
TIGHT_MIN_CONSISTENCY: float = 0.90

LOOSE_MEDIAN_LAG_MS: float = 2000.0
LOOSE_MIN_CONSISTENCY: float = 0.70

# Confidence demotion factor applied when tier == TIGHT. Multiplicative
# rather than additive so already-borderline insights don't disappear
# entirely — a 0.6 insight becomes 0.51 (still emits), an 0.95 becomes
# 0.81 (still strong, just ranks below uncoupled peers).
TIGHT_CONFIDENCE_FACTOR: float = 0.85


def compute_coupling(
    deltas_seconds: list[float],
    leader_count: int,
) -> CouplingScore:
    """Score the coupling strength of a B-follows-A pair.

    Args:
      deltas_seconds: list of (follower_ts - leader_ts) in seconds for
        every observed occurrence of the pair. Detectors already
        compute this for confidence/title; we reuse it.
      leader_count: total times the leader fired with the relevant
        state during the lookback window (including fires that didn't
        produce a follower). Detectors already have this as
        `leader_total`.

    Returns:
      CouplingScore. tier is NONE when deltas is empty or
      leader_count is zero (degenerate input — caller likely
      shouldn't call us, but we don't crash).
    """
    if not deltas_seconds or leader_count <= 0:
        return CouplingScore(
            median_lag_ms=0.0,
            consistency=0.0,
            tier="NONE",
        )

    median_lag_s = statistics.median(deltas_seconds)
    median_lag_ms = median_lag_s * 1000.0
    consistency = min(1.0, len(deltas_seconds) / leader_count)

    if (
        median_lag_ms <= TIGHT_MEDIAN_LAG_MS
        and consistency >= TIGHT_MIN_CONSISTENCY
    ):
        tier: CouplingTier = "TIGHT"
    elif (
        median_lag_ms <= LOOSE_MEDIAN_LAG_MS
        and consistency >= LOOSE_MIN_CONSISTENCY
    ):
        tier = "LOOSE"
    else:
        tier = "NONE"

    return CouplingScore(
        median_lag_ms=round(median_lag_ms, 1),
        consistency=round(consistency, 3),
        tier=tier,
    )


def coupling_payload(score: CouplingScore) -> dict[str, float | str]:
    """Serialize a CouplingScore for inclusion in an Insight payload.

    Keeps the keys flat / JSON-friendly. Used by detectors to stamp
    `payload["_coupling"]`. The card reads tier + median_lag_ms to
    render the 🔗 badge + tooltip.
    """
    return {
        "tier": score.tier,
        "median_lag_ms": score.median_lag_ms,
        "consistency": score.consistency,
    }


def apply_tier_demotion(confidence: float, tier: CouplingTier) -> float:
    """Adjust an insight's confidence based on coupling tier.

    TIGHT-coupled pairs almost certainly already have a binding or
    automation handling them; demote so they rank below uncoupled
    suggestions in the panel. LOOSE and NONE pass through unchanged
    — LOOSE might be HA-automation OR a fast user habit, and we want
    the user to see those and decide.
    """
    if tier == "TIGHT":
        return round(confidence * TIGHT_CONFIDENCE_FACTOR, 3)
    return confidence


__all__ = [
    "LOOSE_MEDIAN_LAG_MS",
    "LOOSE_MIN_CONSISTENCY",
    "TIGHT_CONFIDENCE_FACTOR",
    "TIGHT_MEDIAN_LAG_MS",
    "TIGHT_MIN_CONSISTENCY",
    "CouplingScore",
    "CouplingTier",
    "apply_tier_demotion",
    "compute_coupling",
    "coupling_payload",
]
