"""BLE (Bluetooth Low Energy) trackability detection.

The v1.10 Find-My-Device feature covers two capability axes:

  - Phase A (🔆): self-announcing devices fire `light.flash` etc.
  - Phase B (👆): passive sensors get touch-test perturbation

This lib adds a third axis for the v1.12 BLE live-find feature:

  - 📡 BLE-trackable: real-time RSSI scope ("metal detector" UX).
    User walks around with phone; HA Insights streams the live
    RSSI between phone (or a stationary BLE proxy) and the device,
    with EMA-smoothed values, trend arrows, and color buckets.

## Why BLE specifically?

BLE RSSI is the only "warmer/colder" signal that genuinely works:

  - **WiFi RSSI** is device→AP, not phone→device. Walking around
    the house doesn't change it. Useless for find-my-thing.
  - **Zigbee LQI** is device→coordinator/router, same problem.
  - **Matter/Thread** is mesh-based, same problem.
  - **BLE** is bidirectional and short-range (~10 m). When the
    user's phone (or a portable BLE scanner) is the receiver,
    the RSSI tracks the user's movement.

## What this lib does NOT do

- The actual RSSI streaming — that's the WS handler in `ws_api.py`
  using `bluetooth.async_register_callback`.
- EMA smoothing — also in the WS handler (state lives there
  across callback firings).
- Card-side UI — card v1.10.0 (planned).

## What this lib DOES

Given an `entity_id`, decide whether it's BLE-trackable AND what
its Bluetooth address is. Inputs come from already-fetched
registry data (entity + device); no HA imports at module load
time. Mirrors the structure of `lib/identify_capability.py`.

Optional `bluetooth_proxies` input lists which proxies CURRENTLY
see the device — useful for the card's "narrow to a zone" view
when the user has multiple stationary proxies.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BLECapability:
    """Whether an entity is BLE-trackable and how.

    is_trackable: True when we have a BLE address for this entity
        AND at least one BLE scanner has been seen for it. Card
        renders the 📡 button only when this is True.
    bluetooth_address: the MAC-like BLE address. ALL CAPS, colon-
        separated ("AA:BB:CC:DD:EE:FF"). None when the entity has
        no BLE identifier.
    seen_by_proxies: list of proxy identifiers that have observed
        this device recently. Empty when no proxy has seen it (the
        WS handler treats this as "phone is your only option" —
        you'll need the HA companion app's BLE scanner active to
        actually find it).
    reason: human-readable explanation of the trackability call.
        Surfaced in the card's 📡 button tooltip when supported is
        False ("This entity has no BLE address — try touch test").
    """

    is_trackable: bool
    bluetooth_address: str | None
    seen_by_proxies: list[str] = field(default_factory=list)
    reason: str = ""


# MAC-like pattern check — six hex pairs separated by colons (or
# dashes / underscores, some integrations normalize differently).
# We don't validate strictly here; just check the rough shape so we
# don't accidentally classify a Zigbee IEEE address (8 bytes,
# different format) as BLE.
def _looks_like_ble_address(value: str) -> bool:
    if not value:
        return False
    cleaned = value.replace(":", "").replace("-", "").replace("_", "")
    # 12 hex chars = 6 bytes = MAC/BLE address shape.
    if len(cleaned) != 12:
        return False
    return all(c in "0123456789abcdefABCDEF" for c in cleaned)


def _normalize_ble_address(value: str) -> str:
    """Render as `AA:BB:CC:DD:EE:FF` regardless of input separator.

    Bluetooth integrations vary on case + separator; HA's own
    `bluetooth` module canonicalizes to uppercase colon-separated,
    so we match that. Returns the input unchanged when it doesn't
    look like a BLE address (caller already checked, but
    defensive)."""
    cleaned = value.replace(":", "").replace("-", "").replace("_", "")
    if len(cleaned) != 12:
        return value
    return ":".join(
        cleaned[i : i + 2].upper() for i in range(0, 12, 2)
    )


def ble_capability_for(
    entity_id: str,
    *,
    device_connections: list[tuple[str, str]] | None = None,
    state_attributes: dict | None = None,
    seen_by_proxies: list[str] | None = None,
) -> BLECapability:
    """Decide BLE-trackability for one entity.

    Args:
      entity_id: HA entity_id (used only for the `reason` text).
      device_connections: list of (type, value) tuples from the
        device registry. We look for `("bluetooth", "AA:BB:...")`.
        Falls back to state attributes when None / empty.
      state_attributes: `state.attributes` dict. We look for keys
        named `bluetooth_address`, `mac`, or `address`. Backup
        path for integrations that don't populate device
        connections (Govee BLE used to, BTHome historically).
      seen_by_proxies: optional list of proxy entity_ids / names
        that have observed this address recently. When non-empty,
        the WS handler can render the multi-proxy triangulation
        view. Caller (`ws_api.py`) gets this from
        `bluetooth.async_scanner_devices_by_address`.

    Returns:
      BLECapability describing the trackability call.
    """
    # Primary signal: device-registry connections.
    address: str | None = None
    for ct, cv in device_connections or []:
        if ct == "bluetooth" and _looks_like_ble_address(cv):
            address = _normalize_ble_address(cv)
            break

    # Backup signal: state attributes. Only consult when the
    # connection lookup failed — connections are authoritative.
    if address is None and state_attributes:
        for key in ("bluetooth_address", "mac", "address"):
            v = state_attributes.get(key)
            if isinstance(v, str) and _looks_like_ble_address(v):
                address = _normalize_ble_address(v)
                break

    if address is None:
        return BLECapability(
            is_trackable=False,
            bluetooth_address=None,
            reason=(
                f"{entity_id} has no BLE address visible in the "
                "device registry or state attributes — not BLE-"
                "trackable. Try the 👆 touch-test for passive "
                "sensors, or 🔆 identify for active devices."
            ),
        )

    proxies = list(seen_by_proxies or [])
    if not proxies:
        return BLECapability(
            is_trackable=True,
            bluetooth_address=address,
            seen_by_proxies=[],
            reason=(
                f"BLE address {address} found, but no BLE proxy is "
                "currently observing it. The HA companion app's BLE "
                "scanner (Settings → Companion App → Bluetooth) is "
                "required for live tracking from your phone."
            ),
        )

    return BLECapability(
        is_trackable=True,
        bluetooth_address=address,
        seen_by_proxies=proxies,
        reason=(
            f"BLE address {address} currently visible to "
            f"{len(proxies)} "
            f"{'proxy' if len(proxies) == 1 else 'proxies'}: "
            f"{', '.join(proxies[:3])}"
            f"{'…' if len(proxies) > 3 else ''}."
        ),
    )


__all__ = [
    "BLECapability",
    "ble_capability_for",
]
