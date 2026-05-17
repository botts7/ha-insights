"""Tests for lib/identify_capability — v1.12.8 backfill.

Per agent review (Track E test-coverage), this lib was used by two
WS handlers (`identify_capability`, `identify_entity`) but had no
dedicated test file. Fills the coverage gap.
"""
from __future__ import annotations

from custom_components.ha_insights.lib.identify_capability import (
    IdentifyCapability,
    IdentifyMethod,
    identify_capability_for,
)

# ---------- Tier 1: FLASH_LIGHT for lights with SUPPORT_FLASH -----------


def test_light_with_flash_feature_uses_flash_method() -> None:
    """`light.*` with SUPPORT_FLASH (bit 8) gets the single-shot
    flash. Most modern smart bulbs report this."""
    cap = identify_capability_for(
        "light.kitchen_lamp",
        {"attributes": {"supported_features": 8}},
    )
    assert cap.method == IdentifyMethod.FLASH_LIGHT
    assert len(cap.service_calls) == 1
    assert cap.service_calls[0]["service"] == "turn_on"
    assert cap.service_calls[0]["data"].get("flash") == "short"


def test_light_with_multiple_features_still_uses_flash_if_set() -> None:
    """Bitwise check — flash is bit 8 but feature value may include
    others (e.g. effect=4, transition=2, etc.)."""
    cap = identify_capability_for(
        "light.foo",
        # 8 (flash) + 16 (effect) + 1 (brightness)
        {"attributes": {"supported_features": 25}},
    )
    assert cap.method == IdentifyMethod.FLASH_LIGHT


# ---------- Tier 2: STROBE_LIGHT fallback for lights without flash ------


def test_light_without_flash_uses_strobe() -> None:
    """Light without SUPPORT_FLASH falls back to manual on/off/
    on/off/on at 350ms cadence."""
    cap = identify_capability_for(
        "light.foo",
        {"attributes": {"supported_features": 0}},
    )
    assert cap.method == IdentifyMethod.STROBE_LIGHT
    assert len(cap.service_calls) == 5
    assert cap.inter_call_delay_ms == 350
    # Sequence: on, off, on, off, on (ends ON so user can see it).
    services = [c["service"] for c in cap.service_calls]
    assert services == ["turn_on", "turn_off", "turn_on", "turn_off", "turn_on"]


def test_light_with_no_attributes_still_gets_strobe() -> None:
    """Defensive: no state info → strobe is safe default for any light."""
    cap = identify_capability_for("light.unknown_attrs", None)
    assert cap.method == IdentifyMethod.STROBE_LIGHT


# ---------- Tier 3: PLAY_CHIME for media_players ------------------------


def test_media_player_gets_chime() -> None:
    cap = identify_capability_for(
        "media_player.kitchen_speaker",
        {"attributes": {}},
    )
    assert cap.method == IdentifyMethod.PLAY_CHIME
    assert len(cap.service_calls) == 1
    assert cap.service_calls[0]["domain"] == "media_player"
    assert cap.service_calls[0]["service"] == "play_media"
    assert cap.service_calls[0]["data"]["media_content_type"] == "music"


# ---------- Tier 4: SIREN_CHIRP -----------------------------------------


def test_siren_chirps() -> None:
    cap = identify_capability_for("siren.alarm", {"attributes": {}})
    assert cap.method == IdentifyMethod.SIREN_CHIRP
    assert cap.service_calls[0]["service"] == "turn_on"
    assert cap.service_calls[0]["data"]["duration"] == 1


# ---------- Tier 5: SWITCH_TOGGLE ---------------------------------------


def test_switch_toggles_three_times() -> None:
    cap = identify_capability_for(
        "switch.bedside_lamp",
        {"attributes": {}},
    )
    assert cap.method == IdentifyMethod.SWITCH_TOGGLE
    assert len(cap.service_calls) == 3
    assert all(c["service"] == "toggle" for c in cap.service_calls)
    assert cap.inter_call_delay_ms == 500


# ---------- Tier 6: NONE for unsupported domains ------------------------


def test_passive_sensor_returns_none() -> None:
    """Temperature sensor can't self-announce; falls back to NONE
    (v1.10 Phase B perturbation is the path for these)."""
    cap = identify_capability_for(
        "sensor.kitchen_temperature",
        {"attributes": {"device_class": "temperature"}},
    )
    assert cap.method == IdentifyMethod.NONE
    assert cap.service_calls == []


def test_script_returns_none_for_safety() -> None:
    """Scripts could theoretically be triggered but invoking
    arbitrary user-defined code as an identify signal is unsafe."""
    cap = identify_capability_for("script.morning_routine", {"attributes": {}})
    assert cap.method == IdentifyMethod.NONE


def test_automation_returns_none_for_safety() -> None:
    cap = identify_capability_for("automation.foo", {"attributes": {}})
    assert cap.method == IdentifyMethod.NONE


def test_unknown_domain_returns_none() -> None:
    cap = identify_capability_for("custom_widget.xyz", {"attributes": {}})
    assert cap.method == IdentifyMethod.NONE


# ---------- Defensive: malformed inputs ---------------------------------


def test_entity_id_without_dot_returns_none() -> None:
    cap = identify_capability_for("no_dot_entity_id", {"attributes": {}})
    assert cap.method == IdentifyMethod.NONE


def test_non_dict_state_attributes_handled() -> None:
    """If somehow attributes is a list/None, don't crash."""
    cap = identify_capability_for(
        "light.foo",
        {"attributes": None},
    )
    # Falls back to strobe (default for light when supported_features
    # can't be read).
    assert cap.method == IdentifyMethod.STROBE_LIGHT


def test_supported_features_non_int_handled() -> None:
    """Some integrations may put unexpected types in
    supported_features. Don't crash; treat as 0."""
    cap = identify_capability_for(
        "light.foo",
        {"attributes": {"supported_features": "not a number"}},
    )
    # Treated as 0 → no flash bit → strobe fallback
    assert cap.method == IdentifyMethod.STROBE_LIGHT


# ---------- Output shape ------------------------------------------------


def test_capability_is_frozen_dataclass() -> None:
    cap = identify_capability_for("light.foo", {"attributes": {}})
    assert isinstance(cap, IdentifyCapability)
    # Frozen — should not be mutable
    import dataclasses
    assert dataclasses.is_dataclass(cap)


def test_description_is_human_readable() -> None:
    """Description goes in the button tooltip; must be plain English."""
    cap = identify_capability_for(
        "light.foo",
        {"attributes": {"supported_features": 8}},
    )
    assert "flash" in cap.description.lower()
    assert "light" in cap.description.lower()


def test_method_enum_values_stable() -> None:
    """The WS contract serializes method.value as a string — the
    enum values must stay stable for the card to consume them."""
    assert IdentifyMethod.FLASH_LIGHT.value == "flash_light"
    assert IdentifyMethod.STROBE_LIGHT.value == "strobe_light"
    assert IdentifyMethod.PLAY_CHIME.value == "play_chime"
    assert IdentifyMethod.SIREN_CHIRP.value == "siren_chirp"
    assert IdentifyMethod.SWITCH_TOGGLE.value == "switch_toggle"
    assert IdentifyMethod.NONE.value == "none"
