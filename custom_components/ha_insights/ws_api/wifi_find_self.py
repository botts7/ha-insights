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


# v1.21.3 — only count signal/AP attributes from sister entities sourced
# by integrations that report CONTROLLER-SIDE RSSI (i.e., the AP/router
# measures the client's signal as the client moves). Self-reported
# wifi_signal sensors from ESPHome / Shelly / Tasmota / MQTT-IoT-side
# integrations are AP-as-seen-by-stationary-device — useless for walking
# find. Mobile-app self-reports are kept because the device IS mobile,
# so its self-reported signal does change as the user moves.
#
# Real-install validation 2026-05-20 (user with 326 device-trackers):
# without this whitelist, the "Main Room Light 4" ESPHome smart light
# leaked through as the only Wi-Fi-findable candidate because its
# wifi_signal sensor sat on the same device as a router presence
# tracker. Wrong answer — the light is stationary, walking around won't
# change its self-reported RSSI by a single dB.
_CONTROLLER_SIDE_PLATFORMS: frozenset[str] = frozenset({
    "unifi",            # UniFi Network integration
    "asuswrt",          # Asuswrt + Asuswrt-Merlin
    "tplink_omada",     # TP-Link Omada (official HA core integration)
    # v1.21.5 — HACS community Omada integrations. Real-install
    # validation 2026-05-20: user had RSSI sensors working from a
    # HACS Omada package but v1.21.3's whitelist (tplink_omada only)
    # rejected them as if they were stationary IoT self-reports.
    # Defensively include every plausible platform name; all are
    # controller integrations and safe to allow.
    "omada",            # zachcheatham/ha-omada
    "ha_omada",         # alternative naming
    "omada_open_api",   # bullitt186/ha-omada-open-api
    "omada_controller", # community fork variant
    "tplink_omada_open_api",  # belt-and-suspenders
    "mikrotik",         # RouterOS
    "ubus",             # OpenWRT
    "ddwrt",            # DD-WRT routers
    "fritz",            # AVM Fritz!Box
    "keenetic_ndms2",   # Keenetic routers
    "luci",             # OpenWRT LuCI
    "huawei_lte",       # Huawei LTE routers
    "mobile_app",       # HA Companion — self-reported but device IS mobile
})


