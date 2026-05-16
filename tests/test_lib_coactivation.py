"""Pure-Python unit tests for lib/coactivation.py.

Covers the v1.5.45 signal-builder that populates `coactivation_days`
for `build_candidate_entities`. Verifies the ±5s window, calendar-day
bucketing, manual-only filter, bootstrap exclusion, and lookback cutoff.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from custom_components.ha_insights.lib.coactivation import (
    compute_coactivation_days,
)


@dataclass
class FakeEvent:
    """Duck-typed minimal StateEvent for tests — only fields the lib reads."""

    timestamp: datetime
    entity_id: str
    context_user_id: str | None = "user-1"  # default: manual (UI/mobile)
    context_parent_id: str | None = None
    from_bootstrap: bool = False


_NOW = datetime(2026, 5, 16, 12, 0, 0, tzinfo=UTC)


def test_empty_anchors_returns_empty():
    events = [FakeEvent(_NOW, "light.a")]
    assert compute_coactivation_days(
        events, anchor_entity_ids=set(), now=_NOW
    ) == {}


def test_empty_events_returns_empty():
    assert (
        compute_coactivation_days(
            [], anchor_entity_ids={"light.trigger"}, now=_NOW
        )
        == {}
    )


def test_single_coactivation_one_day():
    """Anchor fires at T, candidate fires at T+2s on same day → 1 day."""
    anchor_time = _NOW - timedelta(days=1)
    events = [
        FakeEvent(anchor_time, "light.trigger"),
        FakeEvent(anchor_time + timedelta(seconds=2), "switch.lamp"),
    ]
    result = compute_coactivation_days(
        events, anchor_entity_ids={"light.trigger"}, now=_NOW
    )
    assert result == {"switch.lamp": 1}


def test_outside_window_excluded():
    """Candidate at T+6s with default window_seconds=5 → not counted."""
    anchor_time = _NOW - timedelta(days=1)
    events = [
        FakeEvent(anchor_time, "light.trigger"),
        FakeEvent(anchor_time + timedelta(seconds=6), "switch.lamp"),
    ]
    result = compute_coactivation_days(
        events, anchor_entity_ids={"light.trigger"}, now=_NOW
    )
    assert result == {}


def test_multi_day_counts_distinct_days():
    """Same pair coactivates on 3 different days → days=3."""
    events: list[FakeEvent] = []
    for day_offset in (1, 2, 3):
        t = _NOW - timedelta(days=day_offset)
        events.append(FakeEvent(t, "light.trigger"))
        events.append(FakeEvent(t + timedelta(seconds=1), "switch.lamp"))
    result = compute_coactivation_days(
        events, anchor_entity_ids={"light.trigger"}, now=_NOW
    )
    assert result == {"switch.lamp": 3}


def test_multiple_fires_same_day_count_once():
    """Three coactivations on the SAME day → still 1 day."""
    day = _NOW - timedelta(days=2)
    events = [
        FakeEvent(day, "light.trigger"),
        FakeEvent(day + timedelta(seconds=1), "switch.lamp"),
        FakeEvent(day + timedelta(hours=2), "light.trigger"),
        FakeEvent(day + timedelta(hours=2, seconds=1), "switch.lamp"),
        FakeEvent(day + timedelta(hours=5), "light.trigger"),
        FakeEvent(day + timedelta(hours=5, seconds=2), "switch.lamp"),
    ]
    result = compute_coactivation_days(
        events, anchor_entity_ids={"light.trigger"}, now=_NOW
    )
    assert result == {"switch.lamp": 1}


def test_anchor_entity_excluded_from_result():
    """The anchor entity firing on itself doesn't appear in result."""
    anchor_time = _NOW - timedelta(days=1)
    events = [
        FakeEvent(anchor_time, "light.trigger"),
        FakeEvent(anchor_time + timedelta(seconds=1), "light.trigger"),
        FakeEvent(anchor_time + timedelta(seconds=2), "switch.lamp"),
    ]
    result = compute_coactivation_days(
        events, anchor_entity_ids={"light.trigger"}, now=_NOW
    )
    assert "light.trigger" not in result
    assert result == {"switch.lamp": 1}


def test_bootstrap_events_excluded():
    """from_bootstrap=True events drop out — both as anchor and as candidate."""
    anchor_time = _NOW - timedelta(days=1)
    events = [
        FakeEvent(
            anchor_time, "light.trigger", from_bootstrap=True
        ),  # dropped as anchor
        FakeEvent(anchor_time + timedelta(seconds=1), "switch.lamp"),
    ]
    result = compute_coactivation_days(
        events, anchor_entity_ids={"light.trigger"}, now=_NOW
    )
    # No valid anchor fire → no coactivation counted
    assert result == {}


def test_lookback_cutoff_excludes_old_events():
    """Events older than `lookback_days` are dropped."""
    old = _NOW - timedelta(days=20)  # default lookback is 14
    events = [
        FakeEvent(old, "light.trigger"),
        FakeEvent(old + timedelta(seconds=1), "switch.lamp"),
    ]
    result = compute_coactivation_days(
        events, anchor_entity_ids={"light.trigger"}, now=_NOW
    )
    assert result == {}


