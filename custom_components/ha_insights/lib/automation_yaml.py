"""Pure-Python helpers for transforming HA automation YAML structures.

No HA imports — these are dict-shape transforms a downstream caller (the
HA-coupled apply pipeline in `apply/automation_writer.py`) uses to mutate
an automation before writing. Pure functions, deterministic, unit-
testable, HA-core-adoptable.

v1.5.44 ships one transform: `append_entities_to_action_block` — adds
new entity_ids to the existing action block when the user selects
candidates from the Suggested-Additions modal.
"""
from __future__ import annotations

from typing import Any

# Domains that share the same "turn_on" / "turn_off" service pattern.
# When appending a new entity to an action block, we match against the
# existing action items' service domains. The new entity must be in
# the SAME domain as at least one existing action item — cross-domain
# additions are not handled deterministically (they need LLM judgment
# to pick the right service like `media_player.play_media`).
_TURN_ON_OFF_DOMAINS = frozenset({
    "light",
    "switch",
    "fan",
    "media_player",
    "cover",
    "lock",
    "vacuum",
    "scene",
    "script",
    "input_boolean",
    "siren",
    "valve",
    "humidifier",
    "water_heater",
    "automation",
    "remote",
    "button",
})


def _domain_of(eid: str) -> str | None:
    if not isinstance(eid, str) or "." not in eid:
        return None
    return eid.split(".", 1)[0]


def _service_domain(service: str | None) -> str | None:
    if not isinstance(service, str) or "." not in service:
        return None
    return service.split(".", 1)[0]


def _normalize_entity_id_field(value: Any) -> list[str]:
    """Return entity_id field as a list. Scalar → 1-elem list; list →
    list copy; None → empty list. Anything else → empty list (defensive)."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    return []


def append_entities_to_action_block(
    automation_payload: dict[str, Any],
    new_entity_ids: list[str],
) -> tuple[dict[str, Any], list[str]]:
    """Append `new_entity_ids` to the matching action item(s) in an
    automation payload's action block.

    Strategy:
      1. For each new entity, find an action item whose service domain
         matches the entity's domain (e.g. `light.turn_on` matches a
         `light.*` entity).
      2. If found, extend that action's `target.entity_id` (or `entity_id`
         in the bare-field form, or `data.entity_id` for the legacy form).
         Promote scalar → list, append, dedupe.
      3. If no matching action item exists, append a NEW action item
         with `service: <domain>.turn_on` as the default. Caller should
         only invoke us when at least one new entity has a same-domain
         existing action — for cross-domain additions, route through
         the LLM Refine path instead.

    Returns `(modified_payload, unhandled_entity_ids)` where
    `unhandled_entity_ids` is the subset of `new_entity_ids` for which
    no matching action item exists AND we chose not to fabricate a new
    `turn_on` service call (e.g. domain is `media_player` where the
    right service is ambiguous between `turn_on` and `play_media`).

    Caveats / non-goals:
      - We do NOT modify trigger or condition blocks. Suggested-
        Additions is action-side only.
      - We do NOT validate the resulting YAML against HA's schema;
        that's the caller's job (typically via `apply/online_validator`).
      - We do NOT change service names — appending to an existing
        `light.turn_on` keeps the verb. If the user wants different
        behavior per-entity, route through LLM Refine.
    """
    if not new_entity_ids:
        return _deep_copy(automation_payload), []

    payload = _deep_copy(automation_payload)
    action_block = payload.get("action") or payload.get("actions")
    action_key = "action" if "action" in payload else "actions"
    if not isinstance(action_block, list):
        # Unsupported shape — return unchanged + everything unhandled
        return payload, list(new_entity_ids)

    # Group new entities by domain so we can find a single action item
    # per domain and extend it.
    by_domain: dict[str, list[str]] = {}
    for eid in new_entity_ids:
        dom = _domain_of(eid)
        if dom is None:
            continue
        by_domain.setdefault(dom, []).append(eid)

    unhandled: list[str] = []

    for dom, eids in by_domain.items():
        # Find first action item whose service matches this domain.
        target_idx = _find_action_idx_for_domain(action_block, dom)
        if target_idx is not None:
            _append_to_action_item(action_block[target_idx], eids)
        else:
            # No matching action — fabricate a `turn_on` call only for
            # well-known on/off domains. Otherwise hand back as unhandled.
            if dom in _TURN_ON_OFF_DOMAINS:
                new_item: dict[str, Any] = {
                    "service": f"{dom}.turn_on",
                    "target": {"entity_id": eids if len(eids) > 1 else eids[0]},
                }
                action_block.append(new_item)
            else:
                unhandled.extend(eids)

    payload[action_key] = action_block
    return payload, unhandled


def _find_action_idx_for_domain(
    action_block: list[Any], domain: str
) -> int | None:
    """Return the index of the first action item whose service domain
    matches `domain`. None if no match."""
    for idx, item in enumerate(action_block):
        if not isinstance(item, dict):
            continue
        svc = item.get("service") or item.get("action")
        if _service_domain(svc) == domain:
            return idx
    return None


def _append_to_action_item(action_item: dict[str, Any], new_eids: list[str]) -> None:
    """Mutate `action_item` to include `new_eids` in its entity_id field,
    deduped, promoting scalar to list where needed.

    Looks at (in order): `target.entity_id`, top-level `entity_id`,
    `data.entity_id`. Uses the first one that exists; if none exist,
    creates `target.entity_id`."""
    target = action_item.get("target")
    if isinstance(target, dict) and "entity_id" in target:
        existing = _normalize_entity_id_field(target["entity_id"])
        merged = _dedupe_keep_order(existing + new_eids)
        target["entity_id"] = merged if len(merged) > 1 else merged[0]
        return

    if "entity_id" in action_item:
        existing = _normalize_entity_id_field(action_item["entity_id"])
        merged = _dedupe_keep_order(existing + new_eids)
        action_item["entity_id"] = merged if len(merged) > 1 else merged[0]
        return

    data = action_item.get("data")
    if isinstance(data, dict) and "entity_id" in data:
        existing = _normalize_entity_id_field(data["entity_id"])
        merged = _dedupe_keep_order(existing + new_eids)
        data["entity_id"] = merged if len(merged) > 1 else merged[0]
        return

    # No existing entity_id field — create target.entity_id
    target_dict = action_item.setdefault("target", {})
    if not isinstance(target_dict, dict):
        # Defensive: target was something weird; overwrite with a dict
        action_item["target"] = {"entity_id": (
            new_eids if len(new_eids) > 1 else new_eids[0]
        )}
        return
    target_dict["entity_id"] = new_eids if len(new_eids) > 1 else new_eids[0]


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _deep_copy(value: Any) -> Any:
    """Cheap deep-copy of plain dict/list/scalar structures. Avoids
    `copy.deepcopy` overhead since automation payloads don't contain
    custom classes."""
    if isinstance(value, dict):
        return {k: _deep_copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_deep_copy(v) for v in value]
    return value


__all__ = ["append_entities_to_action_block"]
