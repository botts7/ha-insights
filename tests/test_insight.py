"""Tests for the Insight contract."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from custom_components.ha_insights.insight import Insight, InsightKind


def _valid_kwargs(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "abc123",
        "kind": InsightKind.AUTOMATION_PROPOSAL,
        "detector": "schedule",
        "area_id": "area_1",
        "title": "Weekday morning routine",
        "confidence": 0.85,
        "fingerprint": {"entity": "light.kitchen", "weekday_minute": 407},
        "payload": {"trigger": {"platform": "time", "at": "06:47"}},
        "payload_format": "blueprint",
        "created_at": datetime(2026, 5, 8, 12, 0, tzinfo=UTC),
    }
    base.update(overrides)
    return base


def test_insight_constructs_with_minimum_fields() -> None:
    insight = Insight(**_valid_kwargs())
    assert insight.kind is InsightKind.AUTOMATION_PROPOSAL
    assert insight.confidence == 0.85
    assert insight.conflicts_with == ()
    assert insight.explanation is None
    assert insight.snoozed_until is None


def test_insight_is_frozen() -> None:
    insight = Insight(**_valid_kwargs())
    with pytest.raises(Exception):  # noqa: PT011 — FrozenInstanceError or AttributeError
        insight.confidence = 0.5  # type: ignore[misc]


def test_confidence_lower_bound_rejected() -> None:
    with pytest.raises(ValueError, match="confidence"):
        Insight(**_valid_kwargs(confidence=-0.1))


def test_confidence_upper_bound_rejected() -> None:
    with pytest.raises(ValueError, match="confidence"):
        Insight(**_valid_kwargs(confidence=1.1))


def test_confidence_zero_and_one_accepted() -> None:
    Insight(**_valid_kwargs(confidence=0.0))
    Insight(**_valid_kwargs(confidence=1.0))


def test_payload_format_unknown_rejected() -> None:
    with pytest.raises(ValueError, match="payload_format"):
        Insight(**_valid_kwargs(payload_format="bogus"))


def test_payload_format_all_documented_accepted() -> None:
    for fmt in ("blueprint", "automation", "card", "group", "scene"):
        Insight(**_valid_kwargs(payload_format=fmt))


def test_compute_id_stable_across_calls() -> None:
    fp = {"entity": "light.kitchen", "weekday_minute": 407}
    a = Insight.compute_id(InsightKind.AUTOMATION_PROPOSAL, fp)
    b = Insight.compute_id(InsightKind.AUTOMATION_PROPOSAL, fp)
    assert a == b
    assert len(a) == 24  # blake2b digest_size=12 -> 24 hex chars


def test_compute_id_distinguishes_kinds() -> None:
    fp = {"entity": "light.kitchen"}
    auto_id = Insight.compute_id(InsightKind.AUTOMATION_PROPOSAL, fp)
    anomaly_id = Insight.compute_id(InsightKind.ANOMALY, fp)
    assert auto_id != anomaly_id


def test_compute_id_distinguishes_fingerprint() -> None:
    a = Insight.compute_id(
        InsightKind.AUTOMATION_PROPOSAL, {"entity": "light.kitchen"}
    )
    b = Insight.compute_id(
        InsightKind.AUTOMATION_PROPOSAL, {"entity": "light.bedroom"}
    )
    assert a != b


def test_compute_id_canonicalizes_dict_order() -> None:
    a = Insight.compute_id(InsightKind.ANOMALY, {"a": 1, "b": 2})
    b = Insight.compute_id(InsightKind.ANOMALY, {"b": 2, "a": 1})
    assert a == b


def test_insight_kind_values_stable() -> None:
    """The string values of InsightKind are part of the stable contract."""
    assert InsightKind.AUTOMATION_PROPOSAL.value == "automation_proposal"
    assert InsightKind.CARD_PROPOSAL.value == "card_proposal"
    assert InsightKind.GROUP_PROPOSAL.value == "group_proposal"
    assert InsightKind.ANOMALY.value == "anomaly"
    assert InsightKind.DASHBOARD_CLEANUP.value == "dashboard_cleanup"
    assert InsightKind.SCENE_PROPOSAL.value == "scene_proposal"