def test_manual_filter_drops_automation_chain():
    """Candidate fires from an automation chain (context_parent_id set) are dropped."""
    anchor_time = _NOW - timedelta(days=1)
    events = [
        FakeEvent(anchor_time, "light.trigger"),
        FakeEvent(
            anchor_time + timedelta(seconds=1),
            "switch.lamp",
            context_user_id=None,
            context_parent_id="parent-context-id",  # automation child
        ),
    ]
    result = compute_coactivation_days(
        events, anchor_entity_ids={"light.trigger"}, now=_NOW
    )
    assert result == {}


def test_manual_filter_keeps_user_id_events():
    """Candidate with context_user_id set (UI/mobile/voice) is counted."""
    anchor_time = _NOW - timedelta(days=1)
    events = [
        FakeEvent(anchor_time, "light.trigger"),
        FakeEvent(
            anchor_time + timedelta(seconds=1),
            "switch.lamp",
            context_user_id="user-abc",
            context_parent_id=None,
        ),
    ]
    result = compute_coactivation_days(
        events, anchor_entity_ids={"light.trigger"}, now=_NOW
    )
    assert result == {"switch.lamp": 1}


def test_manual_filter_keeps_physical_switch_events():
    """Candidate with no user_id AND no parent_id (physical switch / external)
    is counted as manual."""
    anchor_time = _NOW - timedelta(days=1)
    events = [
        FakeEvent(anchor_time, "light.trigger"),
        FakeEvent(
            anchor_time + timedelta(seconds=1),
            "switch.lamp",
            context_user_id=None,
            context_parent_id=None,
        ),
    ]
    result = compute_coactivation_days(
        events, anchor_entity_ids={"light.trigger"}, now=_NOW
    )
    assert result == {"switch.lamp": 1}


def test_manual_only_false_accepts_everything():
    """When manual_only=False, automation-chain candidates count too."""
    anchor_time = _NOW - timedelta(days=1)
    events = [
        FakeEvent(anchor_time, "light.trigger"),
        FakeEvent(
            anchor_time + timedelta(seconds=1),
            "switch.lamp",
            context_user_id=None,
            context_parent_id="parent-context-id",
        ),
    ]
    result = compute_coactivation_days(
        events,
        anchor_entity_ids={"light.trigger"},
        manual_only=False,
        now=_NOW,
    )
    assert result == {"switch.lamp": 1}


def test_multiple_candidates_distinct_counts():
    """Two different candidates with different day counts."""
    events: list[FakeEvent] = []
    # switch.a fires within window on 3 days
    for day_offset in (1, 2, 3):
        t = _NOW - timedelta(days=day_offset)
        events.append(FakeEvent(t, "light.trigger"))
        events.append(FakeEvent(t + timedelta(seconds=1), "switch.a"))
    # switch.b fires within window on 1 day (day 5)
    t5 = _NOW - timedelta(days=5)
    events.append(FakeEvent(t5, "light.trigger"))
    events.append(FakeEvent(t5 + timedelta(seconds=1), "switch.b"))
    result = compute_coactivation_days(
        events, anchor_entity_ids={"light.trigger"}, now=_NOW
    )
    assert result == {"switch.a": 3, "switch.b": 1}


def test_multiple_anchors_one_window_each():
    """Two anchor entities — candidate counted if near either."""
    t = _NOW - timedelta(days=1)
    events = [
        FakeEvent(t, "light.a"),  # anchor 1
        FakeEvent(t + timedelta(hours=3), "switch.b"),  # anchor 2
        FakeEvent(t + timedelta(seconds=2), "media.x"),  # near anchor 1
        FakeEvent(
            t + timedelta(hours=3, seconds=2), "media.x"
        ),  # near anchor 2 (same day)
    ]
    result = compute_coactivation_days(
        events,
        anchor_entity_ids={"light.a", "switch.b"},
        now=_NOW,
    )
    # Both fires are same day → still 1 day for media.x
    assert result == {"media.x": 1}


def test_window_seconds_override():
    """Custom window_seconds=10 captures candidates at T+8s."""
    anchor_time = _NOW - timedelta(days=1)
    events = [
        FakeEvent(anchor_time, "light.trigger"),
        FakeEvent(anchor_time + timedelta(seconds=8), "switch.lamp"),
    ]
    # Default window (5s) → not counted
    assert (
        compute_coactivation_days(
            events, anchor_entity_ids={"light.trigger"}, now=_NOW
        )
        == {}
    )
    # 10s window → counted
    assert compute_coactivation_days(
        events,
        anchor_entity_ids={"light.trigger"},
        window_seconds=10,
        now=_NOW,
    ) == {"switch.lamp": 1}


def test_window_is_symmetric():
    """Candidate fires BEFORE anchor (within window) is also counted."""
    anchor_time = _NOW - timedelta(days=1)
    events = [
        FakeEvent(
            anchor_time - timedelta(seconds=3), "switch.lamp"
        ),  # 3s BEFORE
        FakeEvent(anchor_time, "light.trigger"),
    ]
    result = compute_coactivation_days(
        events, anchor_entity_ids={"light.trigger"}, now=_NOW
    )
    assert result == {"switch.lamp": 1}


def test_unsorted_events_handled():
    """Events passed in arbitrary order — internal sort handles it."""
    anchor_time = _NOW - timedelta(days=1)
    events = [
        FakeEvent(anchor_time + timedelta(seconds=2), "switch.lamp"),  # later
        FakeEvent(anchor_time, "light.trigger"),  # earlier
    ]
    result = compute_coactivation_days(
        events, anchor_entity_ids={"light.trigger"}, now=_NOW
    )
    assert result == {"switch.lamp": 1}
