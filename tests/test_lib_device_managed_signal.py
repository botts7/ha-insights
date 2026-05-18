"""Tests for v1.12.12 lib/device_managed_signal.py — canonical
"is this insight device-managed?" verdict shared between card and
Python filter."""
from __future__ import annotations

from custom_components.ha_insights.lib.device_managed_signal import (
    is_device_managed,
    is_device_managed_from_assessments,
)

# ---------------------------------------------------------------------------
# is_device_managed_from_assessments — typed entry point
# ---------------------------------------------------------------------------


def test_any_strong_signal_fires() -> None:
    """Each of the 3 strong signals on its own must trigger."""
    assert is_device_managed_from_assessments(timing_class="device_likely")
    assert is_device_managed_from_assessments(
        cooccurrence_class="isolated"
    )
    assert is_device_managed_from_assessments(
        persistence_class="fixed_cycle"
    )


def test_single_soft_signal_does_not_fire() -> None:
    """Soft signals individually are insufficient — only 3+ stacked."""
    assert not is_device_managed_from_assessments(
        timing_class="tight_pattern"
    )
    assert not is_device_managed_from_assessments(
        cooccurrence_class="ambiguous"
    )
    assert not is_device_managed_from_assessments(
        persistence_class="tight_duration"
    )
    assert not is_device_managed_from_assessments(
        transition_entropy_class="novel_context"
    )


def test_two_soft_signals_does_not_fire() -> None:
    """Two soft signals stacked is still under the threshold."""
    assert not is_device_managed_from_assessments(
        timing_class="tight_pattern",
        cooccurrence_class="ambiguous",
    )
    assert not is_device_managed_from_assessments(
        persistence_class="tight_duration",
        transition_entropy_class="novel_context",
    )


def test_three_soft_signals_fires() -> None:
    """Three soft signals stacked DO trigger the verdict."""
    assert is_device_managed_from_assessments(
        timing_class="tight_pattern",
        cooccurrence_class="ambiguous",
        persistence_class="tight_duration",
    )
    assert is_device_managed_from_assessments(
        cooccurrence_class="ambiguous",
        persistence_class="tight_duration",
        transition_entropy_class="novel_context",
    )


def test_one_strong_one_soft_fires() -> None:
    """Strong-alone already triggers; soft adds no harm but stays True."""
    assert is_device_managed_from_assessments(
        timing_class="device_likely",
        persistence_class="tight_duration",
    )


def test_human_classifications_do_not_fire() -> None:
    """The user's real-install case: streak with human_likely +
    human_context + fixed_cycle. The fixed_cycle strong signal MUST
    still trigger the verdict even though timing+cooccurrence say
    'human.' This is the v1.12.10 bug that caused the 10% inverter
    streak to slip through the Python filter."""
    assert is_device_managed_from_assessments(
        timing_class="human_likely",
        cooccurrence_class="human_context",
        persistence_class="fixed_cycle",
    )


def test_all_human_does_not_fire() -> None:
    """When EVERY signal says 'human', verdict is False."""
    assert not is_device_managed_from_assessments(
        timing_class="human_likely",
        cooccurrence_class="human_context",
        persistence_class="human_variable",
        transition_entropy_class="routine_context",
    )


def test_no_signals_does_not_fire() -> None:
    """Empty input → False (no opinion)."""
    assert not is_device_managed_from_assessments()


# ---------------------------------------------------------------------------
# is_device_managed — payload-dict entry point
# ---------------------------------------------------------------------------


def test_payload_with_canonical_strong_fires() -> None:
    payload = {
        "_persistence_assessment": {"persistence_class": "fixed_cycle"},
    }
    assert is_device_managed(payload)


def test_payload_with_three_soft_fires() -> None:
    payload = {
        "_timing_assessment": {"timing_class": "tight_pattern"},
        "_cooccurrence_assessment": {"cooccurrence_class": "ambiguous"},
        "_persistence_assessment": {"persistence_class": "tight_duration"},
    }
    assert is_device_managed(payload)


def test_payload_real_install_inverter_streak() -> None:
    """Reproduce the user's actual 2026-05-18 SQL DB row that escaped
    the v1.12.10 filter: streak at 10% confidence with fixed_cycle
    persistence but human-classified timing + cooccurrence."""
    payload = {
        "_timing_assessment": {"timing_class": "human_likely"},
        "_cooccurrence_assessment": {"cooccurrence_class": "human_context"},
        "_persistence_assessment": {
            "persistence_class": "fixed_cycle",
            "coefficient_of_variation": 0.0049,
        },
        "_transition_entropy_assessment": {
            "transition_entropy_class": "ambiguous_context",
        },
    }
    assert is_device_managed(payload)


def test_payload_missing_returns_false() -> None:
    assert not is_device_managed(None)
    assert not is_device_managed({})


def test_payload_malformed_assessment_block_skipped() -> None:
    """A non-dict assessment block must not crash — just skip it."""
    payload = {
        "_timing_assessment": "not a dict",
        "_persistence_assessment": {"persistence_class": "fixed_cycle"},
    }
    assert is_device_managed(payload)  # the valid block still fires


def test_payload_unknown_class_values_do_not_fire() -> None:
    """Class values we don't recognise (e.g. future grader output) are
    silently ignored — no false positives."""
    payload = {
        "_timing_assessment": {"timing_class": "some_new_class_v2"},
        "_persistence_assessment": {
            "persistence_class": "another_unknown_value"
        },
    }
    assert not is_device_managed(payload)
