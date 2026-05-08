"""Tests for the Layer 1 automation validator."""
from __future__ import annotations

from custom_components.ha_insights.apply import validate_automation


def _valid() -> dict:
    return {
        "alias": "Test",
        "trigger": [{"platform": "time", "at": "06:47:00"}],
        "condition": [{"condition": "time", "weekday": ["mon"]}],
        "action": [{"service": "light.turn_on", "target": {"entity_id": "light.kitchen"}}],
        "mode": "single",
    }


def test_valid_payload_returns_no_errors() -> None:
    assert validate_automation(_valid()) == []


def test_missing_trigger() -> None:
    p = _valid()
    del p["trigger"]
    errors = validate_automation(p)
    assert any("trigger" in e for e in errors)


def test_trigger_must_be_list() -> None:
    p = _valid()
    p["trigger"] = {"platform": "time"}
    errors = validate_automation(p)
    assert any("must be a list" in e for e in errors)


def test_trigger_empty_rejected() -> None:
    p = _valid()
    p["trigger"] = []
    errors = validate_automation(p)
    assert any("not be empty" in e for e in errors)


def test_trigger_missing_platform() -> None:
    p = _valid()
    p["trigger"] = [{"at": "06:47"}]
    errors = validate_automation(p)
    assert any("platform" in e for e in errors)


def test_missing_action() -> None:
    p = _valid()
    del p["action"]
    errors = validate_automation(p)
    assert any("action" in e for e in errors)


def test_action_empty_rejected() -> None:
    p = _valid()
    p["action"] = []
    errors = validate_automation(p)
    assert any("not be empty" in e for e in errors)


def test_invalid_mode_rejected() -> None:
    p = _valid()
    p["mode"] = "bogus"
    errors = validate_automation(p)
    assert any("mode" in e for e in errors)


def test_mode_optional() -> None:
    p = _valid()
    del p["mode"]
    assert validate_automation(p) == []


def test_all_valid_modes_accepted() -> None:
    for mode in ("single", "restart", "queued", "parallel"):
        p = _valid()
        p["mode"] = mode
        assert validate_automation(p) == []
