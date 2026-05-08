"""Conflict scanner — detect overlap with existing automations before apply.

v0.1 algorithm:
  - Time-trigger overlap on the same target entity = conflict
  - Time window: +/- 10 minutes by default
  - Entity match: same entity_id in both action targets

Non-time triggers (state, numeric_state, etc.) are not checked at v0.1
since ScheduleDetector only emits time-triggered automations. Coverage
expands as new detectors land.
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
    """Time-trigger overlap on the same target entity (within window)."""
    a_triggers = _as_list(a.get("trigger"))
    b_triggers = _as_list(b.get("trigger"))

    for at in a_triggers:
        if not isinstance(at, dict) or at.get("platform") != "time":
            continue
        for bt in b_triggers:
            if not isinstance(bt, dict) or bt.get("platform") != "time":
                continue
            if not _times_close(at.get("at"), bt.get("at"), time_window_min):
                continue
            a_entities = _extract_target_entities(a.get("action", []))
            b_entities = _extract_target_entities(b.get("action", []))
            if a_entities & b_entities:
                return True
    return False


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
