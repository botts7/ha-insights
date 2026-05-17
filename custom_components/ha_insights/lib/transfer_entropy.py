"""Transfer entropy (Schreiber 2000) on discrete state sequences.

Transfer entropy quantifies directional information flow between two
time series. Given parallel sequences X and Y, `TE(X→Y)` measures how
much knowing X's past reduces uncertainty about Y's future, BEYOND
what Y's own past already tells you.

Formally:
    TE(X→Y) = H(Y_{t+1} | Y_t) - H(Y_{t+1} | Y_t, X_t)

For HA Insights this answers questions the existing detectors can't:

- LaggedCorrelationDetector finds pairs where Y follows X by N seconds
  with high consistency. But "follows" isn't "caused by." TE(X→Y)
  separates real causation from coincidence (both driven by a third
  factor like time of day).
- Cooccurrence pairs benefit from a direction check: TE(X→Y) vs
  TE(Y→X) tells whether motion drives the light or the light drives
  the motion (the latter happens with overlap-shadow false positives).
- Confidence demotion: if TE is near zero despite high temporal
  correlation, the pair is likely coincident, not causal.

## Implementation

Pure stdlib (collections.Counter, math.log2). pyinform has the math
but development stalled in 2018; rolling our own keeps the dep
footprint zero and the math auditable.

The caller is responsible for discretizing event streams into
parallel equal-length state sequences. Common approaches:

1. **Time-binned**: pick a bin size (30-60s typical for HA); for each
   bin record each entity's state at end of bin. Robust, simple.
2. **Event-aligned**: at each event from EITHER entity, sample both.
   More efficient but biased toward the higher-frequency entity.

This lib doesn't pick — `transfer_entropy(x_seq, y_seq)` operates on
two equal-length lists of hashable state values.

## Architecture per memory `ha_insights_research_answers_v1`

This is an **algorithmic lib** — pure math backing ONE detector
(LaggedCorrelationDetector v1.9.1+). Distinct from the
signal-grader libs (timing_likelihood, etc) which compose into a
HumanLikelihoodFeatures bundle.

Zero HA imports. Sample-based — small datasets (50–500 samples)
finish in single-digit milliseconds.
"""
from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class TransferEntropyAssessment:
    """One TE measurement for a pair (X, Y).

    te_x_to_y: TE(X→Y) in bits — how much X's past reduces uncertainty
        about Y's future, beyond Y's own past.
    te_y_to_x: TE(Y→X) in bits — the symmetric measurement.
    asymmetry: te_x_to_y - te_y_to_x. Positive means X drives Y;
        negative means Y drives X; near-zero means symmetric coupling
        (or no coupling — check the absolute values).
    dominant_direction: "x_to_y", "y_to_x", or "symmetric" based on
        which TE is larger AND the magnitude is meaningful
        (>0.05 bits, the conventional weak-signal threshold).
    n_samples: number of (y_{t+1}, y_t, x_t) triples used. Below
        ~30 the estimate is unreliable; callers should check.
    confidence: 0.0–1.0. Blends sample size (more = better) with
        signal strength (larger |asymmetry| = more confident in
        direction). Heuristic — calibrate against synthetic data
        before relying on it for thresholding.
    """

    te_x_to_y: float
    te_y_to_x: float
    asymmetry: float
    dominant_direction: str
    n_samples: int
    confidence: float


# Weak-signal threshold (bits). Below this, TE is statistically
# indistinguishable from sampling noise on small (~100 sample) inputs.
# Exported so callers can apply the same "uninformative" cutoff when
# deciding whether to act on an assessment.
#
# **v1.12.7 calibration**: raised from 0.05 → 0.10 after agent
# review flagged that the plug-in MLE entropy estimator we use is
# positively biased on small samples. At n=300 with 4-symbol
# alphabets (the typical HA event-binned regime), uncorrelated
# series can produce spurious TE of 0.1-0.3 bits. The previous
# 0.05 floor was below that bias and produced false-positive
# direction calls on short traces. 0.10 is still aggressive but
# captures more of the bias regime; bias-correction (Miller-
# Madow) is a v1.13 task if needed.
NOISE_FLOOR_BITS: float = 0.10
_NOISE_FLOOR_BITS: float = NOISE_FLOOR_BITS  # internal alias retained

# Minimum samples for a meaningful estimate. Below this the
# probability tables are too sparse; confidence drops to 0.
_MIN_SAMPLES_FOR_RELIABLE: int = 30


