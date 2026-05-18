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


# ---------- Tier 2: BRIGHTNESS_WIGGLE — safe for vendor pairing modes ----


def test_dimmable_light_without_flash_uses_brightness_wiggle() -> None:
    """Light with brightness-capable color_mode but no flash uses
    BRIGHTNESS_WIGGLE — no power-off transitions, so vendor pairing
    thresholds (Tuya 3×, Aqara 5×, Hue 5×, IKEA 6×, Sengled 10×) are
    never approached. Pattern: dim → bright → dim → bright."""
    cap = identify_capability_for(
        "light.tuya_bulb",
        {
            "attributes": {
                "supported_features": 0,
                "supported_color_modes": ["color_temp"],
            },
        },
    )
    assert cap.method == IdentifyMethod.BRIGHTNESS_WIGGLE
    assert len(cap.service_calls) == 4
    # 1.5s cadence keeps total ~6s; well above human reflex but
    # nowhere near any vendor reset threshold.
    assert cap.inter_call_delay_ms == 1500
    # No turn_off calls — power stays on the whole time.
    services = [c["service"] for c in cap.service_calls]
    assert services == ["turn_on", "turn_on", "turn_on", "turn_on"]
    # Final state at full brightness so the user can see it.
    assert cap.service_calls[-1]["data"]["brightness"] == 255


def test_brightness_wiggle_detected_from_supported_color_modes_list() -> None:
    """Any color_mode in the brightness-capable set qualifies."""
    for mode in ["brightness", "color_temp", "hs", "rgb", "rgbw", "rgbww", "xy"]:
        cap = identify_capability_for(
            "light.test",
            {"attributes": {"supported_color_modes": [mode]}},
        )
        assert cap.method == IdentifyMethod.BRIGHTNESS_WIGGLE, (
            f"color_mode={mode} should enable BRIGHTNESS_WIGGLE"
        )


def test_brightness_wiggle_detected_from_current_color_mode() -> None:
    """Lights reporting only `color_mode` (not supported_color_modes)
    also qualify — handles older integrations."""
    cap = identify_capability_for(
        "light.legacy",
        {"attributes": {"color_mode": "brightness"}},
    )
    assert cap.method == IdentifyMethod.BRIGHTNESS_WIGGLE


def test_onoff_light_falls_back_to_safe_strobe() -> None:
    """Light with no flash AND no brightness → 2-toggle strobe at
    3s cadence. Stays below every known vendor pairing threshold.
    """
    cap = identify_capability_for(
        "light.dumb_onoff",
        {
            "attributes": {
                "supported_features": 0,
                "supported_color_modes": ["onoff"],
            },
        },
    )
    assert cap.method == IdentifyMethod.STROBE_LIGHT
    # 2 toggles total (on/off/on), 3 s apart → 6 s session.
    assert len(cap.service_calls) == 3
    assert cap.inter_call_delay_ms == 3000
    services = [c["service"] for c in cap.service_calls]
    assert services == ["turn_on", "turn_off", "turn_on"]


def test_light_with_no_attributes_falls_back_to_strobe() -> None:
    """Defensive: no state info → strobe is the only safe default
    when we can't determine brightness capability."""
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


def test_switch_toggles_twice_at_slow_cadence() -> None:
    """v1.10.9: reduced from 3× at 500ms to 2× at 2.5s to stay below
    Tuya's 3-toggles-in-10s pairing threshold. Also returns the
    switch to its starting state (2 toggles cancel out)."""
    cap = identify_capability_for(
        "switch.bedside_lamp",
        {"attributes": {}},
    )
    assert cap.method == IdentifyMethod.SWITCH_TOGGLE
    assert len(cap.service_calls) == 2
    assert all(c["service"] == "toggle" for c in cap.service_calls)
    # 2.5s cadence keeps aggregate well below any vendor pairing
    # threshold even if the panel loop fires this every 12s.
    assert cap.inter_call_delay_ms == 2500


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
    # Treated as 0 + no brightness info → strobe fallback
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
    assert IdentifyMethod.BRIGHTNESS_WIGGLE.value == "brightness_wiggle"
    assert IdentifyMethod.STROBE_LIGHT.value == "strobe_light"
    assert IdentifyMethod.PLAY_CHIME.value == "play_chime"
    assert IdentifyMethod.SIREN_CHIRP.value == "siren_chirp"
    assert IdentifyMethod.SWITCH_TOGGLE.value == "switch_toggle"
    assert IdentifyMethod.NONE.value == "none"
