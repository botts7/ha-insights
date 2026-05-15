"""Pure-logic tests for lib/persistence_likelihood.py."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from custom_components.ha_insights.lib.persistence_likelihood import (  # noqa: E402
    PersistenceClass,
    apply_to_confidence,
    assess_persistence,
)


def test_insufficient_samples_returns_neutral() -> None:
    """v1.5.39: lowered _MIN_SAMPLES from 4 to 3 to match StreakDetector."""
    a = assess_persistence([120.0, 121.0])
    assert a.persistence_class is PersistenceClass.INSUFFICIENT_DATA
    assert a.human_likelihood == 1.0
    assert a.sample_count == 2


def test_empty_input_handled() -> None:
    a = assess_persistence([])
    assert a.persistence_class is PersistenceClass.INSUFFICIENT_DATA


def test_toothbrush_2min_cycle_classified_fixed() -> None:
    """Sub-second jitter on a 2-min cycle is unmistakable device
    timer — CV < 5%."""
    durations = [120.005, 120.012, 119.998, 120.008, 120.001, 120.015]
    a = assess_persistence(durations)
    assert a.persistence_class is PersistenceClass.FIXED_CYCLE
    assert a.human_likelihood == 0.25
    assert a.coefficient_of_variation < 0.001  # tighter than threshold
    assert "robotic precision" in a.reason


def test_nvr_cycle_classified_fixed_with_seconds_jitter() -> None:
    """A 3600-second NVR cycle with ±5 second cloud-polling jitter
    is still well under 5% CV. Still fixed-cycle."""
    durations = [3598.2, 3601.5, 3599.8, 3600.4, 3602.1, 3597.9]
    a = assess_persistence(durations)
    assert a.persistence_class is PersistenceClass.FIXED_CYCLE


def test_human_tv_session_classified_variable() -> None:
    """TV watching: 30 min, 4 hours, 2 hours, 15 min, 3 hours. Wide
    range; CV easily > 30%."""
    durations = [1800.0, 14400.0, 7200.0, 900.0, 10800.0, 5400.0]
    a = assess_persistence(durations)
    assert a.persistence_class is PersistenceClass.HUMAN_VARIABLE
    assert a.human_likelihood == 1.0
    assert "variable enough" in a.reason


def test_tight_duration_band() -> None:
    """Alarm-driven routine: coffee maker runs for ~7 minutes most
    days, occasionally 6 or 8. CV between 5% and 30%."""
    durations = [420.0, 415.0, 430.0, 440.0, 405.0, 425.0]
    a = assess_persistence(durations)
    # stddev ≈ 11s, mean ≈ 422s → CV ≈ 2.6% ... actually that's tight too.
    # Let me check more carefully — need values that give CV in the 5-30% band.
    # Using 360s ± 60s: cv ≈ 0.17
    durations2 = [360.0, 300.0, 420.0, 360.0, 450.0, 270.0]
    a2 = assess_persistence(durations2)
    assert a2.persistence_class is PersistenceClass.TIGHT_DURATION
    assert a2.human_likelihood == 0.85


def test_backward_direction_catches_toothbrush_off_event() -> None:
    """The toothbrush OFF event has variable forward-duration (24h
    between brushings, depends on user routine) but the BACKWARD
    duration is a fixed 2-min brushing cycle. v1.5.39 looks in both
    directions; chooses the more-conclusive (lower-CV) one."""
    # Forward: how long the toothbrush stays OFF — varies wildly
    fwd_durations = [22 * 3600, 26 * 3600, 24 * 3600, 23 * 3600, 25 * 3600]
    # Backward: how long it was ON before — fixed 2-minute timer
    bwd_durations = [120.0, 120.01, 119.98, 120.02, 119.99]
    a = assess_persistence(
        fwd_durations,
        previous_state_durations_seconds=bwd_durations,
    )
    # Should pick the BACKWARD direction (lower CV) and flag fixed cycle
    assert a.persistence_class is PersistenceClass.FIXED_CYCLE
    assert a.human_likelihood == 0.25
    # Reason explicitly cites "previous-state duration"
    assert "previous-state duration" in a.reason


def test_backward_only_when_forward_is_empty() -> None:
    """If only backward durations are provided (forward not available),
    use those."""
    a = assess_persistence(
        [],
        previous_state_durations_seconds=[120.0, 120.1, 119.9, 120.05],
    )
    assert a.persistence_class is PersistenceClass.FIXED_CYCLE
    assert "previous-state duration" in a.reason


def test_forward_used_when_more_conclusive() -> None:
    """The classic toothbrush ON event: forward direction (2-min ON
    cycle) is the device fingerprint, backward (varies daily) is
    human. Picks the lower-CV direction."""
    # Forward: fixed 2-min ON
    fwd_durations = [120.0, 120.05, 119.97, 120.02, 120.01]
    # Backward: variable 22-26h gap
    bwd_durations = [22 * 3600, 26 * 3600, 24 * 3600, 23 * 3600, 25 * 3600]
    a = assess_persistence(
        fwd_durations,
        previous_state_durations_seconds=bwd_durations,
    )
    assert a.persistence_class is PersistenceClass.FIXED_CYCLE
    assert "next-state duration" in a.reason


def test_both_directions_insufficient() -> None:
    """If neither direction has enough samples, INSUFFICIENT_DATA."""
    a = assess_persistence(
        [120.0],
        previous_state_durations_seconds=[24.0],
    )
    assert a.persistence_class is PersistenceClass.INSUFFICIENT_DATA


def test_legacy_call_without_backward_still_works() -> None:
    """v1.5.38 callers (only forward direction) get identical
    behavior — backward direction is opt-in."""
    fwd_durations = [120.005, 120.012, 119.998, 120.008, 120.001, 120.015]
    # Same call style as pre-v1.5.39
    a = assess_persistence(fwd_durations)
    assert a.persistence_class is PersistenceClass.FIXED_CYCLE
    assert a.human_likelihood == 0.25
    assert "next-state duration" in a.reason


def test_zero_mean_handled_without_zerodivision() -> None:
    """If all durations are 0 (instant-revert state), CV is undefined.
    Treat as fixed cycle since there's no variation."""
    a = assess_persistence([0.0, 0.0, 0.0, 0.0])
    assert a.persistence_class is PersistenceClass.FIXED_CYCLE


