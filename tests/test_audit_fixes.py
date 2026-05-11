"""Tests for audit/fixes.py — deterministic YAML edits.

These are the no-LLM fixes that ship via Apply directly. Tests
prove the edits are correct AND that they don't damage YAML
that doesn't match the observation kind.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_redundant_target_drops_member_entries():
    """Container + 2 members in action target → 2 members removed,
    container kept."""
    from custom_components.ha_insights.audit.fixes import (
        apply_deterministic_fixes,
    )

    automation = {
        "id": "1",
        "alias": "TV Lights OFF",
        "trigger": [{"platform": "time", "at": "23:30:00"}],
        "action": [
            {
                "service": "light.turn_off",
                "target": {
                    "entity_id": [
                        "light.main_room_tv_lights",
                        "light.led_ambient_bar_left",
                        "light.led_ambient_bar_right",
                    ]
                },
            }
        ],
    }
    observations = [
        {
            "kind": "redundant_target",
            "text": "Action targets group + 2 members",
            "metrics": {
                "container": "light.main_room_tv_lights",
                "redundant_members": [
                    "light.led_ambient_bar_left",
                    "light.led_ambient_bar_right",
                ],
            },
        }
    ]
    refined, summaries = apply_deterministic_fixes(automation, observations)
    assert refined is not None
    assert summaries == [
        "Removed 2 redundant member targets (covered by "
        "light.main_room_tv_lights)."
    ]
    new_targets = refined["action"][0]["target"]["entity_id"]
    assert new_targets == "light.main_room_tv_lights", (
        f"want scalar after collapse, got {new_targets!r}"
    )


def test_redundant_target_no_op_when_container_not_in_action():
    """The container named in metrics isn't actually in any action
    target → don't modify anything; return (None, [])."""
    from custom_components.ha_insights.audit.fixes import (
        apply_deterministic_fixes,
    )

    automation = {
        "id": "2",
        "alias": "Different scope",
        "trigger": [],
        "action": [
            {
                "service": "light.turn_off",
                "target": {"entity_id": "light.unrelated"},
            }
        ],
    }
    observations = [
        {
            "kind": "redundant_target",
            "text": "...",
            "metrics": {
                "container": "light.main_room_tv_lights",
                "redundant_members": ["light.something"],
            },
        }
    ]
    refined, summaries = apply_deterministic_fixes(automation, observations)
    assert refined is None
    assert summaries == []


def test_long_on_raises_for_clause_with_headroom():
    """`for:` of 60 min + observed mean 200 min → raise to ~240 min
    (200 * 1.2 = 240)."""
    from custom_components.ha_insights.audit.fixes import (
        apply_deterministic_fixes,
    )

    automation = {
        "id": "3",
        "alias": "Auto-off too short",
        "trigger": [{"platform": "state", "entity_id": "x"}],
        "action": [
            {
                "service": "light.turn_on",
                "target": {"entity_id": "light.x"},
                "for": {"minutes": 60},
            }
        ],
    }
    observations = [
        {
            "kind": "long_on_duration",
            "text": "stays on 200 min on average",
            "metrics": {
                "entity_id": "light.x",
                "mean_on_min": 200,
                "current_auto_off_min": 60,
                "cycles": 10,
            },
        }
    ]
    refined, summaries = apply_deterministic_fixes(automation, observations)
    assert refined is not None
    new_for = refined["action"][0]["for"]
    assert new_for == {"minutes": 240}, new_for
    assert "240 min" in summaries[0]


def test_long_on_skips_when_current_is_already_big_enough():
    """If `for:` is already ≥ suggested value, no change."""
    from custom_components.ha_insights.audit.fixes import (
        apply_deterministic_fixes,
    )

    automation = {
        "id": "4",
        "trigger": [],
        "action": [
            {
                "service": "light.turn_on",
                "target": {"entity_id": "light.x"},
                "for": {"minutes": 300},  # already > 240
            }
        ],
    }
    observations = [
        {
            "kind": "long_on_duration",
            "text": "...",
            "metrics": {
                "entity_id": "light.x",
                "mean_on_min": 200,
                "current_auto_off_min": 300,
            },
        }
    ]
    refined, summaries = apply_deterministic_fixes(automation, observations)
    assert refined is None
    assert summaries == []


