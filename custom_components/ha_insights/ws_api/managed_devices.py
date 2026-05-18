"""WS handlers for the v1.7.7 per-device "managed externally" flag.

Strategy 2 from the device-internal-logic memory: when a user asserts
"this device handles its own logic" (e.g. an ESPHome thermostat that
runs its own schedule via ``on_press`` automations), insights from
that device are fully suppressed. The user opts in per-device via the
OptionsFlow management screen + the card's detail-dialog toggle.

Two handlers:

  - ``ws_list_managed_devices`` — admin-gated read. Returns each
    flagged device with its display name + entity count, plus a
    ``deleted: true`` marker for devices that were removed from HA
    after being flagged (so the user can clean the stale flag).
  - ``ws_set_device_managed`` — admin-gated write. Toggle a device
    in or out of the set. Idempotent. Persists via the config-entry
    options dict using ``CONF_MANAGED_EXTERNALLY_DEVICES``.

Helper ``_managed_devices_set`` reads the current set from a config
entry's options. Both handlers fail with ``no_entry`` if the
integration isn't set up yet.

Extracted from ``ws_api/__init__.py`` in v1.13.6 (step 4 of the v1.13
refactor) per the dependency-map memory finding that BLE / IDENTIFY /
MANAGED_DEVICES are the most-isolated handler groups (only depend on
universal ``_helpers``, no cross-handler coupling). Imported back into
``__init__`` for backwards-compat — handler names + the
``async_register`` registrations stay valid.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.components import websocket_api

from ..const import DOMAIN
from ._helpers import _require_admin

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


# ---------- v1.7.7: per-device "managed externally" flag ------------------


def _managed_devices_set(entry) -> set[str]:
    """Read the user's current managed-externally device set."""
    from ..config_flow import CONF_MANAGED_EXTERNALLY_DEVICES

    raw = entry.options.get(CONF_MANAGED_EXTERNALLY_DEVICES, [])
    if not isinstance(raw, list | tuple | set):
        return set()
    return {d for d in raw if isinstance(d, str)}


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/list_managed_devices",
    }
)
@websocket_api.async_response
async def ws_list_managed_devices(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return currently-flagged devices with name + entity count.

    Admin-only. Used by the card's per-device toggle UI and the
    OptionsFlow management screen.
    """
    if not _require_admin(hass, connection, msg):
        return
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        connection.send_error(msg["id"], "no_entry", "No HA Insights entry")
        return
    entry = entries[0]
    flagged = _managed_devices_set(entry)
    if not flagged:
        connection.send_result(msg["id"], {"devices": []})
        return
    try:
        from homeassistant.helpers import device_registry as dr
        from homeassistant.helpers import entity_registry as er

        d_reg = dr.async_get(hass)
        e_reg = er.async_get(hass)
        entity_counts: dict[str, int] = {}
        for ent in e_reg.entities.values():
            if ent.device_id:
                entity_counts[ent.device_id] = entity_counts.get(ent.device_id, 0) + 1
        out: list[dict[str, Any]] = []
        for device_id in sorted(flagged):
            device = d_reg.async_get(device_id)
            if device is None:
                # Device deleted from HA but still in our flag list —
                # surface so the user can clean it up.
                out.append({
                    "device_id": device_id,
                    "name": f"<deleted: {device_id[:8]}…>",
                    "entity_count": 0,
                    "deleted": True,
                })
                continue
            out.append({
                "device_id": device_id,
                "name": device.name_by_user or device.name or device_id[:8],
                "manufacturer": device.manufacturer,
                "model": device.model,
                "entity_count": entity_counts.get(device_id, 0),
                "deleted": False,
            })
        connection.send_result(msg["id"], {"devices": out})
    except Exception as err:
        _LOGGER.exception("list_managed_devices failed")
        connection.send_error(msg["id"], "list_failed", str(err))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/set_device_managed",
        vol.Required("device_id"): str,
        vol.Required("managed"): bool,
    }
)
@websocket_api.async_response
async def ws_set_device_managed(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Add or remove a device from the managed-externally set.

    Admin-only. Returns the updated set. Idempotent — adding an
    already-flagged device or removing an absent one is a no-op.
    """
    if not _require_admin(hass, connection, msg):
        return
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        connection.send_error(msg["id"], "no_entry", "No HA Insights entry")
        return
    entry = entries[0]
    device_id = msg["device_id"]
    managed = msg["managed"]
    flagged = _managed_devices_set(entry)
    if managed:
        flagged.add(device_id)
    else:
        flagged.discard(device_id)
    from ..config_flow import CONF_MANAGED_EXTERNALLY_DEVICES

    merged_options = dict(entry.options)
    merged_options[CONF_MANAGED_EXTERNALLY_DEVICES] = sorted(flagged)
    hass.config_entries.async_update_entry(entry, options=merged_options)
    connection.send_result(
        msg["id"],
        {"managed_devices": sorted(flagged)},
    )


__all__ = [
    "ws_list_managed_devices",
    "ws_set_device_managed",
]
