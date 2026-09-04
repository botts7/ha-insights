"""Tests for the conflict scanner."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from custom_components.ha_insights.apply import find_conflicts
from custom_components.ha_insights.insight import Insight, InsightKind


def _insight(payload: dict[str, Any]) -> Insight:
    return Insight(
        id="abc",
        kind=InsightKind.AUTOMATION_PROPOSAL,
        detector="schedule",
        area_id=None,
        title="Test",
        confidence=0.9,
        fingerprint={"k": 1},
        payload=payload,
        payload_format="automation",
        created_at=datetime(2026, 5, 8, tzinfo=UTC),
    )


def _automation(
    *,
    aid: str = "ha_existing_1",
    at: str = "06:47:00",
    entity_id: str = "light.kitchen",
) -> dict[str, Any]:
    return {
        "id": aid,
        "alias": f"Existing automation {aid}",
        "trigger": [{"platform": "time", "at": at}],
        "action": [{"service": "light.turn_on", "target": {"entity_id": entity_id}}],
    }


def test_no_conflicts_with_empty_existing() -> None:
    ins = _insight(_automation())
    assert find_conflicts(ins, []) == []


def test_same_time_same_entity_conflicts() -> None:
    payload = _automation()
    existing = [_automation(aid="ha_old")]
    conflicts = find_conflicts(_insight(payload), existing)
    assert conflicts == ["ha_old"]


def test_same_time_different_entity_no_conflict() -> None:
    payload = _automation(entity_id="light.kitchen")
    existing = [_automation(aid="ha_old", entity_id="light.bedroom")]
    assert find_conflicts(_insight(payload), existing) == []


def test_different_time_same_entity_no_conflict() -> None:
    payload = _automation(at="06:47:00")
    existing = [_automation(aid="ha_old", at="22:00:00")]
    assert find_conflicts(_insight(payload), existing) == []


def test_time_within_window_conflicts() -> None:
    payload = _automation(at="06:47:00")
    existing = [_automation(aid="ha_old", at="06:55:00")]  # 8 min apart
    assert find_conflicts(_insight(payload), existing) == ["ha_old"]


def test_time_outside_window_no_conflict() -> None:
    payload = _automation(at="06:47:00")
    existing = [_automation(aid="ha_old", at="07:30:00")]  # 43 min apart
    assert find_conflicts(_insight(payload), existing) == []


def test_custom_window_respected() -> None:
    payload = _automation(at="06:47:00")
    existing = [_automation(aid="ha_old", at="06:55:00")]  # 8 min
    assert find_conflicts(_insight(payload), existing, time_window_min=5) == []
    assert find_conflicts(_insight(payload), existing, time_window_min=10) == ["ha_old"]


def test_non_automation_insight_skipped() -> None:
    """Insights with payload_format != 'automation' aren't checked."""
    ins = Insight(
        id="abc",
        kind=InsightKind.AUTOMATION_PROPOSAL,
        detector="schedule",
        area_id=None,
        title="Test",
        confidence=0.9,
        fingerprint={"k": 1},
        payload={},
        payload_format="card",
        created_at=datetime(2026, 5, 8, tzinfo=UTC),
    )
    assert find_conflicts(ins, [_automation()]) == []


def test_falls_back_to_alias_if_no_id() -> None:
    payload = _automation()
    existing = [{
        "alias": "no-id automation",
        "trigger": [{"platform": "time", "at": "06:47"}],
        "action": [{"service": "light.turn_on", "target": {"entity_id": "light.kitchen"}}],
    }]
    assert find_conflicts(_insight(payload), existing) == ["no-id automation"]


def test_legacy_action_entity_id_form_detected() -> None:
    """Older HA YAML used action.entity_id (no target wrapper)."""
    payload = _automation()
    existing = [{
        "id": "legacy",
        "trigger": [{"platform": "time", "at": "06:47"}],
        "action": [{"service": "light.turn_on", "entity_id": "light.kitchen"}],
    }]
    assert find_conflicts(_insight(payload), existing) == ["legacy"]


def test_action_entity_id_list_detected() -> None:
    """target.entity_id can be a list."""
    payload = _automation()
    existing = [{
        "id": "list_form",
        "trigger": [{"platform": "time", "at": "06:47"}],
        "action": [{
            "service": "light.turn_on",
            "target": {"entity_id": ["light.kitchen", "light.bedroom"]},
        }],
    }]
    assert find_conflicts(_insight(payload), existing) == ["list_form"]


