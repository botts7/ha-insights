"""Tests for lib/transfer_entropy."""
from __future__ import annotations

import pytest

from custom_components.ha_insights.lib.transfer_entropy import (
    TransferEntropyAssessment,
    discretize_event_stream,
    transfer_entropy,
)

# ---------- Validation -------------------------------------------------


def test_unequal_lengths_raises() -> None:
    with pytest.raises(ValueError, match="equal length"):
        transfer_entropy([0, 1], [0, 1, 0])


def test_too_few_samples_raises() -> None:
    with pytest.raises(ValueError, match="at least 2 samples"):
        transfer_entropy([0], [1])


# ---------- Directional flow -------------------------------------------


def _pseudo_random(n: int, modulus: int = 4, seed: int = 1) -> list[int]:
    """Deterministic pseudo-random integer sequence — non-periodic on
    the test timescale. Real PRNG would also work; this keeps tests
    fully deterministic without seeding `random`.

    Uses the high bits of an LCG state (low bits of LCGs have very
    short cycles when modulo'd to small values).
    """
    state = seed
    out: list[int] = []
    for _ in range(n):
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        # Use high bits — low bits of LCGs are notoriously poor (they
        # cycle with period <= modulus on power-of-2 moduli).
        out.append((state >> 16) % modulus)
    return out


def test_x_drives_y_with_unit_lag() -> None:
    """Y(t+1) = X(t). For non-periodic X, TE(X→Y) should be substantial
    and TE(Y→X) should be near zero.

    Periodic sources give weak TE because each variable can predict
    itself from its own past — we need NON-periodic source data to
    see a strong directional signal.
    """
    x = _pseudo_random(300, modulus=4, seed=42)
    y = [0, *x[:-1]]  # y is x shifted right by 1
    assess = transfer_entropy(x, y)
    assert isinstance(assess, TransferEntropyAssessment)
    # X has ~2 bits of entropy (4 equiprobable states); since Y(t+1)
    # is fully determined by X(t) AND X has no autocorrelation,
    # TE(X→Y) should approach 2 bits. Threshold at 0.5 for safety
    # margin against finite-sample noise.
    assert assess.te_x_to_y > 0.5, (
        f"X→Y TE too small: {assess.te_x_to_y}; expected directional flow"
    )
    assert assess.te_y_to_x < assess.te_x_to_y
    assert assess.dominant_direction == "x_to_y"
    assert assess.asymmetry > 0


def test_y_drives_x_with_unit_lag() -> None:
    """Mirror of the previous test: X(t+1) = Y(t)."""
    y = _pseudo_random(300, modulus=4, seed=7)
    x = [0, *y[:-1]]
    assess = transfer_entropy(x, y)
    assert assess.te_y_to_x > 0.5
    assert assess.dominant_direction == "y_to_x"
    assert assess.asymmetry < 0


# ---------- Independence (TE ~ 0) --------------------------------------


def test_independent_sequences_te_near_zero() -> None:
    """Two unrelated periodic patterns should have minimal TE both
    ways (small finite-sample noise is acceptable)."""
    x = [(i % 4) for i in range(200)]
    y = [(i * 7 % 3) for i in range(200)]  # different period, no relation
    assess = transfer_entropy(x, y)
    # Both directions should be small.
    assert assess.te_x_to_y < 0.3
    assert assess.te_y_to_x < 0.3


def test_constant_sequence_te_zero() -> None:
    """No variation → no entropy → TE = 0."""
    x = [0] * 50
    y = [0] * 50
    assess = transfer_entropy(x, y)
    assert assess.te_x_to_y == 0
    assert assess.te_y_to_x == 0


# ---------- Symmetric coupling -----------------------------------------


def test_self_coupled_pair_is_symmetric() -> None:
    """X and Y always equal — neither drives the other in TE terms
    (each can be fully predicted from its own past alone)."""
    seq = [(i % 3) for i in range(60)]
    assess = transfer_entropy(seq, seq)
    # Per-direction TE near 0 (knowing the OTHER variable adds nothing
    # beyond knowing your own past).
    assert assess.te_x_to_y < 0.1
    assert assess.te_y_to_x < 0.1
    assert assess.dominant_direction == "symmetric"


# ---------- Confidence scaling -----------------------------------------


def test_confidence_low_for_small_samples() -> None:
    x = [0, 1, 0]
    y = [1, 0, 1]
    assess = transfer_entropy(x, y)
    assert assess.confidence < 0.5, (
        f"Tiny samples should be low-confidence; got {assess.confidence}"
    )


def test_confidence_higher_for_larger_samples() -> None:
    x_small = [(i % 4) for i in range(40)]
    y_small = [0, *x_small[:-1]]
    x_big = [(i % 4) for i in range(300)]
    y_big = [0, *x_big[:-1]]
    a_small = transfer_entropy(x_small, y_small)
    a_big = transfer_entropy(x_big, y_big)
    assert a_big.confidence > a_small.confidence


# ---------- Assessment shape -------------------------------------------


def test_assessment_n_samples_matches_input() -> None:
    x = [0, 1, 0, 1, 0]
    y = [1, 0, 1, 0, 1]
    assess = transfer_entropy(x, y)
    assert assess.n_samples == len(x) - 1


def test_asymmetry_field_is_difference() -> None:
    x = [(i % 4) for i in range(100)]
    y = [0, *x[:-1]]
    assess = transfer_entropy(x, y)
    expected = round(assess.te_x_to_y - assess.te_y_to_x, 4)
    assert assess.asymmetry == expected


def test_te_values_non_negative() -> None:
    """TE should be ≥ 0 mathematically (mutual information lower-bound)."""
    x = [0, 1, 0, 1, 0, 1, 0, 1, 0]
    y = [0, 0, 1, 1, 0, 0, 1, 1, 0]
    assess = transfer_entropy(x, y)
    assert assess.te_x_to_y >= 0
    assert assess.te_y_to_x >= 0


# ---------- discretize_event_stream helper -----------------------------


def test_discretize_basic() -> None:
    """30s bins over 120s → 4 bins. Events change the state at each."""
    events = [(10.0, "on"), (50.0, "off"), (100.0, "on")]
    samples = discretize_event_stream(
        events,
        bin_size_seconds=30.0,
        total_duration_seconds=120.0,
    )
    # Bin 0 (0-30s): "on" at t=10 → "on"
    # Bin 1 (30-60s): "off" at t=50 → "off"
    # Bin 2 (60-90s): no change → "off"
    # Bin 3 (90-120s): "on" at t=100 → "on"
    assert samples == ["on", "off", "off", "on"]


def test_discretize_initial_state_for_pre_event_bins() -> None:
    """First event lands in bin 3; bins 0-2 take initial_state."""
    events = [(95.0, "active")]
    samples = discretize_event_stream(
        events,
        bin_size_seconds=30.0,
        total_duration_seconds=120.0,
        initial_state="idle",
    )
    assert samples == ["idle", "idle", "idle", "active"]


def test_discretize_empty_events() -> None:
    samples = discretize_event_stream(
        [], bin_size_seconds=30.0, total_duration_seconds=90.0, initial_state="X"
    )
    assert samples == ["X", "X", "X"]


def test_discretize_invalid_inputs() -> None:
    assert (
        discretize_event_stream([], bin_size_seconds=0, total_duration_seconds=10)
        == []
    )
    assert (
        discretize_event_stream([], bin_size_seconds=10, total_duration_seconds=0)
        == []
    )
