"""Identify-capability detection for unassigned / unfindable entities.

When a user has dozens of entities with cryptic names
(``light.0x00158d000a1b2c3d``) and no area assignments, they often
don't know where each device physically is. This lib answers:
"can we make this entity announce itself?" — what built-in HA service
call will produce a visible / audible signal so the user can walk
toward it and identify the device.

## Capability hierarchy

The lib returns the BEST method available for an entity, in priority
order:

1. **FLASH_LIGHT** — `light.*` with the ``SUPPORT_FLASH`` feature
   bit set. Calls ``light.turn_on`` with ``flash: short`` so the
   device blinks once. Most lights support this.
2. **STROBE_LIGHT** — `light.*` without flash, but with a brightness
   or color attribute. We toggle on/off three times manually with
   short delays. Works for any light that responds to turn_on/off.
3. **PLAY_CHIME** — `media_player.*` that exposes ``play_media``.
   Plays a built-in chime tone so the user can hear which speaker
   is which.
4. **SIREN_CHIRP** — `siren.*` calls ``siren.turn_on`` with the
   shortest configured duration. Built for this exact use case.
5. **SWITCH_TOGGLE** — `switch.*` toggles on/off three times. The
   relay click is often audible at close range, and if the switch
   has a connected load the load cycles too.
6. **NONE** — passive sensors, scripts, automations, device_tracker,
   and other domains we can't make announce. Caller falls back to
   v1.10 Phase B perturbation testing.

## Architecture

Pure function — no HA imports, no side effects. Takes a small dict
of entity state ({domain, attributes, supported_features}) and
returns a frozen ``IdentifyCapability`` dataclass describing the
chosen method and the service-call shape. The actual ``hass.services
.async_call`` happens in the WS handler (``ws_identify_entity`` in
``ws_api.py``), keeping I/O out of the testable layer.

Companion to v1.10 Phase B (`lib/perturbation_capability.py`,
planned): perturbation handles entities this lib returns NONE for
by asking the user to physically perturb a sensor and watching for
the spike on the entity's state stream.

Architecture note per memory `ha_insights_find_my_device_roadmap`:
this is an **algorithmic lib** (single-consumer — the identify WS
endpoint). Distinct from signal-grader libs that compose into
HumanLikelihoodFeatures.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class IdentifyMethod(StrEnum):
    """Discrete identify methods, ordered by preference (best first)."""

    FLASH_LIGHT = "flash_light"
    STROBE_LIGHT = "strobe_light"
    PLAY_CHIME = "play_chime"
    SIREN_CHIRP = "siren_chirp"
    SWITCH_TOGGLE = "switch_toggle"
    NONE = "none"


# HA's `light` domain SUPPORT_FLASH feature bit. Hardcoded here so
# the lib stays HA-import-free; sourced from
# homeassistant/components/light/__init__.py::LightEntityFeature.FLASH.
_LIGHT_SUPPORT_FLASH: int = 8

# Default chime URL — uses HA's built-in TTS chime sound. The
# integration-side WS handler may override this with a user-set URL
# in a future revision.
_DEFAULT_CHIME_URL: str = (
    "https://github.com/home-assistant/core/raw/dev/"
    "homeassistant/components/tts/google_translate.mp3"
)


@dataclass(frozen=True)
class IdentifyCapability:
    """What identify signal an entity can emit, and how to trigger it.

    method: which IdentifyMethod was chosen (NONE if nothing fits).
    description: human-readable phrase the card shows when prompting
        the user — "flash the light briefly", "play a short chime",
        etc. Plain English, no markup.
    service_calls: ordered list of (domain, service, data) tuples the
        WS handler will fire sequentially. Each dict's "target" key
        is implicit — the handler injects the entity_id. Empty list
        when method is NONE.
    inter_call_delay_ms: pause between sequential calls. 0 for
        single-call methods (flash). Used for strobe/toggle patterns
        where the visible/audible effect comes from the rhythm.
    """

    method: IdentifyMethod
    description: str
    service_calls: list[dict[str, Any]] = field(default_factory=list)
    inter_call_delay_ms: int = 0


_NONE_CAPABILITY: IdentifyCapability = IdentifyCapability(
    method=IdentifyMethod.NONE,
    description=(
        "This entity has no built-in way to announce itself. "
        "Try the touch-test mode (v1.10 Phase B) for passive sensors."
    ),
)


def identify_capability_for(
    entity_id: str,
    state_snapshot: dict[str, Any] | None,
) -> IdentifyCapability:
    """Pick the best identify method for one entity.

    Args:
      entity_id: HA entity_id (``light.foo``, ``sensor.bar``, etc.).
        Domain is parsed from the prefix.
      state_snapshot: dict with at least ``attributes`` (a dict). If
        None or missing attributes, falls back to domain-only
        defaults (assumes minimum capabilities for the domain).

    Returns:
      ``IdentifyCapability`` describing the chosen method and the
      service-call shape the WS handler should fire.
    """
    if "." not in entity_id:
        return _NONE_CAPABILITY
    domain = entity_id.split(".", 1)[0]
    attributes = (
        state_snapshot.get("attributes", {})
        if state_snapshot is not None
        else {}
    )
    if not isinstance(attributes, dict):
        attributes = {}

    if domain == "light":
        return _light_capability(attributes)
    if domain == "media_player":
        return _media_player_capability(attributes)
    if domain == "siren":
        return _siren_capability(attributes)
    if domain == "switch":
        return _switch_capability(attributes)
    # `script` and `automation` could theoretically be triggered, but
    # invoking arbitrary user-defined code as an "identify" signal is
    # unsafe — they might do anything (lock doors, send messages).
    # Skip silently.
    return _NONE_CAPABILITY


def _light_capability(attributes: dict[str, Any]) -> IdentifyCapability:
    """Lights: prefer flash if supported, else strobe via turn_on/off."""
    supported = attributes.get("supported_features", 0)
    if not isinstance(supported, int):
        supported = 0
    if supported & _LIGHT_SUPPORT_FLASH:
        return IdentifyCapability(
            method=IdentifyMethod.FLASH_LIGHT,
            description="flash the light briefly",
            service_calls=[
                {
                    "domain": "light",
                    "service": "turn_on",
                    "data": {"flash": "short"},
                },
            ],
        )
    # Manual strobe: on / off / on / off / on (final state ON so a
    # light the user couldn't see remains visible when they walk into
    # the room). 350ms cadence is fast enough to look intentional,
    # slow enough that HA's event bus + the device's response time
    # don't merge them into one transition.
    return IdentifyCapability(
        method=IdentifyMethod.STROBE_LIGHT,
        description="strobe the light (on/off pattern)",
        service_calls=[
            {"domain": "light", "service": "turn_on", "data": {}},
            {"domain": "light", "service": "turn_off", "data": {}},
            {"domain": "light", "service": "turn_on", "data": {}},
            {"domain": "light", "service": "turn_off", "data": {}},
            {"domain": "light", "service": "turn_on", "data": {}},
        ],
        inter_call_delay_ms=350,
    )


def _media_player_capability(attributes: dict[str, Any]) -> IdentifyCapability:
    """Media players: play a built-in chime so the user can hear which
    speaker is which.

    We deliberately use ``play_media`` rather than TTS because TTS
    requires a configured TTS engine and is slower (~2-5s latency).
    A short chime is universally supported and < 1s start-to-sound.
    """
    # NOTE: not all media_players expose play_media (some are
    # read-only like cast groups). We optimistically advertise the
    # capability; if the call fails, the WS handler reports the
    # error back so the card can show "couldn't play chime — try
    # a different identify method or assign manually."
    return IdentifyCapability(
        method=IdentifyMethod.PLAY_CHIME,
        description="play a short chime",
        service_calls=[
            {
                "domain": "media_player",
                "service": "play_media",
                "data": {
                    "media_content_id": _DEFAULT_CHIME_URL,
                    "media_content_type": "music",
                },
            },
        ],
    )


def _siren_capability(attributes: dict[str, Any]) -> IdentifyCapability:
    """Sirens: 1-second chirp. Most sirens cap their minimum duration
    at 1s for hardware/firmware reasons; shorter calls get silently
    extended."""
    return IdentifyCapability(
        method=IdentifyMethod.SIREN_CHIRP,
        description="chirp the siren (~1s)",
        service_calls=[
            {
                "domain": "siren",
                "service": "turn_on",
                "data": {"duration": 1},
            },
        ],
    )


def _switch_capability(attributes: dict[str, Any]) -> IdentifyCapability:
    """Switches: toggle 3× — relay click is audible at close range,
    and if the switch drives a load the load cycles too.

    We don't return to a known state because we don't know whether
    "off" or "on" is the user-intended baseline. After identify the
    switch ends in the OPPOSITE state from where it started, which
    the user can flip back manually after locating it.
    """
    return IdentifyCapability(
        method=IdentifyMethod.SWITCH_TOGGLE,
        description="toggle the switch three times (audible click)",
        service_calls=[
            {"domain": "switch", "service": "toggle", "data": {}},
            {"domain": "switch", "service": "toggle", "data": {}},
            {"domain": "switch", "service": "toggle", "data": {}},
        ],
        inter_call_delay_ms=500,
    )


__all__ = [
    "IdentifyCapability",
    "IdentifyMethod",
    "identify_capability_for",
]
