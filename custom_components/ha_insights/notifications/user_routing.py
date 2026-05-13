"""Per-user routing helpers for multi-user HA.

Three lookups detectors and the notifier need across this codebase:

  1. `get_user_id_for_entity(hass, entity_id)` — which HA user owns
     this entity? Most useful for `*.mobile_app_*` and the entities a
     mobile_app device registers (battery, charging, geolocation).

  2. `get_mobile_app_services_for_user(hass, user_id)` — which
     `notify.mobile_app_*` services are registered to this user?
     A single user can have multiple phones; we send to all.

  3. `resolve_notify_targets(hass, fallback_targets, target_user_id)`
     — used by the notifier. If `target_user_id` is set, returns only
     that user's mobile_app services (intersected with the user's
     configured allowlist when one is present). If None, falls back
     to the configured global list. Single chokepoint, so detectors
     don't reinvent it.

Underlying source of truth: HA's `mobile_app` config entries. Each
entry's `data` contains `user_id` (the HA user who registered the
phone) and `device_name` (slug used to derive the `notify.mobile_app_*`
service name).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

_MOBILE_APP_DOMAIN = "mobile_app"


def _mobile_app_entries(hass: HomeAssistant) -> list["ConfigEntry"]:
    try:
        return list(hass.config_entries.async_entries(_MOBILE_APP_DOMAIN))
    except Exception:  # noqa: BLE001
        return []


def _service_from_entry(entry: "ConfigEntry") -> str | None:
    """`notify.mobile_app_<slug>` for a mobile_app config entry.

    the previous hand-rolled slug only handled
    spaces/hyphens/apostrophes. The mobile_app integration uses
    HA's canonical `slugify()` which also strips emoji, normalises
    Unicode (NFKD), drops anything that isn't [a-z0-9_], and
    handles many more punctuation cases. A "User's iPhone 📱" device
    became "notify.mobile_app_user_s_iphone" via our path but
    `notify.mobile_app_users_iphone` via mobile_app's — push
    silently failed.

    Use HA's slugify() directly. It's a public helper, stable
    across versions, and is what mobile_app itself calls.
    """
    raw = entry.data.get("device_name")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        from homeassistant.util import slugify
    except Exception:  # noqa: BLE001 — defensive; should always be importable
        # Fallback to hand-rolled — better than nothing.
        slug = raw.lower().replace(" ", "_").replace("-", "_").replace("'", "")
    else:
        slug = slugify(raw)
    if not slug:
        return None
    return f"notify.mobile_app_{slug}"


def get_user_id_for_entity(
    hass: HomeAssistant,
    entity_id: str,
    *,
    manual_links: dict[str, str] | None = None,
) -> tuple[str | None, float | None]:
    """Best-effort: (HA user_id, attribution_confidence) for an entity.

    Three-tier resolution, in priority order:

      1. **mobile_app registry (confidence 1.0)** — the entity belongs
         to a `mobile_app` device whose config entry stores the user_id
         of the HA login that registered it. This is the strongest
         attribution available; the OS-level registration tells us
         exactly whose phone it is.

      2. **person.* via device_tracker (confidence 0.85)** — the
         entity is or is tied to a device_tracker that's listed as a
         tracking source on a `person.*` entity, and that person has a
         linked `user_id` attribute. Slightly less certain than (1)
         because users can share devices, but still a strong signal.

      3. **manual links (confidence 0.7)** — the user explicitly
         supplied an `entity_id → user_id` mapping in OptionsFlow.
         Treated as authoritative when present but conservatively
         confidence-flagged so the panel can show "you linked this
         manually" rather than implying registry-grade certainty.

    Returns (None, None) when no tier resolves.
    """
    # Tier 1: mobile_app config entry user_id
    try:
        reg = er.async_get(hass)
        ent = reg.async_get(entity_id)
        if ent is not None and ent.device_id is not None:
            d_reg = dr.async_get(hass)
            device = d_reg.async_get(ent.device_id)
            if device is not None:
                for entry_id in device.config_entries:
                    entry = hass.config_entries.async_get_entry(entry_id)
                    if entry is None or entry.domain != _MOBILE_APP_DOMAIN:
                        continue
                    uid = entry.data.get("user_id")
                    if isinstance(uid, str) and uid:
                        return uid, 1.0
    except Exception:  # noqa: BLE001
        _LOGGER.debug(
            "mobile_app resolution failed for %s", entity_id, exc_info=True
        )

    # Tier 2: person.* device tracker linkage
    try:
        # Walk every person.* entity in the state machine. Each one
        # has attributes.source = device_tracker.* and may have
        # attributes.user_id set when the person is bound to an HA
        # login. If our entity is on the same device as that
        # tracker, attribute the user.
        person_states = [
            s for s in hass.states.async_all() if s.entity_id.startswith("person.")
        ]
        # Build (device_tracker_eid -> user_id) for every linked person
        tracker_to_user: dict[str, str] = {}
        for ps in person_states:
            uid = ps.attributes.get("user_id")
            if not isinstance(uid, str) or not uid:
                continue
            source = ps.attributes.get("source")
            if isinstance(source, str) and source.startswith("device_tracker."):
                tracker_to_user[source] = uid
            # Some person setups list multiple trackers under
            # device_trackers (plural).
            multi = ps.attributes.get("device_trackers")
            if isinstance(multi, (list, tuple)):
                for t in multi:
                    if isinstance(t, str) and t.startswith("device_tracker."):
                        tracker_to_user[t] = uid

        if tracker_to_user:
            reg = er.async_get(hass)
            ent = reg.async_get(entity_id)
            target_device_id = ent.device_id if ent is not None else None
            # Direct: entity_id itself is one of the trackers
            if entity_id in tracker_to_user:
                return tracker_to_user[entity_id], 0.85
            # Indirect: entity is on the same device as a known
            # person-linked tracker
            if target_device_id is not None:
                for tracker_eid, uid in tracker_to_user.items():
                    tent = reg.async_get(tracker_eid)
                    if tent is None:
                        continue
                    if tent.device_id == target_device_id:
                        return uid, 0.85
    except Exception:  # noqa: BLE001
        _LOGGER.debug(
            "person resolution failed for %s", entity_id, exc_info=True
        )

    # Tier 3: explicit manual mapping
    if manual_links:
        uid = manual_links.get(entity_id)
        if isinstance(uid, str) and uid:
            return uid, 0.7

    return None, None


def get_mobile_app_services_for_user(
    hass: HomeAssistant, user_id: str
) -> list[str]:
    """All `notify.mobile_app_*` services registered to this user.
    Empty list if none — caller falls back to the global config list.
    """
    if not user_id:
        return []
    services: list[str] = []
    for entry in _mobile_app_entries(hass):
        if entry.data.get("user_id") != user_id:
            continue
        svc = _service_from_entry(entry)
        if svc is not None:
            services.append(svc)
    return services


def resolve_notify_targets(
    hass: HomeAssistant,
    fallback_targets: list[str],
    *,
    target_user_id: str | None,
) -> list[str]:
    """Pick the actual notify.* services for an insight.

    Routing rules:
      - target_user_id None → use `fallback_targets` as-is (the
        household-level OptionsFlow list). Default behaviour preserves
        the v1.3 model.
      - target_user_id set + that user has registered mobile_app
        devices → use those (intersected with `fallback_targets`
        when fallback is non-empty, so user opt-out still wins).
      - target_user_id set but no mobile_app devices found → empty
        list (don't broadcast to the wrong person). Caller logs and
        falls back to the persistent_notification only.
    """
    if not target_user_id:
        return list(fallback_targets)
    user_services = get_mobile_app_services_for_user(hass, target_user_id)
    if not user_services:
        return []
    if not fallback_targets:
        return user_services
    fallback_set = set(fallback_targets)
    return [s for s in user_services if s in fallback_set]


__all__ = [
    "get_mobile_app_services_for_user",
    "get_user_id_for_entity",
    "resolve_notify_targets",
]
