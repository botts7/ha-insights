"""Identify-capability detection for unassigned / unfindable entities.

When a user has dozens of entities with cryptic names
(``light.0x00158d000a1b2c3d``) and no area assignments, they often
don't know where each device physically is. This lib answers:
"can we make this entity announce itself?" — what built-in HA service
call will produce a visible / audible signal so the user can walk
toward it and identify the device.

## Capability hierarchy

The lib returns the BEST method available for an entity, in priority
order. Methods are ordered so safer (non-power-cycling, non-pairing-
trigger) methods come first:

1. **FLASH_LIGHT** — `light.*` with the ``SUPPORT_FLASH`` feature
   bit set. Calls ``light.turn_on`` with ``flash: short`` so the
   device blinks once. Most lights support this. Safe — driver-level
   flash signal, does not power-cycle the bulb.
2. **BRIGHTNESS_WIGGLE** — `light.*` without flash but supporting
   brightness. We dim from 100% → 30% → 100% with 1.5s gaps. Visible
   change but **no off transitions**, so vendor pairing-mode
   thresholds are never approached. Safer than strobe for Tuya /
   Aqara / Hue / IKEA bulbs.
3. **STROBE_LIGHT** — `light.*` with no flash and no brightness
   (rare: dumb on/off bulbs). Last-resort fallback: 2 slow toggles
   at 3 s cadence (well below every known vendor pairing threshold).
4. **PLAY_CHIME** — `media_player.*` that exposes ``play_media``.
   Plays a built-in chime tone so the user can hear which speaker
   is which.
5. **SIREN_CHIRP** — `siren.*` calls ``siren.turn_on`` with the
   shortest configured duration. Built for this exact use case.
6. **SWITCH_TOGGLE** — `switch.*` toggles on/off twice at 2.5s
   cadence. Below Tuya / Aqara pairing thresholds. The relay click
   is often audible at close range; if the switch drives a load,
   the load cycles too — the card warns about this so users with
   smart bulbs downstream of dumb switches don't get confused.
7. **NONE** — passive sensors, scripts, automations, device_tracker,
   and other domains we can't make announce. Caller falls back to
   v1.10 Phase B perturbation testing.

## Vendor pairing-mode safety

Many smart-light vendors interpret rapid on/off cycles as a factory-
reset / re-pair trigger:

  - Tuya / Smart Life: 3× on/off within 10 s
  - Aqara: 5× toggles in 5 s
  - IKEA Trådfri: 6× toggles in 10 s
  - Philips Hue: 5× off/on within ~10 s
  - Sengled: 10× off/on within 10 s
  - LIFX: 5× off/on (≤2 s each)

Our strobe pre-v1.10.9 fired 5 toggles in 1.4 s, which crossed
**every** threshold listed above — running identify on a Tuya bulb
would have factory-reset it. Post-v1.10.9, the active light pattern
is brightness-wiggle (zero power transitions) wherever brightness
is supported, with a 2-toggle 3-s strobe fallback that stays safely
below all known thresholds.

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
    BRIGHTNESS_WIGGLE = "brightness_wiggle"
    STROBE_LIGHT = "strobe_light"
    PLAY_CHIME = "play_chime"
    SIREN_CHIRP = "siren_chirp"
    SWITCH_TOGGLE = "switch_toggle"
    NONE = "none"


# HA's `light` domain SUPPORT_FLASH feature bit. Hardcoded here so
# the lib stays HA-import-free; sourced from
# homeassistant/components/light/__init__.py::LightEntityFeature.FLASH.
_LIGHT_SUPPORT_FLASH: int = 8

# HA color-mode strings that indicate the light has dimmable brightness.
# Sourced from homeassistant/components/light/const.py::ColorMode. We
# treat any of these as "brightness is settable". ONOFF and UNKNOWN
# are deliberately excluded.
_BRIGHTNESS_COLOR_MODES: frozenset[str] = frozenset(
    {"brightness", "color_temp", "hs", "rgb", "rgbw", "rgbww", "white", "xy"},
)

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
    """Lights: prefer driver flash, then brightness wiggle, then a
    slow 2-toggle strobe. Pattern selection is safety-driven — see
    module docstring for vendor pairing-mode thresholds we must
    stay below.
    """
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
    # Brightness wiggle: dim → bright → dim → bright. No power-off
    # transitions, so vendor pairing thresholds are never approached.
    # Works on any bulb that reports a brightness-capable color_mode
    # or a populated `supported_color_modes` list. Visible at any
    # ambient light because the relative change is ~70%.
    supported_color_modes = attributes.get("supported_color_modes")
    color_mode = attributes.get("color_mode")
    has_brightness = False
    if isinstance(supported_color_modes, list | tuple | set):
        has_brightness = any(
            isinstance(m, str) and m in _BRIGHTNESS_COLOR_MODES
            for m in supported_color_modes
        )
    if not has_brightness and isinstance(color_mode, str):
        has_brightness = color_mode in _BRIGHTNESS_COLOR_MODES
    if has_brightness:
        # 1.5s cadence × 4 calls = 6s total. Final brightness=255 so
        # the user can still see the light at full intensity when they
        # walk into the room. Transition=0.5s makes the dim/bright
        # change feel like a deliberate pulse rather than a glitch.
        return IdentifyCapability(
            method=IdentifyMethod.BRIGHTNESS_WIGGLE,
            description="pulse the light brightness (no power cycle)",
            service_calls=[
                {
                    "domain": "light",
                    "service": "turn_on",
                    "data": {"brightness": 77, "transition": 0.5},
                },
                {
                    "domain": "light",
                    "service": "turn_on",
                    "data": {"brightness": 255, "transition": 0.5},
                },
                {
                    "domain": "light",
                    "service": "turn_on",
                    "data": {"brightness": 77, "transition": 0.5},
                },
                {
                    "domain": "light",
                    "service": "turn_on",
                    "data": {"brightness": 255, "transition": 0.5},
                },
            ],
            inter_call_delay_ms=1500,
        )
    # Last-resort strobe for dumb on/off bulbs. 2 toggles total
    # (on→off→on) at 3 s cadence — total 6 s. Stays safely below
    # every vendor pairing-mode threshold (Tuya needs 3×, Aqara 5×,
    # Hue 5×, IKEA 6×, Sengled 10×). Final state ON so the user
    # can see the bulb when they walk in.
    return IdentifyCapability(
        method=IdentifyMethod.STROBE_LIGHT,
        description="strobe the light (slow on/off pattern)",
        service_calls=[
            {"domain": "light", "service": "turn_on", "data": {}},
            {"domain": "light", "service": "turn_off", "data": {}},
            {"domain": "light", "service": "turn_on", "data": {}},
        ],
        inter_call_delay_ms=3000,
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
    """Switches: 2 toggles at 2.5 s cadence.

    Pre-v1.10.9 fired 3× at 500 ms — that's the Tuya pairing-mode
    threshold (3 toggles in 10 s). Reducing to 2 toggles stays under
    every vendor threshold including Tuya (3×) and Aqara (5×).

    The card surfaces a warning that if the switch is hard-wired to
    a smart bulb downstream, the bulb will flicker too — that's how
    the user discovers wired pairs (deferred to v1.10.10 for
    automated detection).

    The switch returns to its starting state (2 toggles cancel out),
    so we don't strand the user's load in an unexpected position.
    """
    return IdentifyCapability(
        method=IdentifyMethod.SWITCH_TOGGLE,
        description="toggle the switch twice (audible click)",
        service_calls=[
            {"domain": "switch", "service": "toggle", "data": {}},
            {"domain": "switch", "service": "toggle", "data": {}},
        ],
        inter_call_delay_ms=2500,
    )


__all__ = [
    "IdentifyCapability",
    "IdentifyMethod",
    "identify_capability_for",
]
