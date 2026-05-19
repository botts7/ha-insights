"""Tests for lib/user_verdict_history.py — v1.14.3a.

Covers:
  - FingerprintDelta computation (added/removed/per-area)
  - is_empty / is_substantial heuristics
  - VerdictHistory invariants (sort order)
  - latest / latest_of_kind / latest_negative lookups
  - should_re_suggest decision rules
  - apply_rate / dismiss_rate math
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.ha_insights.lib.user_verdict_history import (
    EnvironmentalFingerprint,
    FingerprintDelta,
    Verdict,
    VerdictHistory,
    VerdictKind,
    apply_rate,
    diff_fingerprints,
    dismiss_rate,
    should_re_suggest,
)


def _fp(
    *,
    automations: set[str] | None = None,
    integrations: set[str] | None = None,
    sensors: dict[str, dict[str, int]] | None = None,
) -> EnvironmentalFingerprint:
    return EnvironmentalFingerprint(
        automation_ids=frozenset(automations or set()),
        sensors_per_area=dict(sensors or {}),
        active_integrations=frozenset(integrations or set()),
    )


def _v(
    kind: VerdictKind,
    *,
    at: datetime,
    fingerprint: EnvironmentalFingerprint | None = None,
    insight_id: str = "abc123",
) -> Verdict:
    return Verdict(
        insight_id=insight_id,
        kind=kind,
        timestamp=at,
        fingerprint=fingerprint or _fp(),
    )


# ---------- diff_fingerprints ----------------------------------------


def test_diff_empty_returns_empty_delta() -> None:
    delta = diff_fingerprints(_fp(), _fp())
    assert delta.is_empty
    assert not delta.is_substantial


def test_diff_added_automation() -> None:
    old = _fp(automations={"automation.a"})
    new = _fp(automations={"automation.a", "automation.b"})
    delta = diff_fingerprints(old, new)
    assert delta.automations_added == frozenset({"automation.b"})
    assert delta.automations_removed == frozenset()
    assert delta.is_substantial


def test_diff_removed_automation() -> None:
    old = _fp(automations={"automation.a", "automation.b"})
    new = _fp(automations={"automation.a"})
    delta = diff_fingerprints(old, new)
    assert delta.automations_removed == frozenset({"automation.b"})
    assert delta.automations_added == frozenset()
    assert delta.is_substantial


def test_diff_per_area_sensor_change() -> None:
    old = _fp(sensors={"kitchen": {"motion": 0, "temperature": 1}})
    new = _fp(sensors={"kitchen": {"motion": 1, "temperature": 1}})
    delta = diff_fingerprints(old, new)
    assert delta.sensors_added_per_area == {"kitchen": {"motion": 1}}
    assert delta.sensors_removed_per_area == {}
    assert delta.is_substantial


def test_diff_sensor_added_in_new_area() -> None:
    old = _fp(sensors={})
    new = _fp(sensors={"bedroom": {"temperature": 1}})
    delta = diff_fingerprints(old, new)
    assert delta.sensors_added_per_area == {"bedroom": {"temperature": 1}}


def test_diff_integration_added() -> None:
    old = _fp(integrations={"mqtt"})
    new = _fp(integrations={"mqtt", "zha"})
    delta = diff_fingerprints(old, new)
    assert delta.integrations_added == frozenset({"zha"})
    assert delta.is_substantial


def test_diff_only_removed_sensors_not_substantial() -> None:
    """User reducing data is not a reason to re-suggest."""
    old = _fp(sensors={"kitchen": {"motion": 1}})
    new = _fp(sensors={"kitchen": {"motion": 0}})
    delta = diff_fingerprints(old, new)
    assert delta.sensors_removed_per_area == {"kitchen": {"motion": 1}}
    assert not delta.is_substantial


def test_diff_only_removed_integration_not_substantial() -> None:
    old = _fp(integrations={"mqtt", "zha"})
    new = _fp(integrations={"mqtt"})
    delta = diff_fingerprints(old, new)
    assert delta.integrations_removed == frozenset({"zha"})
    assert not delta.is_substantial


# ---------- VerdictHistory invariants --------------------------------


def test_history_enforces_timestamp_order() -> None:
    later = datetime(2026, 5, 1, tzinfo=UTC)
    earlier = datetime(2026, 4, 1, tzinfo=UTC)
    with pytest.raises(ValueError):
        VerdictHistory(
            insight_id="x",
            verdicts=(
                _v(VerdictKind.DISMISS, at=later),
                _v(VerdictKind.APPLY, at=earlier),
            ),
        )


def test_history_latest_returns_last() -> None:
    t1 = datetime(2026, 1, 1, tzinfo=UTC)
    t2 = datetime(2026, 2, 1, tzinfo=UTC)
    h = VerdictHistory(
        insight_id="x",
        verdicts=(
            _v(VerdictKind.DISMISS, at=t1),
            _v(VerdictKind.APPLY, at=t2),
        ),
    )
    assert h.latest().kind == VerdictKind.APPLY


def test_history_latest_of_kind_walks_backwards() -> None:
    t1 = datetime(2026, 1, 1, tzinfo=UTC)
    t2 = datetime(2026, 2, 1, tzinfo=UTC)
    t3 = datetime(2026, 3, 1, tzinfo=UTC)
    h = VerdictHistory(
        insight_id="x",
        verdicts=(
            _v(VerdictKind.DISMISS, at=t1),
            _v(VerdictKind.APPLY, at=t2),
            _v(VerdictKind.DISMISS, at=t3),
        ),
    )
    assert h.latest_of_kind(VerdictKind.DISMISS).timestamp == t3
    assert h.latest_of_kind(VerdictKind.APPLY).timestamp == t2


def test_history_latest_negative_skips_positive() -> None:
    t1 = datetime(2026, 1, 1, tzinfo=UTC)
    t2 = datetime(2026, 2, 1, tzinfo=UTC)
    h = VerdictHistory(
        insight_id="x",
        verdicts=(
            _v(VerdictKind.DISMISS, at=t1),
            _v(VerdictKind.APPLY, at=t2),
        ),
    )
    assert h.latest_negative().kind == VerdictKind.DISMISS


def test_history_empty_returns_none() -> None:
    h = VerdictHistory(insight_id="x")
    assert h.latest() is None
    assert h.latest_negative() is None
    assert h.latest_of_kind(VerdictKind.APPLY) is None


# ---------- should_re_suggest ---------------------------------------


def test_re_suggest_empty_history_returns_false() -> None:
    assert (
        should_re_suggest(
            VerdictHistory(insight_id="x"),
            _fp(),
            now=datetime(2026, 5, 19, tzinfo=UTC),
        )
        is False
    )


def test_re_suggest_skips_when_last_verdict_positive() -> None:
    """User applied → don't pester, even if environment changed."""
    old_fp = _fp(automations={"automation.a"})
    new_fp = _fp(automations=set())
    history = VerdictHistory(
        insight_id="x",
        verdicts=(
            _v(
                VerdictKind.APPLY,
                at=datetime(2026, 1, 1, tzinfo=UTC),
                fingerprint=old_fp,
            ),
        ),
    )
    assert (
        should_re_suggest(history, new_fp, now=datetime(2026, 5, 19, tzinfo=UTC))
        is False
    )


