"""Pure-logic tests for lib/human_likelihood.py — the composite.

Equivalence-style tests: verify the composite produces the SAME
confidence multiplier and the SAME payload entries as the
hand-rolled chain it replaces. That guarantees the schedule + streak
refactor introduces zero behavior change.

If a future grader lib (transition_entropy, paired_event) is added
to HumanLikelihoodFeatures, extend the equivalence test to cover
the new lib too — the safety net then keeps the composite honest as
it grows."""
from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from custom_components.ha_insights.lib.cooccurrence_likelihood import (
    apply_to_confidence as coocc_apply,
)
from custom_components.ha_insights.lib.cooccurrence_likelihood import (
    assess_cooccurrence,
)
from custom_components.ha_insights.lib.human_likelihood import (
    assess_human_likelihood,
)
from custom_components.ha_insights.lib.persistence_likelihood import (
    apply_to_confidence as pers_apply,
)
from custom_components.ha_insights.lib.persistence_likelihood import (
    assess_persistence,
)
from custom_components.ha_insights.lib.timing_likelihood import (
    apply_to_confidence as timing_apply,
)
from custom_components.ha_insights.lib.timing_likelihood import (
    assess_timing,
)

_TZ = UTC


def _make_inputs(
    *,
    n: int = 10,
    timing_us: int = 5_000,  # microsecond precision spacing
    nearby_per: int = 0,
    duration_s: float = 120.0,
    duration_jitter: float = 0.05,
) -> tuple[list[datetime], list[int], list[float]]:
    """Synthetic input triple — timestamps, nearby_counts, durations.

    Defaults produce a "device-likely" pattern: sub-second timing
    precision, isolated context, fixed-cycle persistence."""
    timestamps = [
        datetime(2026, 5, 1, 17, 25, 0, 10_000 + i * timing_us, tzinfo=_TZ)
        + timedelta(days=i)
        for i in range(n)
    ]
    nearby = [nearby_per] * n
    durations = [
        duration_s * (1.0 + (i % 3 - 1) * duration_jitter / 10)
        for i in range(n)
    ]
    return timestamps, nearby, durations


# ----- Equivalence: composite == hand-chain -----

def test_composite_matches_hand_chained_apply_for_device_pattern() -> None:
    """Device-likely synthetic input. Composite confidence must
    equal what the schedule/streak detectors used to compute by
    hand. If this test fails after a refactor, the refactor
    silently changed scoring — abort the refactor."""
    timestamps, nearby, durations = _make_inputs()

    # Hand-chained (the pre-v1.5.38 pattern, kept here as the
    # ground truth)
    timing_a = assess_timing(timestamps, iot_class="local_push")
    coocc_a = assess_cooccurrence(nearby)
    pers_a = assess_persistence(durations)
    expected = 0.8
    expected = timing_apply(expected, timing_a)
    expected = coocc_apply(expected, coocc_a)
    expected = pers_apply(expected, pers_a)

    # Composite (the post-v1.5.38 pattern)
    features = assess_human_likelihood(
        timestamps=timestamps,
        nearby_counts=nearby,
        durations_seconds=durations,
        iot_class="local_push",
    )
    actual = features.apply_to(0.8)

    assert abs(actual - expected) < 1e-9, (
        f"composite drift! expected={expected}, actual={actual}"
    )


def test_composite_matches_for_human_pattern() -> None:
    """Human-likely synthetic input — wider jitter, busy context,
    variable durations. Same equivalence must hold."""
    second_offsets = [15, 42, 7, 33, 51, 22, 5, 47, 28, 11]
    timestamps = [
        datetime(2026, 5, 1, 17, 25 + (i % 5), second_offsets[i], tzinfo=_TZ)
        + timedelta(days=i)
        for i in range(10)
    ]
    nearby = [4, 5, 3, 6, 4, 5, 3, 4, 5, 4]
    durations = [120.0, 600.0, 90.0, 3600.0, 1800.0, 240.0, 4800.0, 360.0]

    timing_a = assess_timing(timestamps, iot_class="local_push")
    coocc_a = assess_cooccurrence(nearby)
    pers_a = assess_persistence(durations)
    expected = 0.9
    expected = timing_apply(expected, timing_a)
    expected = coocc_apply(expected, coocc_a)
    expected = pers_apply(expected, pers_a)

    features = assess_human_likelihood(
        timestamps=timestamps,
        nearby_counts=nearby,
        durations_seconds=durations,
        iot_class="local_push",
    )
    actual = features.apply_to(0.9)

    assert abs(actual - expected) < 1e-9


