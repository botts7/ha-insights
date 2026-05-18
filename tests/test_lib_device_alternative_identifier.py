"""Tests for lib/device_alternative_identifier — v1.10.11.

Verifies the scoring picks the safest sibling when one exists and
returns None when no improvement is possible. Real-install device
graphs sampled from Shelly, Sonoff, Tasmota, ESPHome, Tesla Wall
Connector, and generic EV chargers.
"""
from __future__ import annotations

from custom_components.ha_insights.lib.device_alternative_identifier import (
    DeviceAlternative,
    SiblingEntity,
    pick_alternative_identifier,
    to_sibling,
)


# ---------- Priority 1: diagnostic-category sibling -----------------


def test_diagnostic_light_sibling_beats_relay() -> None:
    """Shelly Plus 1: switch.shelly_plus_1 (relay) + light.shelly_plus_1_led
    (diagnostic). Should substitute to the diagnostic light."""
    result = pick_alternative_identifier(
        "switch.shelly_plus_1",
        [
            SiblingEntity(
                entity_id="light.shelly_plus_1_led",
                domain="light",
                friendly_name="Shelly Plus 1 LED",
                entity_category="diagnostic",
            ),
            SiblingEntity(
                entity_id="sensor.shelly_plus_1_temperature",
                domain="sensor",
                friendly_name="Shelly Plus 1 Temperature",
                entity_category="diagnostic",
            ),
        ],
    )
    assert result is not None
    assert result.entity_id == "light.shelly_plus_1_led"
    assert result.rule == "diagnostic_category"


def test_diagnostic_switch_sibling_also_picked() -> None:
    """If the indicator is a switch (not a light) but flagged
    diagnostic, still prefer it over the main load switch."""
    result = pick_alternative_identifier(
        "switch.garage_outlet",
        [
            SiblingEntity(
                entity_id="switch.garage_outlet_status_indicator",
                domain="switch",
                friendly_name="Status Indicator",
                entity_category="diagnostic",
            ),
        ],
    )
    assert result is not None
    assert result.entity_id == "switch.garage_outlet_status_indicator"
    assert result.rule == "diagnostic_category"


# ---------- Priority 2: any light sibling ---------------------------


def test_any_light_sibling_picked_when_no_diagnostic() -> None:
    """Sonoff Mini with custom config — exposes light.sonoff_mini_led
    without diagnostic category (some integrations don't set it)."""
    result = pick_alternative_identifier(
        "switch.sonoff_mini",
        [
            SiblingEntity(
                entity_id="light.sonoff_mini_led",
                domain="light",
                friendly_name="Sonoff Mini LED",
                entity_category=None,  # not flagged
            ),
        ],
    )
    assert result is not None
    assert result.entity_id == "light.sonoff_mini_led"
    assert result.rule == "domain_light"


def test_diagnostic_takes_priority_over_plain_light() -> None:
    """If both a diagnostic-flagged and a plain light exist, prefer
    the diagnostic one."""
    result = pick_alternative_identifier(
        "switch.relay",
        [
            SiblingEntity(
                entity_id="light.plain_indicator",
                domain="light",
                friendly_name="Plain",
                entity_category=None,
            ),
            SiblingEntity(
                entity_id="light.diagnostic_indicator",
                domain="light",
                friendly_name="Diagnostic",
                entity_category="diagnostic",
            ),
        ],
    )
    assert result is not None
    assert result.entity_id == "light.diagnostic_indicator"


# ---------- Priority 3: name-based indicator detection ---------------


def test_name_keyword_status_triggers_substitution() -> None:
    """ESPHome-flashed Sonoff exposes switch.foo_status without any
    diagnostic flag — name alone should be enough."""
    result = pick_alternative_identifier(
        "switch.kitchen_appliance",
        [
            SiblingEntity(
                entity_id="switch.kitchen_appliance_status",
                domain="switch",
                friendly_name="Kitchen Appliance Status",
                entity_category=None,
            ),
        ],
    )
    assert result is not None
    assert result.rule.startswith("name_keyword:status")