def test_state_trigger_same_entity_same_to_value_conflicts() -> None:
    """State-trigger overlap on the same source entity AND same action target
    = conflict. (Different action targets = independent intent; tested below.)"""
    payload = {
        "alias": "Insight",
        "trigger": [
            {"platform": "state", "entity_id": "light.kitchen", "to": "on"}
        ],
        "action": [{"service": "light.turn_on", "target": {"entity_id": "light.x"}}],
    }
    existing = [{
        "id": "state_overlap",
        "trigger": [
            {"platform": "state", "entity_id": "light.kitchen", "to": "on"}
        ],
        "action": [{"service": "light.turn_on", "target": {"entity_id": "light.x"}}],
    }]
    assert find_conflicts(_insight(payload), existing) == ["state_overlap"]


def test_state_trigger_different_entity_no_conflict() -> None:
    payload = {
        "alias": "Insight",
        "trigger": [{"platform": "state", "entity_id": "light.kitchen", "to": "on"}],
        "action": [{"service": "light.turn_on", "target": {"entity_id": "light.x"}}],
    }
    existing = [{
        "id": "different_source",
        "trigger": [{"platform": "state", "entity_id": "light.bedroom", "to": "on"}],
        "action": [{"service": "switch.turn_on", "target": {"entity_id": "switch.y"}}],
    }]
    assert find_conflicts(_insight(payload), existing) == []


def test_state_trigger_different_to_value_no_conflict() -> None:
    payload = {
        "alias": "Insight",
        "trigger": [{"platform": "state", "entity_id": "light.kitchen", "to": "on"}],
        "action": [{"service": "light.turn_on", "target": {"entity_id": "light.x"}}],
    }
    existing = [{
        "id": "different_to",
        "trigger": [{"platform": "state", "entity_id": "light.kitchen", "to": "off"}],
        "action": [{"service": "switch.turn_on", "target": {"entity_id": "switch.y"}}],
    }]
    assert find_conflicts(_insight(payload), existing) == []


def test_state_trigger_any_change_matches_specific() -> None:
    """A trigger with no `to:` (any-change) overlaps another any-change
    on the same entity (both sigs are (entity, None, None))."""
    payload = {
        "alias": "Insight",
        "trigger": [{"platform": "state", "entity_id": "light.kitchen"}],  # no to:
        "action": [{"service": "light.turn_on", "target": {"entity_id": "light.x"}}],
    }
    existing = [{
        "id": "any_change",
        "trigger": [{"platform": "state", "entity_id": "light.kitchen"}],  # no to:
        "action": [{"service": "light.turn_on", "target": {"entity_id": "light.x"}}],
    }]
    assert find_conflicts(_insight(payload), existing) == ["any_change"]


def test_state_trigger_entity_id_list_detected() -> None:
    """state trigger entity_id can be a list of entities; overlap on any
    member of the list (with overlapping action target) = conflict."""
    payload = {
        "alias": "Insight",
        "trigger": [
            {
                "platform": "state",
                "entity_id": ["light.kitchen", "light.den"],
                "to": "on",
            }
        ],
        "action": [{"service": "light.turn_on", "target": {"entity_id": "light.x"}}],
    }
    existing = [{
        "id": "list_match",
        "trigger": [
            {"platform": "state", "entity_id": "light.den", "to": "on"}
        ],
        "action": [{"service": "light.turn_on", "target": {"entity_id": "light.x"}}],
    }]
    assert find_conflicts(_insight(payload), existing) == ["list_match"]


def test_motion_automation_shadows_time_insight() -> None:
    """The #114 case: lights fire at a learned clock time BECAUSE a
    motion automation turns them on. Schedule-driven insight vs
    state-triggered automation, same service on the same target =
    conflict."""
    payload = _automation(at="17:34:00", entity_id="light.hallway")
    existing = [{
        "id": "motion_lights",
        "trigger": [
            {"platform": "state", "entity_id": "binary_sensor.hall_motion", "to": "on"}
        ],
        "action": [{"service": "light.turn_on", "target": {"entity_id": "light.hallway"}}],
    }]
    assert find_conflicts(_insight(payload), existing) == ["motion_lights"]


def test_complementary_service_not_flagged() -> None:
    """Same target, different service = complementary intent, not a
    duplicate ("motion → on" vs "22:00 → off")."""
    payload = {
        "alias": "Insight",
        "trigger": [{"platform": "time", "at": "22:00:00"}],
        "action": [{"service": "light.turn_off", "target": {"entity_id": "light.hallway"}}],
    }
    existing = [{
        "id": "motion_lights",
        "trigger": [
            {"platform": "state", "entity_id": "binary_sensor.hall_motion", "to": "on"}
        ],
        "action": [{"service": "light.turn_on", "target": {"entity_id": "light.hallway"}}],
    }]
    assert find_conflicts(_insight(payload), existing) == []


