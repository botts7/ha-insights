"""Wi-Fi location-inference capability (v1.18).

Counterpart to `lib/ble_capability.py`, but with a critically
different physics premise.

## Why this lib is NOT for walking-around find

`lib/ble_capability.py` already explains: Wi-Fi RSSI is
device→AP, not phone→device. Walking around the house with your
phone doesn't change the RSSI a UniFi controller sees from your
Tile-equivalent Wi-Fi tag. So Wi-Fi can't power the "warmer/
colder" UX BLE provides.

What Wi-Fi RSSI *can* do is **passive location inference**: if a
device is consistently associated with a specific AP, and that AP
has a known area_id in the device registry, the device is probably
in that area too. That's what this lib supports, and what
`detectors/wifi_find.py` uses to emit PATTERN_OBSERVATION insights.

The "find" naming follows the v1.18-v1.20 task series for symmetry
with BLE find — but readers should think of it as "where was this
last seen" rather than "metal-detector live find."

## What this lib does

Given an entity's state attributes (and optionally device
connections), decide:

  - Is this entity Wi-Fi-trackable at all? (Has a known Wi-Fi
    signal attribute and a non-None value.)
  - Which attribute carries the signal strength? (`rx_rssi`,
    `signal_strength`, `signal`, …)
  - Which attribute identifies the associated AP/router?
    (`ap_mac`, `bssid`, `host`, …)
  - What's the current signal strength reading (dBm) and the
    current AP identifier?

No HA imports. Caller (detector + future WS handler) feeds in
state.attributes dicts and gets a frozen capability dataclass back.
"""
from __future__ import annotations

from dataclasses import dataclass

# Wi-Fi signal-strength attribute names across integrations.
# Order matters — the FIRST one present wins, so put the more
# specific names ahead of the generic ones.
#
#   - `rx_rssi`        — UniFi network integration on device-tracker.
#   - `signal_strength`— Asuswrt-Merlin, some MQTT-based exporters.
#   - `rssi`           — generic, Asuswrt, TP-Link Omada.
#   - `signal`         — Asuswrt legacy, some Cisco/Meraki bridges.
#   - `signal_dbm`     — some custom MQTT integrations.
#   - `wifi_signal`    — ESPHome Wi-Fi quality sensor.
#
# All are integers in dBm range -30 (very close) to -100 (extremely
# weak). Some integrations report as positive (linkquality 0-100);
# `_is_wifi_dbm_range` filters those out at the read site.
_WIFI_SIGNAL_ATTRS: tuple[str, ...] = (
    "rx_rssi",
    "signal_strength",
    "rssi",
    "signal",
    "signal_dbm",
    "wifi_signal",
)

# Attributes that identify which AP / router this entity is
# currently associated with.
#
#   - `ap_mac`         — UniFi (MAC address of the AP).
#   - `bssid`          — generic 802.11 (the AP's MAC).
#   - `access_point`   — some MQTT integrations.
#   - `host`           — Asuswrt routes by router host name.
#   - `connected_to`   — generic.
#   - `ap_name`        — UniFi friendly name fallback.
_WIFI_AP_ATTRS: tuple[str, ...] = (
    "ap_mac",
    "bssid",
    "access_point",
    "host",
    "connected_to",
    "ap_name",
)


@dataclass(frozen=True)
class WifiFindCapability:
    """Whether an entity has Wi-Fi location-inference data.

    Attributes:
      is_trackable: True when this entity exposes both a Wi-Fi
        signal-strength reading AND an AP identifier we can
        cross-reference to an area_id. False otherwise; the `reason`
        field explains why.
      signal_attribute: which state.attributes key carried the
        signal-strength reading we picked. None when no signal
        attribute matched.
      signal_dbm: the current signal-strength reading. dBm range
        roughly -30 (very close) to -100 (extremely weak). None
        when no reading was found.
      ap_attribute: which state.attributes key identified the AP.
        None when no AP attribute matched.
      ap_identifier: the value of the AP attribute — typically a
        MAC address or hostname. None when unset.
      reason: short human-readable explanation for the trackability
        call. Surfaced on the card.
    """

    is_trackable: bool
    signal_attribute: str | None = None
    signal_dbm: int | None = None
    ap_attribute: str | None = None
    ap_identifier: str | None = None
    reason: str = ""


def _is_wifi_dbm_range(value: object) -> bool:
    """Filter accidental matches like Zigbee `linkquality` (0-255).

    Wi-Fi RSSI in dBm is always negative and within a roughly
    -30 to -100 band. We're permissive on the boundaries but reject
    anything outside the plausible range — a `signal=200` reading
    is almost certainly a Zigbee `linkquality` or similar that
    happened to share the attribute name."""
    if not isinstance(value, (int, float)):
        return False
    # Accept negative dBm range and a small positive sliver for
    # integrations that report unsigned values close to 0 dBm.
    return -120 <= float(value) <= 0


def wifi_find_capability_for(
    entity_id: str,
    *,
    state_attributes: dict | None = None,
) -> WifiFindCapability:
    """Decide Wi-Fi trackability for one entity.

    Returns a WifiFindCapability. `is_trackable` is True only when
    BOTH a signal-strength reading AND an AP identifier were found
    — neither alone is enough to infer location.

    Args:
      entity_id: HA entity_id, used only for the reason text.
      state_attributes: `state.attributes` dict for the entity.
        When None or empty, the call short-circuits to not-trackable.
    """
    attrs = state_attributes or {}

    signal_attr: str | None = None
    signal_dbm: int | None = None
    for name in _WIFI_SIGNAL_ATTRS:
        if name in attrs:
            value = attrs[name]
            if _is_wifi_dbm_range(value):
                signal_attr = name
                signal_dbm = int(value)
                break

    ap_attr: str | None = None
    ap_id: str | None = None
    for name in _WIFI_AP_ATTRS:
        v = attrs.get(name)
        if isinstance(v, str) and v.strip():
            ap_attr = name
            ap_id = v.strip()
            break

    if signal_attr is None and ap_attr is None:
        return WifiFindCapability(
            is_trackable=False,
            reason=(
                f"{entity_id} has no recognised Wi-Fi signal or AP "
                "attribute. UniFi typically exposes rx_rssi + ap_mac; "
                "Asuswrt exposes signal + host. If your integration "
                "uses different attribute names, the detector can be "
                "extended."
            ),
        )

    if signal_attr is None:
        return WifiFindCapability(
            is_trackable=False,
            ap_attribute=ap_attr,
            ap_identifier=ap_id,
            reason=(
                f"{entity_id} has an AP attribute ({ap_attr}={ap_id}) "
                "but no signal-strength reading — can't gauge "
                "proximity, so the area inference would be a weak "
                "guess. Skipped."
            ),
        )

    if ap_attr is None:
        return WifiFindCapability(
            is_trackable=False,
            signal_attribute=signal_attr,
            signal_dbm=signal_dbm,
            reason=(
                f"{entity_id} has a Wi-Fi signal reading "
                f"({signal_attr}={signal_dbm} dBm) but no AP "
                "identifier — without knowing which AP saw the "
                "signal we can't cross-reference to an area."
            ),
        )

    return WifiFindCapability(
        is_trackable=True,
        signal_attribute=signal_attr,
        signal_dbm=signal_dbm,
        ap_attribute=ap_attr,
        ap_identifier=ap_id,
        reason=(
            f"Signal {signal_dbm} dBm via {signal_attr}; "
            f"associated with AP {ap_id} via {ap_attr}."
        ),
    )


__all__ = [
    "WifiFindCapability",
    "wifi_find_capability_for",
]
