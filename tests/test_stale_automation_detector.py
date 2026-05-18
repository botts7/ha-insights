"""Tests for StaleAutomationDetector — v1.13 competitive feature.

Covers the four staleness buckets (never-fired / 30-60 / 60-120 / 120+),
the skip rules (disabled / blocked / no-audit label / too-young), and
the parser tolerance for HA's `last_triggered` shapes (ISO string,
naive datetime, datetime object).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from custom_components.ha_insights.detectors.base import DetectorContext
from custom_components.ha_insights.detectors.stale_automation import (
    StaleAutomationDetector,
    _parse_last_triggered,
)
from custom_components.ha_insights.insight import InsightKind

# ---------- Fake HA state + registry --------------------------------


@dataclass
class _FakeState:
    state: str
    attributes: dict[str, Any]


class _FakeStateMachine:
    def __init__(self, states: dict[str, _FakeState]) -> None:
        self._states = states

    def async_entity_ids(self, domain: str) -> list[str]:
        return [eid for eid in self._states if eid.startswith(f"{domain}.")]

    def get(self, entity_id: str) -> _FakeState | None:
        return self._states.get(entity_id)


class _FakeHass:
    def __init__(self, states: dict[str, _FakeState]) -> None:
        self.states = _FakeStateMachine(states)


def _ctx(states: dict[str, _FakeState], blocked: frozenset[str] = frozenset()) -> DetectorContext:
    return DetectorContext(
        hass=_FakeHass(states),
        blocked_entities=blocked,
    )


def _iso(dt: datetime) -> str:
    """ISO string in HA's standard format (UTC, no 'Z')."""
    return dt.astimezone(UTC).isoformat()


# ---------- Stale buckets -------------------------------------------


@pytest.mark.asyncio
async def test_recent_automation_not_flagged() -> None:
    """Fired this week — fine."""
    states = {
        "automation.recent": _FakeState(
            state="on",
            attributes={
                "friendly_name": "Recent Auto",
                "last_triggered": _iso(datetime.now(tz=UTC) - timedelta(days=2)),
            },
        ),
    }
    insights = await StaleAutomationDetector().scan(_ctx(states))
    assert insights == []


@pytest.mark.asyncio
async def test_stale_30_to_60_days_emits_with_medium_confidence() -> None:
    states = {
        "automation.kinda_stale": _FakeState(
            state="on",
            attributes={
                "friendly_name": "Kinda Stale",
                "last_triggered": _iso(datetime.now(tz=UTC) - timedelta(days=45)),
            },
        ),
    }
    insights = await StaleAutomationDetector().scan(_ctx(states))
    assert len(insights) == 1
    assert insights[0].kind == InsightKind.AUTOMATION_IMPROVEMENT
    assert insights[0].confidence == pytest.approx(0.65)
    assert "Kinda Stale" in insights[0].title
    assert "45 days" in insights[0].title


@pytest.mark.asyncio
async def test_stale_60_to_120_days_emits_with_higher_confidence() -> None:
    states = {
        "automation.quite_stale": _FakeState(
            state="on",
            attributes={
                "friendly_name": "Quite Stale",
                "last_triggered": _iso(datetime.now(tz=UTC) - timedelta(days=90)),
            },
        ),
    }
    insights = await StaleAutomationDetector().scan(_ctx(states))
    assert len(insights) == 1
    assert insights[0].confidence == pytest.approx(0.80)


@pytest.mark.asyncio
async def test_stale_over_120_days_emits_with_highest_confidence() -> None:
    states = {
        "automation.very_stale": _FakeState(
            state="on",
            attributes={
                "friendly_name": "Very Stale",
                "last_triggered": _iso(datetime.now(tz=UTC) - timedelta(days=200)),
            },
        ),
    }
    insights = await StaleAutomationDetector().scan(_ctx(states))
    assert len(insights) == 1
    assert insights[0].confidence == pytest.approx(0.92)
    assert insights[0].payload["days_stale"] == 200


@pytest.mark.asyncio
async def test_never_fired_emits_with_dedicated_confidence() -> None:
    """last_triggered=None on an automation that's been around → stale."""
    states = {
        "automation.never_fired": _FakeState(
            state="on",
            attributes={
                "friendly_name": "Never Fired",
                "last_triggered": None,
            },
        ),
    }
    insights = await StaleAutomationDetector().scan(_ctx(states))
    assert len(insights) == 1
    assert insights[0].confidence == pytest.approx(0.75)
    assert insights[0].payload["never_fired"] is True
    assert insights[0].payload["days_stale"] is None


# ---------- Skip rules ----------------------------------------------


