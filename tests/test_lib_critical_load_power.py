"""Tests for lib/critical_load_power — v1.10.13 power-consumption gate.

We mock the HA registry + state machine because building a real
HomeAssistant fixture for these tiny lookups is more code than the
function under test. The lib's contract with HA is small:

  - `entity_registry.async_get(hass)` returns a registry with
    `.async_get(entity_id) -> RegistryEntry | None` and
    `.entities.values() -> Iterable[RegistryEntry]`
  - Each `RegistryEntry` has `.entity_id` and `.device_id`
  - `hass.states.get(entity_id) -> State | None` with
    `.state` and `.attributes`

A minimal Fake* hierarchy below satisfies those contracts.
"""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest


@dataclass
class _FakeEntry:
    entity_id: str
    device_id: str | None


@dataclass
class _FakeState:
    state: str
    attributes: dict[str, Any]


class _FakeRegistry:
    def __init__(self, entries: list[_FakeEntry]) -> None:
        self._by_eid = {e.entity_id: e for e in entries}
        self.entities = MagicMock()
        self.entities.values = lambda: list(self._by_eid.values())

    def async_get(self, entity_id: str) -> _FakeEntry | None:
        return self._by_eid.get(entity_id)


class _FakeStates:
    def __init__(self, states: dict[str, _FakeState]) -> None:
        self._d = states

    def get(self, entity_id: str) -> _FakeState | None:
        return self._d.get(entity_id)


@dataclass
class _FakeHass:
    registry: _FakeRegistry
    states: _FakeStates


@pytest.fixture(autouse=True)
def _patch_entity_registry(monkeypatch):
    """Inject a fake `homeassistant.helpers.entity_registry` module
    so `async_get(hass)` returns our test fixture's registry."""
    fake_module = types.ModuleType("homeassistant.helpers.entity_registry")
    fake_module.async_get = lambda hass: hass.registry
    monkeypatch.setitem(
        sys.modules, "homeassistant.helpers.entity_registry", fake_module,
    )
    yield


from custom_components.ha_insights.lib.critical_load_power import (  # noqa: E402
    DEFAULT_POWER_THRESHOLD_W,
    find_linked_power_sensor,
    is_critical_by_power,
)

# ---------- find_linked_power_sensor ---------------------------------


def test_finds_sensor_with_device_class_power() -> None:
    """device_class=power is the strongest signal — should win even
    when a name-match also exists."""
    hass = _FakeHass(
        registry=_FakeRegistry([
            _FakeEntry("switch.fridge_outlet", "dev_a"),
            _FakeEntry("sensor.fridge_outlet_consumption", "dev_a"),  # device_class match
            _FakeEntry("sensor.fridge_outlet_power_estimate", "dev_a"),  # name match
        ]),
        states=_FakeStates({
            "switch.fridge_outlet": _FakeState("on", {}),
            "sensor.fridge_outlet_consumption": _FakeState(
                "150.0", {"device_class": "power", "unit_of_measurement": "W"},
            ),
            "sensor.fridge_outlet_power_estimate": _FakeState("0", {}),
        }),
    )
    sensor = find_linked_power_sensor(hass, "switch.fridge_outlet")
    assert sensor == "sensor.fridge_outlet_consumption"


def test_falls_back_to_name_suffix_match() -> None:
    hass = _FakeHass(
        registry=_FakeRegistry([
            _FakeEntry("switch.outlet", "dev_b"),
            _FakeEntry("sensor.outlet_power", "dev_b"),
            _FakeEntry("sensor.outlet_voltage", "dev_b"),
        ]),
        states=_FakeStates({
            "switch.outlet": _FakeState("on", {}),
            "sensor.outlet_power": _FakeState("75.0", {"unit_of_measurement": "W"}),
            "sensor.outlet_voltage": _FakeState("230", {}),
        }),
    )
    sensor = find_linked_power_sensor(hass, "switch.outlet")
    assert sensor == "sensor.outlet_power"


def test_falls_back_to_loose_power_substring() -> None:
    """If no suffix match and no device_class, accept any sensor
    with 'power' in the entity_id."""
    hass = _FakeHass(
        registry=_FakeRegistry([
            _FakeEntry("switch.relay", "dev_c"),
            _FakeEntry("sensor.relay_power_factor", "dev_c"),
        ]),
        states=_FakeStates({
            "switch.relay": _FakeState("on", {}),
            "sensor.relay_power_factor": _FakeState("0.95", {}),
        }),
    )
    sensor = find_linked_power_sensor(hass, "switch.relay")
    assert sensor == "sensor.relay_power_factor"


