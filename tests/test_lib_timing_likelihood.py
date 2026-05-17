"""Pure-logic tests for lib/timing_likelihood.py.

No HA imports required — module is a pure function over datetimes."""
from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Add the repo root so we can import custom_components.ha_insights.lib
sys.path.insert(0, str(Path(__file__).parent.parent))

from custom_components.ha_insights.lib.timing_likelihood import (
    TimingClass,
    apply_to_confidence,
    assess_timing,
)

_TZ = UTC


def _at(hour: int, minute: int, second: int = 0, microsecond: int = 0,
        day_offset: int = 0) -> datetime:
    """Build a datetime at the given time-of-day, ON A SPECIFIC DAY.
    Day offset lets us simulate "fires every day at 17:25" → 7 distinct
    events with the same time-of-day but different dates."""
    base = datetime(2026, 5, 1, hour, minute, second, microsecond, tzinfo=_TZ)
    return base + timedelta(days=day_offset)


# ----- Sample-size guards -----

def test_insufficient_samples_returns_neutral_assessment() -> None:
    """Fewer than 3 events → INSUFFICIENT_DATA, human_likelihood=1.0
    so detectors don't penalize what we can't measure. v1.5.39
    lowered _MIN_SAMPLES from 4 to 3 to match StreakDetector's floor."""
    events = [_at(17, 25, day_offset=i) for i in range(2)]
    a = assess_timing(events)
    assert a.timing_class is TimingClass.INSUFFICIENT_DATA
    assert a.human_likelihood == 1.0
    assert a.sample_count == 2


def test_empty_event_list_handled() -> None:
    a = assess_timing([])
    assert a.timing_class is TimingClass.INSUFFICIENT_DATA
    assert a.sample_count == 0


# ----- Device-likely: tight sub-second clustering -----

def test_local_device_sub_second_range_classified_device() -> None:
    """A Zigbee/ESPHome device firing at 17:25:00.XXX every day with
    < 100ms jitter is unambiguously device-driven."""
    events = [
        _at(17, 25, 0, microsecond=10_000 + i * 5_000, day_offset=i)
        for i in range(10)
    ]
    a = assess_timing(events, iot_class="local_push")
    assert a.timing_class is TimingClass.DEVICE_LIKELY
    assert a.range_seconds < 2.0
    assert a.human_likelihood == 0.20
    assert "device internal timer" in a.reason.lower()


def test_cloud_polling_wider_threshold() -> None:
    """Cloud-polled integrations get a 10s range threshold instead of
    2s — network round-trip + poll cycle add real noise on top of an
    otherwise-device-tight timer."""
    # 5s spread — would be DEVICE for local, still DEVICE for cloud
    events = [
        _at(7, 23, second=i, day_offset=i)
        for i in range(8)
    ]
    a_cloud = assess_timing(events, iot_class="cloud_polling")
    a_local = assess_timing(events, iot_class="local_push")
    assert a_cloud.timing_class is TimingClass.DEVICE_LIKELY  # 7s < 10s cloud
    assert a_local.timing_class is TimingClass.TIGHT_PATTERN  # 7s > 2s local
    assert a_cloud.range_seconds == a_local.range_seconds  # same input data


def test_cloud_polling_outside_range_still_tight() -> None:
    """Cloud device with 15s spread is above the cloud drop threshold
    (10s) but within the tight-pattern stddev band — tagged not dropped."""
    events = [
        _at(7, 23, second=i * 2, day_offset=i)
        for i in range(8)
    ]
    a = assess_timing(events, iot_class="cloud_polling")
    # 14s range > 10s drop, but stddev is small → tight pattern
    assert a.timing_class is TimingClass.TIGHT_PATTERN
    assert a.range_seconds > 10.0


# ----- Human-likely: natural jitter -----

def test_human_jitter_is_classified_human() -> None:
    """User flipping a switch ±2 minutes around 17:25 — typical for
    routine actions. Should NOT be penalized."""
    minutes_offsets = [25, 27, 24, 26, 25, 23, 28, 25, 27, 24]  # ±2-3 min
    # Vary seconds across the realistic 0-59 range so the spread is
    # genuinely human-like, not artificially tight inside each minute.
    second_offsets = [15, 42, 7, 33, 51, 22, 5, 47, 28, 11]
    events = [
        _at(17, m, second=second_offsets[i], day_offset=i)
        for i, m in enumerate(minutes_offsets)
    ]
    a = assess_timing(events, iot_class="local_push")
    assert a.timing_class is TimingClass.HUMAN_LIKELY, (
        f"expected HUMAN_LIKELY got {a.timing_class}: "
        f"stddev={a.stddev_seconds}, range={a.range_seconds}"
    )
    assert a.human_likelihood == 1.0


def test_tight_human_routine_landed_in_tight_pattern_band() -> None:
    """User who's REALLY regular — alarm-driven, ±15 seconds. Possible
    for humans but suspicious. Lands in tight-pattern band: visible
    but slight confidence cut."""
    events = [
        _at(7, 0, second=i * 3, day_offset=i)  # 0, 3, 6, 9, 12, 15, 18, 21
        for i in range(8)
    ]
    a = assess_timing(events, iot_class="local_push")
    # 21s range > 2s drop, stddev ~7s < 30s tag → tight pattern
    assert a.timing_class is TimingClass.TIGHT_PATTERN
    assert a.human_likelihood == 0.85


