"""Transition-entropy assessment — does a pattern's cluster of events occur in predictable surrounding context?

Fourth signal-grader sibling to timing / co-occurrence / persistence
likelihood libs. Same architecture, same return-shape, same
`apply_to_confidence` signature so detectors chain it through the
v1.5.38 `HumanLikelihoodFeatures` composite.

---

## The signal (Houzé 2022, Markov approximation)

Algorithmic information theory ("memorability") asks: if you observed
this event, would you remember it? Routine events compress to a short
rule ("Friday 5pm, like every Friday"); memorable events resist
compression ("Friday 5pm, but the door was wide open and the dog was
barking"). The full AIT measure is uncomputable, but a cheap proxy
falls out of Markov chains: the Shannon entropy of the transition
distribution from the preceding events to the current one.

For HA Insights' habit detectors, "context" = the set of OTHER
entities that have recently changed state. A toothbrush brushing at
08:54 surrounded by 5 always-the-same entities (presence sensors,
bathroom light, etc.) is a tight routine. A toothbrush brushing at
08:54 surrounded by a different random set of entities each day is
either noise or genuinely-novel behavior. The first deserves a
confidence boost; the second deserves a penalty.

We measure the *diversity* of context across cluster events. If the
median number of DISTINCT preceding entities is small, the entity is
embedded in a stable surrounding routine (low entropy → human-
likely). If the median is large, the entity fires in a constantly-
shifting context (high entropy → either user noise or device polling
that happens to coincide with varied background activity).

## Why this isn't redundant with cooccurrence

`cooccurrence_likelihood` counts HOW MANY other entities fire near
each cluster event. `transition_entropy` counts HOW MANY DISTINCT
entities fire across the cluster — same window, different axis.

  - Toothbrush flapping during brushing: cooccurrence sees many
    nearby events (the brush ON/OFF flapping itself), classifies as
    human_context. Entropy sees few distinct entities (mostly just
    the brush appearing multiple times), classifies as routine.

  - Solar inverter polling at sunrise: cooccurrence might see 1-2
    nearby events (sister sensors from same SEMS integration),
    classifies as ambiguous. Entropy sees those same few distinct
    entities every day, classifies as routine — agrees.

  - A user opens the fridge while phone is charging and dog is
    barking: cooccurrence and entropy both classify human_context.

The two signals are *correlated* but not identical, and cases like
the toothbrush show they can diverge usefully.

## Architecture

Pure function over a list of distinct-entity counts (one count per
cluster event). Detectors compute the counts by querying the event
buffer within ±5s of each cluster event and counting DISTINCT
entity_ids in the result (excluding the entity itself).

Same `apply_to_confidence` helper shape as the prior three libs.
"""
from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class TransitionEntropyClass(str, Enum):
    """Coarse classification of context-diversity distribution."""

    ROUTINE_CONTEXT = "routine_context"
    """Median ≤ 2 distinct preceding entities — the cluster event
    is embedded in a stable surrounding routine. Strong human-habit
    signal (or a very-predictable device cycle, which timing and
    persistence already catch)."""

    AMBIGUOUS_CONTEXT = "ambiguous_context"
    """Median 3-5 distinct preceding entities — mixed context. Some
    overlap day-to-day, some variation."""

    NOVEL_CONTEXT = "novel_context"
    """Median > 5 distinct preceding entities — wildly different
    contexts across cluster events. Either real noise (HA boot bursts,
    integration reloads) or coincidental co-firing of unrelated
    entities. Demotes confidence because the "habit" isn't actually
    embedded in a stable behavioral pattern."""

    INSUFFICIENT_DATA = "insufficient_data"
    """< _MIN_SAMPLES cluster events. Not enough to compute median."""


_MIN_SAMPLES = 3