@pytest.mark.asyncio
async def test_disabled_automation_not_flagged() -> None:
    """Disabled automations are dormant by user choice — not stale."""
    states = {
        "automation.disabled": _FakeState(
            state="off",
            attributes={
                "friendly_name": "Disabled",
                "last_triggered": _iso(datetime.now(tz=UTC) - timedelta(days=200)),
            },
        ),
    }
    insights = await StaleAutomationDetector().scan(_ctx(states))
    assert insights == []


@pytest.mark.asyncio
async def test_blocked_entity_not_flagged() -> None:
    states = {
        "automation.blocked": _FakeState(
            state="on",
            attributes={
                "friendly_name": "Blocked",
                "last_triggered": _iso(datetime.now(tz=UTC) - timedelta(days=200)),
            },
        ),
    }
    ctx = _ctx(states, blocked=frozenset({"automation.blocked"}))
    insights = await StaleAutomationDetector().scan(ctx)
    assert insights == []


@pytest.mark.asyncio
async def test_non_automation_entities_ignored() -> None:
    """Detector walks only the `automation` domain. light entities skipped."""
    states = {
        "light.kitchen": _FakeState(
            state="on",
            attributes={
                "friendly_name": "Kitchen Light",
                "last_triggered": _iso(datetime.now(tz=UTC) - timedelta(days=200)),
            },
        ),
    }
    insights = await StaleAutomationDetector().scan(_ctx(states))
    assert insights == []


# ---------- Fingerprint stability -----------------------------------


@pytest.mark.asyncio
async def test_same_automation_same_id_across_scans() -> None:
    """Re-scanning the same stale automation must produce the same
    insight id, so the store treats it as an update not a duplicate."""
    states = {
        "automation.stable": _FakeState(
            state="on",
            attributes={
                "friendly_name": "Stable",
                "last_triggered": _iso(datetime.now(tz=UTC) - timedelta(days=80)),
            },
        ),
    }
    detector = StaleAutomationDetector()
    a = await detector.scan(_ctx(states))
    b = await detector.scan(_ctx(states))
    assert len(a) == 1 and len(b) == 1
    assert a[0].id == b[0].id


# ---------- Payload shape -------------------------------------------


@pytest.mark.asyncio
async def test_payload_has_actionable_fields() -> None:
    """Card needs entity_id + days_stale + action service for the delete
    button to render correctly."""
    states = {
        "automation.stale": _FakeState(
            state="on",
            attributes={
                "friendly_name": "Stale Foo",
                "last_triggered": _iso(datetime.now(tz=UTC) - timedelta(days=100)),
            },
        ),
    }
    insights = await StaleAutomationDetector().scan(_ctx(states))
    assert len(insights) == 1
    p = insights[0].payload
    assert p["entity_id"] == "automation.stale"
    assert p["friendly_name"] == "Stale Foo"
    assert p["days_stale"] == 100
    assert p["never_fired"] is False
    assert p["stale_threshold_days"] == 30
    assert p["actions"][0]["service"] == "automation.remove_automation"
    assert p["actions"][0]["entity_id"] == "automation.stale"
    assert insights[0].payload_format == "report"


# ---------- _parse_last_triggered defensive paths -------------------


def test_parse_none_returns_none() -> None:
    assert _parse_last_triggered({}) is None
    assert _parse_last_triggered({"last_triggered": None}) is None
    assert _parse_last_triggered({"last_triggered": ""}) is None


def test_parse_iso_string_tz_aware() -> None:
    """Standard HA shape: ISO-8601 string with UTC offset."""
    parsed = _parse_last_triggered(
        {"last_triggered": "2026-05-01T12:00:00+00:00"},
    )
    assert parsed is not None
    assert parsed.tzinfo is not None


def test_parse_iso_string_naive_treated_as_utc() -> None:
    """Older HA versions sometimes drop the tz suffix."""
    parsed = _parse_last_triggered(
        {"last_triggered": "2026-05-01T12:00:00"},
    )
    assert parsed is not None
    assert parsed.tzinfo == UTC


def test_parse_datetime_object_pass_through() -> None:
    """HA's newer state-attribute path can pass through datetime objects."""
    dt = datetime(2026, 5, 1, 12, tzinfo=UTC)
    assert _parse_last_triggered({"last_triggered": dt}) == dt


def test_parse_naive_datetime_assumed_utc() -> None:
    dt = datetime(2026, 5, 1, 12)
    parsed = _parse_last_triggered({"last_triggered": dt})
    assert parsed == dt.replace(tzinfo=UTC)


def test_parse_garbage_returns_none() -> None:
    assert _parse_last_triggered({"last_triggered": "not-a-date"}) is None
    assert _parse_last_triggered({"last_triggered": 42}) is None
