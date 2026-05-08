"""Tests for the drift detector."""
from __future__ import annotations

from custom_components.ha_insights.apply import detect_drift, hash_config


def _automation() -> dict:
    return {
        "id": "ha_insights_abc",
        "alias": "Test routine",
        "trigger": [{"platform": "time", "at": "06:47:00"}],
        "action": [{"service": "light.turn_on", "target": {"entity_id": "light.kitchen"}}],
        "mode": "single",
    }


def test_hash_is_deterministic() -> None:
    a = _automation()
    assert hash_config(a) == hash_config(a)
    assert len(hash_config(a)) == 32  # blake2b digest_size=16 -> 32 hex chars


def test_hash_canonicalizes_dict_order() -> None:
    """Reordering fields must not change the hash."""
    a = {"id": "x", "alias": "y", "mode": "single"}
    b = {"mode": "single", "alias": "y", "id": "x"}
    assert hash_config(a) == hash_config(b)


def test_no_drift_when_unchanged() -> None:
    a = _automation()
    assert detect_drift(a, a) is False
    assert detect_drift(a, dict(a)) is False  # equivalent dict


def test_drift_when_field_added() -> None:
    snapshot = _automation()
    current = _automation()
    current["description"] = "Manually edited"
    assert detect_drift(snapshot, current) is True


def test_drift_when_field_changed() -> None:
    snapshot = _automation()
    current = _automation()
    current["alias"] = "Renamed"
    assert detect_drift(snapshot, current) is True


def test_drift_when_trigger_time_changed() -> None:
    snapshot = _automation()
    current = _automation()
    current["trigger"] = [{"platform": "time", "at": "07:00:00"}]
    assert detect_drift(snapshot, current) is True


def test_no_drift_when_only_underscore_fields_change() -> None:
    """Fields starting with _ are stripped before hashing."""
    snapshot = _automation()
    current = _automation()
    current["_internal_marker"] = "ha-only-bookkeeping"
    assert detect_drift(snapshot, current) is False
