"""Tests for lib/environmental_fingerprint.py — v1.14.5a.

Covers:
  - capture_environmental_fingerprint pulls from hass + entity registry
  - fingerprint_to_dict / dict_to_fingerprint round-trip
  - hash_user_id hashes deterministically + handles None
  - Defensive behaviour against broken hass / registry
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest

from custom_components.ha_insights.lib import environmental_fingerprint as ef
from custom_components.ha_insights.lib.environmental_fingerprint import (
    capture_environmental_fingerprint,
    dict_to_fingerprint,
    fingerprint_to_dict,
    hash_user_id,
)
from custom_components.ha_insights.lib.user_verdict_history import (
    EnvironmentalFingerprint,
)

# ---------- hash_user_id --------------------------------------------


def test_hash_user_id_handles_none() -> None:
    assert hash_user_id(None) is None


def test_hash_user_id_handles_empty_string() -> None:
    assert hash_user_id("") is None


def test_hash_user_id_handles_non_string() -> None:
    # Defensive — the WS connection could in principle hand us
    # something unexpected.
    assert hash_user_id(12345) is None  # type: ignore[arg-type]


def test_hash_user_id_is_deterministic() -> None:
    a = hash_user_id("user_abc")
    b = hash_user_id("user_abc")
    assert a == b
    assert isinstance(a, str)
    assert len(a) == 24  # 12-byte blake2b → 24 hex chars


def test_hash_user_id_differs_per_user() -> None:
    a = hash_user_id("user_abc")
    b = hash_user_id("user_xyz")
    assert a != b


def test_hash_user_id_does_not_leak_input() -> None:
    """Confirm the raw user id isn't a substring of the hash."""
    raw = "alice_hass_user_id"
    h = hash_user_id(raw)
    assert h is not None
    assert raw not in h


# ---------- fingerprint_to_dict / dict_to_fingerprint ---------------


def test_dict_round_trip_preserves_data() -> None:
    fp = EnvironmentalFingerprint(
        automation_ids=frozenset({"automation.a", "automation.b"}),
        sensors_per_area={"kitchen": {"motion": 1, "light": 4}},
        active_integrations=frozenset({"mqtt", "zha"}),
    )
    d = fingerprint_to_dict(fp)
    back = dict_to_fingerprint(d)
    assert back == fp


def test_dict_serialization_uses_sorted_lists() -> None:
    """Frozensets become sorted lists — deterministic JSON downstream."""
    fp = EnvironmentalFingerprint(
        automation_ids=frozenset({"automation.b", "automation.a", "automation.c"}),
        sensors_per_area={},
        active_integrations=frozenset({"zha", "mqtt"}),
    )
    d = fingerprint_to_dict(fp)
    assert d["automation_ids"] == ["automation.a", "automation.b", "automation.c"]
    assert d["active_integrations"] == ["mqtt", "zha"]


def test_dict_to_fingerprint_tolerates_missing_keys() -> None:
    """Older verdict rows (pre-v1.14.5) may have empty / partial fingerprints."""
    back = dict_to_fingerprint({})
    assert back == EnvironmentalFingerprint()
    back = dict_to_fingerprint({"automation_ids": ["a"]})
    assert back.automation_ids == frozenset({"a"})
    assert back.sensors_per_area == {}
    assert back.active_integrations == frozenset()


def test_dict_to_fingerprint_drops_bad_types() -> None:
    """Garbage in → empty out, not exceptions."""
    back = dict_to_fingerprint(
        {
            "automation_ids": ["good", 42, None, "also_good"],
            "sensors_per_area": {"kitchen": {"motion": 1}, "bad": "string"},
            "active_integrations": [1, 2, "mqtt"],
        }
    )
    assert back.automation_ids == frozenset({"good", "also_good"})
    assert back.sensors_per_area == {"kitchen": {"motion": 1}}
    assert back.active_integrations == frozenset({"mqtt"})


