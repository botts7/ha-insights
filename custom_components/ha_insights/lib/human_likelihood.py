"""HumanLikelihoodFeatures — compose timing / co-occurrence / persistence into one assessment.

Pre-v1.5.38, schedule + streak (and any future habit detector) each
inlined the same 6-line chain:

    timing = assess_timing(...)
    coocc = assess_cooccurrence(...)
    pers = assess_persistence(...)
    c = timing_apply(c, timing)
    c = coocc_apply(c, coocc)
    c = pers_apply(c, pers)
    payload["_timing_assessment"] = timing.to_dict()
    payload["_cooccurrence_assessment"] = coocc.to_dict()
    payload["_persistence_assessment"] = pers.to_dict()

That worked at 1 lib (timing only). Tolerable at 2 libs. With 3 libs
the pattern duplicates 18 lines across every habit detector and every
new grader lib (transition_entropy v1.5.39, paired_event v1.6+) adds
3 more lines per call site.

The composite:
- One function call per detector to compute the bundle.
- One method to apply all penalties to a confidence value.
- One method to serialize all assessments into payload.
- Future grader libs drop into THIS module; detectors don't change.

That's the modularity rule (CLAUDE.md):
  "If the same fix has to apply in N>1 places, the previous code was
   wrong. Factor a helper into ui/theme, AppBase, or a shared service
   module so future fixes propagate automatically."

So while each grader lib stays a pure-math sibling, the *composition*
pattern is what should be reusable.

---

## Usage

```python
from ..lib.human_likelihood import assess_human_likelihood

features = assess_human_likelihood(
    timestamps=[ev.timestamp for ev in events],
    nearby_counts=[count_others_within_window(ev) for ev in events],
    durations_seconds=[next_change_delta(ev) for ev in events],
    iot_class=ctx.iot_class_of(entity_id),
)
confidence = features.apply_to(base_confidence)
payload.update(features.payload_keys())
```

Detectors now write 3 lines of feature-extraction + 2 lines of
composition, total 5 vs the previous 18+.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .cooccurrence_likelihood import (
    CooccurrenceAssessment,
    assess_cooccurrence,
)
from .cooccurrence_likelihood import (
    apply_to_confidence as _apply_coocc,
)
from .persistence_likelihood import (
    PersistenceAssessment,
    assess_persistence,
)
from .persistence_likelihood import (
    apply_to_confidence as _apply_pers,
)
from .timing_likelihood import (
    TimingAssessment,
    assess_timing,
)
from .timing_likelihood import (
    apply_to_confidence as _apply_timing,
)
from .transition_entropy import (
    TransitionEntropyAssessment,
    assess_transition_entropy,
)
from .transition_entropy import (
    apply_to_confidence as _apply_entropy,
)


@dataclass(frozen=True)
class HumanLikelihoodFeatures:
    """Bundle of all four signal-grader assessments for one pattern.

    Each field holds the structured assessment from the corresponding
    sibling lib. The bundle exposes two operations:

    - `apply_to(base_confidence)` — chains all penalties in canonical
      order. Detectors call this instead of separate apply calls.
    - `payload_keys()` — yields the underscore-prefixed payload keys
      detectors should merge into their insight payload. Underscores
      keep these out of automations.yaml (automation_writer strips).

    Pattern for adding the next grader lib (v1.6+):
      1. Build `lib/<name>_likelihood.py` matching the pattern.
      2. Add new field here as Optional (so old callers don't break).
      3. Apply in `apply_to()` only if not None.
      4. Add to `payload_keys()` only if not None.
      5. Detectors that pass the new arg pick up the new grader;
         detectors that don't get identical pre-v1.6 behavior.

    v1.5.40: `transition_entropy` is Optional for that reason — until
    every consuming detector computes its input, we don't want to
    error or under-grade by silently passing zero.
    """

    timing: TimingAssessment
    cooccurrence: CooccurrenceAssessment
    persistence: PersistenceAssessment
    transition_entropy: TransitionEntropyAssessment | None = None

    def apply_to(self, base_confidence: float) -> float:
        """Chain all apply_to_confidence calls. Order is commutative
        (multiplication); we chain in the original lib-addition order
        for readability. Optional graders are skipped when None."""
        c = base_confidence
        c = _apply_timing(c, self.timing)
        c = _apply_coocc(c, self.cooccurrence)
        c = _apply_pers(c, self.persistence)
        if self.transition_entropy is not None:
            c = _apply_entropy(c, self.transition_entropy)
        return c

    def payload_keys(self) -> dict[str, Any]:
        """Return the underscore-prefixed payload entries to merge."""
        d = {
            "_timing_assessment": self.timing.to_dict(),
            "_cooccurrence_assessment": self.cooccurrence.to_dict(),
            "_persistence_assessment": self.persistence.to_dict(),
        }
        if self.transition_entropy is not None:
            d["_transition_entropy_assessment"] = (
                self.transition_entropy.to_dict()
            )
        return d


def assess_human_likelihood(
    timestamps: list[datetime],
    nearby_counts: list[int],
    durations_seconds: list[float],
    iot_class: str | None = None,
    previous_state_durations_seconds: list[float] | None = None,
    distinct_entity_counts: list[int] | None = None,
) -> HumanLikelihoodFeatures:
    """One-shot composite assessment.

    Detectors pre-compute the input lists (cluster event timestamps,
    surrounding-event counts, durations forward + optionally backward)
    and pass them all in. This module dispatches to each sibling lib.

    Args:
        timestamps: cluster event timestamps (timezone-aware datetimes).
        nearby_counts: surrounding-event count per cluster event.
        durations_seconds: forward duration-in-state per cluster
            event (how long the entity stayed in the new state).
        iot_class: HA integration iot_class for the entity (e.g.
            "cloud_polling", "local_push").
        previous_state_durations_seconds: v1.5.39 — backward duration
            (how long the entity WAS in the previous state before
            the cluster event). When provided, the persistence lib
            picks whichever direction has the lower CV — catches
            things like toothbrush OFF events where the brushing
            session length (backward) is the device fingerprint.
            None means "skip backward analysis"; an empty list
            means "tried, no data".

    Returns:
        HumanLikelihoodFeatures bundle. Use `.apply_to(base)` and
        `.payload_keys()`.
    """
    return HumanLikelihoodFeatures(
        timing=assess_timing(timestamps=timestamps, iot_class=iot_class),
        cooccurrence=assess_cooccurrence(nearby_counts),
        persistence=assess_persistence(
            durations_seconds,
            previous_state_durations_seconds=previous_state_durations_seconds,
        ),
        transition_entropy=(
            assess_transition_entropy(distinct_entity_counts)
            if distinct_entity_counts is not None
            else None
        ),
    )