def test_to_dict_serialization_shape() -> None:
    a = assess_persistence([120.0, 120.5, 119.5, 120.1, 120.3])
    d = a.to_dict()
    assert d["persistence_class"] in {
        "human_variable", "tight_duration", "fixed_cycle", "insufficient_data",
    }
    for k in (
        "mean_duration_seconds",
        "stddev_duration_seconds",
        "coefficient_of_variation",
        "human_likelihood",
        "reason",
        "sample_count",
    ):
        assert k in d


def test_apply_to_confidence_clamps() -> None:
    a = assess_persistence([120.0, 120.5, 119.5, 120.1, 120.3])
    out = apply_to_confidence(0.8, a)
    assert 0.0 <= out <= 1.0
    # Fixed cycle should drop 0.8 substantially
    assert out < 0.5


def test_compose_with_timing_and_cooccurrence() -> None:
    """All three libs share apply_to_confidence signature so detectors
    chain. Worst-case (fixed cycle + isolated + tight timing) should
    aggressively demote."""
    from datetime import datetime, timedelta, timezone

    from custom_components.ha_insights.lib.cooccurrence_likelihood import (
        apply_to_confidence as coocc_apply,
        assess_cooccurrence,
    )
    from custom_components.ha_insights.lib.timing_likelihood import (
        apply_to_confidence as timing_apply,
        assess_timing,
    )

    # Sub-second precision events
    events = [
        datetime(2026, 5, 1, 17, 25, 0, 10_000 + i * 5_000,
                 tzinfo=timezone.utc) + timedelta(days=i)
        for i in range(10)
    ]
    timing_a = assess_timing(events, iot_class="local_push")
    coocc_a = assess_cooccurrence([0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
    pers_a = assess_persistence([120.0, 120.1, 119.9, 120.05, 120.02])

    c = 0.9
    c = timing_apply(c, timing_a)   # × 0.20
    c = coocc_apply(c, coocc_a)     # × 0.40
    c = apply_to_confidence(c, pers_a)  # × 0.25
    # 0.9 * 0.20 * 0.40 * 0.25 = 0.018
    assert c < 0.05
    assert c > 0.0


if __name__ == "__main__":
    import sys as _sys
    results: list[tuple[str, bool, str]] = []
    for name in list(globals().keys()):
        if not name.startswith("test_"):
            continue
        fn = globals()[name]
        if not callable(fn):
            continue
        try:
            fn()
            results.append((name, True, ""))
        except AssertionError as e:
            results.append((name, False, str(e)))
        except Exception as e:  # noqa: BLE001
            results.append((name, False, f"{type(e).__name__}: {e}"))
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} tests passed")
    for name, ok, err in results:
        marker = "OK" if ok else "FAIL"
        print(f"  [{marker}] {name}{'  -- ' + err if err else ''}")
    _sys.exit(0 if passed == len(results) else 1)