# Multipliers per class. NOVEL_CONTEXT gets a soft penalty (0.75) —
# stronger than tight-pattern but not as severe as fixed-cycle. The
# logic: if a "habit" fires in random contexts, it's probably not a
# stable user routine even if the time-of-day is consistent.
# ROUTINE_CONTEXT is neutral; we don't BOOST confidence above the
# detector's own number (libs only ever penalize, never inflate).
_LIKELIHOOD_BY_CLASS: dict[TransitionEntropyClass, float] = {
    TransitionEntropyClass.ROUTINE_CONTEXT: 1.0,
    TransitionEntropyClass.AMBIGUOUS_CONTEXT: 0.95,
    TransitionEntropyClass.NOVEL_CONTEXT: 0.75,
    TransitionEntropyClass.INSUFFICIENT_DATA: 1.0,
}


@dataclass(frozen=True)
class TransitionEntropyAssessment:
    """Result of context-diversity analysis.

    Fields:
        mean_distinct_entities: average count of distinct surrounding
            entities across cluster events.
        median_distinct_entities: median count; robust to outliers.
        transition_entropy_class: coarse classification.
        human_likelihood: confidence multiplier in [0, 1].
        reason: human-readable explanation for the tooltip.
        sample_count: how many cluster events were analyzed.
    """

    mean_distinct_entities: float
    median_distinct_entities: float
    transition_entropy_class: TransitionEntropyClass
    human_likelihood: float
    reason: str
    sample_count: int

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready dict for payload storage."""
        d = asdict(self)
        d["transition_entropy_class"] = self.transition_entropy_class.value
        return d


def assess_transition_entropy(
    distinct_entity_counts: list[int],
) -> TransitionEntropyAssessment:
    """Classify the context-diversity distribution across cluster events.

    Args:
        distinct_entity_counts: per cluster event, the count of
            DISTINCT other-entity state changes within the surrounding
            window. Detector pre-computes by querying buffer ±5s and
            building a set of entity_ids.

    Returns:
        TransitionEntropyAssessment with median-based classification.

    Pure function; no I/O, no HA imports.
    """
    n = len(distinct_entity_counts)
    if n < _MIN_SAMPLES:
        return TransitionEntropyAssessment(
            mean_distinct_entities=0.0,
            median_distinct_entities=0.0,
            transition_entropy_class=TransitionEntropyClass.INSUFFICIENT_DATA,
            human_likelihood=_LIKELIHOOD_BY_CLASS[
                TransitionEntropyClass.INSUFFICIENT_DATA
            ],
            reason=(
                f"only {n} events — need ≥ {_MIN_SAMPLES} for "
                f"context-diversity analysis."
            ),
            sample_count=n,
        )

    mean_v = statistics.fmean(distinct_entity_counts)
    median_v = statistics.median(distinct_entity_counts)

    if median_v <= 2:
        cls = TransitionEntropyClass.ROUTINE_CONTEXT
        reason = (
            f"each event has a median of {median_v:.0f} distinct "
            f"preceding entities across {n} events — embedded in a "
            f"stable routine context."
        )
    elif median_v <= 5:
        cls = TransitionEntropyClass.AMBIGUOUS_CONTEXT
        reason = (
            f"median {median_v:.0f} distinct preceding entities across "
            f"{n} events — mixed context. Some day-to-day overlap, "
            f"some variation."
        )
    else:
        cls = TransitionEntropyClass.NOVEL_CONTEXT
        reason = (
            f"median {median_v:.0f} distinct preceding entities across "
            f"{n} events — wildly different contexts. Either user noise "
            f"or coincidental co-firing rather than a stable routine."
        )

    return TransitionEntropyAssessment(
        mean_distinct_entities=round(mean_v, 2),
        median_distinct_entities=round(median_v, 2),
        transition_entropy_class=cls,
        human_likelihood=_LIKELIHOOD_BY_CLASS[cls],
        reason=reason,
        sample_count=n,
    )


def apply_to_confidence(
    base_confidence: float,
    assessment: TransitionEntropyAssessment,
) -> float:
    """clamp(base * assessment.human_likelihood). Matches the
    timing / cooccurrence / persistence helper signatures so detectors
    chain all four (or use the HumanLikelihoodFeatures composite,
    which handles this for them)."""
    out = base_confidence * assessment.human_likelihood
    return max(0.0, min(1.0, out))
