"""Build an ``EnvironmentalFingerprint`` from current HA state.

v1.14.5a (May 2026). HA-aware counterpart to the pure-stdlib
``lib/user_verdict_history.py``. Splitting the capture out of the
verdict-history lib keeps that one free of HA imports
(testability + upstream-PR friendliness).

The capture is the **lossy** half of the round-trip — we deliberately
do NOT serialize the full HA state. We only capture the three fields
``EnvironmentalFingerprint`` defines:

  - ``automation_ids`` — currently-enabled automation entity_ids.
    Drives AdaptiveFeedback's "user dismissed but later deleted the
    competing automation → re-suggest" path.
  - ``sensors_per_area`` — per-area count of device_class categories
    among non-blocked, non-disabled, non-hidden entities. Drives
    "user added a sensor that changes our analysis" path.
  - ``active_integrations`` — set of integration domains (platforms)
    represented by entities in the registry. Drives "user added a
    new integration" path.

## Why a separate helper module

``lib/user_verdict_history.py`` is pure stdlib so it's trivially
unit-testable and could be donated upstream. Capture needs the HA
entity registry + state machine, which are HA-only. Keeping the
two apart preserves the lib's portability.

## Privacy

The fingerprint does NOT include:

  - Entity IDs (except for automations, which are coarse-grained
    pattern identifiers — `automation.morning_lights` rather than
    `light.kitchen_pendant`).
  - State values.
  - User identifiers (those are captured separately as hashed
    ``user_id_hash`` on the verdict row).
  - Friendly names.

Any future expansion must preserve this contract — the verdict
fingerprint is meant to detect environmental DELTAS, not to log
home contents.
"""
from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from .user_verdict_history import EnvironmentalFingerprint

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

# Entities in these domains aren't real "sensors" for fingerprint
# purposes — they're derived or scaffolding entities that don't
# change the analysis when added/removed. Excluding them keeps the
# fingerprint stable across uninteresting churn (e.g. group
# membership shuffles).
_NON_SENSOR_DOMAINS = frozenset({
    "automation",
    "script",
    "scene",
    "group",
    "input_boolean",
    "input_number",
    "input_select",
    "input_text",
    "input_datetime",
    "zone",
    "persistent_notification",
    "sun",
    "person",  # derived from device_tracker — counted only via device_tracker
})


def capture_environmental_fingerprint(
    hass: HomeAssistant,
) -> EnvironmentalFingerprint:
    """Snapshot the parts of HA state that AdaptiveFeedback cares about.

    Defensive: catches registry/states errors and returns an empty
    fingerprint rather than failing the verdict-record path. A bad
    fingerprint is recoverable (next verdict captures fresh state);
    a failed verdict-record loses the timeline entry forever.
    """
    automation_ids: set[str] = set()
    sensors_per_area: dict[str, dict[str, int]] = {}
    active_integrations: set[str] = set()

    e_reg = _try_entity_registry(hass)

    # Automations: enabled-state from the state machine; entity_id
    # only. Disabled automations don't count because they're not
    # currently providing the behaviour the user would have
    # dismissed our suggestion in favour of.
    try:
        for entity_id in hass.states.async_entity_ids("automation"):
            state = hass.states.get(entity_id)
            if state is None or state.state != "on":
                continue
            automation_ids.add(entity_id)
    except Exception:
        pass

    # Per-area device_class counts. Walk the entity registry so we
    # only count user-owned entities (registry-disabled / -hidden
    # don't count — same rule as setup_quality / hardware_suggestion).
    if e_reg is not None:
        try:
            for entry in e_reg.entities.values():
                if not isinstance(entry.entity_id, str):
                    continue
                if entry.disabled_by is not None or entry.hidden_by is not None:
                    continue
                eid = entry.entity_id
                domain = eid.split(".", 1)[0]

                # Track integration (platform) for any registered entity
                # regardless of domain. Cloud cameras and zigbee
                # switches both count toward "user has the X integration".
                platform = getattr(entry, "platform", None)
                if isinstance(platform, str):
                    active_integrations.add(platform)

                if domain in _NON_SENSOR_DOMAINS:
                    continue

                # device_class can live on the entry (registry override)
                # or on the live state attributes (vendor-default).
                # Try entry first, fall back to state.
                dc = getattr(entry, "device_class", None)
                if not isinstance(dc, str):
                    state = hass.states.get(eid)
                    if state is not None:
                        attr_dc = state.attributes.get("device_class")
                        if isinstance(attr_dc, str):
                            dc = attr_dc
                if not isinstance(dc, str):
                    # No device_class — count by domain instead. Lights,
                    # switches, etc. all matter even without a class.
                    dc = domain
                dc_norm = dc.lower()

                area_id = getattr(entry, "area_id", None)
                if not isinstance(area_id, str) or not area_id:
                    continue

                sensors_per_area.setdefault(area_id, {})
                sensors_per_area[area_id][dc_norm] = (
                    sensors_per_area[area_id].get(dc_norm, 0) + 1
                )
        except Exception:
            pass

    return EnvironmentalFingerprint(
        automation_ids=frozenset(automation_ids),
        sensors_per_area=sensors_per_area,
        active_integrations=frozenset(active_integrations),
    )