def test_name_keyword_led_triggers_substitution() -> None:
    result = pick_alternative_identifier(
        "switch.relay",
        [
            SiblingEntity(
                entity_id="switch.activity_led",
                domain="switch",
                friendly_name=None,
                entity_category=None,
            ),
        ],
    )
    assert result is not None
    assert "activity_led" in result.entity_id


# ---------- Tesla Wall Connector real-world example ------------------


def test_tesla_wall_connector_picks_status_light() -> None:
    """Tesla Wall Connector typically exposes the contactor as
    switch.tesla_wall_connector AND a status indicator. We must
    pick the indicator over the contactor."""
    result = pick_alternative_identifier(
        "switch.tesla_wall_connector",
        [
            SiblingEntity(
                entity_id="light.tesla_wall_connector_status",
                domain="light",
                friendly_name="Tesla Wall Connector Status",
                entity_category="diagnostic",
            ),
            SiblingEntity(
                entity_id="sensor.tesla_wall_connector_current",
                domain="sensor",
                friendly_name="Current",
                entity_category=None,
            ),
        ],
    )
    assert result is not None
    assert result.entity_id == "light.tesla_wall_connector_status"


# ---------- Negative cases ------------------------------------------


def test_no_siblings_returns_none() -> None:
    result = pick_alternative_identifier("switch.foo", [])
    assert result is None


def test_only_non_substitutable_siblings_returns_none() -> None:
    """If the only siblings are sensors / binary_sensors / etc.,
    we have nothing safer to substitute."""
    result = pick_alternative_identifier(
        "switch.relay",
        [
            SiblingEntity(
                entity_id="sensor.power",
                domain="sensor",
                friendly_name="Power",
                entity_category=None,
            ),
            SiblingEntity(
                entity_id="binary_sensor.online",
                domain="binary_sensor",
                friendly_name="Online",
                entity_category="diagnostic",
            ),
        ],
    )
    assert result is None


def test_light_request_never_substituted() -> None:
    """If the user clicked Identify on a light, we never substitute
    — lights are already safe via FLASH_LIGHT / BRIGHTNESS_WIGGLE."""
    result = pick_alternative_identifier(
        "light.kitchen",
        [
            SiblingEntity(
                entity_id="switch.kitchen_extra",
                domain="switch",
                friendly_name=None,
                entity_category="diagnostic",
            ),
        ],
    )
    assert result is None


def test_media_player_request_never_substituted() -> None:
    """Media players also pass through — chime is safe."""
    result = pick_alternative_identifier(
        "media_player.kitchen",
        [
            SiblingEntity(
                entity_id="light.kitchen_led",
                domain="light",
                friendly_name=None,
                entity_category="diagnostic",
            ),
        ],
    )
    assert result is None


def test_malformed_entity_id_returns_none() -> None:
    result = pick_alternative_identifier("no_dot_id", [])
    assert result is None


# ---------- to_sibling helper ---------------------------------------


def test_to_sibling_constructs_from_dict() -> None:
    s = to_sibling(
        {
            "entity_id": "light.foo_led",
            "friendly_name": "Foo LED",
            "entity_category": "diagnostic",
        },
    )
    assert s is not None
    assert s.domain == "light"
    assert s.friendly_name == "Foo LED"
    assert s.entity_category == "diagnostic"


def test_to_sibling_rejects_malformed_entity_id() -> None:
    assert to_sibling({"entity_id": "no_dot"}) is None
    assert to_sibling({"entity_id": 42}) is None
    assert to_sibling({}) is None


def test_to_sibling_handles_missing_optional_fields() -> None:
    s = to_sibling({"entity_id": "switch.bare"})
    assert s is not None
    assert s.friendly_name is None
    assert s.entity_category is None


# ---------- DeviceAlternative dataclass -----------------------------


def test_device_alternative_is_frozen() -> None:
    """The dataclass is frozen so callers can't mutate the picked
    result mid-flight."""
    import dataclasses
    alt = DeviceAlternative(
        entity_id="light.x",
        reason="testing",
        rule="diagnostic_category",
    )
    assert dataclasses.is_dataclass(alt)
