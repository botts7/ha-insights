"""Coactivation signal — entity_id → days co-fired with anchor entities.

Used by Suggested-Additions (`ws_api.ws_suggest_additions` →
`build_candidate_entities`) as the strongest of four candidate signals:
"the user habitually toggles X around the same time the automation runs,
so X is a likely Add candidate."

Anchor entities are the `required_entity_ids` collected from the
automation payload (trigger + condition + action entities). For each
anchor fire, every OTHER state change within ±`window_seconds` on the
same calendar day counts that day as a co-fire for the other entity.
The result is `entity_id → distinct_days_count`.

`manual_only=True` (default) drops the chain-automation noise:
- `context_user_id is not None` → UI / mobile / voice → keep
- `context_user_id is None AND context_parent_id is None` → likely
  physical-switch / external → keep (some cloud-app noise; tolerable
  for a signal that only nominates candidates, doesn't apply them)
- `context_parent_id is not None` → child of another automation → drop

`from_bootstrap=True` events are always excluded — HA's startup
fan-out produces correlated bursts that would false-positive every
window. See docs/HA_EVENT_SEMANTICS.md Gotcha 5.

Zero HA imports. Pure function operating on a sequence of StateEvent-
shaped objects (duck-typed by attribute access). Unit-testable from a
plain Python env, HA-core-adoptable.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol


class _EventLike(Protocol):
    """Duck-typed shape — every StateEvent attribute we read.

    Stays a Protocol (not a hard dep on StateEvent) so this module can
    be tested without importing the observers package.
    """

    timestamp: datetime
    entity_id: str
    context_user_id: str | None
    context_parent_id: str | None
    from_bootstrap: bool


def _is_manual(ev: _EventLike) -> bool:
    """Mirror manual_habit.py's classification, minus the
    local-integration allowlist (which needs hierarchy / iot_class
    context and would couple this pure-logic module to the integration
    layer). Result: a slightly looser filter that may include some
    cloud-app schedule events as "manual." Acceptable for a candidate-
    nomination signal — false positives appear in the modal but the
    user reviews before applying.
    """
    if ev.context_user_id is not None:
        return True  # HA UI / mobile app / voice
    if ev.context_parent_id is None:
        return True  # physical switch / external (no HA-side parent)
    return False


def compute_coactivation_days(
    events: Iterable[_EventLike],
    *,
    anchor_entity_ids: set[str],
    window_seconds: float = 5.0,
    lookback_days: int = 14,
    manual_only: bool = True,
    now: datetime | None = None,
) -> dict[str, int]:
    """Return `entity_id → distinct_days_co-fired_within_window`.

    Args:
      events: any iterable of StateEvent-shaped objects. Typically
        `buffer.snapshot()` from the StateEventBuffer.
      anchor_entity_ids: entities to anchor windows around. For
        Suggested-Additions, these are the automation's existing
        target entities (`required_entity_ids`). An anchor fire at
        time T marks the window [T - window_seconds, T + window_seconds]
        on calendar day date(T).
      window_seconds: half-width of the coactivation window. Default
        5 s matches the candidate-entities reason string ("±5 s").
      lookback_days: only events with `timestamp >= now - lookback_days`
        are considered. Default 14 matches the candidate-entities
        comment ("of 14 days").
      manual_only: when True (default), candidate events (the OTHER
        entity firing) must pass the `_is_manual` filter. Anchor
        events are NOT filtered — automations firing the anchor is
        exactly the signal we want to anchor on.
      now: clock injection for tests; defaults to `datetime.now(UTC)`.

    Returns:
      `dict[str, int]` — entity_id → count of distinct calendar days
      on which that entity fired within the coactivation window of at
      least one anchor event. Anchor entities themselves are excluded
      from the result. Empty dict when no events / no anchors / nothing
      coactivates.
    """
    if not anchor_entity_ids:
        return {}

    if now is None:
        now = datetime.now(tz=UTC)
    cutoff = now - timedelta(days=lookback_days)
    window = timedelta(seconds=window_seconds)

    # Single pass through events, sorted by timestamp. Split into
    # anchor fires (one list of timestamps per anchor entity) and
    # candidate fires (per-entity list of timestamps that pass the
    # manual filter). Bootstrap and out-of-window events drop here.
    anchor_times: list[datetime] = []
    candidate_events: list[tuple[datetime, str]] = []
    for ev in events:
        if ev.from_bootstrap:
            continue
        if ev.timestamp < cutoff:
            continue
        if ev.entity_id in anchor_entity_ids:
            anchor_times.append(ev.timestamp)
            continue
        if manual_only and not _is_manual(ev):
            continue
        candidate_events.append((ev.timestamp, ev.entity_id))

    if not anchor_times or not candidate_events:
        return {}

    # Sort once so the per-candidate window check can short-circuit
    # via bisect-style traversal. For typical 14d buffers (~50K events
    # bounded by the cap of 500K) this is well under 100ms even before
    # the early-exit.
    anchor_times.sort()
    candidate_events.sort(key=lambda e: e[0])

    # entity_id → set of dates on which it co-fired with at least one
    # anchor. Dates (not datetimes) so multiple fires within the same
    # window on the same day count once.
    days_by_entity: dict[str, set[date]] = defaultdict(set)

    # Two-pointer sweep. Candidates and anchors are both sorted
    # ascending. `i_start` is the leftmost anchor that could still
    # match the current (or any later) candidate — anchors before it
    # are too early for every remaining candidate.
    i_start = 0
    for ts, eid in candidate_events:
        lo = ts - window
        hi = ts + window
        while i_start < len(anchor_times) and anchor_times[i_start] < lo:
            i_start += 1
        # One anchor hit on this day is enough to mark the day.
        if i_start < len(anchor_times) and anchor_times[i_start] <= hi:
            days_by_entity[eid].add(ts.date())

    return {eid: len(days) for eid, days in days_by_entity.items()}


__all__ = ["compute_coactivation_days"]
