"""Pure-logic tests for lib/transition_entropy.py."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from custom_components.ha_insights.lib.transition_entropy import (  # noqa: E402
    TransitionEntropyClass,
    apply_to_confidence,
    assess_transition_entropy,
)


def test_insufficient_samples_returns_neutral() -> None:
    a = assess_transition_entropy([3, 2])
    assert a.transition_entropy_class is TransitionEntropyClass.INSUFFICIENT_DATA
    assert a.human_likelihood == 1.0
    assert a.sample_count == 2


def test_empty_input_handled() -> None:
    a = assess_transition_entropy([])
    assert a.transition_entropy_class is TransitionEntropyClass.INSUFFICIENT_DATA


def test_routine_context_classified() -> None:
    """Median ≤ 2 distinct entities = embedded in a stable routine."""
    a = assess_transition_entropy([1, 2, 1, 2, 0])
    assert a.transition_entropy_class is TransitionEntropyClass.ROUTINE_CONTEXT
    assert a.human_likelihood == 1.0


def test_ambiguous_context_classified() -> None:
    """Median 3-5 distinct entities = mixed context."""
    a = assess_transition_entropy([3, 4, 5, 3, 4])
    assert a.transition_entropy_class is TransitionEntropyClass.AMBIGUOUS_CONTEXT
    assert a.human_likelihood == 0.95


def test_novel_context_classified() -> None:
    """Median > 5 = random / coincidental context — not a stable routine."""
    a = assess_transition_entropy([8, 9, 10, 7, 8])
    assert a.transition_entropy_class is TransitionEntropyClass.NOVEL_CONTEXT
    assert a.human_likelihood == 0.75


def test_outlier_does_not_skew_classification() -> None:
    """One HA-restart burst doesn't pull median up."""
    # 4 events with 1 distinct + 1 event with 50 distinct (boot fanout)
    a = assess_transition_entropy([1, 1, 1, 1, 50])
    assert a.transition_entropy_class is TransitionEntropyClass.ROUTINE_CONTEXT


def test_to_dict_serialization_shape() -> None:
    a = assess_transition_entropy([1, 2, 1, 2, 0])
    d = a.to_dict()
    assert d["transition_entropy_class"] == "routine_context"
    assert isinstance(d["mean_distinct_entities"], (int, float))
    assert isinstance(d["median_distinct_entities"], (int, float))
    assert isinstance(d["human_likelihood"], float)


def test_apply_to_confidence_clamps() -> None:
    a = assess_transition_entropy([10, 12, 11, 9, 8])
    out = apply_to_confidence(0.8, a)
    assert 0.0 <= out <= 1.0
    # Novel context → 0.75 multiplier
    assert abs(out - 0.6) < 1e-9


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