def test_numeric_state_automation_shadows_time_insight() -> None:
    payload = _automation(at="17:34:00", entity_id="light.hallway")
    existing = [{
        "id": "lux_lights",
        "trigger": [
            {"platform": "numeric_state", "entity_id": "sensor.hall_lux", "below": 20}
        ],
        "action": [{"service": "light.turn_on", "target": {"entity_id": "light.hallway"}}],
    }]
    assert find_conflicts(_insight(payload), existing) == ["lux_lights"]


def test_device_trigger_automation_shadows_time_insight() -> None:
    """UI-built motion automations use `platform: device`."""
    payload = _automation(at="17:34:00", entity_id="light.hallway")
    existing = [{
        "id": "ui_motion",
        "trigger": [{
            "platform": "device",
            "device_id": "abc123",
            "domain": "binary_sensor",
            "type": "motion",
        }],
        "action": [{"service": "light.turn_on", "target": {"entity_id": "light.hallway"}}],
    }]
    assert find_conflicts(_insight(payload), existing) == ["ui_motion"]


def test_event_insight_shadowed_by_sun_automation() -> None:
    """Reverse direction: state-triggered insight vs sun-triggered
    existing automation, same service + target."""
    payload = {
        "alias": "Insight",
        "trigger": [
            {"platform": "state", "entity_id": "binary_sensor.door", "to": "on"}
        ],
        "action": [{"service": "light.turn_on", "target": {"entity_id": "light.porch"}}],
    }
    existing = [{
        "id": "sunset_porch",
        "trigger": [{"platform": "sun", "event": "sunset"}],
        "action": [{"service": "light.turn_on", "target": {"entity_id": "light.porch"}}],
    }]
    assert find_conflicts(_insight(payload), existing) == ["sunset_porch"]


def test_two_event_driven_sides_not_cross_matched() -> None:
    """The cross-trigger branch needs a schedule side. Two automations
    on different motion sensors turning on the same light are additive
    coverage, not duplicates — unchanged behavior."""
    payload = {
        "alias": "Insight",
        "trigger": [
            {"platform": "state", "entity_id": "binary_sensor.hall_motion", "to": "on"}
        ],
        "action": [{"service": "light.turn_on", "target": {"entity_id": "light.hallway"}}],
    }
    existing = [{
        "id": "other_motion",
        "trigger": [
            {"platform": "state", "entity_id": "binary_sensor.stair_motion", "to": "on"}
        ],
        "action": [{"service": "light.turn_on", "target": {"entity_id": "light.hallway"}}],
    }]
    assert find_conflicts(_insight(payload), existing) == []


def test_modern_action_key_detected() -> None:
    """2024.8+ YAML uses `action:` instead of `service:` in actions."""
    payload = _automation(at="17:34:00", entity_id="light.hallway")
    existing = [{
        "id": "modern_yaml",
        "trigger": [
            {"platform": "state", "entity_id": "binary_sensor.hall_motion", "to": "on"}
        ],
        "action": [{"action": "light.turn_on", "target": {"entity_id": "light.hallway"}}],
    }]
    assert find_conflicts(_insight(payload), existing) == ["modern_yaml"]


def test_cross_trigger_expands_group_members() -> None:
    """Insight targets a group; motion automation targets a member.
    members_of expansion applies to the cross-trigger branch too."""
    payload = _automation(at="17:34:00", entity_id="light.garden_group")
    existing = [{
        "id": "motion_member",
        "trigger": [
            {"platform": "state", "entity_id": "binary_sensor.garden_motion", "to": "on"}
        ],
        "action": [{"service": "light.turn_on", "target": {"entity_id": "light.deck_01"}}],
    }]
    members = {"light.garden_group": frozenset({"light.deck_01", "light.deck_02"})}
    assert find_conflicts(
        _insight(payload), existing, members_of=members
    ) == ["motion_member"]


def test_malformed_time_does_not_crash() -> None:
    payload = _automation(at="06:47:00")
    existing = [{
        "id": "broken",
        "trigger": [{"platform": "time", "at": "not-a-time"}],
        "action": [{"service": "light.turn_on", "target": {"entity_id": "light.kitchen"}}],
    }]
    assert find_conflicts(_insight(payload), existing) == []
