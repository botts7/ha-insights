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


def test_non_time_trigger_not_checked() -> None:
    """v0.1 only checks time-trigger overlap; state-trigger pairings ignored."""
    payload = _automation()
    existing = [{
        "id": "state_trig",
        "trigger": [{"platform": "state", "entity_id": "light.kitchen"}],
        "action": [{"service": "light.turn_on", "target": {"entity_id": "light.kitchen"}}],
    }]
    assert find_conflicts(_insight(payload), existing) == []


def test_malformed_time_does_not_crash() -> None:
    payload = _automation(at="06:47:00")
    existing = [{
        "id": "broken",
        "trigger": [{"platform": "time", "at": "not-a-time"}],
        "action": [{"service": "light.turn_on", "target": {"entity_id": "light.kitchen"}}],
    }]
    assert find_conflicts(_insight(payload), existing) == []
