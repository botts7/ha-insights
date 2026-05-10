"""Shared helper: walk loaded scripts, return script_id → target entities.

Used by:
  - ws_api.ws_list (for the 🤖 in-automation pill expansion when an
    automation calls a script)
  - detectors._build_entity_dependencies (so the group dedup helper
    can merge insights from entities co-targeted by the same script)

Best-effort: if HA's script integration isn't loaded, returns {}.
Doesn't recurse — a script that calls another script is captured at
its own level only.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


def collect_script_targets(hass: HomeAssistant) -> dict[str, set[str]]:
    """Return a map of script.X → set of entity_ids the script's
    actions target. Empty dict on any failure to read script configs."""
    from .apply.conflict_scanner import _extract_target_entities

    out: dict[str, set[str]] = {}
    component = hass.data.get("script")
    entities_iter = None
    if hasattr(component, "entities"):
        entities_iter = component.entities
    elif isinstance(component, dict):
        entities_iter = component.values()
    if entities_iter is None:
        return out
    for ent in entities_iter:
        raw = (
            getattr(ent, "raw_config", None)
            or getattr(ent, "_raw_config", None)
        )
        if not isinstance(raw, dict):
            continue
        sid = getattr(ent, "entity_id", None)
        if not isinstance(sid, str) or "." not in sid:
            continue
        # Script config has `sequence` (or `action`) at the top
        actions = raw.get("sequence") or raw.get("action") or []
        targets = _extract_target_entities(actions)
        if targets:
            out[sid] = set(targets)
    return out
