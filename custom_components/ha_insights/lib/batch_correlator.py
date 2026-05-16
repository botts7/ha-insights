"""Batch correlator — group state_changed events by `context.id`.

When HA fires N state_changed events that all share the same
`context.id`, they're the downstream effect of ONE logical operation:

  - Group toggle: `light.living_room.turn_on` → forwarded service
    call to each member entity, each fires state_changed with
    `context = group_context`. (HA_EVENT_SEMANTICS.md Gotcha 1)
  - Scene activation: each target entity gets its own service call
    with the same shared context. (Gotcha 2)
  - Script run: every action in the script fires with the script's
    context. (Gotcha 3)

Without this correlator, detectors see N independent events:
  - cooccurrence flags "B follows A within 50ms" for every member
    pair (often dozens per group toggle)
  - manual_habit counts N habits when the user did ONE thing
  - routine detects "B + C + D fire together" as a multi-entity
    routine when it's actually just one scene call

The correlator is intentionally **annotative**, not destructive —
it groups events into batches but leaves the underlying StateEvent
records unchanged. Detectors opt in by calling `iter_batches()`
or `group_by_context_id()` and applying batch-aware logic. This
keeps detector-specific filtering local.

Upstream-PR candidate: HA core has no `async_track_state_change_batched`
helper. If this proves useful here, the pattern could be proposed
upstream — `homeassistant.helpers.event.batched_state_changes()`.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Iterator
from datetime import timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..observers.state_event_buffer import StateEvent


# Default batch window. HA service-call fan-out typically completes
# in <200ms per member; 1s gives generous margin. Wider windows risk
# joining unrelated events that coincidentally share a context.id
# (rare but possible — context.id is a UUID, collisions don't happen,
# but the SAME parent automation could call multiple services in a
# loop and reuse its context).
DEFAULT_BATCH_WINDOW = timedelta(seconds=1)
# Minimum events for a "batch" to be meaningful. A single event
# trivially has the same context.id as itself; that's not a batch.
MIN_BATCH_SIZE = 2


def group_by_context_id(
    events: Iterable[StateEvent],
) -> dict[str, list[StateEvent]]:
    """Bucket events by their context_id. Skips events whose
    context_id is None (system events, recorder backfill before
    we started capturing). Returns a dict — caller iterates
    `.values()` for the batches.
    """
    out: dict[str, list[StateEvent]] = defaultdict(list)
    for ev in events:
        ctx_id = getattr(ev, "context_id", None)
        if ctx_id:
            out[ctx_id].append(ev)
    return dict(out)


def iter_batches(
    events: Iterable[StateEvent],
    *,
    window: timedelta = DEFAULT_BATCH_WINDOW,
    min_size: int = MIN_BATCH_SIZE,
) -> Iterator[tuple[str, list[StateEvent]]]:
    """Yield (context_id, batch_events) for groups of 2+ events that
    share a context_id AND fall within `window` of each other.

    Same context.id but separated by minutes is NOT a batch — that's
    a long-running script or parallel-mode automation; treating it
    as one batch would mask genuine timing patterns. The window
    check enforces "near-simultaneous" semantics that match HA's
    real service-call fan-out behaviour.
    """
    by_ctx = group_by_context_id(events)
    for ctx_id, batch in by_ctx.items():
        if len(batch) < min_size:
            continue
        # Sort by timestamp; split if there's a gap larger than window
        batch.sort(key=lambda e: e.timestamp)
        run: list[StateEvent] = [batch[0]]
        for ev in batch[1:]:
            if ev.timestamp - run[-1].timestamp <= window:
                run.append(ev)
            else:
                if len(run) >= min_size:
                    yield ctx_id, run
                run = [ev]
        if len(run) >= min_size:
            yield ctx_id, run


def batched_entity_set(
    events: Iterable[StateEvent],
    *,
    window: timedelta = DEFAULT_BATCH_WINDOW,
) -> set[tuple[str, str]]:
    """Return the set of (entity_id_a, entity_id_b) pairs that
    appear TOGETHER in at least one batch.

    Used by cooccurrence + lagged_correlation to drop pairs that
    are co-effects of the same group toggle / scene / script call.
    Both directions are included so the caller can do `(A, B) in
    batched_pairs` regardless of which they called the leader.
    """
    pairs: set[tuple[str, str]] = set()
    for _ctx_id, batch in iter_batches(events, window=window):
        eids = sorted({ev.entity_id for ev in batch})
        for i, a in enumerate(eids):
            for b in eids[i + 1 :]:
                pairs.add((a, b))
                pairs.add((b, a))
    return pairs


__all__ = [
    "DEFAULT_BATCH_WINDOW",
    "MIN_BATCH_SIZE",
    "batched_entity_set",
    "group_by_context_id",
    "iter_batches",
]
