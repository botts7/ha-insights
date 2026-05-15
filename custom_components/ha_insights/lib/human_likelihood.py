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

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .cooccurrence_likelihood import (
    CooccurrenceAssessment,
    apply_to_confidence as _apply_coocc,
    assess_cooccurrence,
)
from .persistence_likelihood import (
    PersistenceAssessment,
    apply_to_confidence as _apply_pers,
    assess_persistence,
)
from .timing_likelihood import (
    TimingAssessment,
    apply_to_confidence as _apply_timing,
    assess_timing,
)


@dataclass(frozen=True)
class HumanLikelihoodFeatures:
    """Bundle of all three signal-grader assessments for one pattern.

    Each field holds the structured assessment from the corresponding
    sibling lib. The bundle exposes two operations:

    - `apply_to(base_confidence)` — chains all penalties in canonical
      order. Detectors call this instead of 3 separate apply calls.
    - `payload_keys()` — yields the underscore-prefixed payload keys
      detectors should merge into their insight payload. Underscores
      keep these out of automations.yaml (automation_writer strips).

    Future grader libs (transition_entropy v1.5.39+, paired_event
    v1.6+) extend this dataclass by adding a new field + plumbing it
    through the two methods. Detectors that already use the composite
    pick up the new grader automatically.
    """

    timing: TimingAssessment
    cooccurrence: CooccurrenceAssessment
    persistence: PersistenceAssessment

    def apply_to(self, base_confidence: float) -> float:
        """Chain all three apply_to_confidence calls. Order matters
        only for readability — multiplication is commutative; the
        composite penalty is the product of human_likelihoods,
        clamped to [0, 1] at the end."""
        c = base_confidence
        c = _apply_timing(c, self.timing)
        c = _apply_coocc(c, self.cooccurrence)
        c = _apply_pers(c, self.persistence)
        return c

    def payload_keys(self) -> dict[str, Any]:
        """Return the underscore-prefixed payload entries to merge.
        Caller does `payload.update(features.payload_keys())` — the
        underscore-prefix convention (v1.5.34 automation_writer)
        strips them before YAML write."""
        return {
            "_timing_assessment": self.timing.to_dict(),
            "_cooccurrence_assessment": self.cooccurrence.to_dict(),
            "_persistence_assessment": self.persistence.to_dict(),
        }


def assess_human_likelihood(
    timestamps: list[datetime],
    nearby_counts: list[int],
    durations_seconds: list[float],
    iot_class: str | None = None,
) -> HumanLikelihoodFeatures:
    """One-shot composite assessment.

    Detectors pre-compute the three input lists (timestamps from
    cluster events, nearby_counts from event_buffer.query() windows,
    durations from next-state-change lookups) and pass them all in.
    This module dispatches to each sibling lib in turn.

    Args:
        timestamps: cluster event timestamps (timezone-aware datetimes).
        nearby_counts: surrounding-event count per cluster event.
        durations_seconds: duration-in-state per cluster event;
            sessions still open at buffer edge should be omitted.
        iot_class: HA integration iot_class for the entity (e.g.
            "cloud_polling", "local_push"). Drives the timing
            threshold table.

    Returns:
        HumanLikelihoodFeatures bundle. Use `.apply_to(base)` for
        the chained confidence and `.payload_keys()` for the
        payload merge.
    """
    return HumanLikelihoodFeatures(
        timing=assess_timing(timestamps=timestamps, iot_class=iot_class),
        cooccurrence=assess_cooccurrence(nearby_counts),
        persistence=assess_persistence(durations_seconds),
    )
