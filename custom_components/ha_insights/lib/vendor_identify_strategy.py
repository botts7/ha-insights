"""Vendor-native identify primitives.

Most integrations expose a built-in "identify this device" service
that does NOT cycle power and does NOT trigger pairing-mode. Using
the vendor primitive is always safer than our generic toggle /
strobe fallback. This lib maps an integration's HA-domain (the
``platform`` field in the entity registry, e.g. ``zha`` / ``hue`` /
``zwave_js``) onto the canonical native service call.

## Priority chain (in identify_capability_for + WS handler)

Picking the identify method now goes:

  1. **Vendor-native** (this lib) — Zigbee Identify cluster, Z-Wave
     Indicator CC, LIFX flash, Yeelight flow, Hue native flash.
     Always preferred when present. No power cycle, no pairing risk.
  2. **FLASH_LIGHT** — HA's built-in ``light.turn_on flash: short``,
     used when no vendor primitive is mapped but the entity reports
     ``SUPPORT_FLASH``.
  3. **BRIGHTNESS_WIGGLE** — dim/bright pulse, no off transition.
  4. **STROBE_LIGHT / SWITCH_TOGGLE / SIREN_CHIRP** — last-resort
     fallbacks gated by the v1.10.9 critical-load deny-list +
     power-cycle confirmation.

## Architecture

Pure function — no HA imports, no side effects. Takes the entity's
``platform`` string (which integration provides the entity — from
``entity_registry.RegistryEntry.platform``) plus the entity_id and
returns a ``VendorIdentifyStrategy`` if one applies, else None.

Most platforms expose effect-style primitives via well-defined
service calls. The mapping below is sourced from:

  - **ZHA**: ``zha.issue_zigbee_cluster_command`` — Zigbee Identify
    cluster ``0x0003``, ``identify`` command ``0x00`` with
    ``identify_time`` parameter. Bulb breathes for the duration.
  - **MQTT (Zigbee2MQTT)**: bulbs expose ``effect`` attribute via
    ``light.turn_on effect: 'blink'`` — set on the entity.
  - **Z-Wave JS**: ``zwave_js.invoke_cc_api`` with command class
    Indicator (0x87). Most modern Inovelli / Zooz / GE devices
    flash an indicator LED without cycling the load.
  - **LIFX**: ``lifx.effect_pulse`` with ``mode='blink'``. Native
    HSBK pulse, no on/off cycle.
  - **Yeelight**: ``yeelight.start_flow`` with ``count=2``,
    ``transitions=[{...flash transitions...}]``. Built-in flow.
  - **Hue**: ``light.turn_on flash: short`` already routes through
    the bridge's native identify; no separate service needed —
    FLASH_LIGHT covers Hue.
  - **ESPHome**: ``light.turn_on flash: short`` if the firmware
    exposes flash; FLASH_LIGHT covers it.

Returns ``None`` for integrations without a known vendor primitive
— caller falls back to the v1.10.9 pipeline (BRIGHTNESS_WIGGLE /
STROBE_LIGHT / SWITCH_TOGGLE).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class VendorIdentifyStrategy:
    """A vendor-native identify primitive for a single entity.

    platform: HA integration platform (``zha``, ``zwave_js``, etc.).
    method_label: short tag for the response payload + card UX
        ("zigbee_identify_cluster", "zwave_indicator_cc", etc.).
    description: human-readable phrase the card shows
        ("breathe (Zigbee Identify cluster)", "flash status LED
        (Z-Wave Indicator)").
    service_calls: list of ``{domain, service, data}`` dicts. The
        WS handler injects ``entity_id`` (or the appropriate target
        field) when firing.
    """

    platform: str
    method_label: str
    description: str
    service_calls: list[dict[str, Any]] = field(default_factory=list)


def vendor_identify_strategy_for(
    entity_id: str,
    platform: str | None,
) -> VendorIdentifyStrategy | None:
    """Pick the vendor-native identify primitive for an entity, or
    None if no mapping exists for the integration.

    Args:
      entity_id: the entity_id to identify. Used only for service
        call shaping (target field).
      platform: the entity's integration platform — typically
        ``entity_registry.RegistryEntry.platform``. May be None if
        the entity isn't in the registry (rare; templates etc.).

    Returns:
      VendorIdentifyStrategy when a vendor primitive is known.
      None when the integration has no mapping — caller falls back
      to the generic pipeline.
    """
    if not platform or "." not in entity_id:
        return None
    domain = entity_id.split(".", 1)[0]

    if platform == "zha":
        return _zha_strategy(entity_id, domain)
    if platform == "zwave_js":
        return _zwave_js_strategy(entity_id, domain)
    if platform == "lifx":
        return _lifx_strategy(entity_id, domain)
    if platform == "yeelight":
        return _yeelight_strategy(entity_id, domain)
    if platform == "mqtt":
        # Zigbee2MQTT publishes via MQTT; most bulbs accept
        # `effect: blink` via the standard light service.
        return _zigbee2mqtt_strategy(entity_id, domain)
    # Hue + ESPHome lights pass through to FLASH_LIGHT (already safe).
    return None


def _zha_strategy(entity_id: str, domain: str) -> VendorIdentifyStrategy | None:
    """ZHA: trigger Zigbee Identify cluster (0x0003), command 0x00
    (identify), identify_time=3s. The cluster spec mandates a visible
    response (LED blink, breathing pattern, beep) for the duration.

    Works on any Zigbee device that advertises the Identify server
    cluster — which is most ZLL/ZHA-certified bulbs, switches,
    sensors, and even some Zigbee-only relays. Refused gracefully
    by devices without the cluster."""
    if domain not in {"light", "switch", "sensor", "binary_sensor", "siren"}:
        return None
    return VendorIdentifyStrategy(
        platform="zha",
        method_label="zigbee_identify_cluster",
        description="breathe via Zigbee Identify cluster (3 s)",
        service_calls=[
            {
                "domain": "zha",
                "service": "issue_zigbee_cluster_command",
                "data": {
                    "ieee": None,  # Filled in by WS handler from device registry.
                    "endpoint_id": 1,
                    "cluster_id": 3,        # Identify cluster
                    "cluster_type": "in",
                    "command": 0,           # Identify command
                    "command_type": "server",
                    "params": {"identify_time": 3},
                },
                # Hint for the handler — this call needs the IEEE
                # address resolved from the device's `identifiers`.
                "_resolve_ieee_from_entity": entity_id,
            },
        ],
    )


def _zwave_js_strategy(
    entity_id: str, domain: str,
) -> VendorIdentifyStrategy | None:
    """Z-Wave JS: trigger the Indicator command class (0x87) to
    blink the device's indicator LED.

    Most modern Z-Wave devices (Inovelli, Zooz, GE, Leviton, Aeotec)
    implement Indicator CC v3+ which supports an explicit "identify"
    indicator type. Older devices ignore the call gracefully."""
    if domain not in {"light", "switch", "sensor", "binary_sensor", "siren"}:
        return None
    return VendorIdentifyStrategy(
        platform="zwave_js",
        method_label="zwave_indicator_cc",
        description="flash status LED via Z-Wave Indicator CC",
        service_calls=[
            {
                "domain": "zwave_js",
                "service": "invoke_cc_api",
                "data": {
                    "command_class": 135,   # 0x87 Indicator
                    "method_name": "set",
                    "parameters": [
                        # Indicator ID 0x50 = Identify (Z-Wave Plus v2)
                        # On/Off period in 1/10s steps, count, on/off ratio.
                        {
                            "indicatorId": 0x50,
                            "propertyId": 0x03,  # On/Off period
                            "value": 5,           # 0.5 s period
                        },
                        {
                            "indicatorId": 0x50,
                            "propertyId": 0x04,  # On/Off cycles
                            "value": 6,           # ~3 s of blinking
                        },
                    ],
                },
                "target": {"entity_id": entity_id},
            },
        ],
    )


def _lifx_strategy(entity_id: str, domain: str) -> VendorIdentifyStrategy | None:
    """LIFX: native pulse effect — no power cycle, smooth HSBK
    transition. Mode 'blink' alternates between current and a
    contrast colour."""
    if domain != "light":
        return None
    return VendorIdentifyStrategy(
        platform="lifx",
        method_label="lifx_pulse",
        description="pulse via LIFX native effect",
        service_calls=[
            {
                "domain": "lifx",
                "service": "effect_pulse",
                "data": {
                    "mode": "blink",
                    "cycles": 3,
                    "period": 1.0,
                    "power_on": False,  # don't override the current on/off state
                },
                "target": {"entity_id": entity_id},
            },
        ],
    )


def _yeelight_strategy(
    entity_id: str, domain: str,
) -> VendorIdentifyStrategy | None:
    """Yeelight: ``start_flow`` with a 4-step flash transition that
    returns to the current state. Native to the bulb — no power
    cycle."""
    if domain != "light":
        return None
    return VendorIdentifyStrategy(
        platform="yeelight",
        method_label="yeelight_flow",
        description="flow via Yeelight native flash",
        service_calls=[
            {
                "domain": "yeelight",
                "service": "start_flow",
                "data": {
                    "count": 2,
                    "action": "recover",
                    "transitions": [
                        {"Temperature": {"temperature": 2700, "brightness": 100, "duration": 300}},
                        {"Temperature": {"temperature": 2700, "brightness": 30, "duration": 300}},
                    ],
                },
                "target": {"entity_id": entity_id},
            },
        ],
    )


def _zigbee2mqtt_strategy(
    entity_id: str, domain: str,
) -> VendorIdentifyStrategy | None:
    """Zigbee2MQTT: most bulbs accept ``effect: blink`` via the
    standard ``light.turn_on`` service. Z2M's converter translates
    it into the Zigbee Identify cluster on the device.

    Heuristic: we route any ``mqtt``-platform light through this
    path. False-positive risk: non-Z2M MQTT lights (custom MQTT
    devices) may ignore the effect attribute, but the call is
    safe — worst case nothing visible happens and we report
    success."""
    if domain != "light":
        return None
    return VendorIdentifyStrategy(
        platform="mqtt",
        method_label="zigbee2mqtt_effect_blink",
        description="blink via Zigbee2MQTT effect attribute",
        service_calls=[
            {
                "domain": "light",
                "service": "turn_on",
                "data": {"effect": "blink"},
                "target": {"entity_id": entity_id},
            },
        ],
    )


__all__ = [
    "VendorIdentifyStrategy",
    "vendor_identify_strategy_for",
]
