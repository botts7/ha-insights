"""Predictive sun-relative trigger detection.

Some habits aren't really tied to clock time — they're tied to
sunset (evening lights on), sunrise (morning blinds open), or
dusk (porch lights). Those habits look messy on a clock: a
17:30 routine in December slides to 19:30 by June. But the
offset from sunset is stable year-round (~10 min before sunset).

This helper takes the timestamps of an observed habit + the
HA hass object (used to query astral for that location's
sun events) and returns the best trigger description:

  - Clock-time trigger (no sun correlation found)
  - Sunrise-relative trigger (offset = ±N minutes from sunrise)
  - Sunset-relative trigger

Decision rule: pick the sun event whose offset-stddev across the
observed days is materially smaller than the clock-time-stddev
AND whose mean offset is within ±2 hours. The mean-offset check
guards against false-positives at high latitudes (where 02:00
would otherwise correlate weakly with "sunrise" because both
shift slowly).

ManualHabitDetector + RoutineDetector both call this. When it
returns a sun-relative recommendation, the YAML builder uses a
`platform: sun` trigger with `offset:` set accordingly; when it
returns None, they fall back to the fixed `platform: time` /
`at:` trigger.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


# A sun event is only meaningfully "the trigger" when the habit
# happens within this many minutes of it. Beyond that and we'd be
# saying "midnight is sunset-relative" which is technically true
# but nonsensical.
_MAX_OFFSET_MINUTES = 120
# Sun-stddev must be this fraction (or less) of clock-stddev to
# count as a tighter fit. Below 1.0 = sun is meaningfully better;
# 0.6 keeps the bar high enough that wide clock-time scatter
# can't always be "explained" by sun drift.
_TIGHTER_FIT_RATIO = 0.6


def detect_sun_relative_trigger(
    habit_times: list[datetime],
    hass: HomeAssistant,
) -> tuple[str, int] | None:
    """If habit_times correlate more tightly with sunrise or sunset
    than with the wall clock, return (event_name, offset_minutes).

    `event_name` is "sunrise" or "sunset"; `offset_minutes` is
    signed (negative = before the event, positive = after).

    Returns None when clock time is the better fit, sun data isn't
    available, or the timestamps are too few to be statistically
    meaningful.
    """
    if len(habit_times) < 3:
        return None

    try:
        from homeassistant.components.sun import (
            get_astral_event_date,
        )
    except ImportError:
        return None

    sunrise_offsets: list[float] = []
    sunset_offsets: list[float] = []
    for t in habit_times:
        try:
            sunrise = get_astral_event_date(hass, "sunrise", date=t.date())
            sunset = get_astral_event_date(hass, "sunset", date=t.date())
        except Exception:
            return None
        if sunrise is None or sunset is None:
            continue
        sunrise_offsets.append((t - sunrise).total_seconds() / 60.0)
        sunset_offsets.append((t - sunset).total_seconds() / 60.0)

    if len(sunrise_offsets) < 3:
        return None

    # Clock-time stddev for the same set
    minutes = [t.hour * 60 + t.minute + t.second / 60.0 for t in habit_times]
    clock_stddev = _stddev(minutes)
    # Don't bother flipping to sun-relative if the clock fit is
    # already great. Avoids redundant changes for stable indoor
    # routines.
    if clock_stddev < 15.0:
        return None

    avg_sunrise = sum(sunrise_offsets) / len(sunrise_offsets)
    sunrise_stddev = _stddev(sunrise_offsets)
    avg_sunset = sum(sunset_offsets) / len(sunset_offsets)
    sunset_stddev = _stddev(sunset_offsets)

    best_event: str | None = None
    best_offset: int | None = None
    best_stddev = clock_stddev

    if (
        sunrise_stddev < best_stddev * _TIGHTER_FIT_RATIO
        and abs(avg_sunrise) <= _MAX_OFFSET_MINUTES
    ):
        best_event = "sunrise"
        best_offset = _round_to_5(avg_sunrise)
        best_stddev = sunrise_stddev

    if (
        sunset_stddev < best_stddev * _TIGHTER_FIT_RATIO
        and abs(avg_sunset) <= _MAX_OFFSET_MINUTES
    ):
        best_event = "sunset"
        best_offset = _round_to_5(avg_sunset)

    if best_event is None or best_offset is None:
        return None
    return best_event, best_offset


def format_sun_offset(offset_minutes: int) -> str:
    """Render an offset as HA's `HH:MM:SS` string with sign prefix.

    HA accepts negative `offset:` strings starting with `-`. For
    positive offsets the sign is optional but we include `+` for
    readability in the generated YAML.
    """
    sign = "-" if offset_minutes < 0 else "+"
    abs_min = abs(offset_minutes)
    hours = abs_min // 60
    mins = abs_min % 60
    return f"{sign}{hours:02d}:{mins:02d}:00"


def build_sun_trigger(event: str, offset_minutes: int) -> dict:
    """Convenience for detectors — returns a `platform: sun` trigger
    dict ready to drop into an automation `trigger:` list."""
    return {
        "platform": "sun",
        "event": event,
        "offset": format_sun_offset(offset_minutes),
    }


def _stddev(values: list[float]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))


def _round_to_5(value: float) -> int:
    """Round to nearest 5 — cleaner offset for the generated YAML.
    `13.7` → 15; `-7.2` → -5; `0.0` → 0."""
    return int(round(value / 5.0) * 5)