def test_re_suggest_dismiss_plus_no_change_returns_false() -> None:
    fp = _fp(automations={"automation.a"})
    history = VerdictHistory(
        insight_id="x",
        verdicts=(
            _v(
                VerdictKind.DISMISS,
                at=datetime(2026, 1, 1, tzinfo=UTC),
                fingerprint=fp,
            ),
        ),
    )
    assert (
        should_re_suggest(history, fp, now=datetime(2026, 5, 19, tzinfo=UTC))
        is False
    )


def test_re_suggest_dismiss_plus_automation_removed_returns_true() -> None:
    """Classic AdaptiveFeedback case: user dismissed, then deleted the
    automation they were using instead → re-suggest."""
    old_fp = _fp(automations={"automation.lights_off"})
    new_fp = _fp(automations=set())
    history = VerdictHistory(
        insight_id="x",
        verdicts=(
            _v(
                VerdictKind.DISMISS,
                at=datetime(2026, 1, 1, tzinfo=UTC),
                fingerprint=old_fp,
            ),
        ),
    )
    assert (
        should_re_suggest(history, new_fp, now=datetime(2026, 5, 19, tzinfo=UTC))
        is True
    )


def test_re_suggest_dismiss_plus_new_sensor_returns_true() -> None:
    """A new sensor that could improve analysis → re-suggest."""
    old_fp = _fp(sensors={})
    new_fp = _fp(sensors={"bedroom": {"motion": 1}})
    history = VerdictHistory(
        insight_id="x",
        verdicts=(
            _v(
                VerdictKind.DISMISS,
                at=datetime(2026, 1, 1, tzinfo=UTC),
                fingerprint=old_fp,
            ),
        ),
    )
    assert (
        should_re_suggest(history, new_fp, now=datetime(2026, 5, 19, tzinfo=UTC))
        is True
    )


