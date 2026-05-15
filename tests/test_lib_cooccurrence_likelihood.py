"""Pure-logic tests for lib/cooccurrence_likelihood.py.

Pure function, no HA imports — no Unix fcntl dependency."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from custom_components.ha_insights.lib.cooccurrence_likelihood import (  # noqa: E402
    CooccurrenceClass,
    apply_to_confidence,
    assess_cooccurrence,
)


# ----- Sample-size guards -----

def test_insufficient_samples_returns_neutral() -> None:
    """v1.5.39: lowered _MIN_SAMPLES from 4 to 3 to match StreakDetector."""
    a = assess_cooccurrence([5, 3])
    assert a.cooccurrence_class is CooccurrenceClass.INSUFFICIENT_DATA
    assert a.human_likelihood == 1.0
    assert a.sample_count == 2


def test_empty_input_handled() -> None:
    a = assess_cooccurrence([])
    assert a.cooccurrence_class is CooccurrenceClass.INSUFFICIENT_DATA


# ----- Human-context classification -----

def test_busy_context_classified_human() -> None:
    """Median ≥ 3 nearby events → busy home, multimodal action."""
    a = assess_cooccurrence([4, 5, 3, 6, 4])
    assert a.cooccurrence_class is CooccurrenceClass.HUMAN_CONTEXT
    assert a.human_likelihood == 1.0
    assert "busy" in a.reason


def test_outlier_does_not_skew_classification() -> None:
    """One HA-restart burst (huge count) doesn't pull median up. The
    detector should still see ISOLATED if 4 of 5 events were alone."""
    # 4 events with 0 nearby + 1 event with 50 nearby (HA restart burst)
    a = assess_cooccurrence([0, 0, 0, 0, 50])
    # Mean would be 10 — false busy. Median = 0 — correctly isolated.
    assert a.cooccurrence_class is CooccurrenceClass.ISOLATED


# ----- Ambiguous classification -----

def test_one_or_two_nearby_is_ambiguous() -> None:
    """1-2 nearby events could be a sibling sensor (battery, signal)
    rather than human presence. Should not be confidently classified."""
    a = assess_cooccurrence([1, 2, 1, 1, 2])
    assert a.cooccurrence_class is CooccurrenceClass.AMBIGUOUS
    assert a.human_likelihood == 0.90


# ----- Isolated classification -----

def test_zero_nearby_classified_isolated() -> None:
    """Every event fires alone — strong device-timer signal."""
    a = assess_cooccurrence([0, 0, 0, 0, 0])
    assert a.cooccurrence_class is CooccurrenceClass.ISOLATED
    assert a.human_likelihood == 0.40
    assert "isolation" in a.reason


# ----- Custom window -----

def test_window_seconds_echoed_in_assessment() -> None:
    """Detector can pass a non-default window; the assessment echoes
    it so downstream consumers know what was applied."""
    a = assess_cooccurrence([3, 4, 5, 3, 4], window_seconds=10.0)
    assert a.window_seconds == 10.0
    assert "±10s" in a.reason


# ----- to_dict shape -----

def test_to_dict_includes_class_as_string() -> None:
    """Payload-ready dict — class is the str value, not enum object."""
    a = assess_cooccurrence([4, 5, 3, 6, 4])
    d = a.to_dict()
    assert d["cooccurrence_class"] == "human_context"
    assert isinstance(d["mean_nearby"], (int, float))
    assert isinstance(d["median_nearby"], (int, float))
    assert isinstance(d["human_likelihood"], float)
    assert isinstance(d["reason"], str)


# ----- apply_to_confidence -----

def test_apply_to_confidence_multiplies_and_clamps() -> None:
    """Detector chains lib's apply_to_confidence calls; helper
    multiplies + clamps."""
    a = assess_cooccurrence([0, 0, 0, 0, 0])  # ISOLATED → 0.40
    out = apply_to_confidence(0.5, a)
    assert abs(out - 0.20) < 1e-9
    # Clamps over-1
    assert apply_to_confidence(2.0, a) <= 1.0
    # Clamps under-0
    assert apply_to_confidence(-0.5, a) >= 0.0


# ----- Composition with timing_likelihood -----

def test_compose_with_timing_likelihood() -> None:
    """The two libs share an apply_to_confidence signature so a
    detector can chain them: device-timer with isolated context →
    aggressive demotion (intended)."""
    from datetime import datetime, timedelta, timezone

    from custom_components.ha_insights.lib.timing_likelihood import (
        assess_timing,
        apply_to_confidence as timing_apply,
    )

    # Sub-second precision events across 10 days = device-likely (0.20)
    events = [
        datetime(2026, 5, 1, 17, 25, 0, 10_000 + i * 5_000,
                 tzinfo=timezone.utc) + timedelta(days=i)
        for i in range(10)
    ]
    timing_a = assess_timing(events, iot_class="local_push")
    # Plus isolated context (0.40)
    coocc_a = assess_cooccurrence([0, 0, 0, 0, 0, 0, 0, 0, 0, 0])

    c = 0.9
    c = timing_apply(c, timing_a)
    c = apply_to_confidence(c, coocc_a)
    # 0.9 * 0.20 * 0.40 = 0.072 — well below default min_confidence
    assert c < 0.10
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