def test_returns_none_when_no_power_sibling() -> None:
    hass = _FakeHass(
        registry=_FakeRegistry([
            _FakeEntry("switch.simple", "dev_d"),
            _FakeEntry("sensor.simple_temperature", "dev_d"),
        ]),
        states=_FakeStates({
            "switch.simple": _FakeState("on", {}),
            "sensor.simple_temperature": _FakeState("21.0", {}),
        }),
    )
    assert find_linked_power_sensor(hass, "switch.simple") is None


def test_returns_none_when_no_device_id() -> None:
    """Template entities and standalone helpers have no device_id —
    we have no way to find related sensors."""
    hass = _FakeHass(
        registry=_FakeRegistry([
            _FakeEntry("switch.template", None),
        ]),
        states=_FakeStates({}),
    )
    assert find_linked_power_sensor(hass, "switch.template") is None


def test_returns_none_when_entity_not_in_registry() -> None:
    hass = _FakeHass(
        registry=_FakeRegistry([]),
        states=_FakeStates({}),
    )
    assert find_linked_power_sensor(hass, "switch.unknown") is None


def test_malformed_entity_id_returns_none() -> None:
    hass = _FakeHass(
        registry=_FakeRegistry([]),
        states=_FakeStates({}),
    )
    assert find_linked_power_sensor(hass, "no_dot") is None


def test_excludes_original_entity_even_if_named_power() -> None:
    """The original entity is excluded from the sibling search
    even if its own name matches the heuristic."""
    hass = _FakeHass(
        registry=_FakeRegistry([
            _FakeEntry("sensor.my_power", "dev_e"),  # original entity
            _FakeEntry("sensor.my_temperature", "dev_e"),
        ]),
        states=_FakeStates({
            "sensor.my_power": _FakeState("100", {"unit_of_measurement": "W"}),
            "sensor.my_temperature": _FakeState("21.0", {}),
        }),
    )
    assert find_linked_power_sensor(hass, "sensor.my_power") is None


# ---------- is_critical_by_power -------------------------------------


def test_critical_when_above_threshold_in_watts() -> None:
    hass = _FakeHass(
        registry=_FakeRegistry([
            _FakeEntry("switch.unmarked_fridge", "dev_f"),
            _FakeEntry("sensor.unmarked_fridge_power", "dev_f"),
        ]),
        states=_FakeStates({
            "switch.unmarked_fridge": _FakeState("on", {}),
            "sensor.unmarked_fridge_power": _FakeState(
                "180.0", {"device_class": "power", "unit_of_measurement": "W"},
            ),
        }),
    )
    crit, watts, sensor = is_critical_by_power(hass, "switch.unmarked_fridge")
    assert crit is True
    assert watts == 180.0
    assert sensor == "sensor.unmarked_fridge_power"


def test_critical_when_above_threshold_in_kw() -> None:
    """EV chargers report in kW — must scale to W before comparing."""
    hass = _FakeHass(
        registry=_FakeRegistry([
            _FakeEntry("switch.ev_outlet_5", "dev_g"),
            _FakeEntry("sensor.ev_outlet_5_power", "dev_g"),
        ]),
        states=_FakeStates({
            "switch.ev_outlet_5": _FakeState("on", {}),
            "sensor.ev_outlet_5_power": _FakeState(
                "7.4", {"device_class": "power", "unit_of_measurement": "kW"},
            ),
        }),
    )
    crit, watts, _ = is_critical_by_power(hass, "switch.ev_outlet_5")
    assert crit is True
    assert watts == 7400.0


def test_not_critical_when_below_threshold() -> None:
    """A 5 W IoT board — safe to cycle."""
    hass = _FakeHass(
        registry=_FakeRegistry([
            _FakeEntry("switch.iot_board", "dev_h"),
            _FakeEntry("sensor.iot_board_power", "dev_h"),
        ]),
        states=_FakeStates({
            "switch.iot_board": _FakeState("on", {}),
            "sensor.iot_board_power": _FakeState(
                "5.0", {"device_class": "power", "unit_of_measurement": "W"},
            ),
        }),
    )
    crit, watts, sensor = is_critical_by_power(hass, "switch.iot_board")
    assert crit is False
    assert watts == 5.0
    assert sensor == "sensor.iot_board_power"


