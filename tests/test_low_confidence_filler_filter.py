"""Tests for v1.12.10 _is_low_confidence_filler — the filler-
insight suppression added after real-install testing showed
~5 noise insights per scan (10-15% confidence + already-automated
or device-managed tags)."""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from custom_components.ha_insights.detectors import (
    _FILLER_INSIGHT_MAX_CONFIDENCE,
    _is_low_confidence_filler,
)


def _ins(
    *,
    confidence: float,
    conflicts_with: tuple = (),
    timing_class: str | None = None,
) -> SimpleNamespace:
    """Build a minimal duck-typed insight stand-in for the filter."""
    payload: dict = {}
    if timing_class is not None:
        payload["_timing_assessment"] = {"timing_class": timing_class}
    return SimpleNamespace(
        confidence=confidence,
        conflicts_with=conflicts_with,
        payload=payload,
        created_at=datetime.now(tz=UTC),
    )


# ---------- Suppression cases (matches user-reported noise) ------------


def test_low_conf_already_automated_is_filtered() -> None:
    """User's actual case: schedule at 10% confidence with
    `🔁 already automated` (conflicts_with non-empty)."""
    insight = _ins(confidence=0.10, conflicts_with=("automation.foo",))
    assert _is_low_confidence_filler(insight)


def test_low_conf_device_managed_is_filtered() -> None:
    """User's actual case: streak at 11% with `🤖 device-managed`
    timing pill."""
    insight = _ins(confidence=0.11, timing_class="device_likely")
    assert _is_low_confidence_filler(insight)


def test_low_conf_both_tags_is_filtered() -> None:
    """Belt + suspenders — both signals present."""
    insight = _ins(
        confidence=0.15,
        conflicts_with=("automation.bar",),
        timing_class="device_likely",
    )
    assert _is_low_confidence_filler(insight)


# ---------- Preservation cases (must NOT filter) -----------------------


def test_high_conf_already_automated_preserved() -> None:
    """High-confidence shadowed insights ARE actionable — the user
    might want to refine or replace the existing automation. Don't
    suppress just because there's a conflict."""
    insight = _ins(confidence=0.85, conflicts_with=("automation.x",))
    assert not _is_low_confidence_filler(insight)


def test_high_conf_device_managed_preserved() -> None:
    """High-confidence device-managed insights still help users
    understand WHY a pattern looks the way it does."""
    insight = _ins(confidence=0.75, timing_class="device_likely")
    assert not _is_low_confidence_filler(insight)


def test_low_conf_without_filler_signals_preserved() -> None:
    """Low confidence alone doesn't make an insight filler. Some
    detectors emit low-confidence insights that are still
    legitimate — e.g. a schedule with only 5 days of data may have
    low confidence but be a real emerging pattern."""
    insight = _ins(confidence=0.20)
    assert not _is_low_confidence_filler(insight)


def test_low_conf_tight_pattern_preserved() -> None:
    """TIGHT_PATTERN is different from DEVICE_LIKELY — it indicates
    a coincident user routine, not device-internal logic. Surface
    those even at low confidence; the user may want to know."""
    insight = _ins(confidence=0.20, timing_class="tight_pattern")
    assert not _is_low_confidence_filler(insight)


# ---------- Boundary conditions ----------------------------------------


def test_at_threshold_not_filtered() -> None:
    """Exactly at the threshold is NOT filtered — strict less-than."""
    insight = _ins(
        confidence=_FILLER_INSIGHT_MAX_CONFIDENCE,
        conflicts_with=("automation.x",),
    )
    assert not _is_low_confidence_filler(insight)


def test_just_below_threshold_filtered() -> None:
    insight = _ins(
        confidence=_FILLER_INSIGHT_MAX_CONFIDENCE - 0.01,
        conflicts_with=("automation.x",),
    )
    assert _is_low_confidence_filler(insight)


# ---------- Defensive ---------------------------------------------------


def test_missing_payload_handled() -> None:
    """Insight without a payload (or with payload=None) must not
    crash the filter."""
    insight = SimpleNamespace(
        confidence=0.10,
        conflicts_with=("automation.x",),
        payload=None,
    )
    # conflicts_with present → filtered regardless of payload
    assert _is_low_confidence_filler(insight)


def test_malformed_timing_assessment_handled() -> None:
    """`_timing_assessment` not a dict → ignore it gracefully."""
    insight = SimpleNamespace(
        confidence=0.10,
        conflicts_with=(),
        payload={"_timing_assessment": "not a dict"},
    )
    # No conflicts + malformed timing → not filtered
    assert not _is_low_confidence_filler(insight)


def test_missing_confidence_treated_as_high() -> None:
    """If somehow confidence isn't on the insight, default to 1.0
    (don't filter — let it surface and the user can react)."""
    insight = SimpleNamespace(
        conflicts_with=("automation.x",),
        payload={"_timing_assessment": {"timing_class": "device_likely"}},
    )
    # getattr default = 1.0 → above threshold → not filtered
    assert not _is_low_confidence_filler(insight)
