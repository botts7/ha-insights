"""Tests for lib/vendor_identify_strategy — v1.10.12.

Verifies the mapping between integration platforms and vendor-native
identify primitives. Each strategy must produce a service call that
doesn't power-cycle the device.
"""

from __future__ import annotations

from custom_components.ha_insights.lib.vendor_identify_strategy import (
    VendorIdentifyStrategy,
    vendor_identify_strategy_for,
)

# ---------- ZHA: Zigbee Identify cluster ---------------------------


def test_zha_light_uses_identify_cluster() -> None:
    s = vendor_identify_strategy_for("light.zigbee_bulb", "zha")
    assert s is not None
    assert s.method_label == "zigbee_identify_cluster"
    assert s.platform == "zha"
    call = s.service_calls[0]
    assert call["domain"] == "zha"
    assert call["service"] == "issue_zigbee_cluster_command"
    assert call["data"]["cluster_id"] == 3
    assert call["data"]["command"] == 0


def test_zha_switch_also_supported() -> None:
    """Some Zigbee switches implement Identify cluster too."""
    s = vendor_identify_strategy_for("switch.zigbee_relay", "zha")
    assert s is not None
    assert s.method_label == "zigbee_identify_cluster"


def test_zha_irrelevant_domain_returns_none() -> None:
    s = vendor_identify_strategy_for("media_player.zha_speaker", "zha")
    assert s is None


# ---------- Z-Wave JS: Indicator CC ---------------------------------


def test_zwave_js_uses_indicator_cc() -> None:
    s = vendor_identify_strategy_for("switch.zwave_relay", "zwave_js")
    assert s is not None
    assert s.method_label == "zwave_indicator_cc"
    call = s.service_calls[0]
    assert call["domain"] == "zwave_js"
    assert call["service"] == "invoke_cc_api"
    assert call["data"]["command_class"] == 135  # 0x87


def test_zwave_js_light_also_supported() -> None:
    s = vendor_identify_strategy_for("light.zwave_dimmer", "zwave_js")
    assert s is not None
    assert s.method_label == "zwave_indicator_cc"


# ---------- LIFX: native pulse --------------------------------------


def test_lifx_uses_effect_pulse() -> None:
    s = vendor_identify_strategy_for("light.lifx_bulb", "lifx")
    assert s is not None
    assert s.method_label == "lifx_pulse"
    call = s.service_calls[0]
    assert call["domain"] == "lifx"
    assert call["service"] == "effect_pulse"
    assert call["data"]["mode"] == "blink"
    # Critically: power_on=False so we don't toggle an off bulb.
    assert call["data"]["power_on"] is False


def test_lifx_switch_returns_none() -> None:
    """LIFX only makes lights; the platform mapping is light-only."""
    s = vendor_identify_strategy_for("switch.lifx_thing", "lifx")
    assert s is None


# ---------- Yeelight: start_flow ------------------------------------


def test_yeelight_uses_start_flow() -> None:
    s = vendor_identify_strategy_for("light.yeelight_bulb", "yeelight")
    assert s is not None
    assert s.method_label == "yeelight_flow"
    call = s.service_calls[0]
    assert call["domain"] == "yeelight"
    assert call["service"] == "start_flow"
    # action=recover so the bulb returns to its starting state.
    assert call["data"]["action"] == "recover"


# ---------- Zigbee2MQTT: effect attribute ---------------------------


def test_z2m_uses_effect_blink() -> None:
    s = vendor_identify_strategy_for("light.z2m_bulb", "mqtt")
    assert s is not None
    assert s.method_label == "zigbee2mqtt_effect_blink"
    call = s.service_calls[0]
    assert call["domain"] == "light"
    assert call["service"] == "turn_on"
    assert call["data"]["effect"] == "blink"


def test_mqtt_switch_returns_none() -> None:
    """We only route MQTT lights — switches may be custom devices
    that ignore effect attributes."""
    s = vendor_identify_strategy_for("switch.mqtt_relay", "mqtt")
    assert s is None


# ---------- Unmapped platforms --------------------------------------


def test_hue_platform_returns_none() -> None:
    """Hue passes through to FLASH_LIGHT via the standard pipeline
    — the bridge handles flash natively. No vendor mapping needed."""
    s = vendor_identify_strategy_for("light.hue_bulb", "hue")
    assert s is None


def test_esphome_returns_none() -> None:
    """ESPHome lights use the standard flash service if firmware
    exposes it."""
    s = vendor_identify_strategy_for("light.esphome_thing", "esphome")
    assert s is None


def test_unknown_platform_returns_none() -> None:
    s = vendor_identify_strategy_for("light.foo", "custom_widget")
    assert s is None


# ---------- Defensive inputs ----------------------------------------


def test_none_platform_returns_none() -> None:
    """Entities without a registry entry (template entities, etc.)
    pass through. None platform → no vendor mapping."""
    s = vendor_identify_strategy_for("light.template_one", None)
    assert s is None


def test_malformed_entity_id_returns_none() -> None:
    s = vendor_identify_strategy_for("no_dot_id", "zha")
    assert s is None


def test_empty_platform_returns_none() -> None:
    s = vendor_identify_strategy_for("light.foo", "")
    assert s is None


# ---------- Output shape ---------------------------------------------


def test_strategy_is_frozen_dataclass() -> None:
    import dataclasses
    s = vendor_identify_strategy_for("light.zha", "zha")
    assert s is not None
    assert dataclasses.is_dataclass(s)
    assert isinstance(s, VendorIdentifyStrategy)


def test_descriptions_are_human_readable() -> None:
    """Each description shown in the card must be plain English,
    no service-call syntax."""
    for platform, eid in [
        ("zha", "light.zha"),
        ("zwave_js", "switch.zwave"),
        ("lifx", "light.lifx"),
        ("yeelight", "light.yeelight"),
        ("mqtt", "light.z2m"),
    ]:
        s = vendor_identify_strategy_for(eid, platform)
        assert s is not None
        assert "{" not in s.description
        assert "service" not in s.description.lower()
        assert len(s.description) < 100