def test_re_suggest_cooldown_blocks_recent_dismiss() -> None:
    """User dismissed yesterday + automation gone today → still don't
    re-suggest. Cooldown prevents thrashing."""
    old_fp = _fp(automations={"automation.x"})
    new_fp = _fp(automations=set())
    now = datetime(2026, 5, 19, tzinfo=UTC)
    history = VerdictHistory(
        insight_id="x",
        verdicts=(
            _v(
                VerdictKind.DISMISS,
                at=now - timedelta(days=2),
                fingerprint=old_fp,
            ),
        ),
    )
    assert should_re_suggest(history, new_fp, now=now) is False


def test_re_suggest_retire_only_overridden_by_automation_removal() -> None:
    """Retire is the "permanent no" — only an automation removal can
    override it. New sensors / integrations alone aren't enough."""
    # Adding sensors after retire → still don't re-suggest.
    old_fp = _fp()
    new_fp = _fp(sensors={"bedroom": {"motion": 1}})
    history = VerdictHistory(
        insight_id="x",
        verdicts=(
            _v(
                VerdictKind.RETIRE,
                at=datetime(2026, 1, 1, tzinfo=UTC),
                fingerprint=old_fp,
            ),
        ),
    )
    assert (
        should_re_suggest(history, new_fp, now=datetime(2026, 5, 19, tzinfo=UTC))
        is False
    )

    # Removing the competing automation → DO re-suggest.
    old_fp = _fp(automations={"automation.competing"})
    new_fp = _fp(automations=set())
    history = VerdictHistory(
        insight_id="x",
        verdicts=(
            _v(
                VerdictKind.RETIRE,
                at=datetime(2026, 1, 1, tzinfo=UTC),
                fingerprint=old_fp,
            ),
        ),
    )
    assert (
        should_re_suggest(history, new_fp, now=datetime(2026, 5, 19, tzinfo=UTC))
        is True
    )


def test_re_suggest_after_apply_then_dismiss_uses_most_recent() -> None:
    """User applied, later dismissed (uninstalled the automation). The
    most recent verdict dictates behavior — re-suggest if env changed
    since the dismiss, not since the apply."""
    apply_fp = _fp(automations={"automation.a"})
    dismiss_fp = _fp(automations=set())  # automation already gone
    now_fp = _fp(automations=set(), integrations={"new_integration"})
    history = VerdictHistory(
        insight_id="x",
        verdicts=(
            _v(
                VerdictKind.APPLY,
                at=datetime(2026, 1, 1, tzinfo=UTC),
                fingerprint=apply_fp,
            ),
            _v(
                VerdictKind.DISMISS,
                at=datetime(2026, 2, 1, tzinfo=UTC),
                fingerprint=dismiss_fp,
            ),
        ),
    )
    # Env added an integration since the dismiss → re-suggest.
    assert (
        should_re_suggest(history, now_fp, now=datetime(2026, 5, 19, tzinfo=UTC))
        is True
    )