# ----- Midnight crossing -----

def test_midnight_crossing_correctly_unwrapped() -> None:
    """Events at 23:59, 00:01, 23:58, 00:00 across days span just
    3 minutes around midnight, not 23h57m. The unwrap helper rotates
    the seconds-of-day list so range is meaningful — without it the
    range_seconds would be ~86,200 and the assessment would
    incorrectly conclude "fires across the whole day" (it doesn't —
    fires within a 3-min midnight window every day).

    We only assert the unwrap WORKED — the resulting class depends on
    the exact stddev. With 5 events spanning 3 minutes the stddev is
    ~60-70s which exceeds the tag threshold, so this naturally lands
    in HUMAN_LIKELY. That's correct: 3-min spread IS human-like."""
    events = [
        _at(23, 59, 0, day_offset=0),
        _at(0, 1, 0, day_offset=1),
        _at(23, 58, 0, day_offset=2),
        _at(0, 0, 0, day_offset=3),
        _at(23, 59, 30, day_offset=4),
    ]
    a = assess_timing(events, iot_class="local_push")
    # Without the unwrap this would be ~86,200s. With it, ~180s.
    assert a.range_seconds < 300.0, (
        f"midnight unwrap failed — range_seconds={a.range_seconds}, "
        f"expected <300s but got the wrap-around full-day range. "
        f"reason={a.reason!r}"
    )


# ----- iot_class fallback -----

def test_unknown_iot_class_uses_default_thresholds() -> None:
    """Missing / unrecognized iot_class falls back to a conservative
    5s range threshold — wider than local (don't false-positive on
    integrations with manifest gaps), tighter than cloud."""
    # 3s range — well under the 5s default drop threshold.
    events = [
        _at(8, 0, second=i // 2, day_offset=i)
        for i in range(8)
    ]
    a_unknown = assess_timing(events, iot_class=None)
    a_garbage = assess_timing(events, iot_class="totally_made_up")
    assert a_unknown.timing_class is TimingClass.DEVICE_LIKELY
    assert a_garbage.timing_class is TimingClass.DEVICE_LIKELY


# ----- to_dict shape -----

def test_to_dict_serialization_shape() -> None:
    """Payload-ready dict that integrates into JSON-shipped insights."""
    events = [_at(17, 25, day_offset=i) for i in range(5)]
    a = assess_timing(events, iot_class="local_push")
    d = a.to_dict()
    # All numeric fields present and serializable
    assert isinstance(d["stddev_seconds"], (int, float))
    assert isinstance(d["range_seconds"], (int, float))
    assert isinstance(d["human_likelihood"], float)
    assert isinstance(d["sample_count"], int)
    assert isinstance(d["timing_class"], str)
    assert isinstance(d["reason"], str)
    # Enum serialized as plain string
    assert d["timing_class"] in {
        "human_likely",
        "tight_pattern",
        "device_likely",
        "insufficient_data",
    }


# ----- apply_to_confidence -----

def test_apply_to_confidence_clamps_to_unit_interval() -> None:
    """Multiply + clamp helper — never returns negative or > 1."""
    events = [
        _at(17, 25, 0, microsecond=i * 1000, day_offset=i)
        for i in range(10)
    ]
    a = assess_timing(events, iot_class="local_push")
    assert a.timing_class is TimingClass.DEVICE_LIKELY
    # Device-likely → 0.20 multiplier; use approx for float math.
    out = apply_to_confidence(0.9, a)
    assert abs(out - 0.18) < 1e-9, f"expected ~0.18, got {out}"
    # Even an over-1 base confidence clamps to 1.0
    assert apply_to_confidence(2.0, a) <= 1.0
    # Negative base clamps to 0.0
    assert apply_to_confidence(-0.5, a) >= 0.0


# ----- Reason text usability -----

def test_reason_text_includes_concrete_numbers() -> None:
    """The `reason` field is shown in card tooltips — it should
    quote concrete numbers so users see WHY the score is what it is."""
    events = [_at(7, 0, second=i, day_offset=i) for i in range(10)]
    a = assess_timing(events, iot_class="cloud_polling")
    # Either the range or the stddev or the count should appear
    assert any(
        marker in a.reason
        for marker in ("s window", "±", "across")
    ), f"reason missing concrete numbers: {a.reason!r}"


if __name__ == "__main__":
    import sys as _sys
    # Tiny in-process runner so the file can be executed directly
    # without pytest (mirrors test_lib_dedup.py's pattern).
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
        except Exception as e:
            results.append((name, False, f"{type(e).__name__}: {e}"))
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} tests passed")
    for name, ok, err in results:
        marker = "OK" if ok else "FAIL"
        print(f"  [{marker}] {name}{'  -- ' + err if err else ''}")
    _sys.exit(0 if passed == len(results) else 1)
