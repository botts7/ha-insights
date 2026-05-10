"""Conflict scanner — detect overlap with existing automations before apply.

Algorithm:
  - **Time-trigger overlap** on the same target entity = conflict
    (Time window: +/- 10 minutes by default; entity match: same
    entity_id in both action targets)
  - **State-trigger overlap** on the same source entity = conflict
    (Two automations both firing on `state(entity_id) -> X` would
    cascade; we flag this so the user can decide whether to consolidate)

Numeric-state and template-trigger overlap are not yet checked.
"""
from __future__ import annotations

from typing import Any

from ..insight import Insight

DEFAULT_TIME_WINDOW_MIN = 10


def find_conflicts(
    insight: Insight,
    existing_automations: list[dict[str, Any]],
    *,
    time_window_min: int = DEFAULT_TIME_WINDOW_MIN,
) -> list[str]:
    """Return identifiers of existing automations that overlap with this insight.

    Identifier preference: 'id' field, then 'alias', then 'unknown'. Caller
    can use the returned list to attach `conflicts_with` on the Insight or
    to suppress emission entirely.
    """
    if insight.payload_format != "automation":
        return []

    candidate = insight.payload
    conflicts: list[str] = []
    for existing in existing_automations:
        if _automations_overlap(candidate, existing, time_window_min):
            ident = (
                existing.get("id")
                or existing.get("alias")
                or "unknown"
            )
            conflicts.append(str(ident))
    return conflicts


def _automations_overlap(
    a: dict[str, Any], b: dict[str, Any], time_window_min: int
) -> bool:
    """Detect overlap between two automations: target + trigger pattern.

    All checks require BOTH trigger overlap AND action-target overlap.
    Without the action check we'd flag any two automations triggered by
    the same entity as conflicts — but two automations on `motion -> on`
    that turn on different things (light vs notification vs scene) are
    independent, not duplicates.

    Trigger overlap branches (in order of strictness):
      1. Time-trigger: both `platform: time`, time strings within ±N min
      2. State-trigger: same source entity_id + target state
      3. Schedule-like fallback: both triggers are schedule-y in any way
         (time / time_pattern / sun / calendar / template), targets match.
         This catches morning-routine automations triggered by `sun`
         that the user reports as "missing" because the streak detector
         sees the resulting state change at a fixed clock time but the
         automation triggers on a celestial event.
    """
    a_triggers = _as_list(a.get("trigger"))
    b_triggers = _as_list(b.get("trigger"))
    a_entities = _extract_target_entities(a.get("action", []))
    b_entities = _extract_target_entities(b.get("action", []))
    target_overlap = bool(a_entities & b_entities)
    if not target_overlap:
        # Different action targets = different intent. No conflict.
        return False

    # Time-trigger overlap: same trigger time AND same target entity
    for at in a_triggers:
        if not isinstance(at, dict) or at.get("platform") != "time":
            continue
        for bt in b_triggers:
            if not isinstance(bt, dict) or bt.get("platform") != "time":
                continue
            if _times_close(at.get("at"), bt.get("at"), time_window_min):
                return True

    # State-trigger overlap: same trigger signature AND same target entity.
    a_states = _state_trigger_signatures(a_triggers)
    b_states = _state_trigger_signatures(b_triggers)
    if a_states & b_states:
        return True

    # Schedule-like fallback: when target overlaps AND BOTH automations
    # have a schedule-driven trigger of any kind, we can't compare exact
    # times (the existing automation triggers on sun, the insight on a
    # learned clock time), but the intent is the same. Flag as conflict.
    if _has_schedule_like_trigger(a_triggers) and _has_schedule_like_trigger(
        b_triggers
    ):
        return True

    return False


_SCHEDULE_LIKE_PLATFORMS: frozenset[str] = frozenset(
    {
        "time",
        "time_pattern",
        "sun",
        "calendar",
        "homeassistant",  # startup / shutdown trigger
    }
)


def _has_schedule_like_trigger(triggers: list[Any]) -> bool:
    """Whether any trigger fires on a schedule-driven event."""
    for t in triggers:
        if isinstance(t, dict) and t.get("platform") in _SCHEDULE_LIKE_PLATFORMS:
            return True
    return False


def _state_trigger_signatures(
    triggers: list[Any],
) -> set[tuple[str, str | None]]:
    """Extract (entity_id, to_state) signatures from state triggers.

    `to` is normalized to None when missing so triggers without a
    specific value (the "any change" form) match each other.
    """
    sigs: set[tuple[str, str | None]] = set()
    for t in triggers:
        if not isinstance(t, dict) or t.get("platform") != "state":
            continue
        eid = t.get("entity_id")
        to_val = t.get("to")
        # entity_id can be a string or list of strings
        if isinstance(eid, str):
            entity_ids = [eid]
        elif isinstance(eid, list):
            entity_ids = [e for e in eid if isinstance(e, str)]
        else:
            continue
        # to: can be a string, list, or None ("any change")
        if isinstance(to_val, list):
            to_values: list[str | None] = [
                str(v) for v in to_val if isinstance(v, (str, int, bool))
            ]
        elif isinstance(to_val, str):
            to_values = [to_val]
        else:
            to_values = [None]
        for e in entity_ids:
            for v in to_values:
                sigs.add((e, v))
    return sigs


def _as_list(value: Any) -> list[Any]:
    """Triggers/actions can be a single dict or a list of dicts in HA YAML."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _times_close(t1: str | None, t2: str | None, threshold_min: int) -> bool:
    """Whether HH:MM[:SS] strings are within threshold_min minutes."""
    if not isinstance(t1, str) or not isinstance(t2, str):
        return False
    try:
        m1 = _to_minutes(t1)
        m2 = _to_minutes(t2)
    except (ValueError, IndexError):
        return False
    return abs(m1 - m2) <= threshold_min


def _to_minutes(t: str) -> int:
    parts = t.split(":")
    return int(parts[0]) * 60 + int(parts[1])


def _extract_target_entities(actions: Any) -> set[str]:
    """Pull all entity_ids from a list of action dicts."""
    entities: set[str] = set()
    for action in _as_list(actions):
        if not isinstance(action, dict):
            continue
        target = action.get("target")
        if isinstance(target, dict):
            eid = target.get("entity_id")
            if isinstance(eid, str):
                entities.add(eid)
            elif isinstance(eid, list):
                entities.update(e for e in eid if isinstance(e, str))
        # legacy form: action.entity_id
        eid_top = action.get("entity_id")
        if isinstance(eid_top, str):
            entities.add(eid_top)
    return entities
