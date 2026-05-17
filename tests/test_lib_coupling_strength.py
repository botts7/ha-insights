"""Tests for lib/coupling_strength."""
from __future__ import annotations

from custom_components.ha_insights.lib.coupling_strength import (
    LOOSE_MEDIAN_LAG_MS,
    LOOSE_MIN_CONSISTENCY,
    TIGHT_CONFIDENCE_FACTOR,
    TIGHT_MEDIAN_LAG_MS,
    TIGHT_MIN_CONSISTENCY,
    apply_tier_demotion,
    compute_coupling,
    coupling_payload,
)


def test_empty_deltas_returns_none_tier() -> None:
    score = compute_coupling(deltas_seconds=[], leader_count=10)
    assert score.tier == "NONE"
    assert score.median_lag_ms == 0.0
    assert score.consistency == 0.0


def test_zero_leader_count_returns_none_tier() -> None:
    # Defensive — detectors shouldn't call us with leader_count=0,
    # but if they do we shouldn't divide-by-zero.
    score = compute_coupling(deltas_seconds=[0.1, 0.2], leader_count=0)
    assert score.tier == "NONE"


def test_tight_coupling_sub_500ms_perfect_consistency() -> None:
    """Sub-half-second deltas with every leader producing a follower."""
    score = compute_coupling(
        deltas_seconds=[0.15, 0.18, 0.16, 0.17, 0.19, 0.16, 0.18, 0.17],
        leader_count=8,
    )
    assert score.tier == "TIGHT"
    assert score.median_lag_ms == 170.0  # median of the 8 values × 1000
    assert score.consistency == 1.0


def test_tight_boundary_exact_thresholds() -> None:
    """At exactly TIGHT_MEDIAN_LAG_MS and TIGHT_MIN_CONSISTENCY, still TIGHT."""
    deltas = [TIGHT_MEDIAN_LAG_MS / 1000.0] * 9
    # 9 deltas / 10 leader_count = 0.9 = exactly TIGHT_MIN_CONSISTENCY
    score = compute_coupling(deltas_seconds=deltas, leader_count=10)
    assert score.tier == "TIGHT"


def test_just_over_tight_lag_drops_to_loose() -> None:
    deltas = [(TIGHT_MEDIAN_LAG_MS + 1.0) / 1000.0] * 8
    score = compute_coupling(deltas_seconds=deltas, leader_count=8)
    # Lag exceeds TIGHT threshold but still in LOOSE range with perfect
    # consistency — should land LOOSE.
    assert score.tier == "LOOSE"


def test_just_under_tight_consistency_drops_to_loose() -> None:
    # 7/10 = 0.70 — exactly the LOOSE_MIN_CONSISTENCY floor, below TIGHT.
    deltas = [0.2] * 7
    score = compute_coupling(deltas_seconds=deltas, leader_count=10)
    assert score.tier == "LOOSE"


def test_loose_coupling_one_to_two_seconds() -> None:
    """1-2s deltas with 80% consistency — looks like an HA-side automation."""
    score = compute_coupling(
        deltas_seconds=[1.5, 1.2, 1.8, 1.4, 1.6, 1.3, 1.7, 1.5],
        leader_count=10,
    )
    assert score.tier == "LOOSE"
    assert score.median_lag_ms > TIGHT_MEDIAN_LAG_MS


def test_loose_boundary_exact_thresholds() -> None:
    deltas = [LOOSE_MEDIAN_LAG_MS / 1000.0] * 7
    # 7/10 = 0.70 = exactly LOOSE_MIN_CONSISTENCY
    score = compute_coupling(deltas_seconds=deltas, leader_count=10)
    assert score.tier == "LOOSE"


def test_none_tier_slow_lag() -> None:
    """5-second deltas — well past LOOSE; user habit territory."""
    score = compute_coupling(
        deltas_seconds=[5.0, 6.0, 4.0, 5.5, 5.0, 4.5, 5.5, 6.0],
        leader_count=8,
    )
    assert score.tier == "NONE"


def test_none_tier_low_consistency_even_when_fast() -> None:
    """Fast deltas but the leader fires 100x and only 30 produce followers."""
    score = compute_coupling(
        deltas_seconds=[0.1] * 30,
        leader_count=100,
    )
    # Fast lag but 30% consistency — looks coincidental, not coupled.
    assert score.tier == "NONE"
    assert score.consistency == 0.3


def test_single_delta_uses_that_value_as_median() -> None:
    score = compute_coupling(deltas_seconds=[0.25], leader_count=1)
    assert score.median_lag_ms == 250.0
    assert score.consistency == 1.0
    assert score.tier == "TIGHT"


def test_consistency_capped_at_one() -> None:
    # Pathological: more deltas than leader_count (shouldn't happen in
    # practice — would indicate detector double-counting — but the
    # min(1.0, ...) cap keeps the score in range).
    score = compute_coupling(deltas_seconds=[0.1] * 15, leader_count=10)
    assert score.consistency == 1.0


def test_payload_serialization_shape() -> None:
    score = compute_coupling(deltas_seconds=[0.2, 0.3], leader_count=2)
    payload = coupling_payload(score)
    assert set(payload.keys()) == {"tier", "median_lag_ms", "consistency"}
    assert isinstance(payload["tier"], str)
    assert isinstance(payload["median_lag_ms"], (int, float))
    assert isinstance(payload["consistency"], (int, float))


def test_apply_tier_demotion_tight_multiplies() -> None:
    # 0.95 * 0.85 = 0.8075 → 0.808 after round(.., 3)
    assert apply_tier_demotion(0.95, "TIGHT") == round(
        0.95 * TIGHT_CONFIDENCE_FACTOR, 3
    )


def test_apply_tier_demotion_loose_passes_through() -> None:
    assert apply_tier_demotion(0.8, "LOOSE") == 0.8


def test_apply_tier_demotion_none_passes_through() -> None:
    assert apply_tier_demotion(0.6, "NONE") == 0.6


def test_apply_tier_demotion_preserves_low_confidence_emissibility() -> None:
    # Borderline insight (just above 0.55 cooccurrence floor) with TIGHT
    # tier: 0.56 * 0.85 = 0.476 → 0.476 rounded. Still below floor —
    # but multiplicative is intentionally permissive vs flat subtraction.
    # This test documents the trade-off: we DO sometimes push insights
    # below the emit floor; we accept that for the noise-reduction win.
    demoted = apply_tier_demotion(0.56, "TIGHT")
    assert demoted < 0.56
    assert demoted > 0.4  # not catastrophic