def test_custom_threshold_respected() -> None:
    """Caller may pass a stricter threshold for noisy installs."""
    hass = _FakeHass(
        registry=_FakeRegistry([
            _FakeEntry("switch.outlet", "dev_i"),
            _FakeEntry("sensor.outlet_power", "dev_i"),
        ]),
        states=_FakeStates({
            "switch.outlet": _FakeState("on", {}),
            "sensor.outlet_power": _FakeState(
                "30.0", {"device_class": "power", "unit_of_measurement": "W"},
            ),
        }),
    )
    # Default 50 W → not critical at 30 W
    crit_default, _, _ = is_critical_by_power(hass, "switch.outlet")
    assert crit_default is False
    # Stricter 20 W → critical
    crit_strict, _, _ = is_critical_by_power(
        hass, "switch.outlet", threshold_w=20.0,
    )
    assert crit_strict is True


def test_unparseable_state_treated_as_no_info() -> None:
    """`unknown`, `unavailable`, or `""` mean the sensor isn't
    reporting. We don't refuse on missing data — would block
    legit identify on devices with broken sensors."""
    for bad_state in ["unknown", "unavailable", "", "none"]:
        hass = _FakeHass(
            registry=_FakeRegistry([
                _FakeEntry("switch.x", "dev_j"),
                _FakeEntry("sensor.x_power", "dev_j"),
            ]),
            states=_FakeStates({
                "switch.x": _FakeState("on", {}),
                "sensor.x_power": _FakeState(
                    bad_state, {"unit_of_measurement": "W"},
                ),
            }),
        )
        crit, watts, _ = is_critical_by_power(hass, "switch.x")
        assert crit is False, f"bad_state={bad_state!r} should not block"
        assert watts is None


def test_unknown_unit_treated_as_no_info() -> None:
    """If the unit isn't W / kW / mW we can't compare. Don't guess."""
    hass = _FakeHass(
        registry=_FakeRegistry([
            _FakeEntry("switch.x", "dev_k"),
            _FakeEntry("sensor.x_power", "dev_k"),
        ]),
        states=_FakeStates({
            "switch.x": _FakeState("on", {}),
            "sensor.x_power": _FakeState(
                "9999",
                {"device_class": "power", "unit_of_measurement": "lumens"},
            ),
        }),
    )
    crit, watts, _ = is_critical_by_power(hass, "switch.x")
    assert crit is False
    assert watts is None


def test_no_unit_assumed_watts() -> None:
    """Some integrations omit unit_of_measurement; HA's default
    for power is W."""
    hass = _FakeHass(
        registry=_FakeRegistry([
            _FakeEntry("switch.x", "dev_l"),
            _FakeEntry("sensor.x_power", "dev_l"),
        ]),
        states=_FakeStates({
            "switch.x": _FakeState("on", {}),
            "sensor.x_power": _FakeState("120.0", {}),  # no unit
        }),
    )
    crit, watts, _ = is_critical_by_power(hass, "switch.x")
    assert crit is True
    assert watts == 120.0


def test_no_power_sensor_returns_false() -> None:
    """No power info available → caller should fall through. Doesn't
    refuse on absence of data."""
    hass = _FakeHass(
        registry=_FakeRegistry([
            _FakeEntry("switch.x", "dev_m"),
        ]),
        states=_FakeStates({"switch.x": _FakeState("on", {})}),
    )
    crit, watts, sensor = is_critical_by_power(hass, "switch.x")
    assert crit is False
    assert watts is None
    assert sensor is None


def test_threshold_boundary_inclusive() -> None:
    """Exactly the threshold value counts as critical (>= comparison).
    Boundary: 50.0 W default threshold."""
    hass = _FakeHass(
        registry=_FakeRegistry([
            _FakeEntry("switch.x", "dev_n"),
            _FakeEntry("sensor.x_power", "dev_n"),
        ]),
        states=_FakeStates({
            "switch.x": _FakeState("on", {}),
            "sensor.x_power": _FakeState(
                "50.0", {"unit_of_measurement": "W"},
            ),
        }),
    )
    crit, watts, _ = is_critical_by_power(hass, "switch.x")
    assert crit is True
    assert watts == 50.0


def test_constants_stable() -> None:
    """The default threshold is part of the public API — drift here
    would change the deny semantics across releases."""
    assert DEFAULT_POWER_THRESHOLD_W == 50.0
