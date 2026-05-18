"""Tests for lib/critical_load_keywords — v1.10.9 safety floor.

The keyword deny-list is the last line of defence against accidentally
factory-resetting a Tuya fridge controller, cycling a CPAP, or
killing the switch that powers HA itself. These tests verify the
matcher is permissive (false positives are cheap) and complete
(every category in the docstring has at least one keyword that
matches a realistic entity_id).
"""
from __future__ import annotations

import pytest

from custom_components.ha_insights.lib.critical_load_keywords import (
    critical_keywords,
    is_critical_load,
)

# Real-world entity_id patterns sampled from community installs +
# common defaults from each integration. The exact string is what
# the user is likely to see in their UI; if our matcher misses
# these, the matcher is broken.
_CRITICAL_CASES = [
    # Medical
    ("switch.cpap_outlet", "CPAP outlet"),
    ("switch.oxygen_concentrator", "Oxygen concentrator"),
    # HA host (self-destruct prevention)
    ("switch.homeassistant_outlet", "Home Assistant outlet"),
    ("switch.ha_box_power", "HA Box"),
    ("switch.hass_pi_5", "Hass Pi 5"),
    ("switch.supervisor_outlet", None),
    # Power infra
    ("switch.network_rack_main", "Network rack"),
    ("switch.modem_outlet", "Modem"),
    ("switch.proxmox_host", None),
    ("switch.raspberry_pi_4b", None),
    ("switch.synology_ds920", None),
    # Refrigeration
    ("switch.kitchen_fridge", "Kitchen fridge"),
    ("switch.garage_freezer", "Garage freezer"),
    ("switch.beer_fridge", None),
    # EV
    ("switch.ev_charger_main", "EV Charger"),
    ("switch.tesla_wall_connector", "Tesla Wall Connector"),
    ("switch.easee_home_charger", None),
    ("switch.zappi_garage", None),
    # Pumps / climate
    ("switch.basement_sump_pump", None),
    ("switch.boiler_pump", None),
    ("switch.well_pump_main", None),
    ("switch.sprinkler_zone_1", None),
    # Animals / plants
    ("switch.aquarium_pump", None),
    ("switch.reptile_heat_lamp", None),
    # Safety / security
    ("switch.cctv_dvr", None),
    ("switch.garage_door_opener", None),
    # User-labelled
    ("switch.critical_load_a", None),
    ("switch.do_not_toggle_office", None),
    ("switch.always_on_router", None),
]


@pytest.mark.parametrize("entity_id,friendly", _CRITICAL_CASES)
def test_realistic_critical_entity_ids_are_refused(
    entity_id: str, friendly: str | None
) -> None:
    """Every entity_id sampled from real installs must match."""
    is_critical, kw = is_critical_load(entity_id, friendly)
    assert is_critical, (
        f"{entity_id} (friendly={friendly}) should match the deny-list "
        "but did not. Either the keyword needs adding, or matching is broken."
    )
    assert kw is not None
    assert kw in critical_keywords()


# Non-critical entities should pass through. False positives waste
# the user's time but are safe; false negatives cause real harm.
# These are entities the user would expect to identify normally.
_SAFE_CASES = [
    # Generic lights — all light domains pass regardless of name
    # (brightness-wiggle doesn't power-cycle).
    ("light.kitchen_fridge_above", "Above-fridge light"),
    ("light.living_room", "Living Room Light"),
    # Generic switches that don't match keywords.
    ("switch.bedroom_lamp", "Bedroom Lamp"),
    ("switch.bathroom_fan", "Bathroom Fan"),
    ("switch.outdoor_lights", "Outdoor Lights"),
    # Media players, sensors — never gated.
    ("media_player.kitchen_speaker", "Kitchen Speaker"),
    ("sensor.kitchen_fridge_temperature", "Fridge Temperature"),
    # Status / diagnostic LEDs even if device name contains a keyword
    # (light domain bypasses the gate — brightness wiggle is safe).
    ("light.ev_charger_status_led", "EV Charger Status LED"),
]


@pytest.mark.parametrize("entity_id,friendly", _SAFE_CASES)
def test_safe_entities_pass_through(
    entity_id: str, friendly: str | None
) -> None:
    is_critical, _ = is_critical_load(entity_id, friendly)
    assert not is_critical, (
        f"{entity_id} should not be gated as critical."
    )


def test_lights_are_never_gated_even_with_critical_keyword() -> None:
    """`light.*` always passes — brightness-wiggle doesn't power-cycle
    so the keyword gate doesn't apply. Strobe fallback is rare and
    each per-call delay is 3s, keeping cycles below all thresholds."""
    is_critical, _ = is_critical_load(
        "light.fridge_interior", "Fridge Interior"
    )
    assert not is_critical


def test_media_players_are_never_gated() -> None:
    """Media players play a chime — no power cycle."""
    is_critical, _ = is_critical_load(
        "media_player.server_room_speaker", "Server Speaker"
    )
    assert not is_critical


def test_friendly_name_alone_can_trigger_match() -> None:
    """Cryptic entity_id but human-readable friendly name catches
    Zigbee/Z-Wave devices that haven't been renamed yet."""
    is_critical, kw = is_critical_load(
        "switch.0x00158d000a1b2c3d", "Garage EV Charger Controller"
    )
    assert is_critical
    # Should match 'ev_charger' substring in friendly name.
    assert kw is not None


def test_case_insensitive_match() -> None:
    """User-typed friendly names use any casing."""
    is_critical, _ = is_critical_load(
        "switch.x", "TESLA Wall Connector"
    )
    assert is_critical


def test_no_dot_entity_id_returns_false() -> None:
    is_critical, kw = is_critical_load("no_dot", None)
    assert not is_critical
    assert kw is None


def test_returns_first_matching_keyword() -> None:
    """When multiple keywords match, we return one of them (set
    iteration order, but at least one MUST match)."""
    is_critical, kw = is_critical_load(
        "switch.aquarium_server_uplink", "Aquarium Server"
    )
    assert is_critical
    assert kw in {"aquarium", "server"}
