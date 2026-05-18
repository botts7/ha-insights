"""Regression test for v1.12.12 seasonality robotic-precision gate.

Same root cause as the ManualHabitDetector porch-light bug (also
v1.12.12): SeasonalityDetector finds weekly patterns
("every Tuesday at 8am") but never checked context.user_id and had
NO lower bound on time-of-day stddev.

Result: a Tuya weekly schedule firing every Tuesday at exactly 8am
across 4 weeks would emit at high confidence as "you do this every
Tuesday — automate it!" — even though the user can't (the vendor
device runs the schedule, HA never sees it as a user action).

v1.12.12 adds `TIME_STDDEV_MIN_MIN = 0.25` (15s) as a lower bound.
Same threshold as ManualHabitDetector for consistency.

This test asserts the gate constant exists and is positioned
correctly relative to the upper bound.
"""
from __future__ import annotations

from custom_components.ha_insights.detectors.seasonality import (
    SeasonalityDetector,
)


def test_min_stddev_constant_exists() -> None:
    assert hasattr(SeasonalityDetector, "TIME_STDDEV_MIN_MIN")
    assert SeasonalityDetector.TIME_STDDEV_MIN_MIN == 0.25


def test_min_stddev_below_max_stddev() -> None:
    """Sanity: lower bound must be below upper bound."""
    assert (
        SeasonalityDetector.TIME_STDDEV_MIN_MIN
        < SeasonalityDetector.TIME_STDDEV_MAX_MIN
    )


def test_min_stddev_matches_manual_habit() -> None:
    """v1.12.12 design: both detectors share the same human-jitter
    floor. If one changes the threshold (e.g. v1.13 evidence widens
    the band to 30s), the other should follow. This test catches
    accidental drift."""
    from custom_components.ha_insights.detectors import manual_habit

    assert (
        SeasonalityDetector.TIME_STDDEV_MIN_MIN
        == manual_habit._TIME_STDDEV_MIN_MIN
    )