# ---------- capture_environmental_fingerprint -----------------------


@dataclass
class _FakeState:
    state: str
    attributes: dict[str, Any]


@dataclass
class _FakeRegistryEntry:
    entity_id: str
    platform: str | None = None
    area_id: str | None = None
    device_class: str | None = None
    disabled_by: str | None = None
    hidden_by: str | None = None


@pytest.fixture(autouse=True)
def _patch_entity_registry(monkeypatch):
    """Replace ``_try_entity_registry`` per-test so we never touch
    ``sys.modules``. Tests opt into a fake registry by setting
    ``_REGISTRY_OVERRIDE`` via ``_make_hass``; the default is None
    (capture treats as "no registry" — automations still get captured
    via hass.states, but per-area / integrations stay empty)."""
    monkeypatch.setattr(
        ef, "_try_entity_registry", lambda hass: getattr(hass, "_fake_registry", None)
    )


def _make_hass(
    *,
    automations: dict[str, str] | None = None,  # entity_id → state
    registry_entries: list[_FakeRegistryEntry] | None = None,
    state_overrides: dict[str, _FakeState] | None = None,
) -> MagicMock:
    hass = MagicMock()

    automations = automations or {}
    state_overrides = state_overrides or {}
    registry_entries = registry_entries or []

    def _async_entity_ids(domain: str) -> list[str]:
        if domain == "automation":
            return list(automations)
        return []

    def _states_get(eid: str):
        if eid in automations:
            return _FakeState(state=automations[eid], attributes={})
        if eid in state_overrides:
            return state_overrides[eid]
        return None

    hass.states.async_entity_ids = _async_entity_ids
    hass.states.get = _states_get

    # Attach the fake registry as an attribute on hass; the
    # autouse monkeypatch above wires _try_entity_registry to
    # read it back.
    fake_registry = MagicMock()
    fake_registry.entities = {e.entity_id: e for e in registry_entries}
    hass._fake_registry = fake_registry

    return hass


def test_capture_with_no_hass_returns_empty_fingerprint() -> None:
    """Defensive: a broken hass shouldn't crash the capture path."""
    hass = MagicMock()
    hass.states.async_entity_ids.side_effect = RuntimeError("not ready")
    # No _fake_registry attribute → _try_entity_registry returns None
    # (via the autouse fixture above) → registry-derived fields stay empty.
    fp = capture_environmental_fingerprint(hass)
    assert isinstance(fp, EnvironmentalFingerprint)
    assert fp.automation_ids == frozenset()


def test_capture_records_enabled_automations() -> None:
    hass = _make_hass(
        automations={
            "automation.morning": "on",
            "automation.evening": "off",  # disabled — not counted
            "automation.away_mode": "on",
        },
    )
    fp = capture_environmental_fingerprint(hass)
    assert fp.automation_ids == frozenset(
        {"automation.morning", "automation.away_mode"}
    )


def test_capture_records_per_area_device_classes() -> None:
    hass = _make_hass(
        registry_entries=[
            _FakeRegistryEntry(
                entity_id="binary_sensor.kitchen_motion",
                platform="zha",
                area_id="kitchen",
                device_class="motion",
            ),
            _FakeRegistryEntry(
                entity_id="sensor.kitchen_temp",
                platform="mqtt",
                area_id="kitchen",
                device_class="temperature",
            ),
            _FakeRegistryEntry(
                entity_id="binary_sensor.bedroom_motion",
                platform="zha",
                area_id="bedroom",
                device_class="motion",
            ),
        ],
    )
    fp = capture_environmental_fingerprint(hass)
    assert fp.sensors_per_area == {
        "kitchen": {"motion": 1, "temperature": 1},
        "bedroom": {"motion": 1},
    }


