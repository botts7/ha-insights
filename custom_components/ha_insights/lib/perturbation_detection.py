"""Z-score ranking of candidate entities during a perturbation test.

The user perturbs a sensor (touches it / breathes on it / shines
light); the WS handler captures values from EVERY entity of the same
`device_class` during a listening window. This lib decides which
entity actually spiked.

## Why z-score, not absolute delta

A temp sensor that naturally fluctuates ±0.5 °C in still air shouldn't
false-positive on a +0.6 °C ambient drift. A temp sensor that's
normally rock-stable at ±0.05 °C SHOULD trigger on a +0.5 °C nudge.
Z-scoring against per-entity baseline noise picks the right answer
for both — the magnitude that matters is *relative to that sensor's
own variation*, not relative to a hardcoded threshold.

## The killer outcome: elimination

When the user touched what they THINK is `sensor.foo` but the
spike actually appears on `sensor.bar`, the result says:

  - top_match = "sensor.bar"
  - decision = "clear"
  - the card can pop "you touched what you said was foo, but bar
    actually spiked — they're probably mislabeled."

Mislabeling is endemic in HA installs. This is the most powerful
moment of the whole Find-My-Device feature.

## Decision logic

Three outcomes:

  1. **clear** — top z > z_threshold AND gap to runner-up > ambiguity_gap.
     The user can act with confidence.
  2. **ambiguous** — multiple candidates above z_threshold with no
     clear winner. Common when:
       - Multiple sensors are on the same multi-function device
         (e.g. one Aqara air-quality monitor exposes temp + humidity
         + CO₂; touching it spikes all three).
       - Two sensors are physically very close (kitchen counter pair).
     The card lists all qualifying candidates.
  3. **no_signal** — no candidate above z_threshold. Possible causes:
       - User didn't perturb yet
       - Wrong sensor type (device_class mismatch)
       - Sensor reports too infrequently (5-minute updates won't
         catch a 15-second touch)
       - Perturbation too weak (cold finger on warm sensor)
     Card prompts user to retry with stronger perturbation.

## Architecture

Pure function — no HA imports. Takes pre-collected sample lists
per entity_id (caller is responsible for capturing them). Sized
for typical inputs: 5-50 candidates, 5-60 samples each. Cost is
O(N * M).
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class CandidateAssessment:
    """One candidate entity's response to the perturbation.

    entity_id: the candidate.
    baseline_mean: average of pre-test samples in native units.
    baseline_stddev: std-dev of pre-test samples. Floored at
        STDDEV_FLOOR so a perfectly-stable sensor doesn't divide by
        zero and report z=infinity on the tiniest spike.
    peak_value: maximum absolute deviation from baseline_mean during
        the test window. We take MAX(|x - mean|) so spikes in either
        direction count (illuminance covering → drop; flashlight →
        rise; both signal "you touched the right one").
    peak_delta: signed difference (peak_value - baseline_mean). UI
        can render direction-aware ("rose by 2.3 °C" vs "dropped by
        180 lx"). Note: when peak_value was selected from MAX of
        absolute deltas, peak_delta keeps the sign of that selected
        sample so the renderer doesn't lose direction.
    z_score: (|peak_delta|) / baseline_stddev. Always non-negative.
    spike_detected: z_score >= caller's z_threshold.
    sample_count: number of test-window samples evaluated. Below ~3
        the assessment is unreliable — caller should warn.
    """

    entity_id: str
    baseline_mean: float
    baseline_stddev: float
    peak_value: float
    peak_delta: float
    z_score: float
    spike_detected: bool
    sample_count: int


@dataclass(frozen=True)
class PerturbationResult:
    """Aggregated outcome of one perturbation test.

    candidates: every evaluated entity, sorted by z_score descending.
    decision: "clear" | "ambiguous" | "no_signal" — see module docstring.
    top_match: the winning entity_id when decision == "clear", else None.
        For "ambiguous" the card lists all candidates above threshold;
        for "no_signal" there's nothing to surface.
    runner_up_gap: z-score gap between top and runner-up. Useful for
        the card to render "matched by N points clear" vs "edged by
        a hair." None when there's only one candidate.
    reason: one-sentence explanation of the decision. Surfaced
        directly in the card.
    """

    candidates: list[CandidateAssessment]
    decision: str
    top_match: str | None
    runner_up_gap: float | None
    reason: str


# Floor so a perfectly-stable sensor doesn't divide by zero and
# report z=infinity on the tiniest spike. In native units; for temp
# this is essentially "the sensor's quantization noise."
STDDEV_FLOOR: float = 0.1

# Minimum baseline samples for a meaningful stddev. Below this we
# fall back to a wider absolute-delta heuristic — single-sample
# baselines have no notion of variability.
_MIN_BASELINE_SAMPLES: int = 3


def analyze_perturbation(
    baseline_samples_per_entity: dict[str, list[float]],
    test_samples_per_entity: dict[str, list[float]],
    *,
    z_threshold: float = 3.0,
    ambiguity_gap: float = 1.5,
) -> PerturbationResult:
    """Decide which candidate entity spiked during the test window.

    Args:
      baseline_samples_per_entity: pre-test values per entity.
        Typically 10-60 samples covering the previous 1-2 minutes.
      test_samples_per_entity: values captured during the listening
        window. Typically 5-30 samples over 10-60 seconds depending
        on sensor reporting cadence.
      z_threshold: minimum z-score for "spike_detected". Default 3.0
        — covers ~99.7% of normal-distribution noise; spikes above
        this are unlikely to be ambient drift.
      ambiguity_gap: minimum z-score gap between top and runner-up
        for "clear" decision. Default 1.5 — empirically separates
        single-sensor matches from multi-function device spikes.

    Returns:
      PerturbationResult with ranked candidates + decision + reason.
    """
    if not test_samples_per_entity:
        return PerturbationResult(
            candidates=[],
            decision="no_signal",
            top_match=None,
            runner_up_gap=None,
            reason=(
                "No test-window samples were collected. The sensors "
                "may report too infrequently — try a sensor type "
                "with a faster update cadence."
            ),
        )

    assessments: list[CandidateAssessment] = []
    for entity_id, test_samples in test_samples_per_entity.items():
        baseline = baseline_samples_per_entity.get(entity_id, [])
        assess = _evaluate_one(
            entity_id, baseline, test_samples, z_threshold
        )
        if assess is not None:
            assessments.append(assess)

    assessments.sort(key=lambda a: a.z_score, reverse=True)

    if not assessments:
        return PerturbationResult(
            candidates=[],
            decision="no_signal",
            top_match=None,
            runner_up_gap=None,
            reason=(
                "No candidate entities had usable samples. "
                "Check that the sensors are reporting values."
            ),
        )

    top = assessments[0]
    if not top.spike_detected:
        return PerturbationResult(
            candidates=assessments,
            decision="no_signal",
            top_match=None,
            runner_up_gap=None,
            reason=(
                f"No candidate spiked above z={z_threshold:.1f}. "
                "Top response was just "
                f"{top.peak_delta:+.2f} on {top.entity_id} "
                f"(z={top.z_score:.2f}). Try a stronger perturbation "
                "or confirm the sensor type — passive sensors with "
                "5-minute update cadence may not catch a 15-second "
                "touch."
            ),
        )

    if len(assessments) == 1:
        return PerturbationResult(
            candidates=assessments,
            decision="clear",
            top_match=top.entity_id,
            runner_up_gap=None,
            reason=(
                f"Only candidate: {top.entity_id} spiked "
                f"{top.peak_delta:+.2f} (z={top.z_score:.2f})."
            ),
        )

    runner_up = assessments[1]
    gap = top.z_score - runner_up.z_score
    if gap >= ambiguity_gap:
        return PerturbationResult(
            candidates=assessments,
            decision="clear",
            top_match=top.entity_id,
            runner_up_gap=gap,
            reason=(
                f"{top.entity_id} spiked {top.peak_delta:+.2f} "
                f"(z={top.z_score:.2f}); next best was "
                f"{runner_up.entity_id} at z={runner_up.z_score:.2f} — "
                f"a {gap:.1f}-point margin is clear."
            ),
        )

    # Ambiguous: collect everyone above the threshold.
    above_threshold = [a for a in assessments if a.spike_detected]
    eids = ", ".join(a.entity_id for a in above_threshold)
    return PerturbationResult(
        candidates=assessments,
        decision="ambiguous",
        top_match=None,
        runner_up_gap=gap,
        reason=(
            f"Multiple candidates spiked similarly: {eids}. "
            "They may be on the same multi-function device "
            "(one physical sensor exposed as N entities), or two "
            "sensors are physically close enough that one "
            "perturbation hit both. The cohort dedup step (v1.10.3 "
            "🔗 pill) is the next thing to check."
        ),
    )


def _evaluate_one(
    entity_id: str,
    baseline: list[float],
    test_samples: list[float],
    z_threshold: float,
) -> CandidateAssessment | None:
    """Compute a single candidate's assessment. Returns None when
    we can't form an opinion (no test samples)."""
    if not test_samples:
        return None

    if len(baseline) >= _MIN_BASELINE_SAMPLES:
        mean = sum(baseline) / len(baseline)
        variance = sum((x - mean) ** 2 for x in baseline) / len(baseline)
        stddev = max(STDDEV_FLOOR, math.sqrt(variance))
    else:
        # Single-sample (or empty) baseline: use the test-sample's
        # first value as the "before" reference and fall back to
        # STDDEV_FLOOR as the noise estimate. Less reliable, but
        # better than rejecting the entity entirely.
        mean = baseline[0] if baseline else test_samples[0]
        stddev = STDDEV_FLOOR

    # Find the sample farthest from baseline mean (in either direction).
    peak_value = test_samples[0]
    max_abs_delta = abs(test_samples[0] - mean)
    for sample in test_samples[1:]:
        d = abs(sample - mean)
        if d > max_abs_delta:
            max_abs_delta = d
            peak_value = sample

    peak_delta = peak_value - mean
    z_score = abs(peak_delta) / stddev

    return CandidateAssessment(
        entity_id=entity_id,
        baseline_mean=round(mean, 3),
        baseline_stddev=round(stddev, 3),
        peak_value=round(peak_value, 3),
        peak_delta=round(peak_delta, 3),
        z_score=round(z_score, 2),
        spike_detected=z_score >= z_threshold,
        sample_count=len(test_samples),
    )


__all__ = [
    "STDDEV_FLOOR",
    "CandidateAssessment",
    "PerturbationResult",
    "analyze_perturbation",
]
