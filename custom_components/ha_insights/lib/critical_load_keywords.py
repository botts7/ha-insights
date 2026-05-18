"""Critical-load detection for safe identify-mode operation.

Toggling a switch or strobing a light during a Find-Device session
is fine for a Hue bulb in a bedroom — disastrous for a server PSU,
medical CPAP, aquarium heater, EV charger contactor, sump pump, or
fridge. v1.10.9 introduces a deny-list of keywords commonly used
in entity_id / friendly_name for loads we MUST NOT cycle, even
once.

This is the **last line of defence**. The proper fix is:

1. **v1.10.10**: prefer diagnostic-category LED entities over the
   relay when a device exposes one (EV chargers, Shelly, Sonoff
   with status LEDs).
2. **v1.10.11**: vendor-aware identify (ZHA `effect: blink`, Z-Wave
   Indicator CC, LIFX `flash`, Yeelight `flash`) so the toggle path
   is rare.
3. **v1.10.12**: live power-consumption check — if the linked
   `sensor.<entity>_power` shows > 50 W continuous over the last
   10 min, treat as critical regardless of keyword match.

Until those land, names are the cheapest correct signal — and
combined with the per-session ceilings already in place, they
catch the bulk of the dangerous cases.

## Architecture

Pure function — no HA imports, no side effects. The WS handler
(`ws_identify_entity`) consults this lib before firing any toggle
or strobe pattern. Lights are not gated because brightness-wiggle
is safe; switches and sirens are.

False positives are acceptable here (refusing to identify an
entity costs the user 30 s of squinting at labels); false
negatives are not (factory-resetting a Tuya bulb, or worse,
cycling a CPAP). Keyword list is intentionally broad.
"""
from __future__ import annotations

# Keywords that, when matched in entity_id or friendly_name, refuse
# any toggle / strobe pattern. Matching is substring + case-insensitive.
# Sourced from real HA install audit + community-reported incidents.
#
# Categories — keep groups together for review:
#
#   Medical / life-safety:
#     cpap, oxygen, ventilator, dialysis, incubator, fridge_medicine,
#     insulin
#
#   Power-critical infra:
#     server, nas, router, modem, switch_rack, network, firewall, ups,
#     pdu, rack
#
#   Refrigeration (food-loss):
#     fridge, freezer, refrigerator, deepfreeze, wine_cooler, cellar,
#     beer_fridge
#
#   Live animals / plants:
#     aquarium, fish, reptile, terrarium, vivarium, hatchery, brooder,
#     coop, incubator, grow, hydroponic
#
#   Pumps / climate / safety:
#     sump, septic, well, boiler, furnace, hvac, heater, hot_water,
#     pool_pump, spa_pump
#
#   EV / high-current:
#     ev_charger, ev_charging, tesla_charger, wallbox, easee, zappi,
#     chargepoint, ocpp, evse
#
#   Safety / security:
#     alarm, monitor, smoke, co2_alarm, gas_leak, water_leak, camera
#     (some IP cams reset on power-cycle, losing config)
#
#   Solar / battery / generators:
#     solar_inverter, inverter, generator, battery_storage,
#     powerwall, pwall, lifepo4
#
#   Personal / labeled-critical:
#     critical, do_not_toggle, dnt, keep_on, always_on, locked,
#     production
_CRITICAL_KEYWORDS: frozenset[str] = frozenset(
    {
        # Medical
        "cpap", "oxygen", "ventilator", "dialysis", "insulin",
        "incubator", "nebulizer", "feeding_pump",
        # HA host / self-destruct prevention — toggling the switch
        # that powers HA itself terminates the running session and
        # could corrupt the recorder DB mid-write.
        "homeassistant", "home_assistant", "ha_host", "ha_box",
        "ha_server", "hass", "hassio", "haos", "supervisor",
        # Power infra (general)
        "server", "nas", "router", "modem", "firewall", "ups", "pdu",
        "rack", "network_switch", "switch_rack", "homeserver",
        "home_server", "home_lab", "homelab", "proxmox", "unraid",
        "truenas", "synology", "qnap", "raspberry_pi", "rpi",
        "raspberry", "intel_nuc", "docker_host",
        # Refrigeration
        "fridge", "freezer", "refrigerator", "deepfreeze",
        "wine_cooler", "wine_fridge", "beer_fridge", "kegerator",
        "ice_maker",
        # Live animals / plants
        "aquarium", "fish_tank", "reptile", "terrarium", "vivarium",
        "hatchery", "brooder", "chicken_coop", "grow_light",
        "hydroponic", "vivarium_heat", "petfeeder",
        # Pumps / climate / safety
        "sump_pump", "septic", "well_pump", "boiler", "furnace",
        "hot_water", "water_heater", "pool_pump", "spa_pump",
        "irrigation", "sprinkler",
        # EV / high-current
        "ev_charger", "ev_charging", "evse", "wallbox", "easee",
        "zappi", "chargepoint", "ocpp", "tesla_charger", "tesla_wall",
        "ev_outlet",
        # Safety / security
        "alarm_panel", "smoke_detector", "co_alarm", "gas_leak",
        "water_leak", "monitoring", "ip_camera", "cctv", "nvr",
        "dvr", "doorbell", "garage_door", "gate_motor",
        # Solar / battery / generators
        "solar_inverter", "inverter", "generator", "powerwall",
        "battery_storage", "pwall", "lifepo4",
        # User-labelled
        "critical", "do_not_toggle", "do_not_switch", "dnt",
        "keep_on", "always_on", "locked_on", "production",
    },
)

# Words that look critical but are not in real installs. Excluded
# substring matches to prevent false positives like:
#   - "router_status_light" (a wifi router's status LED, safe to flash)
#   - "fridge_door_sensor" (binary_sensor, not a switch)
#   - "wine_cellar_humidity" (sensor)
# These domains never get gated; the gate ONLY applies to switch and
# siren (and any future power-cycling identify methods). Lights via
# brightness-wiggle are always allowed because they don't cut power.
_GATED_DOMAINS: frozenset[str] = frozenset({"switch", "siren"})


def is_critical_load(
    entity_id: str,
    friendly_name: str | None = None,
) -> tuple[bool, str | None]:
    """Return ``(critical, matched_keyword)``.

    Only domains in ``_GATED_DOMAINS`` are evaluated. For other
    domains (light, media_player) the lib always returns
    ``(False, None)`` because their identify methods don't
    interrupt power.

    Match is case-insensitive substring over both ``entity_id`` and
    ``friendly_name``. We deliberately do not split on underscores
    — keyword ``ev_charger`` matches ``switch.garage_ev_charger_1``
    even though token order differs.

    Returns:
      ``(True, "freezer")`` if a critical keyword matched.
      ``(False, None)`` if no match or domain isn't gated.
    """
    if "." not in entity_id:
        return False, None
    domain = entity_id.split(".", 1)[0]
    if domain not in _GATED_DOMAINS:
        return False, None
    haystack = entity_id.lower()
    if friendly_name:
        haystack = f"{haystack} {friendly_name.lower()}"
    for kw in _CRITICAL_KEYWORDS:
        if kw in haystack:
            return True, kw
    return False, None


def critical_keywords() -> frozenset[str]:
    """Return the immutable keyword set. For tests / introspection."""
    return _CRITICAL_KEYWORDS


__all__ = [
    "critical_keywords",
    "is_critical_load",
]
