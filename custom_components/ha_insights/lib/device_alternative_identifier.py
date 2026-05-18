"""Pick a safer sibling entity for identify when one exists.

The identify pipeline (see ``identify_capability.py``) chooses how to
make an entity announce itself. For a Shelly Plus 1, Sonoff Mini,
Tesla Wall Connector, or generic EV charger the user typically points
identify at the main relay or contactor — but cycling that relay
interrupts power to whatever load is downstream (a server, the
fridge, the car charge session).

Many of those same devices expose a separate ``light.*`` or
``switch.*`` entity that's a **status LED / indicator** — typically
flagged as ``entity_category: diagnostic`` in the entity registry,
or named with ``led`` / ``status`` / ``indicator``. Toggling the LED
is harmless: it doesn't carry the load, doesn't cycle the relay,
doesn't trigger vendor pairing modes.

This lib picks the safest sibling on a device when one is available.

## Architecture

Pure function — no HA imports, no side effects. Takes the list of
sibling entities (already collected by the WS handler from the
device registry) and returns the best candidate by priority order.
The WS handler performs the registry lookup and substitutes the
alternative entity_id when one is found.

Priority ranking (highest priority first):

  1. Sibling has ``entity_category="diagnostic"`` AND
     ``domain in {light, switch}``. These are intentional indicator
     entities exposed by the integration (Shelly LED, Tasmota status
     LED, etc.).
  2. Sibling has domain ``light`` and the **original** request was for
     a non-light entity. Lights use BRIGHTNESS_WIGGLE (safe, no
     power cycle) while switches use SWITCH_TOGGLE (power cycle).
  3. Sibling's entity_id / name contains ``led``, ``status``,
     ``indicator``, ``led_ring``, ``signal_light``, ``mode_light``.
  4. No alternative — return None and let the caller fall back to
     the original entity.

Lights are NEVER substituted; if the user asked for ``light.foo`` and
that device has a ``switch.foo`` LED, the light is already safe via
brightness-wiggle. Switches are only substituted with same-device
siblings (never cross-device).

Returns ``DeviceAlternative`` describing the picked entity plus a
``reason`` string the card can show: "Identifying via status LED
(safer than cycling relay)".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# Domains where substitution makes sense — power-cycling identify
# methods. Lights bypass entirely (their identify is already safe
# via FLASH_LIGHT / BRIGHTNESS_WIGGLE).
_SUBSTITUTABLE_DOMAINS: frozenset[str] = frozenset({"switch", "siren"})

# Keywords in entity_id or friendly_name that suggest an indicator
# entity. Lowered before match; substring semantics.
_INDICATOR_KEYWORDS: frozenset[str] = frozenset(
    {
        "led",
        "led_ring",
        "led_strip",
        "status",
        "status_light",
        "indicator",
        "signal_light",
        "mode_light",
        "power_led",
        "wifi_led",
        "activity_led",
        "ring_light",
    },
)


@dataclass(frozen=True)
class SiblingEntity:
    """A sibling entity on the same device as the original request.

    Caller (WS handler) collects these from
    ``homeassistant.helpers.entity_registry`` and passes them in as
    a list. Keeping this struct HA-import-free preserves the
    pure-function contract.
    """

    entity_id: str
    domain: str
    friendly_name: str | None
    entity_category: str | None  # "diagnostic", "config", or None


@dataclass(frozen=True)
class DeviceAlternative:
    """The chosen safer sibling and why we chose it.

    entity_id: the substitute entity_id to fire identify against.
    reason: human-readable rationale shown in the card.
    rule: short tag for telemetry / debugging — which priority rule
        triggered.
    """

    entity_id: str
    reason: str
    rule: str


def pick_alternative_identifier(
    original_entity_id: str,
    siblings: list[SiblingEntity],
) -> DeviceAlternative | None:
    """Pick a safer sibling for identify, or None if no improvement.

    Args:
      original_entity_id: the entity the user clicked Identify on.
      siblings: list of OTHER entities on the same device (the
        caller has already excluded the original). Empty list is
        valid and returns None.

    Returns:
      DeviceAlternative when a safer sibling exists.
      None when the original entity should be used as-is.
    """
    if "." not in original_entity_id:
        return None
    original_domain = original_entity_id.split(".", 1)[0]

    # Only substitute switch/siren — lights are already safe.
    if original_domain not in _SUBSTITUTABLE_DOMAINS:
        return None

    # Priority 1: diagnostic-category light / switch sibling.
    for s in siblings:
        if s.entity_category == "diagnostic" and s.domain in {"light", "switch"}:
            return DeviceAlternative(
                entity_id=s.entity_id,
                reason=(
                    f"Identifying via the device's diagnostic "
                    f"{s.domain} ({s.entity_id}) — safer than "
                    f"cycling the main relay."
                ),
                rule="diagnostic_category",
            )

    # Priority 2: any light sibling (brightness-wiggle is safe).
    for s in siblings:
        if s.domain == "light":
            return DeviceAlternative(
                entity_id=s.entity_id,
                reason=(
                    f"Identifying via the device's light "
                    f"({s.entity_id}) — safer than cycling the "
                    f"main relay."
                ),
                rule="domain_light",
            )

    # Priority 3: name-based indicator detection.
    for s in siblings:
        if s.domain not in {"light", "switch"}:
            continue
        hay = s.entity_id.lower()
        if s.friendly_name:
            hay = f"{hay} {s.friendly_name.lower()}"
        for kw in _INDICATOR_KEYWORDS:
            if kw in hay:
                return DeviceAlternative(
                    entity_id=s.entity_id,
                    reason=(
                        f"Identifying via the device's status LED "
                        f"({s.entity_id}) — safer than cycling the "
                        f"main relay."
                    ),
                    rule=f"name_keyword:{kw}",
                )

    return None


def to_sibling(entity_dict: dict[str, Any]) -> SiblingEntity | None:
    """Convenience constructor from a plain dict (for tests + WS
    handler). Returns None if the dict is malformed."""
    entity_id = entity_dict.get("entity_id")
    if not isinstance(entity_id, str) or "." not in entity_id:
        return None
    domain = entity_id.split(".", 1)[0]
    return SiblingEntity(
        entity_id=entity_id,
        domain=domain,
        friendly_name=entity_dict.get("friendly_name") if isinstance(
            entity_dict.get("friendly_name"), str
        ) else None,
        entity_category=entity_dict.get("entity_category") if isinstance(
            entity_dict.get("entity_category"), str
        ) else None,
    )


__all__ = [
    "DeviceAlternative",
    "SiblingEntity",
    "pick_alternative_identifier",
    "to_sibling",
]
