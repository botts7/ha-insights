"""Regression test for v1.12.12 manual_habit robotic-precision gate.

The user reported on 2026-05-18 a 100%-confidence manual_habit insight
for `light.porch -> off` at ~23:27 with `time_stddev_min: 0.0` across
7 days — but they did NOT do this manually. The light is on a Hue
schedule running inside the Hue bridge. Pre-v1.12.12, the detector's
'is_manual' classifier saw:

  - No HA context.user_id (Hue bridge runs without HA authentication)
  - No HA context.parent_id (event arrives uncorrelated from any
    HA-side action)
  - Hue is in the local-integration allow-list

…and concluded the events were physical-switch presses. The 0-minute
stddev was the canonical fingerprint of "not human" but was never
gated on.

v1.12.12 adds `_TIME_STDDEV_MIN_MIN = 0.25` (15s) as a lower bound.
Real human routines have at least that much jitter because:
  - tablet/dashboard taps land ±5–30s of intent
  - voice commands carry variable processing latency (±15–60s)
  - physical switches need walking-to-the-switch time (±15–60s)

This regression test asserts the constant exists with the right value
(so a future refactor can't silently regress it). End-to-end behavior
is covered by the smoke test in the broader test suite.
"""
from __future__ import annotations

from custom_components.ha_insights.detectors import manual_habit


def test_min_stddev_constant_exists() -> None:
    assert hasattr(manual_habit, "_TIME_STDDEV_MIN_MIN")
    # 15 seconds = 0.25 min — the floor for plausible human
    # repeatability across multiple days.
    assert manual_habit._TIME_STDDEV_MIN_MIN == 0.25


def test_min_stddev_below_max_stddev() -> None:
    """Sanity: the lower bound must be below the upper bound, otherwise
    no value can satisfy the gate."""
    assert (
        manual_habit._TIME_STDDEV_MIN_MIN
        < manual_habit._TIME_STDDEV_MAX_MIN
    )