def fingerprint_to_dict(
    fingerprint: EnvironmentalFingerprint,
) -> dict[str, object]:
    """Serialize an ``EnvironmentalFingerprint`` to a JSON-safe dict.

    Frozensets become sorted lists (deterministic order matters for
    the store's ``sort_keys=True`` JSON serialization downstream).
    Nested dict is passed through as-is.
    """
    return {
        "automation_ids": sorted(fingerprint.automation_ids),
        "sensors_per_area": {
            aid: dict(classes)
            for aid, classes in fingerprint.sensors_per_area.items()
        },
        "active_integrations": sorted(fingerprint.active_integrations),
    }


def dict_to_fingerprint(
    payload: dict[str, object],
) -> EnvironmentalFingerprint:
    """Inverse of ``fingerprint_to_dict``. Tolerant of missing keys
    so older verdict rows (pre-v1.14.5) deserialize as empty rather
    than raising."""
    automation_ids = payload.get("automation_ids") or []
    sensors_per_area = payload.get("sensors_per_area") or {}
    active_integrations = payload.get("active_integrations") or []
    return EnvironmentalFingerprint(
        automation_ids=frozenset(
            a for a in automation_ids if isinstance(a, str)
        ),
        sensors_per_area={
            aid: dict(classes)
            for aid, classes in sensors_per_area.items()
            if isinstance(aid, str) and isinstance(classes, dict)
        },
        active_integrations=frozenset(
            i for i in active_integrations if isinstance(i, str)
        ),
    )


def hash_user_id(user_id: str | None) -> str | None:
    """Hash an HA user_id for verdict attribution.

    We hash so the timeline doesn't store raw HA user_ids — those
    can be linked to specific people, and the verdict timeline is
    a long-lived audit log. The hash is short (12-byte blake2b)
    and stable across restarts (no per-install salt yet; v2.0 per-
    person presence may add one).

    Returns None when ``user_id`` is None (system actions like
    snoozed-by-undo-window-expiry).
    """
    if user_id is None or not isinstance(user_id, str) or not user_id:
        return None
    return hashlib.blake2b(user_id.encode("utf-8"), digest_size=12).hexdigest()


def _try_entity_registry(hass: HomeAssistant):
    try:
        from homeassistant.helpers import entity_registry as er

        return er.async_get(hass)
    except (ImportError, AttributeError, TypeError):
        return None


__all__ = [
    "capture_environmental_fingerprint",
    "dict_to_fingerprint",
    "fingerprint_to_dict",
    "hash_user_id",
]
