"""Regression test for v1.12.12 long_tail fixed-duty-cycle gate.

Real-install incident 2026-05-18: detector emitted an AUTO-OFF
proposal for a solar inverter at 100% confidence:

    switch.inverter_5010kmsc252s0046_switch stays active for ~584 min
    (11 times in 14d, max 609 min). Auto-off after 120 min?

The inverter runs ~10 hours every day from sunrise to sunset — that's
its DESIGN. Applying the suggested automation would have shut it off
at noon every day, eliminating most solar generation. The detector
had no signal to distinguish "device's intentional duty cycle" from
"user forgot to turn off."

v1.12.12 fix: compute coefficient of variation across all observed
long spans. If CV < 5%, every recorded duration is essentially the
same length — the fingerprint of a fixed-cycle device — and we
suppress the insight rather than propose a dangerous auto-off.

This test asserts the gate exists and fires for the user's actual
real-install pattern (~600 min spans with ~5 min stddev = ~0.8% CV).
"""
from __future__ import annotations

from custom_components.ha_insights.detectors.long_tail import LongTailDetector


def test_threshold_constant_exists() -> None:
    """Documented behaviour: the threshold matches lib/persistence_
    likelihood.py's fixed_cycle definition. If that lib's threshold
    changes, this should change too."""
    assert hasattr(LongTailDetector, "_FIXED_CYCLE_CV_THRESHOLD")
    assert LongTailDetector._FIXED_CYCLE_CV_THRESHOLD == 0.05


def test_solar_inverter_pattern_suppressed() -> None:
    """User's actual data: 11 spans averaging ~584 min (35,040s) with
    very tight stddev (~5 min, ~300s). CV ≈ 0.85% — well below 5%
    threshold."""
    detector = LongTailDetector()
    spans = [
        35040, 35100, 34980, 35160, 34920, 35040, 35220, 34980,
        35100, 35040, 36540,  # max 609 min outlier
    ]
    assert detector._is_fixed_duty_cycle(spans)


def test_human_forgot_to_turn_off_pattern_preserved() -> None:
    """Real human pattern: light left on for varying lengths. CV is
    high because some nights it's 90 min, others 6+ hours."""
    detector = LongTailDetector()
    spans = [
        90 * 60,    # 1.5h
        360 * 60,   # 6h
        180 * 60,   # 3h
        540 * 60,   # 9h
        120 * 60,   # 2h
        420 * 60,   # 7h
    ]
    assert not detector._is_fixed_duty_cycle(spans)


def test_two_spans_does_not_classify() -> None:
    """Need at least 3 samples for variance to be meaningful — return
    False (don't gate) when too few."""
    detector = LongTailDetector()
    assert not detector._is_fixed_duty_cycle([3600, 3650])
    assert not detector._is_fixed_duty_cycle([3600])
    assert not detector._is_fixed_duty_cycle([])


def test_zero_mean_handled_defensively() -> None:
    """If somehow all spans are 0 (shouldn't happen given upstream
    threshold filter, but defensive), don't divide-by-zero."""
    detector = LongTailDetector()
    assert not detector._is_fixed_duty_cycle([0, 0, 0])


def test_boundary_just_above_threshold_preserved() -> None:
    """CV just above 5% means there IS meaningful human variance —
    preserve (the detector should still emit)."""
    detector = LongTailDetector()
    # mean=10000, stddev≈636 → CV≈6.36% (just above 5% threshold)
    spans = [9100, 9550, 10000, 10450, 10900]
    assert not detector._is_fixed_duty_cycle(spans)


def test_boundary_just_below_threshold_suppressed() -> None:
    """CV just below 5% means robotic precision — suppress."""
    detector = LongTailDetector()
    # mean=10000, stddev≈212 → CV≈2.12% (below 5%)
    spans = [9700, 9850, 10000, 10150, 10300]
    assert detector._is_fixed_duty_cycle(spans)
