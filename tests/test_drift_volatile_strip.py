"""Regression test for drift detection (review #19).

`detect_drift` hashes the snapshot + current config and compares. We
strip volatile fields (currently anything starting with `_`) before
hashing so HA's own bookkeeping fields don't trip drift on every save.

This test guards against a class of bugs where HA's automation editor
canonicalizes YAML on save (key reorder, quote-style changes) and we
end up flagging every UI save as drift, blocking undo.
"""
from __future__ import annotations

from custom_components.ha_insights.apply.drift_detector import (
    _strip_volatile,
    detect_drift,
    hash_config,
)


def _automation() -> dict:
    return {
        "alias": "Test routine",
        "description": "auto-detected",
        "trigger": [{"platform": "time", "at": "06:47:00"}],
        "condition": [
            {"condition": "time", "weekday": ["mon", "tue", "wed", "thu", "fri"]}
        ],
        "action": [
            {"service": "light.turn_on", "target": {"entity_id": "light.kitchen"}}
        ],
        "mode": "single",
    }


def test_identical_no_drift() -> None:
    snap = _automation()
    assert detect_drift(snap, dict(snap)) is False


def test_real_change_is_drift() -> None:
    snap = _automation()
    edited = {**snap, "alias": "User's renamed alias"}
    assert detect_drift(snap, edited) is True


def test_underscored_keys_are_volatile() -> None:
    """Anything starting with `_` is stripped — HA's bookkeeping shouldn't drift."""
    snap = _automation()
    # HA may add fields like `_unique_id` or `_metadata` on save without
    # the user touching the user-visible config.
    after_save = {**snap, "_unique_id": "abc123", "_last_triggered": "2026-05-10"}
    assert detect_drift(snap, after_save) is False


def test_strip_volatile_drops_underscored() -> None:
    config = {"alias": "ok", "_internal": "wat", "trigger": [{"x": 1}]}
    stripped = _strip_volatile(config)
    assert "alias" in stripped
    assert "trigger" in stripped
    assert "_internal" not in stripped


def test_hash_is_stable_across_dict_iteration_order() -> None:
    """Hash uses sort_keys; insertion order doesn't affect the hash."""
    snap = _automation()
    same_keys_different_order = {
        "mode": snap["mode"],
        "action": snap["action"],
        "trigger": snap["trigger"],
        "alias": snap["alias"],
        "condition": snap["condition"],
        "description": snap["description"],
    }
    assert hash_config(snap) == hash_config(same_keys_different_order)


def test_top_level_key_addition_is_drift() -> None:
    """A new top-level config key (non-underscored) is a real edit."""
    snap = _automation()
    edited = {**snap, "max_exceeded": "silent"}
    assert detect_drift(snap, edited) is True
