"""WS handlers for v1.21 Wi-Fi inverse-multilateration find.

v1.21.1 added ``ws_wifi_find_capability`` — a batch trackability
query mirroring ``ws_ble_capability``. The PWA calls it on entering
Wi-Fi mode to pre-filter the entity picker to only entities that
actually expose Wi-Fi RSSI + an AP identifier, so users don't pick
a useless mobile_app GPS tracker and only discover the mistake after
hitting Start.

Walking warmer/colder for Wi-Fi-trackable devices, without needing
phone→device direct RSSI (which browsers can't read anyway).

## The flip

`lib/ble_capability.py` correctly notes that Wi-Fi RSSI is
device→AP, not phone→device. We can't make the phone scan for the
target's Wi-Fi signal directly. So we flip the problem:

  - The phone (user-carried) moves through the house.
  - Stationary APs (UniFi / Asuswrt / Omada) see the PHONE'S
    signal change as the user walks.
  - v1.18 WifiFindDetector inferred which AP the target device
    lives near (its area_id).
  - As the phone's RSSI to THAT AP strengthens, the user is
    walking toward the target.

We don't subscribe to the target device's RSSI (won't change as
the user moves). We subscribe to the PHONE'S state changes
(the user's device-tracker entity) and forward the AP-RSSI value
as the warmer/colder signal.

## Cadence trade-off

UniFi controllers poll per-client signal every ~30 s by default
(can be lowered to ~10 s on UDM); Asuswrt updates on state-changed
events from the router. That's slower than BLE's ~1 Hz
advertisement rate. EMA smoothed, the UX is "walk slowly, the
arrow updates every 10-30 s." Slower than ideal, but works
today on stock setups — and unlocks Wi-Fi find for the (large)
class of devices BLE can't reach.

## Handler

  - ``ws_wifi_find_self`` — streaming subscription. Admin-gated
    (phone-location data). Takes the phone's entity_id and an
    optional target_ap_device_id. Subscribes to state changes
    for the phone entity; forwards {rssi, ap_id, ap_matches_target}
    as the phone roams.

Reuses ``apply_rssi_ema`` from ``ble_find.py`` so card-side
smoothing is consistent across BLE and Wi-Fi find paths.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import callback

from ..lib.wifi_find_capability import wifi_find_capability_for
from ._helpers import _require_admin
from .ble_find import apply_rssi_ema

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


def _resolve_ap_device_id(
    hass: HomeAssistant,
    ap_identifier: str,
) -> str | None:
    """Match a Wi-Fi AP identifier to a device_id in the registry.

    Tries MAC connections first (UniFi `ap_mac`, generic `bssid`),
    then falls back to substring match on device names (Asuswrt
    `host`, UniFi `ap_name`). Returns None when no device matches.
    """
    try:
        from homeassistant.helpers import device_registry as dr
    except ImportError:
        return None
    d_reg = dr.async_get(hass)
    ap_key = ap_identifier.lower()
    for dev in d_reg.devices.values():
        for conn_type, conn_value in dev.connections:
            if conn_type == "mac" and conn_value.lower() == ap_key:
                return dev.id
    # Friendly-name fallback.
    for dev in d_reg.devices.values():
        name = (dev.name_by_user or dev.name or "").lower()
        if name and ap_key and ap_key in name:
            return dev.id
    return None


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/wifi_find_self",
        vol.Required("entity_id"): str,
        vol.Optional("target_ap_device_id"): str,
    }
)
@websocket_api.async_response
async def ws_wifi_find_self(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Stream the phone's per-AP RSSI for inverse-multilateration find.

    The phone (user-carried) emits state changes as it roams across
    APs. Each change carries new attributes including the
    currently-associated AP and the RSSI the controller reads. We
    forward those values to the card as warmer/colder updates.

    Args:
      entity_id: the user's phone device-tracker entity_id (the
        scanner). Must be Wi-Fi-trackable per
        ``lib/wifi_find_capability``.
      target_ap_device_id: optional device_id of the AP where the
        target device lives (from v1.18 WifiFindDetector inference).
        When provided, events include ``ap_matches_target: True/False``
        so the card can render "you're walking toward / away from"
        copy. When omitted, the card gets raw RSSI + AP labels and
        renders a generic "currently near AP X" view.

    Event payload per state change:
      {
        "rssi_raw": -53,
        "rssi_smoothed": -54.2,
        "ap_device_id": "ap_kitchen",
        "ap_name": "UniFi AP Kitchen",
        "ap_identifier": "aa:bb:cc:dd:ee:01",
        "signal_attribute": "rx_rssi",
        "ap_matches_target": true,
        "timestamp": "2026-05-19T13:42:18Z",
      }

    Admin-gated — phone-location data is sensitive.
    """
    if not _require_admin(hass, connection, msg):
        return

    entity_id = msg["entity_id"]
    target_ap_device_id = msg.get("target_ap_device_id")

    if "." not in entity_id:
        connection.send_error(
            msg["id"],
            "bad_entity_id",
            "entity_id must be a fully-qualified HA entity_id "
            "(e.g. device_tracker.alice_phone).",
        )
        return

    # Sanity-check: the entity exists right now AND looks Wi-Fi-
    # trackable. We don't fail outright if it doesn't — the user's
    # phone might be momentarily disconnected — but we warn so the
    # PWA can show "phone shows as disconnected; reconnect to start
    # streaming" instead of just no events.
    state = hass.states.get(entity_id)
    if state is None:
        connection.send_error(
            msg["id"],
            "entity_not_found",
            f"{entity_id} is not in the state machine. Check that the "
            "Wi-Fi integration is loaded and the phone is online.",
        )
        return
    cap = wifi_find_capability_for(
        entity_id, state_attributes=dict(state.attributes)
    )

    # Per-subscription EMA state. Reused across every advertisement
    # received on this WS subscription; cleared when the WS unsubs.
    ema_state: dict[str, float | None] = {"value": None}

    try:
        from homeassistant.helpers.event import (
            async_track_state_change_event,
        )
    except ImportError:
        connection.send_error(
            msg["id"],
            "no_state_tracking",
            "Home Assistant's state-tracking helper is unavailable.",
        )
        return

    @callback
    def _on_state_change(event: Any) -> None:
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        sample_cap = wifi_find_capability_for(
            entity_id, state_attributes=dict(new_state.attributes)
        )
        if not sample_cap.is_trackable or sample_cap.signal_dbm is None:
            return
        raw_rssi = float(sample_cap.signal_dbm)
        smoothed = apply_rssi_ema(ema_state["value"], raw_rssi)
        ema_state["value"] = smoothed

        ap_device_id = None
        if sample_cap.ap_identifier:
            ap_device_id = _resolve_ap_device_id(
                hass, sample_cap.ap_identifier
            )
        ap_matches_target = (
            target_ap_device_id is not None
            and ap_device_id == target_ap_device_id
        )
        # AP name lookup — best-effort, falls back to the raw
        # identifier so the PWA always has something to render.
        ap_name: str | None = None
        if ap_device_id is not None:
            try:
                from homeassistant.helpers import device_registry as dr
            except ImportError:
                ap_name = sample_cap.ap_identifier
            else:
                d_reg = dr.async_get(hass)
                dev = d_reg.async_get(ap_device_id)
                if dev is not None:
                    ap_name = dev.name_by_user or dev.name
        if ap_name is None:
            ap_name = sample_cap.ap_identifier

        connection.send_event(
            msg["id"],
            {
                "rssi_raw": int(raw_rssi),
                "rssi_smoothed": round(smoothed, 1),
                "ap_device_id": ap_device_id,
                "ap_name": ap_name,
                "ap_identifier": sample_cap.ap_identifier,
                "signal_attribute": sample_cap.signal_attribute,
                "ap_matches_target": ap_matches_target,
                "timestamp": new_state.last_updated.isoformat(),
            },
        )

    try:
        cancel = async_track_state_change_event(
            hass, [entity_id], _on_state_change
        )
    except Exception as err:
        connection.send_error(
            msg["id"],
            "subscribe_failed",
            f"Could not subscribe to state changes: {err}",
        )
        return

    connection.subscriptions[msg["id"]] = cancel
    # Initial confirmation with the entity's CURRENT readings so the
    # PWA has data immediately without waiting for the first state
    # change (which on UniFi can be 30 s away).
    initial: dict[str, Any] = {
        "subscribed": True,
        "entity_id": entity_id,
        "is_trackable": cap.is_trackable,
        "reason": cap.reason,
        "target_ap_device_id": target_ap_device_id,
    }
    if cap.is_trackable and cap.signal_dbm is not None:
        ema_state["value"] = float(cap.signal_dbm)
        initial_ap_device_id = (
            _resolve_ap_device_id(hass, cap.ap_identifier or "")
            if cap.ap_identifier
            else None
        )
        initial.update(
            {
                "rssi_raw": cap.signal_dbm,
                "rssi_smoothed": float(cap.signal_dbm),
                "ap_device_id": initial_ap_device_id,
                "ap_identifier": cap.ap_identifier,
                "ap_matches_target": (
                    target_ap_device_id is not None
                    and initial_ap_device_id == target_ap_device_id
                ),
            }
        )
    connection.send_result(msg["id"], initial)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/wifi_find_capability",
        vol.Required("entity_ids"): [str],
    }
)
@websocket_api.async_response
async def ws_wifi_find_capability(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Batch Wi-Fi-trackability query for the PWA's mode-aware entity
    filter.

    Mirrors ``ws_ble_capability``. Read-only, not admin-gated — same
    data the entity registry already exposes (we just enrich with the
    Wi-Fi-attribute check).

    Response per entity:
      {
        "is_trackable": true,
        "signal_attribute": "rx_rssi",
        "signal_dbm": -53,
        "ap_attribute": "ap_mac",
        "ap_identifier": "aa:bb:cc:dd:ee:01",
        "reason": "...",
      }

    Non-existent / unrecognised entities still get a row with
    ``is_trackable: false`` so the PWA can show "N of M trackable" for
    the full input set without losing the count.
    """
    capabilities: dict[str, dict[str, Any]] = {}
    for eid in msg["entity_ids"]:
        if not isinstance(eid, str):
            continue
        state = hass.states.get(eid)
        if state is None:
            capabilities[eid] = {
                "is_trackable": False,
                "signal_attribute": None,
                "signal_dbm": None,
                "ap_attribute": None,
                "ap_identifier": None,
                "reason": (
                    f"{eid} is not in the state machine. Integration "
                    "may not be loaded, or the entity is disabled."
                ),
            }
            continue
        cap = wifi_find_capability_for(
            eid, state_attributes=dict(state.attributes)
        )
        capabilities[eid] = {
            "is_trackable": cap.is_trackable,
            "signal_attribute": cap.signal_attribute,
            "signal_dbm": cap.signal_dbm,
            "ap_attribute": cap.ap_attribute,
            "ap_identifier": cap.ap_identifier,
            "reason": cap.reason,
        }
    connection.send_result(msg["id"], {"capabilities": capabilities})


__all__ = [
    "ws_wifi_find_capability",
    "ws_wifi_find_self",
]