def test_composite_matches_when_iot_class_is_cloud() -> None:
    """iot_class is the only non-trivial parameter that changes
    thresholds. Verify it's threaded through correctly."""
    timestamps, nearby, durations = _make_inputs()
    timing_a = assess_timing(timestamps, iot_class="cloud_polling")
    coocc_a = assess_cooccurrence(nearby)
    pers_a = assess_persistence(durations)
    expected = 0.5
    expected = timing_apply(expected, timing_a)
    expected = coocc_apply(expected, coocc_a)
    expected = pers_apply(expected, pers_a)

    features = assess_human_likelihood(
        timestamps=timestamps,
        nearby_counts=nearby,
        durations_seconds=durations,
        iot_class="cloud_polling",
    )
    actual = features.apply_to(0.5)
    assert abs(actual - expected) < 1e-9


def test_composite_matches_when_iot_class_is_none() -> None:
    """Default-threshold path."""
    timestamps, nearby, durations = _make_inputs()
    timing_a = assess_timing(timestamps, iot_class=None)
    coocc_a = assess_cooccurrence(nearby)
    pers_a = assess_persistence(durations)
    expected = 0.7
    expected = timing_apply(expected, timing_a)
    expected = coocc_apply(expected, coocc_a)
    expected = pers_apply(expected, pers_a)

    features = assess_human_likelihood(
        timestamps=timestamps,
        nearby_counts=nearby,
        durations_seconds=durations,
        iot_class=None,
    )
    actual = features.apply_to(0.7)
    assert abs(actual - expected) < 1e-9


# ----- Equivalence: payload_keys() shape -----

def test_payload_keys_match_hand_built_dict() -> None:
    """The payload entries the composite emits must be IDENTICAL to
    what the detectors used to build by hand. If a key name or value
    shape changes, the card / LLM / future consumers silently break.

    v1.12.12: composite now also emits `_is_device_managed` (canonical
    bool verdict) — verified separately in
    test_payload_keys_includes_canonical_device_managed_field. The
    three legacy assessment blocks must still match exactly.
    """
    timestamps, nearby, durations = _make_inputs()

    # Hand-built
    timing_a = assess_timing(timestamps, iot_class="local_push")
    coocc_a = assess_cooccurrence(nearby)
    pers_a = assess_persistence(durations)
    expected_keys = {
        "_timing_assessment": timing_a.to_dict(),
        "_cooccurrence_assessment": coocc_a.to_dict(),
        "_persistence_assessment": pers_a.to_dict(),
    }

    # Composite
    features = assess_human_likelihood(
        timestamps=timestamps,
        nearby_counts=nearby,
        durations_seconds=durations,
        iot_class="local_push",
    )
    actual_keys = features.payload_keys()

    # All hand-built keys must be present with identical values.
    # Composite is allowed to add ADDITIONAL keys (v1.12.12 added
    # `_is_device_managed`); they're covered by separate tests so
    # this assertion can stay focused on the legacy contract.
    for k, v in expected_keys.items():
        assert k in actual_keys, f"missing key in composite: {k}"
        assert actual_keys[k] == v, (
            f"value drift for {k}: expected={v}, got={actual_keys[k]}"
        )


def test_payload_keys_includes_canonical_device_managed_field() -> None:
    """v1.12.12: composite must emit `_is_device_managed: bool` so the
    card and Python filler-filter read one canonical verdict instead of
    re-implementing the 6-signal rule in two languages."""
    timestamps, nearby, durations = _make_inputs()
    features = assess_human_likelihood(
        timestamps=timestamps,
        nearby_counts=nearby,
        durations_seconds=durations,
        iot_class="local_push",
    )
    keys = features.payload_keys()
    assert "_is_device_managed" in keys
    assert isinstance(keys["_is_device_managed"], bool)


# ----- Shape contract -----

