"""Tests for lib/detector_quality.py — v1.14.7."""
from __future__ import annotations

from custom_components.ha_insights.lib.detector_quality import (
    MIN_DECISIVE_VERDICTS,
    apply_rate_from_kinds,
    compute_penalties_by_detector,
    compute_penalty_factor,
)

# ---------- apply_rate_from_kinds -----------------------------------


def test_apply_rate_empty() -> None:
    assert apply_rate_from_kinds([]) == (0.0, 0)


def test_apply_rate_all_applies() -> None:
    rate, count = apply_rate_from_kinds(["applied"] * 7)
    assert rate == 1.0
    assert count == 7


def test_apply_rate_mixed() -> None:
    rate, count = apply_rate_from_kinds(
        ["applied", "dismissed", "dismissed", "applied"],
    )
    assert rate == 0.5
    assert count == 4


def test_apply_rate_retire_counts_as_negative() -> None:
    """Retires count toward the denominator but not the numerator."""
    rate, count = apply_rate_from_kinds(["applied", "retired", "retired"])
    assert count == 3
    assert rate == 1 / 3


def test_apply_rate_ignores_snoozes() -> None:
    """Snoozes / undos / clear_applied don't represent value opinion."""
    rate, count = apply_rate_from_kinds(
        ["snoozed", "snoozed", "undone", "clear_applied", "applied"],
    )
    assert count == 1
    assert rate == 1.0


def test_apply_rate_ignores_unknown_kinds() -> None:
    """A future verdict kind in the DB shouldn't crash; just skip."""
    rate, count = apply_rate_from_kinds(
        ["applied", "applied", "what_is_this"],
    )
    assert count == 2
    assert rate == 1.0


# ---------- compute_penalty_factor ----------------------------------


def test_penalty_neutral_below_min_decisive() -> None:
    """With 4 verdicts and 0% apply-rate, factor stays 1.0 because
    we don't have enough signal to penalize."""
    assert compute_penalty_factor(0.0, MIN_DECISIVE_VERDICTS - 1) == 1.0


def test_penalty_heavy_below_20_pct() -> None:
    assert compute_penalty_factor(0.10, 10) == 0.60
    assert compute_penalty_factor(0.0, 10) == 0.60


def test_penalty_light_between_20_and_50_pct() -> None:
    assert compute_penalty_factor(0.20, 10) == 0.85
    assert compute_penalty_factor(0.49, 10) == 0.85


def test_penalty_neutral_at_50_pct_and_above() -> None:
    assert compute_penalty_factor(0.50, 10) == 1.0
    assert compute_penalty_factor(0.80, 10) == 1.0
    assert compute_penalty_factor(1.0, 10) == 1.0


def test_penalty_threshold_exact_boundaries() -> None:
    """Exactly-at-boundary cases — make sure the comparison sense is right."""
    # 0.20 is NOT < 0.20 → light band, not heavy
    assert compute_penalty_factor(0.20, 10) == 0.85
    # 0.50 is NOT < 0.50 → neutral, not light
    assert compute_penalty_factor(0.50, 10) == 1.0


def test_penalty_min_decisive_exact() -> None:
    """At exactly MIN_DECISIVE_VERDICTS the penalty kicks in."""
    assert compute_penalty_factor(0.0, MIN_DECISIVE_VERDICTS) == 0.60


# ---------- compute_penalties_by_detector ---------------------------


def test_bulk_per_detector_basic() -> None:
    """Three detectors with different histories → three different factors."""
    inputs = {
        "schedule": ["applied"] * 10,  # 100% → neutral
        "cooccurrence": ["dismissed"] * 8,  # 0% → heavy demotion
        "long_tail": ["applied", "dismissed", "applied", "dismissed", "dismissed", "dismissed"],
        # ↑ 2/6 = 33% → light demotion
    }
    out = compute_penalties_by_detector(inputs)
    assert out["schedule"] == 1.0
    assert out["cooccurrence"] == 0.60
    assert out["long_tail"] == 0.85


def test_bulk_omits_low_count_detectors() -> None:
    """A detector with 3 verdicts should still appear in the dict but
    with factor 1.0 (not penalized)."""
    inputs = {
        "new_detector": ["dismissed", "dismissed", "dismissed"],  # 0%/3 → neutral
    }
    out = compute_penalties_by_detector(inputs)
    assert out == {"new_detector": 1.0}


def test_bulk_empty_input() -> None:
    assert compute_penalties_by_detector({}) == {}