def _collect_device_state_attrs(
    hass: HomeAssistant, entity_id: str
) -> tuple[dict[str, Any], list[str]]:
    """Gather state attributes from `entity_id` AND every sister entity
    on the same device, merged into one dict.

    Background (v1.21.2): the HA UniFi integration creates one device
    per client, but splits the data across multiple entities:
      - device_tracker.<client>     → connected / not_home state, no
        signal info on recent integration versions
      - sensor.<client>_rx_signal    → RSSI in dBm
      - sensor.<client>_access_point → AP friendly name
    Same for Asuswrt + Omada in various forms. v1.21.0/v1.21.1
    checked only the picked entity's own attributes, so every
    user reported "no devices found". Looking across sister entities
    on the same device closes the gap without forcing users to pick
    the right one of three siblings.

    Returns the merged-attribute dict + the list of entity_ids
    consulted (caller uses the list to subscribe to all of them so
    state changes on the sister sensor still drive updates).

    Picked-entity attributes take precedence over sister attributes
    on key collisions, mirroring the v1.18 capability lib's existing
    "first match wins" semantics.
    """
    try:
        from homeassistant.helpers import entity_registry as er
    except ImportError:
        # Standalone unit tests may run without HA registry helpers.
        state = hass.states.get(entity_id)
        return (dict(state.attributes) if state else {}, [entity_id])

    e_reg = er.async_get(hass)
    state = hass.states.get(entity_id)
    merged: dict[str, Any] = dict(state.attributes) if state else {}
    consulted: list[str] = [entity_id]

    primary = e_reg.async_get(entity_id)
    if primary is None or primary.device_id is None:
        return (merged, consulted)

    # v1.21.3: only proceed if the picked entity itself comes from a
    # controller-side integration (or mobile_app). Skips the "ESPHome
    # device tracked by router presence" false positive that fooled
    # v1.21.2 — the router tracker's `platform` is something like
    # `asuswrt`, but if a stationary ESPHome device just happens to be
    # registered by it AND has a self-reported wifi_signal sister, we
    # don't want to flag the ESP light as Wi-Fi-findable.
    #
    # Rule: the picked entity's platform must be in the whitelist.
    # That excludes ESPHome/Shelly/Tasmota tracked-by-router cases
    # where the device's primary identity is the IoT integration even
    # though presence happens to be tracked by the router.
    primary_platform = (primary.platform or "").lower()
    if primary_platform and primary_platform not in _CONTROLLER_SIDE_PLATFORMS:
        # Picked entity is from a non-controller integration. The merge
        # would just pick up its self-reported wifi_signal sister.
        # Reject before even walking the device's entities.
        return (merged, consulted)

    # Walk sister entities on the same device. Skip the picked entity
    # itself (already merged); skip disabled / hidden entries (HA
    # already hides them from the UI); skip sisters from non-controller
    # integrations (an ESPHome wifi_signal sister on a UniFi-tracked
    # device should not be merged).
    for sister in e_reg.entities.values():
        if sister.device_id != primary.device_id:
            continue
        if sister.entity_id == entity_id:
            continue
        if sister.disabled_by or sister.hidden_by:
            continue
        sister_platform = (sister.platform or "").lower()
        if (
            sister_platform
            and sister_platform not in _CONTROLLER_SIDE_PLATFORMS
        ):
            continue
        sister_state = hass.states.get(sister.entity_id)
        if sister_state is None:
            continue
        # v1.21.2: many UniFi sister sensors put the value in
        # `state.state` (not state.attributes). The capability lib
        # only reads attributes, so promote the state-string into a
        # synthetic attribute keyed by either device_class or the
        # entity's last name-segment. Both heuristics catch the
        # common cases:
        #
        #   sensor.alice_phone_rx_signal — state="-53", device_class="signal_strength"
        #     → synthetic attr signal_strength=-53
        #   sensor.alice_phone_access_point — state="UniFi AP Kitchen"
        #     → synthetic attr access_point="UniFi AP Kitchen"
        raw_state = sister_state.state
        dc = sister_state.attributes.get("device_class")
        if (
            isinstance(dc, str)
            and dc.lower() == "signal_strength"
            and raw_state not in (None, "", "unknown", "unavailable")
        ):
            try:
                merged.setdefault("signal_strength", int(float(raw_state)))
            except (TypeError, ValueError):
                pass
        # Promote state to a key matching the entity's name-segment when
        # the segment looks like a known capability attribute.
        last_segment = sister.entity_id.split(".", 1)[-1].rsplit("_", 1)[-1]
        if last_segment in {
            "signal", "rssi", "rx_signal", "tx_signal",
            "access_point", "ap", "bssid",
        } and raw_state not in (None, "", "unknown", "unavailable"):
            # Map a few aliases to the canonical capability-lib keys.
            alias = {
                "rx_signal": "rx_rssi",
                "tx_signal": "signal_strength",
                "ap": "access_point",
            }.get(last_segment, last_segment)
            if alias in ("rx_rssi", "signal_strength", "rssi", "signal"):
                try:
                    merged.setdefault(alias, int(float(raw_state)))
                except (TypeError, ValueError):
                    pass
            else:
                merged.setdefault(alias, raw_state)
        # Finally, lift sister attributes that we recognise as Wi-Fi
        # related. Don't blindly merge everything — that would risk
        # name collisions (two sisters with `state` or `friendly_name`
        # both populated etc.).
        for key, value in sister_state.attributes.items():
            if key in {
                "rx_rssi", "signal_strength", "rssi", "signal",
                "signal_dbm", "wifi_signal",
                "ap_mac", "bssid", "access_point", "ap_name",
                "host", "connected_to",
            }:
                merged.setdefault(key, value)
        consulted.append(sister.entity_id)
    return (merged, consulted)


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
    # v1.21.2: merge sister-entity attributes so the cap check uses
    # signal + AP info that may live on different entities of the
    # same device (UniFi's standard layout).
    merged_attrs, consulted_entities = _collect_device_state_attrs(
        hass, entity_id
    )
    cap = wifi_find_capability_for(
        entity_id, state_attributes=merged_attrs
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
        # v1.21.2: re-collect merged attrs from device's siblings on
        # each state change. Cheap (~ms for typical 2-4 sisters per
        # device); essential so we pick up the AP friendly name from
        # a sensor that ticks at a different cadence than the tracker.
        sample_attrs, _ = _collect_device_state_attrs(hass, entity_id)
        sample_cap = wifi_find_capability_for(
            entity_id, state_attributes=sample_attrs
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
        # v1.21.2: subscribe to state changes on every consulted entity
        # (the picked tracker plus its sisters), so a UniFi signal-
        # sensor tick re-evaluates the capability + forwards an event,
        # not just state changes on the tracker itself.
        cancel = async_track_state_change_event(
            hass, list({entity_id, *consulted_entities}), _on_state_change
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
                "consulted_entities": [eid],
            }
            continue
        # v1.21.2: gather attributes from the entity AND every sister
        # entity on the same device. UniFi etc. split signal + AP into
        # separate sensors; checking just the picked entity rejected
        # essentially every real install.
        merged_attrs, consulted = _collect_device_state_attrs(hass, eid)
        cap = wifi_find_capability_for(eid, state_attributes=merged_attrs)
        # v1.21.3: also surface the picked entity's integration platform
        # so the PWA can decide whether to even show the Wi-Fi mode button.
        try:
            from homeassistant.helpers import entity_registry as er
        except ImportError:
            picked_platform = None
        else:
            e_reg = er.async_get(hass)
            picked = e_reg.async_get(eid)
            picked_platform = picked.platform if picked else None
        capabilities[eid] = {
            "is_trackable": cap.is_trackable,
            "signal_attribute": cap.signal_attribute,
            "signal_dbm": cap.signal_dbm,
            "ap_attribute": cap.ap_attribute,
            "ap_identifier": cap.ap_identifier,
            "reason": cap.reason,
            "consulted_entities": consulted,
            "platform": picked_platform,
        }
    connection.send_result(msg["id"], {"capabilities": capabilities})


__all__ = [
    "ws_wifi_find_capability",
    "ws_wifi_find_self",
]