def test_features_dataclass_carries_all_three_assessments() -> None:
    """The composite must EXPOSE each sub-assessment (not just hide
    them behind apply_to). Future code may need direct access to
    e.g. features.timing.timing_class for routing decisions."""
    timestamps, nearby, durations = _make_inputs()
    features = assess_human_likelihood(
        timestamps=timestamps,
        nearby_counts=nearby,
        durations_seconds=durations,
        iot_class="local_push",
    )
    assert features.timing is not None
    assert features.cooccurrence is not None
    assert features.persistence is not None
    # Each is the underlying assessment type
    from custom_components.ha_insights.lib.cooccurrence_likelihood import (
        CooccurrenceAssessment,
    )
    from custom_components.ha_insights.lib.persistence_likelihood import (
        PersistenceAssessment,
    )
    from custom_components.ha_insights.lib.timing_likelihood import (
        TimingAssessment,
    )
    assert isinstance(features.timing, TimingAssessment)
    assert isinstance(features.cooccurrence, CooccurrenceAssessment)
    assert isinstance(features.persistence, PersistenceAssessment)


# ----- Clamping survives the chain -----

def test_v1540_transition_entropy_optional_backward_compat() -> None:
    """v1.5.40 added transition_entropy as the 4th grader. It's
    Optional so legacy callers (no distinct_entity_counts arg) get
    IDENTICAL results to v1.5.38/v1.5.39. This pins that contract."""
    timestamps, nearby, durations = _make_inputs()
    # Legacy call — no distinct_entity_counts
    legacy = assess_human_likelihood(
        timestamps=timestamps,
        nearby_counts=nearby,
        durations_seconds=durations,
        iot_class="local_push",
    )
    assert legacy.transition_entropy is None
    # apply_to skips the missing grader cleanly
    legacy_score = legacy.apply_to(0.8)
    # payload_keys doesn't include the new key
    assert "_transition_entropy_assessment" not in legacy.payload_keys()

    # New caller — distinct_entity_counts provided
    new_caller = assess_human_likelihood(
        timestamps=timestamps,
        nearby_counts=nearby,
        durations_seconds=durations,
        iot_class="local_push",
        distinct_entity_counts=[1, 1, 1, 1, 1, 1, 1, 1, 1, 1],  # routine
    )
    assert new_caller.transition_entropy is not None
    # Routine context = 1.0 multiplier, so score is identical to legacy
    assert abs(new_caller.apply_to(0.8) - legacy_score) < 1e-9
    # payload now includes the new key
    assert "_transition_entropy_assessment" in new_caller.payload_keys()


def test_v1540_novel_context_demotes() -> None:
    """When transition_entropy fires NOVEL_CONTEXT, the composite
    score drops by 0.75x vs the legacy chain."""
    timestamps, nearby, durations = _make_inputs()
    legacy = assess_human_likelihood(
        timestamps=timestamps,
        nearby_counts=nearby,
        durations_seconds=durations,
        iot_class="local_push",
    )
    legacy_score = legacy.apply_to(0.8)

    novel = assess_human_likelihood(
        timestamps=timestamps,
        nearby_counts=nearby,
        durations_seconds=durations,
        iot_class="local_push",
        distinct_entity_counts=[10, 12, 11, 9, 8, 10, 11, 9, 10, 11],  # novel
    )
    novel_score = novel.apply_to(0.8)
    # 0.75 multiplier on top of legacy
    assert abs(novel_score - legacy_score * 0.75) < 1e-9


def test_apply_to_clamps_overflow() -> None:
    """Worst-case overflow inputs should still produce [0, 1]."""
    timestamps, nearby, durations = _make_inputs()
    features = assess_human_likelihood(
        timestamps=timestamps,
        nearby_counts=nearby,
        durations_seconds=durations,
        iot_class="local_push",
    )
    # Way over 1.0 base
    assert features.apply_to(5.0) <= 1.0
    # Negative base
    assert features.apply_to(-1.0) >= 0.0


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
        except Exception as e:
            results.append((name, False, f"{type(e).__name__}: {e}"))
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} tests passed")
    for name, ok, err in results:
        marker = "OK" if ok else "FAIL"
        print(f"  [{marker}] {name}{'  -- ' + err if err else ''}")
    _sys.exit(0 if passed == len(results) else 1)