def transfer_entropy(
    x_seq: Sequence,
    y_seq: Sequence,
) -> TransferEntropyAssessment:
    """Compute TE(X→Y), TE(Y→X), and directionality for two
    equal-length state sequences.

    Args:
      x_seq: discrete states (hashable) sampled at each timestep.
      y_seq: discrete states (hashable) sampled at the same timesteps.
        Must have equal length to x_seq.

    Returns:
      TransferEntropyAssessment summarizing both directions, the
      dominant flow, and a confidence in that classification.

    Raises:
      ValueError: lengths differ or sequences have fewer than 2
        samples (no transition to evaluate).
    """
    if len(x_seq) != len(y_seq):
        raise ValueError(
            f"x_seq and y_seq must be equal length; "
            f"got {len(x_seq)} vs {len(y_seq)}"
        )
    n = len(x_seq)
    if n < 2:
        raise ValueError(
            f"need at least 2 samples; got {n}"
        )

    n_samples = n - 1  # we form (t, t+1) triples
    te_xy = _te_one_direction(x_seq, y_seq)
    te_yx = _te_one_direction(y_seq, x_seq)
    asymmetry = te_xy - te_yx

    # Direction classification.
    if max(te_xy, te_yx) < _NOISE_FLOOR_BITS:
        dominant = "symmetric"
    elif abs(asymmetry) < _NOISE_FLOOR_BITS:
        dominant = "symmetric"
    elif asymmetry > 0:
        dominant = "x_to_y"
    else:
        dominant = "y_to_x"

    # Confidence: sample-size factor × signal-strength factor.
    if n_samples < _MIN_SAMPLES_FOR_RELIABLE:
        confidence = round(n_samples / (2 * _MIN_SAMPLES_FOR_RELIABLE), 3)
    else:
        sample_factor = min(1.0, n_samples / 200.0)
        # Larger |asymmetry| → more confident in direction call.
        # Symmetric pairs have asymmetry ~0 → low direction confidence
        # (we're not confident WHICH direction, but we are confident
        # that it's symmetric).
        if dominant == "symmetric":
            signal_factor = 1.0 - min(1.0, abs(asymmetry) / 0.2)
        else:
            signal_factor = min(1.0, abs(asymmetry) / 0.2)
        confidence = round(sample_factor * (0.4 + 0.6 * signal_factor), 3)

    return TransferEntropyAssessment(
        te_x_to_y=round(te_xy, 4),
        te_y_to_x=round(te_yx, 4),
        asymmetry=round(asymmetry, 4),
        dominant_direction=dominant,
        n_samples=n_samples,
        confidence=confidence,
    )


def _te_one_direction(
    source: Sequence,
    target: Sequence,
) -> float:
    """Compute TE(source → target) in bits.

    TE(X→Y) = sum over (y_{t+1}, y_t, x_t) of
              p(y_{t+1}, y_t, x_t) *
              log2( p(y_{t+1} | y_t, x_t) / p(y_{t+1} | y_t) )

    Equivalent (and what we compute, for fewer subtractions):
      TE = H(Y_{t+1}, Y_t) + H(Y_t, X_t)
         - H(Y_{t+1}, Y_t, X_t) - H(Y_t)
    """
    # Joint counts of triples (y_{t+1}, y_t, x_t).
    triples = Counter(
        (target[t + 1], target[t], source[t]) for t in range(len(target) - 1)
    )
    # Marginal joints we need.
    y_pair = Counter(
        (target[t + 1], target[t]) for t in range(len(target) - 1)
    )
    y_t_x_t = Counter(
        (target[t], source[t]) for t in range(len(target) - 1)
    )
    y_t = Counter(target[t] for t in range(len(target) - 1))

    n = sum(triples.values())
    if n == 0:
        return 0.0

    # Shannon-entropy helpers in bits. H = -Σ p log2(p).
    def _h(counter: Counter) -> float:
        total = sum(counter.values())
        if total == 0:
            return 0.0
        h = 0.0
        for v in counter.values():
            if v > 0:
                p = v / total
                h -= p * math.log2(p)
        return h

    # All four entropies share the same denominator (n), so the
    # entropy values are directly comparable.
    return _h(y_pair) + _h(y_t_x_t) - _h(triples) - _h(y_t)


def discretize_event_stream(
    events: Sequence[tuple[float, str]],
    bin_size_seconds: float,
    total_duration_seconds: float,
    initial_state: str = "off",
) -> list[str]:
    """Helper: turn an event stream into time-binned state samples.

    Each bin's value is the entity's LAST state at or before the bin's
    end time. Bins where the entity hadn't seen any event yet take
    `initial_state`.

    Args:
      events: list of (timestamp_seconds, state) tuples, sorted by ts.
      bin_size_seconds: bin width.
      total_duration_seconds: total time span to discretize.
      initial_state: value for bins before any event arrives.

    Returns:
      List of state strings, one per bin.

    Convenience helper for callers that want event-aligned TE; not
    used by the core transfer_entropy function. Detector wiring will
    likely use this or a richer variant.
    """
    if bin_size_seconds <= 0 or total_duration_seconds <= 0:
        return []
    n_bins = int(total_duration_seconds / bin_size_seconds)
    samples: list[str] = []
    event_iter = iter(events)
    next_event: tuple[float, str] | None = next(event_iter, None)
    current_state = initial_state
    for bin_index in range(n_bins):
        bin_end = (bin_index + 1) * bin_size_seconds
        while next_event is not None and next_event[0] <= bin_end:
            current_state = next_event[1]
            next_event = next(event_iter, None)
        samples.append(current_state)
    return samples


__all__ = [
    "NOISE_FLOOR_BITS",
    "TransferEntropyAssessment",
    "discretize_event_stream",
    "transfer_entropy",
]