def test_trigger_time_drift_shifts_at_to_rounded_5min():
    """Trigger at 07:00 + delta of +8 min → shift to 07:10 (rounded
    to nearest 5-min boundary)."""
    from custom_components.ha_insights.audit.fixes import (
        apply_deterministic_fixes,
    )

    automation = {
        "id": "5",
        "trigger": [{"platform": "time", "at": "07:00:00"}],
        "action": [{"service": "light.turn_on", "target": {"entity_id": "x"}}],
    }
    observations = [
        {
            "kind": "trigger_time_drift",
            "text": "...",
            "metrics": {
                "trigger_time": "07:00:00",
                "delta_min": 8.0,
            },
        }
    ]
    refined, summaries = apply_deterministic_fixes(automation, observations)
    assert refined is not None
    assert refined["trigger"][0]["at"] == "07:10"
    assert "07:00:00 → 07:10" in summaries[0]


def test_trigger_time_drift_no_change_when_delta_rounds_to_zero():
    """+2 min delta rounds to 0 at the 5-min boundary → no-op."""
    from custom_components.ha_insights.audit.fixes import (
        apply_deterministic_fixes,
    )

    automation = {
        "id": "6",
        "trigger": [{"platform": "time", "at": "07:00:00"}],
        "action": [{"service": "light.turn_on", "target": {"entity_id": "x"}}],
    }
    observations = [
        {
            "kind": "trigger_time_drift",
            "metrics": {"trigger_time": "07:00:00", "delta_min": 2.0},
            "text": "",
        }
    ]
    refined, summaries = apply_deterministic_fixes(automation, observations)
    assert refined is None


def test_entity_silent_has_no_deterministic_fix():
    """Dead-entity findings need user action; the fixer should
    defer."""
    from custom_components.ha_insights.audit.fixes import (
        apply_deterministic_fixes,
    )

    automation = {
        "id": "7",
        "trigger": [{"platform": "state", "entity_id": "binary_sensor.dead"}],
        "action": [],
    }
    observations = [
        {
            "kind": "entity_silent",
            "text": "...",
            "metrics": {"entity_id": "binary_sensor.dead"},
        }
    ]
    refined, summaries = apply_deterministic_fixes(automation, observations)
    assert refined is None
    assert summaries == []


def test_multiple_observations_compose():
    """One automation can have BOTH a redundant_target AND a
    long_on_duration finding. Both fixes apply on the same refined dict."""
    from custom_components.ha_insights.audit.fixes import (
        apply_deterministic_fixes,
    )

    automation = {
        "id": "8",
        "trigger": [{"platform": "state", "entity_id": "x"}],
        "action": [
            {
                "service": "light.turn_on",
                "target": {
                    "entity_id": [
                        "light.group",
                        "light.member_1",
                    ]
                },
                "for": {"minutes": 30},
            }
        ],
    }
    observations = [
        {
            "kind": "redundant_target",
            "metrics": {
                "container": "light.group",
                "redundant_members": ["light.member_1"],
            },
            "text": "",
        },
        {
            "kind": "long_on_duration",
            "metrics": {
                "entity_id": "light.group",
                "mean_on_min": 100,
                "current_auto_off_min": 30,
            },
            "text": "",
        },
    ]
    refined, summaries = apply_deterministic_fixes(automation, observations)
    assert refined is not None
    assert len(summaries) == 2
    # both edits visible
    assert refined["action"][0]["target"]["entity_id"] == "light.group"
    assert refined["action"][0]["for"]["minutes"] == 120  # 100 * 1.2
