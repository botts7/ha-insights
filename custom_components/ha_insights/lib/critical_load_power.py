"""Power-consumption-based critical-load detection.

The v1.10.9 keyword deny-list (`critical_load_keywords.py`) catches
named critical loads — entities the user has labelled with words
like ``fridge``, ``server``, ``ev_charger``, etc. But many real-
install critical loads escape the keyword check because their
entity_id is cryptic:

  - ``switch.0x00158d000a1b2c3d`` powering a 200 W kitchen
    refrigerator
  - ``switch.outlet_4`` on a TP-Link strip powering a 90 W home
    server
  - ``switch.zigbee_relay_kc`` driving an aquarium heater +
    bubbler

This lib adds a runtime power-consumption check. When an entity has
a linked power sensor (same device, ``device_class: power`` or
``_power`` suffix), we read the current power draw before firing
identify. Above the threshold → refuse, regardless of keyword.

## Architecture

This module is **not pure** — it imports ``HomeAssistant`` and
reads ``hass.states`` / the entity registry. Pairs with
``critical_load_keywords.is_critical_load`` (which IS pure) to
provide the full critical-load gate.

The WS handler chains them: keyword refusal first (cheap, no
runtime), power-based refusal second (one state lookup per
sibling). Either match refuses identify.

## Heuristics + thresholds

**Power sensor discovery** — scan siblings of the original entity's
device for any entity matching ANY of:

  1. ``state.attributes.device_class == "power"``
  2. ``entity_id.endswith("_power")``
  3. ``entity_id`` contains ``power`` AND domain is ``sensor``

If multiple match, prefer device_class match over name match.

**Threshold (default 50 W)** — phone chargers, doorbell controllers,
small home-automation gear cluster < 10 W. Anything > 50 W
continuous is doing real work and shouldn't be casually toggled.
Caller can pass `threshold_w` to override per-call.

**Unit handling** — recognise ``W``, ``kW``, ``mW``. Anything else
is logged and ignored (treats entity as "no power info"). Most HA
integrations normalise to W or kW.

**State validation** — if the power sensor state is non-numeric
(``unknown`` / ``unavailable`` / ``""``) we treat it as no info,
NOT zero. Refusing in the absence of data would block legit
identify on devices with broken power sensors.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


# Default threshold — anything drawing > 50 W continuously is
# treated as load-carrying. Below this clusters phone chargers,
# doorbell adapters, smart-plug standby, ESP32 boards, etc.
DEFAULT_POWER_THRESHOLD_W: float = 50.0


def find_linked_power_sensor(
    hass: HomeAssistant,
    entity_id: str,
) -> str | None:
    """Return the entity_id of a power sensor on the same device
    as ``entity_id``, or None if none exists.

    Lookup priority:

      1. Sibling with ``state.attributes.device_class == "power"``.
      2. Sibling with entity_id ending in ``_power`` and domain
         ``sensor``.
      3. Sibling whose entity_id contains ``power`` and domain
         ``sensor``.

    Returns None if the entity isn't in the registry, has no
    device_id, or no sibling matches. Defensive against registry
    lookup exceptions (returns None instead of raising).
    """
    if "." not in entity_id:
        return None
    try:
        from homeassistant.helpers import entity_registry as er

        registry = er.async_get(hass)
        entry = registry.async_get(entity_id)
    except Exception:
        return None
    if entry is None or entry.device_id is None:
        return None
    device_id = entry.device_id

    name_match: str | None = None
    weak_match: str | None = None
    for sibling in registry.entities.values():
        if sibling.device_id != device_id:
            continue
        if sibling.entity_id == entity_id:
            continue
        if not sibling.entity_id.startswith("sensor."):
            continue
        state = hass.states.get(sibling.entity_id)
        device_class = (
            state.attributes.get("device_class") if state is not None else None
        )
        if device_class == "power":
            # Strongest signal — return immediately.
            return sibling.entity_id
        if sibling.entity_id.endswith("_power") and name_match is None:
            name_match = sibling.entity_id
        elif "power" in sibling.entity_id and weak_match is None:
            weak_match = sibling.entity_id

    return name_match or weak_match


def _parse_power_watts(state_value: str, unit: str | None) -> float | None:
    """Convert a power sensor's state + unit to watts.

    Returns None when the value isn't parseable or the unit isn't
    recognised. Caller treats None as "no power info" — defaults to
    allowing identify rather than blocking on missing data.
    """
    try:
        v = float(state_value)
    except (TypeError, ValueError):
        return None
    if not unit:
        # No unit — assume W (HA's default for power sensors).
        return v
    unit_norm = unit.strip().lower()
    if unit_norm == "w":
        return v
    if unit_norm == "kw":
        return v * 1000.0
    if unit_norm == "mw":
        return v / 1000.0
    # Unknown unit — refuse to guess.
    return None


def is_critical_by_power(
    hass: HomeAssistant,
    entity_id: str,
    threshold_w: float = DEFAULT_POWER_THRESHOLD_W,
) -> tuple[bool, float | None, str | None]:
    """Return ``(critical, current_watts, sensor_entity_id)``.

    Looks for a power sensor on the same device as ``entity_id``.
    If found and the current reading exceeds ``threshold_w``, the
    entity is treated as a load-carrying critical device that
    shouldn't be casually cycled.

    Returns ``(False, None, None)`` when:
      - no power sensor exists on the device
      - the power sensor state is non-numeric or has an unknown unit
      - reading is at or below threshold

    Returns ``(True, watts, sensor_eid)`` when the reading exceeds
    threshold. Caller surfaces the watts + sensor_eid in the error
    message so the user knows exactly which sensor triggered.
    """
    sensor_eid = find_linked_power_sensor(hass, entity_id)
    if sensor_eid is None:
        return False, None, None
    state = hass.states.get(sensor_eid)
    if state is None:
        return False, None, sensor_eid
    unit = state.attributes.get("unit_of_measurement")
    if unit is not None and not isinstance(unit, str):
        unit = None
    watts = _parse_power_watts(state.state, unit)
    if watts is None:
        return False, None, sensor_eid
    if watts >= threshold_w:
        return True, watts, sensor_eid
    return False, watts, sensor_eid


__all__ = [
    "DEFAULT_POWER_THRESHOLD_W",
    "find_linked_power_sensor",
    "is_critical_by_power",
]
