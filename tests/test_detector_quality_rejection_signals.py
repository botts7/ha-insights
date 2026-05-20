"""Tests for v1.22 detector-level rejection signal in lib/detector_quality."""
from __future__ import annotations

from custom_components.ha_insights.lib.detector_quality import (
    APPLY_RATE_DISABLE_THRESHOLD,
    MIN_DECISIVE_VERDICTS_FOR_DISABLE_HINT,
    find_rejection_signals,
)


def test_empty_input_returns_empty():
    assert find_rejection_signals({}) == []


def test_below_min_decisive_filtered_out():
    """19 rejections with 0 applies is overwhelming but not enough samples."""
    kinds = {"schedule": ["dismissed"] * 19}
    assert find_rejection_signals(kinds) == []


def test_at_min_decisive_with_zero_applies_fires():
    kinds = {"schedule": ["dismissed"] * 20}
    out = find_rejection_signals(kinds)
    assert len(out) == 1
    assert out[0]["detector"] == "schedule"
    assert out[0]["n_decisive"] == 20
    assert out[0]["n_rejections"] == 20
    assert out[0]["apply_rate"] == 0.0


def test_apply_rate_at_threshold_does_not_fire():
    """Apply rate exactly 0.10 should NOT fire (strict <)."""
    kinds = {"schedule": ["applied"] * 2 + ["dismissed"] * 18}
    # apply_rate == 2/20 == 0.10 — at threshold, not below
    assert find_rejection_signals(kinds) == []


def test_apply_rate_just_below_threshold_fires():
    """One apply less than the threshold → fires."""
    kinds = {"schedule": ["applied"] * 1 + ["dismissed"] * 19}
    # apply_rate == 1/20 == 0.05
    out = find_rejection_signals(kinds)
    assert len(out) == 1
    assert out[0]["apply_rate"] == 0.05


def test_snoozes_and_undos_ignored():
    """Only applied / dismissed / retired count toward decisive_count."""
    kinds = {
        "schedule": (
            ["applied"] * 1
            + ["dismissed"] * 19
            + ["snoozed"] * 50
            + ["undone"] * 50
        ),
    }
    out = find_rejection_signals(kinds)
    assert len(out) == 1
    assert out[0]["n_decisive"] == 20  # 50 + 50 snoozes/undos NOT counted


def test_retire_counts_as_rejection():
    """Retire is a rejection — louder than dismiss, still counts."""
    kinds = {"schedule": ["retired"] * 20}
    out = find_rejection_signals(kinds)
    assert len(out) == 1
    assert out[0]["n_rejections"] == 20
    assert out[0]["n_applies"] == 0


def test_multiple_detectors_sorted_by_apply_rate_ascending():
    """Most-rejected detector should lead."""
    kinds = {
        "schedule": ["applied"] * 1 + ["dismissed"] * 19,  # 5%
        "cooccurrence": ["dismissed"] * 20,                # 0%
        "long_tail": ["applied"] * 2 + ["dismissed"] * 18, # 10% — does NOT fire
    }
    out = find_rejection_signals(kinds)
    # long_tail is at threshold (10%) → excluded.
    assert [r["detector"] for r in out] == ["cooccurrence", "schedule"]


def test_healthy_detector_not_in_output():
    """Detector with 60% apply rate is fine — not in signal list."""
    kinds = {
        "streak": ["applied"] * 12 + ["dismissed"] * 8,  # 60% — healthy
    }
    assert find_rejection_signals(kinds) == []


def test_custom_thresholds_honored():
    """Stricter threshold can demote detectors that wouldn't normally fire."""
    kinds = {"schedule": ["applied"] * 5 + ["dismissed"] * 15}  # 25%
    # Default: 25% > 10% → no fire
    assert find_rejection_signals(kinds) == []
    # Stricter threshold: 25% < 30% → fires
    out = find_rejection_signals(
        kinds, apply_rate_threshold=0.30, min_decisive=15
    )
    assert len(out) == 1
    assert out[0]["apply_rate"] == 0.25


def test_constants_are_sane():
    """Sanity-check the constants we ship publicly."""
    assert MIN_DECISIVE_VERDICTS_FOR_DISABLE_HINT >= 10
    assert 0.0 < APPLY_RATE_DISABLE_THRESHOLD <= 0.25
