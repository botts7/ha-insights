"""Pure-Python unit tests for lib/automation_yaml.py.

Covers the YAML-shape transforms that drive Suggested-Additions'
deterministic apply path. Tests the three field shapes (target.entity_id,
top-level entity_id, data.entity_id), scalar-to-list promotion, dedupe,
cross-domain action-item creation, and unhandled-domain handoff.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from custom_components.ha_insights.lib.automation_yaml import (
    append_entities_to_action_block,
)


def test_target_entity_id_scalar_to_list():
    """Existing target.entity_id is a scalar — promote to list when adding."""
    payload = {
        "alias": "morning",
        "action": [
            {
                "service": "light.turn_on",
                "target": {"entity_id": "light.kitchen_main"},
            }
        ],
    }
    result, unhandled = append_entities_to_action_block(
        payload, ["light.kitchen_under_cabinet"]
    )
    assert unhandled == []
    assert result["action"][0]["target"]["entity_id"] == [
        "light.kitchen_main",
        "light.kitchen_under_cabinet",
    ]


def test_target_entity_id_list_append():
    """Existing list — append, dedupe, preserve order."""
    payload = {
        "alias": "x",
        "action": [
            {
                "service": "light.turn_on",
                "target": {"entity_id": ["light.a", "light.b"]},
            }
        ],
    }
    result, unhandled = append_entities_to_action_block(
        payload, ["light.c", "light.b"]
    )
    assert unhandled == []
    assert result["action"][0]["target"]["entity_id"] == [
        "light.a",
        "light.b",
        "light.c",
    ]


def test_top_level_entity_id():
    payload = {
        "alias": "x",
        "action": [{"service": "light.turn_on", "entity_id": "light.a"}],
    }
    result, _ = append_entities_to_action_block(payload, ["light.b"])
    assert result["action"][0]["entity_id"] == ["light.a", "light.b"]


def test_data_entity_id():
    payload = {
        "alias": "x",
        "action": [
            {"service": "light.turn_on", "data": {"entity_id": "light.a"}},
        ],
    }
    result, _ = append_entities_to_action_block(payload, ["light.b"])
    assert result["action"][0]["data"]["entity_id"] == ["light.a", "light.b"]


def test_creates_target_when_action_has_none():
    payload = {
        "alias": "x",
        "action": [{"service": "light.turn_on"}],
    }
    result, _ = append_entities_to_action_block(payload, ["light.b"])
    assert result["action"][0]["target"] == {"entity_id": "light.b"}


def test_cross_domain_creates_new_action_for_known_turn_on_domain():
    """Existing action is light.turn_on, new entity is switch.* —
    create a new switch.turn_on action."""
    payload = {
        "alias": "x",
        "action": [
            {"service": "light.turn_on", "target": {"entity_id": "light.a"}},
        ],
    }
    result, unhandled = append_entities_to_action_block(payload, ["switch.b"])
    assert unhandled == []
    assert len(result["action"]) == 2
    assert result["action"][1] == {
        "service": "switch.turn_on",
        "target": {"entity_id": "switch.b"},
    }


def test_cross_domain_unknown_domain_returned_as_unhandled():
    payload = {
        "alias": "x",
        "action": [
            {"service": "light.turn_on", "target": {"entity_id": "light.a"}},
        ],
    }
    result, unhandled = append_entities_to_action_block(
        payload, ["climate.thermostat"]
    )
    assert "climate.thermostat" in unhandled
    assert len(result["action"]) == 1


def test_multiple_same_domain_added_in_one_action():
    payload = {
        "alias": "x",
        "action": [
            {"service": "light.turn_on", "target": {"entity_id": "light.a"}},
        ],
    }
    result, _ = append_entities_to_action_block(
        payload, ["light.b", "light.c", "light.d"]
    )
    assert len(result["action"]) == 1
    assert result["action"][0]["target"]["entity_id"] == [
        "light.a", "light.b", "light.c", "light.d"
    ]


def test_multiple_domains_mixed():
    payload = {
        "alias": "x",
        "action": [
            {"service": "light.turn_on", "target": {"entity_id": "light.a"}},
        ],
    }
    result, unhandled = append_entities_to_action_block(
        payload, ["light.b", "switch.c", "switch.d"]
    )
    assert unhandled == []
    light_action = result["action"][0]
    assert "light.a" in light_action["target"]["entity_id"]
    assert "light.b" in light_action["target"]["entity_id"]
    switch_action = result["action"][1]
    assert switch_action["service"] == "switch.turn_on"
    switch_eids = switch_action["target"]["entity_id"]
    if isinstance(switch_eids, str):
        switch_eids = [switch_eids]
    assert set(switch_eids) == {"switch.c", "switch.d"}


def test_actions_key_supported_alongside_action():
    """HA 2024.10+ allows `actions:` plural. Both work."""
    payload = {
        "alias": "x",
        "actions": [
            {"service": "light.turn_on", "target": {"entity_id": "light.a"}},
        ],
    }
    result, _ = append_entities_to_action_block(payload, ["light.b"])
    assert "light.b" in result["actions"][0]["target"]["entity_id"]


def test_no_action_block_returns_unchanged():
    payload = {"alias": "x", "trigger": []}
    result, unhandled = append_entities_to_action_block(payload, ["light.a"])
    assert unhandled == ["light.a"]
    assert "action" not in result and "actions" not in result


def test_input_not_mutated():
    payload = {
        "alias": "x",
        "action": [
            {"service": "light.turn_on", "target": {"entity_id": "light.a"}},
        ],
    }
    original_snapshot = repr(payload)
    append_entities_to_action_block(payload, ["light.b"])
    assert repr(payload) == original_snapshot


def test_empty_new_entities_returns_copy_unchanged():
    payload = {"alias": "x", "action": []}
    result, unhandled = append_entities_to_action_block(payload, [])
    assert unhandled == []
    assert result == payload


def test_malformed_entity_id_skipped():
    payload = {
        "alias": "x",
        "action": [
            {"service": "light.turn_on", "target": {"entity_id": "light.a"}},
        ],
    }
    result, _ = append_entities_to_action_block(
        payload, ["malformed", "light.b"]
    )
    assert "light.b" in result["action"][0]["target"]["entity_id"]
