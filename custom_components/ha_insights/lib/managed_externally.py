"""User-managed device suppression — "stop surfacing patterns from this device".

The integration already infers DEVICE_LIKELY automatically from timing
signatures (lib/timing_likelihood) and from integration-platform
whitelists (Tuya, Shelly, etc — see ws_api._EXTERNAL_SCHEDULE_PLATFORMS).
Those signals DEMOTE insights — surface them at lower confidence with a
pill explaining why.

This module is the third orthogonal signal: a USER ASSERTION that a
specific device handles its own logic, and any pattern HA Insights
detects on it should be filtered out entirely. The user has already
decided; we don't keep nagging.

Architecture:
- Device IDs are stored in entry options under `managed_externally_devices`
  (list[str] of HA device_registry IDs).
- This module exports a pure function `is_suppressed(insight,
  managed_devices, hierarchy)` that returns True if the insight
  references ANY entity whose device is in the managed set.
- The detector pipeline (run_all_detectors) calls this filter after
  each detector emits and drops suppressed insights before they enter
  the store.
- WS endpoints `home_insights/list_managed_devices` +
  `home_insights/set_device_managed` let the card add/remove flags.

Zero HA imports. Pure functions on the Insight + device-of mapping.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

# Entity-ID-shaped field names. Detectors put entities in different
# places (cooccurrence: leader_entity_id/follower_entity_id, manual_habit:
# entity_id, audit: target_entities/trigger_entities, etc), so rather
# than enumerate every key we accept any key that ENDS with these
# suffixes OR matches the literal forms.
_ENTITY_ID_KEY_SUFFIXES: tuple[str, ...] = (
    "entity_id",
    "entity_ids",
    "_eid",
)

_ENTITY_ID_RE = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")


def _is_entity_id_string(value: Any) -> bool:
    """True if value looks like an HA entity_id (`domain.object_id`)."""
    return isinstance(value, str) and bool(_ENTITY_ID_RE.match(value))


def _is_entity_field_key(key: Any) -> bool:
    """True if a dict key is an entity-id-bearing field name.

    Matches `entity_id`, `entity_ids`, anything ending in `_eid` or
    `_entity_id` (cooccurrence's leader_entity_id, etc), and a small
    set of detector-specific list keys.
    """
    if not isinstance(key, str):
        return False
    if key in {"entity_id", "entity_ids"}:
        return True
    if key.endswith("_entity_id") or key.endswith("_entity_ids"):
        return True
    if key.endswith("_eid"):
        return True
    # Detector-specific aggregations seen in audit packets.
    return key in {"target_entities", "trigger_entities"}


def collect_referenced_entities(
    fingerprint: dict[str, Any],
    payload: dict[str, Any],
) -> set[str]:
    """Walk an insight's fingerprint + payload and collect every
    entity_id referenced via entity-id-bearing fields.

    Free-text fields (alias, description, title) are NOT scanned —
    those may legitimately mention `light.turn_on` (a service name)
    or other dot-namespaced strings that aren't entities.
    """
    found: set[str] = set()
    _walk(fingerprint, found, in_entity_field=False)
    _walk(payload, found, in_entity_field=False)
    return found


def _walk(value: Any, accumulator: set[str], *, in_entity_field: bool) -> None:
    if isinstance(value, str):
        if in_entity_field and _is_entity_id_string(value):
            accumulator.add(value)
        return
    if isinstance(value, dict):
        for key, sub in value.items():
            sub_in_field = in_entity_field or _is_entity_field_key(key)
            _walk(sub, accumulator, in_entity_field=sub_in_field)
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            _walk(item, accumulator, in_entity_field=in_entity_field)


def is_suppressed(
    *,
    fingerprint: dict[str, Any],
    payload: dict[str, Any],
    managed_devices: frozenset[str],
    device_of: dict[str, str | None],
) -> bool:
    """Return True if any entity referenced by the insight belongs to
    a managed-externally device.

    Args:
      fingerprint: Insight.fingerprint dict.
      payload:     Insight.payload dict.
      managed_devices: device_ids the user has marked managed externally.
      device_of:   entity_id -> device_id (or None) mapping. Source of
        truth is hierarchy.device_of from the detector context.

    Returns False when managed_devices is empty (fast path — most
    installs won't have any flagged devices).
    """
    if not managed_devices:
        return False
    entities = collect_referenced_entities(fingerprint, payload)
    for eid in entities:
        device_id = device_of.get(eid)
        if device_id is not None and device_id in managed_devices:
            return True
    return False


def filter_insights(
    insights: Iterable[Any],
    managed_devices: frozenset[str],
    device_of: dict[str, str | None],
) -> tuple[list[Any], list[Any]]:
    """Split an insight list into (kept, suppressed).

    Convenience for the detector pipeline. Insight is duck-typed —
    anything with `.fingerprint` and `.payload` dicts works, so this
    avoids importing the Insight class and creating a cycle.
    """
    if not managed_devices:
        return list(insights), []
    kept: list[Any] = []
    suppressed: list[Any] = []
    for insight in insights:
        if is_suppressed(
            fingerprint=getattr(insight, "fingerprint", {}) or {},
            payload=getattr(insight, "payload", {}) or {},
            managed_devices=managed_devices,
            device_of=device_of,
        ):
            suppressed.append(insight)
        else:
            kept.append(insight)
    return kept, suppressed


__all__ = [
    "collect_referenced_entities",
    "filter_insights",
    "is_suppressed",
]
