"""WS handlers for the v1.12 BLE live-find feature.

Two handlers + two helpers, all related to locating a Bluetooth
device by streaming RSSI advertisements from HA's BLE proxy network:

  - ``ws_ble_capability`` — batch BLE-trackability lookup. Returns,
    per entity: ``is_trackable`` flag, the device's Bluetooth address,
    the list of currently-observing proxies, and a human-readable
    reason. Read-only, not admin-gated (no sensitive info beyond what
    the existing `entity_registry` exposes).
  - ``ws_ble_live_find`` — streaming RSSI subscription. Opens a
    server-side BLE advertisement callback for the given address,
    EMA-smooths the raw RSSI, forwards live updates to the card for
    the "warmer/colder" UI. **Admin-gated** because streaming
    subscriptions tie up server resources and the address parameter
    could leak fingerprint info about devices the user doesn't own.

Helpers:
  - ``_ble_proxy_label(service_info)`` — render a BLE service_info
    into a short proxy label for the UI.
  - ``_seen_proxies_for(hass, address)`` — labels of every BLE scanner
    currently seeing this address.

Extracted from ``ws_api/__init__.py`` in v1.13.5 (step 3 of the v1.13
refactor) per the dependency-map memory finding that BLE / IDENTIFY /
MANAGED_DEVICES are the most-isolated handler groups (no cross-handler
coupling beyond the universal helpers in ``_helpers.py``). Imported
back into ``__init__`` for backwards-compat — handler names + the
``async_register`` registrations stay valid.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import callback

from ._helpers import _require_admin

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


# v1.12 — BLE live-find ------------------------------------------------


def _ble_proxy_label(service_info: Any) -> str:
    """Render a BLE service_info into a short proxy label for the UI."""
    src = getattr(service_info, "source", None)
    if isinstance(src, str) and src:
        return src
    return "unknown"


def _seen_proxies_for(hass: HomeAssistant, address: str) -> list[str]:
    """Return labels of every BLE scanner currently seeing this
    address. Empty list when bluetooth integration isn't loaded or
    nothing's observing the device."""
    try:
        from homeassistant.components.bluetooth import (
            async_scanner_devices_by_address,
        )
    except ImportError:
        return []
    try:
        devices = async_scanner_devices_by_address(
            hass, address, connectable=False
        )
    except Exception:
        return []
    labels = [_ble_proxy_label(d) for d in devices]
    # Dedup while preserving order.
    seen = set()
    out: list[str] = []
    for label in labels:
        if label not in seen:
            out.append(label)
            seen.add(label)
    return out


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/ble_capability",
        vol.Required("entity_ids"): [str],
    }
)
@websocket_api.async_response
async def ws_ble_capability(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Batch BLE-capability query for the card.

    Mirrors `identify_capability` — read-only, not admin-gated.
    Card calls this once per dialog open to know which entities can
    show the 📡 BLE live-find button.

    Response per entity:
      {
        "is_trackable": true,
        "bluetooth_address": "AA:BB:CC:DD:EE:FF",
        "seen_by_proxies": ["esphome_kitchen_proxy", ...],
        "reason": "...",
      }
    """
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    from ..lib.ble_capability import ble_capability_for

    e_reg = er.async_get(hass)
    d_reg = dr.async_get(hass)

    capabilities: dict[str, dict[str, Any]] = {}
    for eid in msg["entity_ids"]:
        if not isinstance(eid, str):
            continue
        # Pull device connections from the registry.
        connections: list[tuple[str, str]] = []
        attrs: dict[str, Any] = {}
        er_ent = e_reg.async_get(eid)
        if er_ent is not None and er_ent.device_id is not None:
            dev = d_reg.async_get(er_ent.device_id)
            if dev is not None:
                connections = [
                    (t, v) for t, v in (dev.connections or set())
                ]
        state = hass.states.get(eid)
        if state is not None:
            attrs = dict(state.attributes)

        # First pass: get the address (proxies require an address).
        partial = ble_capability_for(
            eid,
            device_connections=connections,
            state_attributes=attrs,
            seen_by_proxies=None,
        )
        seen: list[str] = []
        if partial.bluetooth_address is not None:
            seen = _seen_proxies_for(hass, partial.bluetooth_address)
        # Re-evaluate with proxies so the `reason` reflects them.
        cap = ble_capability_for(
            eid,
            device_connections=connections,
            state_attributes=attrs,
            seen_by_proxies=seen,
        )
        capabilities[eid] = {
            "is_trackable": cap.is_trackable,
            "bluetooth_address": cap.bluetooth_address,
            "seen_by_proxies": list(cap.seen_by_proxies),
            "reason": cap.reason,
        }
    connection.send_result(msg["id"], {"capabilities": capabilities})


# EMA smoothing for live RSSI. alpha=0.3 gives an effective ~3s
# window at the typical 1Hz BLE advertisement rate — fast enough to
# track user movement, slow enough to kill multipath jitter.
_BLE_EMA_ALPHA: float = 0.3


def apply_rssi_ema(
    prev: float | None,
    raw: float,
    *,
    alpha: float = _BLE_EMA_ALPHA,
) -> float:
    """Single-step EMA for live RSSI samples.

    Shared between ``ws_ble_live_find`` (stationary BLE proxies) and
    ``companion_scan`` (PWA-streamed samples) so the card UI sees the
    same smoothing regardless of which scanner produced the sample.
    First sample (``prev is None``) is its own seed — avoids a long
    convergence from an arbitrary fixed seed.
    """
    if prev is None:
        return raw
    return alpha * raw + (1.0 - alpha) * prev


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/ble_live_find",
        vol.Required("bluetooth_address"): str,
    }
)
@websocket_api.async_response
async def ws_ble_live_find(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Streaming RSSI subscription for the BLE live-find UI.

    Opens a server-side BLE advertisement callback for the given
    address. Each advertisement received forwards an event message
    to the WS client with raw + EMA-smoothed RSSI + which proxy
    saw it. Auto-unsubscribes when the WS connection closes or the
    client sends `unsubscribe_events`.

    Admin-gated — streaming subscriptions tie up server resources
    and the address parameter could leak fingerprint info about
    devices the user doesn't own.
    """
    if not _require_admin(hass, connection, msg):
        return

    try:
        from homeassistant.components.bluetooth import (
            BluetoothCallbackMatcher,
            BluetoothChange,
            async_register_callback,
        )
    except ImportError:
        connection.send_error(
            msg["id"],
            "no_bluetooth",
            "Home Assistant's bluetooth integration is not available "
            "in this install. Install and configure it (Settings → "
            "Devices & Services → Add Integration → Bluetooth) to "
            "enable BLE live-find.",
        )
        return

    raw_address = msg["bluetooth_address"]
    if not isinstance(raw_address, str) or len(raw_address) < 12:
        connection.send_error(
            msg["id"], "bad_address", "bluetooth_address looks invalid."
        )
        return
    address = raw_address.upper().replace("-", ":").replace("_", ":")

    # Per-subscription state (kept in this closure; cleaned up via
    # the cancel callback HA assigns when the WS unsubscribes).
    ema_state: dict[str, float | None] = {"value": None}

    @callback
    def _on_advertisement(
        service_info: Any,
        change: Any,
    ) -> None:
        # `change` is the BluetoothChange enum value; we don't act on
        # it here (we accept ADVERTISEMENT only via the registration
        # filter), but the callback signature requires it.
        del change
        if not hasattr(service_info, "address"):
            return
        if service_info.address.upper() != address:
            return
        try:
            raw_rssi = float(service_info.rssi)
        except (TypeError, AttributeError, ValueError):
            return
        ema = apply_rssi_ema(ema_state["value"], raw_rssi)
        ema_state["value"] = ema
        connection.send_event(
            msg["id"],
            {
                "rssi_raw": int(raw_rssi),
                "rssi_smoothed": round(ema, 1),
                "scanner": _ble_proxy_label(service_info),
            },
        )

    try:
        cancel = async_register_callback(
            hass,
            _on_advertisement,
            BluetoothCallbackMatcher(address=address),
            BluetoothChange.ADVERTISEMENT,
        )
    except Exception as err:
        connection.send_error(
            msg["id"],
            "subscribe_failed",
            f"Could not subscribe to BLE advertisements: {err}",
        )
        return

    # Confirm the subscription is live; HA's WS framework calls our
    # `cancel` when the client unsubscribes or the connection drops.
    connection.subscriptions[msg["id"]] = cancel
    connection.send_result(msg["id"])


__all__ = [
    "apply_rssi_ema",
    "ws_ble_capability",
    "ws_ble_live_find",
]
