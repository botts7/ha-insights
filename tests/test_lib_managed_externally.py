"""Tests for lib/managed_externally — user-marked device suppression."""
from __future__ import annotations

from custom_components.ha_insights.lib.managed_externally import (
    collect_referenced_entities,
    filter_insights,
    is_suppressed,
)


# ---------- collect_referenced_entities ----------------------------------


def test_collect_handles_empty() -> None:
    assert collect_referenced_entities({}, {}) == set()


def test_collect_from_fingerprint_entity_id() -> None:
    fp = {"kind": "manual_habit", "entity_id": "light.kitchen"}
    assert collect_referenced_entities(fp, {}) == {"light.kitchen"}


def test_collect_from_cooccurrence_fingerprint() -> None:
    fp = {
        "kind": "cooccurrence",
        "leader_entity_id": "binary_sensor.door",
        "follower_entity_id": "light.porch",
        "leader_state": "on",
        "follower_state": "on",
    }
    assert collect_referenced_entities(fp, {}) == {
        "binary_sensor.door",
        "light.porch",
    }


def test_collect_from_button_press_fingerprint() -> None:
    fp = {
        "kind": "button_press_habit",
        "event_entity_id": "event.kitchen_dimmer",
        "consequent_entity_id": "light.kitchen",
        "event_type": "single_press",
    }
    assert collect_referenced_entities(fp, {}) == {
        "event.kitchen_dimmer",
        "light.kitchen",
    }


def test_collect_from_payload_trigger_and_action() -> None:
    payload = {
        "alias": "Foo",
        "trigger": [{"platform": "state", "entity_id": "binary_sensor.x"}],
        "action": [
            {
                "service": "light.turn_on",
                "target": {"entity_id": "light.y"},
            }
        ],
    }
    assert collect_referenced_entities({}, payload) == {
        "binary_sensor.x",
        "light.y",
    }


def test_collect_handles_list_form_entity_id() -> None:
    payload = {
        "trigger": [
            {
                "platform": "state",
                "entity_id": ["light.a", "light.b"],
            }
        ],
    }
    assert collect_referenced_entities({}, payload) == {"light.a", "light.b"}


def test_collect_from_audit_packet_aggregates() -> None:
    payload = {
        "target_entities": ["light.x", "switch.y"],
        "trigger_entities": ["binary_sensor.z"],
        "alias": "ignored",
    }
    assert collect_referenced_entities({}, payload) == {
        "light.x",
        "switch.y",
        "binary_sensor.z",
    }


def test_collect_ignores_service_strings_in_non_entity_fields() -> None:
    """`service: light.turn_on` looks dot-namespaced but isn't an entity."""
    payload = {
        "action": [
            {"service": "light.turn_on", "target": {"entity_id": "light.x"}}
        ],
    }
    found = collect_referenced_entities({}, payload)
    assert found == {"light.x"}
    assert "light.turn_on" not in found


def test_collect_ignores_random_text_with_dots() -> None:
    payload = {"description": "Switches off light.foo daily"}
    assert collect_referenced_entities({}, payload) == set()


def test_collect_handles_deeply_nested_payload() -> None:
    payload = {
        "_audit": {
            "observations": [{"text": "x"}],
            "fix_summaries": ["y"],
            "target_entities": ["light.deep"],
        },
        "_coupling": {
            "tier": "TIGHT",
            "median_lag_ms": 180,
        },
    }
    assert collect_referenced_entities({}, payload) == {"light.deep"}


# ---------- is_suppressed -------------------------------------------------


def test_suppressed_empty_managed_set_returns_false() -> None:
    assert (
        is_suppressed(
            fingerprint={"entity_id": "light.x"},
            payload={},
            managed_devices=frozenset(),
            device_of={"light.x": "dev_a"},
        )
        is False
    )


def test_suppressed_when_referenced_entity_belongs_to_managed_device() -> None:
    assert is_suppressed(
        fingerprint={"entity_id": "light.x"},
        payload={},
        managed_devices=frozenset({"dev_a"}),
        device_of={"light.x": "dev_a"},
    )


def test_suppressed_false_when_device_not_in_managed_set() -> None:
    assert (
        is_suppressed(
            fingerprint={"entity_id": "light.x"},
            payload={},
            managed_devices=frozenset({"dev_b"}),
            device_of={"light.x": "dev_a"},
        )
        is False
    )


def test_suppressed_false_when_entity_has_no_device() -> None:
    """Template sensors and helpers typically lack a device_id; they
    can never be suppressed via the device-managed flag."""
    assert (
        is_suppressed(
            fingerprint={"entity_id": "sensor.template_x"},
            payload={},
            managed_devices=frozenset({"dev_a"}),
            device_of={"sensor.template_x": None},
        )
        is False
    )


def test_suppressed_true_when_any_of_multiple_entities_is_managed() -> None:
    """Cooccurrence pairs reference two entities; either being managed
    should suppress the pair insight."""
    assert is_suppressed(
        fingerprint={
            "leader_entity_id": "binary_sensor.door",
            "follower_entity_id": "light.porch",
        },
        payload={},
        managed_devices=frozenset({"dev_porch"}),
        device_of={
            "binary_sensor.door": "dev_door",
            "light.porch": "dev_porch",
        },
    )


def test_suppressed_handles_unknown_entity_gracefully() -> None:
    """An entity whose device mapping is missing falls through cleanly."""
    assert (
        is_suppressed(
            fingerprint={"entity_id": "light.unknown"},
            payload={},
            managed_devices=frozenset({"dev_a"}),
            device_of={},  # mapping missing
        )
        is False
    )


# ---------- filter_insights ----------------------------------------------


class _FakeInsight:
    def __init__(self, fp: dict, payload: dict) -> None:
        self.fingerprint = fp
        self.payload = payload


def test_filter_empty_managed_keeps_everything() -> None:
    insights = [
        _FakeInsight({"entity_id": "light.x"}, {}),
        _FakeInsight({"entity_id": "light.y"}, {}),
    ]
    kept, suppressed = filter_insights(
        insights, frozenset(), {"light.x": "dev_a", "light.y": "dev_b"}
    )
    assert len(kept) == 2
    assert suppressed == []


def test_filter_separates_kept_and_suppressed() -> None:
    insights = [
        _FakeInsight({"entity_id": "light.x"}, {}),
        _FakeInsight({"entity_id": "light.y"}, {}),
        _FakeInsight({"entity_id": "light.z"}, {}),
    ]
    kept, suppressed = filter_insights(
        insights,
        frozenset({"dev_managed"}),
        {
            "light.x": "dev_a",
            "light.y": "dev_managed",
            "light.z": "dev_b",
        },
    )
    assert len(kept) == 2
    assert len(suppressed) == 1
    assert suppressed[0].fingerprint["entity_id"] == "light.y"