# ---------- apply_rate / dismiss_rate -------------------------------


def test_apply_rate_empty() -> None:
    assert apply_rate(()) == 0.0


def test_apply_rate_all_applies() -> None:
    verdicts = tuple(
        _v(VerdictKind.APPLY, at=datetime(2026, 1, i + 1, tzinfo=UTC))
        for i in range(3)
    )
    assert apply_rate(verdicts) == 1.0


def test_apply_rate_mixed() -> None:
    verdicts = (
        _v(VerdictKind.APPLY, at=datetime(2026, 1, 1, tzinfo=UTC)),
        _v(VerdictKind.DISMISS, at=datetime(2026, 1, 2, tzinfo=UTC)),
        _v(VerdictKind.DISMISS, at=datetime(2026, 1, 3, tzinfo=UTC)),
    )
    assert apply_rate(verdicts) == pytest.approx(1 / 3)


def test_apply_rate_ignores_snoozes() -> None:
    verdicts = (
        _v(VerdictKind.SNOOZE, at=datetime(2026, 1, 1, tzinfo=UTC)),
        _v(VerdictKind.SNOOZE, at=datetime(2026, 1, 2, tzinfo=UTC)),
        _v(VerdictKind.APPLY, at=datetime(2026, 1, 3, tzinfo=UTC)),
    )
    # 1 decisive verdict (the APPLY) → rate is 1.0
    assert apply_rate(verdicts) == 1.0


def test_dismiss_rate_excludes_retires() -> None:
    """Retires shouldn't penalize the detector's dismiss-rate stat.

    Retire is "permanent no" rather than "this specific suggestion no"
    — counting it as a dismiss would inflate the penalty beyond what
    the detector deserves."""
    verdicts = (
        _v(VerdictKind.APPLY, at=datetime(2026, 1, 1, tzinfo=UTC)),
        _v(VerdictKind.RETIRE, at=datetime(2026, 1, 2, tzinfo=UTC)),
    )
    # APPLY is the only decisive verdict for dismiss_rate.
    assert dismiss_rate(verdicts) == 0.0


def test_dismiss_rate_typical_mixed() -> None:
    verdicts = (
        _v(VerdictKind.APPLY, at=datetime(2026, 1, 1, tzinfo=UTC)),
        _v(VerdictKind.DISMISS, at=datetime(2026, 1, 2, tzinfo=UTC)),
        _v(VerdictKind.DISMISS, at=datetime(2026, 1, 3, tzinfo=UTC)),
        _v(VerdictKind.APPLY, at=datetime(2026, 1, 4, tzinfo=UTC)),
    )
    assert dismiss_rate(verdicts) == 0.5


# ---------- EnvironmentalFingerprint hashability --------------------


def test_fingerprint_hashable() -> None:
    """Required for use in sets / dict keys / dataclass(frozen=True)
    nesting."""
    fp1 = _fp(automations={"a"}, sensors={"kitchen": {"motion": 1}})
    fp2 = _fp(automations={"a"}, sensors={"kitchen": {"motion": 1}})
    assert hash(fp1) == hash(fp2)
    # Inverse: meaningfully-different fps should usually hash different.
    fp3 = _fp(automations={"b"})
    assert hash(fp1) != hash(fp3)


def test_fingerprint_delta_is_a_dataclass() -> None:
    """Smoke check that the public surface didn't drift."""
    delta = FingerprintDelta()
    assert delta.is_empty
    assert not delta.is_substantial