def test_capture_records_active_integrations() -> None:
    hass = _make_hass(
        registry_entries=[
            _FakeRegistryEntry(
                entity_id="sensor.a", platform="zha",
                area_id="kitchen", device_class="temperature",
            ),
            _FakeRegistryEntry(
                entity_id="sensor.b", platform="mqtt",
                area_id="bedroom", device_class="humidity",
            ),
            _FakeRegistryEntry(
                entity_id="binary_sensor.c", platform="zha",
                area_id="lr", device_class="motion",
            ),
        ],
    )
    fp = capture_environmental_fingerprint(hass)
    assert fp.active_integrations == frozenset({"zha", "mqtt"})


def test_capture_excludes_disabled_entities() -> None:
    hass = _make_hass(
        registry_entries=[
            _FakeRegistryEntry(
                entity_id="binary_sensor.kitchen_motion",
                platform="zha",
                area_id="kitchen",
                device_class="motion",
                disabled_by="user",
            ),
            _FakeRegistryEntry(
                entity_id="sensor.kitchen_temp",
                platform="mqtt",
                area_id="kitchen",
                device_class="temperature",
            ),
        ],
    )
    fp = capture_environmental_fingerprint(hass)
    assert fp.sensors_per_area == {"kitchen": {"temperature": 1}}


def test_capture_excludes_hidden_entities() -> None:
    hass = _make_hass(
        registry_entries=[
            _FakeRegistryEntry(
                entity_id="binary_sensor.k",
                platform="zha",
                area_id="kitchen",
                device_class="motion",
                hidden_by="integration",
            ),
        ],
    )
    fp = capture_environmental_fingerprint(hass)
    assert fp.sensors_per_area == {}


def test_capture_skips_non_sensor_domains() -> None:
    """Scenes, groups, scripts etc. don't belong in sensors_per_area —
    they're scaffolding, not real-world sensors. But the integration
    they came from still counts toward active_integrations."""
    hass = _make_hass(
        registry_entries=[
            _FakeRegistryEntry(
                entity_id="scene.movie_time", platform="homeassistant",
                area_id="lr",
            ),
            _FakeRegistryEntry(
                entity_id="group.lights", platform="group", area_id="lr",
            ),
            _FakeRegistryEntry(
                entity_id="light.lamp", platform="zha", area_id="lr",
            ),
        ],
    )
    fp = capture_environmental_fingerprint(hass)
    assert fp.sensors_per_area == {"lr": {"light": 1}}
    # Integrations still tracked
    assert fp.active_integrations == frozenset(
        {"homeassistant", "group", "zha"}
    )


def test_capture_falls_back_to_domain_when_no_device_class() -> None:
    """Lights and switches don't have device_class by default but
    SHOULD count toward the area's "stuff that matters" tally — the
    capture treats domain as the device_class fallback."""
    hass = _make_hass(
        registry_entries=[
            _FakeRegistryEntry(entity_id="light.lamp_1", platform="zha", area_id="kitchen"),
            _FakeRegistryEntry(entity_id="light.lamp_2", platform="zha", area_id="kitchen"),
            _FakeRegistryEntry(entity_id="switch.fan", platform="mqtt", area_id="kitchen"),
        ],
    )
    fp = capture_environmental_fingerprint(hass)
    assert fp.sensors_per_area == {"kitchen": {"light": 2, "switch": 1}}


def test_capture_skips_entities_without_area() -> None:
    """Per-area inventory needs an area. Unassigned entities don't
    contribute — they show up in active_integrations but not
    sensors_per_area."""
    hass = _make_hass(
        registry_entries=[
            _FakeRegistryEntry(
                entity_id="sensor.a", platform="zha",
                area_id=None, device_class="motion",
            ),
            _FakeRegistryEntry(
                entity_id="sensor.b", platform="mqtt",
                area_id="kitchen", device_class="motion",
            ),
        ],
    )
    fp = capture_environmental_fingerprint(hass)
    assert fp.sensors_per_area == {"kitchen": {"motion": 1}}
    assert "zha" in fp.active_integrations
