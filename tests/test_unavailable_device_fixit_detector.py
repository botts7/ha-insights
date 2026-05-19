"""Tests for UnavailableDeviceFixItDetector — v1.14.0.

Covers the four hours-stuck buckets (48-72 / 72-168 / 168-720 / 720+),
the skip rules (recent / wrong state / excluded domain / blocked /
registry-disabled / registry-hidden), and the payload structure
(integration deeplink, suggested actions, friendly_name).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from custom_components.ha_insights.detectors.base import DetectorContext
from custom_components.ha_insights.detectors.unavailable_device_fixit import (
    UnavailableDeviceFixItDetector,
    _suggested_actions,
)
from custom_components.ha_insights.insight import InsightKind

# ---------- Fake HA state + registry --------------------------------


@dataclass
class _FakeState:
    entity_id: str
    state: str
    last_changed: datetime
    attributes: dict[str, Any] = field(default_factory=dict)


class _FakeStateMachine:
    def __init__(self, states: list[_FakeState]) -> None:
        self._states = states

    def async_all(self) -> list[_FakeState]:
        return list(self._states)


class _FakeHass:
    def __init__(self, states: list[_FakeState]) -> None:
        self.states = _FakeStateMachine(states)


def _ctx(
    states: list[_FakeState],
    blocked: frozenset[str] = frozenset(),
    iot_classes: dict[str, str] | None = None,
) -> DetectorContext:
    return DetectorContext(
        hass=_FakeHass(states),
        blocked_entities=blocked,
        iot_class_by_integration=iot_classes or {},
    )


def _state(
    eid: str,
    value: str,
    hours_ago: float,
    friendly: str | None = None,
) -> _FakeState:
    return _FakeState(
        entity_id=eid,
        state=value,
        last_changed=datetime.now(tz=UTC) - timedelta(hours=hours_ago),
        attributes={"friendly_name": friendly} if friendly else {},
    )


# ---------- Bucket / confidence tests -------------------------------


@pytest.mark.asyncio
async def test_recently_unavailable_not_flagged() -> None:
    """24h stuck is below the 48h threshold — fine."""
    states = [_state("sensor.kitchen_temp", "unavailable", hours_ago=24)]
    insights = await UnavailableDeviceFixItDetector().scan(_ctx(states))
    assert insights == []


@pytest.mark.asyncio
async def test_48_to_72_hours_emits_with_low_confidence() -> None:
    """Just over threshold — could still be a transient outage."""
    states = [
        _state("sensor.bathroom_temp", "unavailable", hours_ago=50, friendly="Bath Temp"),
    ]
    insights = await UnavailableDeviceFixItDetector().scan(_ctx(states))
    assert len(insights) == 1
    assert insights[0].kind == InsightKind.ANOMALY
    assert insights[0].confidence == pytest.approx(0.65)
    assert "Bath Temp" in insights[0].title


@pytest.mark.asyncio
async def test_72_to_168_hours_emits_with_medium_confidence() -> None:
    states = [_state("sensor.outdoor", "unavailable", hours_ago=100)]
    insights = await UnavailableDeviceFixItDetector().scan(_ctx(states))
    assert len(insights) == 1
    assert insights[0].confidence == pytest.approx(0.78)


@pytest.mark.asyncio
async def test_168_to_720_hours_emits_with_high_confidence() -> None:
    """1-4 weeks stuck."""
    states = [_state("binary_sensor.garage_door", "unavailable", hours_ago=400)]
    insights = await UnavailableDeviceFixItDetector().scan(_ctx(states))
    assert len(insights) == 1
    assert insights[0].confidence == pytest.approx(0.88)


@pytest.mark.asyncio
async def test_over_720_hours_emits_with_highest_confidence() -> None:
    """4+ weeks — almost certainly abandoned/broken."""
    states = [_state("sensor.attic_temp", "unavailable", hours_ago=800)]
    insights = await UnavailableDeviceFixItDetector().scan(_ctx(states))
    assert len(insights) == 1
    assert insights[0].confidence == pytest.approx(0.95)
    assert insights[0].payload["hours_unavailable"] == 800


@pytest.mark.asyncio
async def test_unknown_state_also_flagged() -> None:
    """`unknown` is treated the same as `unavailable` — both signal a
    diagnostic state that doesn't self-resolve."""
    states = [_state("sensor.basement", "unknown", hours_ago=100)]
    insights = await UnavailableDeviceFixItDetector().scan(_ctx(states))
    assert len(insights) == 1
    assert insights[0].payload["current_state"] == "unknown"


# ---------- Skip rules ----------------------------------------------


@pytest.mark.asyncio
async def test_healthy_state_not_flagged() -> None:
    states = [_state("sensor.living_room_temp", "21.5", hours_ago=200)]
    insights = await UnavailableDeviceFixItDetector().scan(_ctx(states))
    assert insights == []


@pytest.mark.asyncio
async def test_blocked_entity_not_flagged() -> None:
    states = [_state("sensor.private_one", "unavailable", hours_ago=100)]
    insights = await UnavailableDeviceFixItDetector().scan(
        _ctx(states, blocked=frozenset({"sensor.private_one"})),
    )
    assert insights == []


@pytest.mark.asyncio
async def test_excluded_domain_not_flagged() -> None:
    """Automations / scripts / scenes / zones / sun never have these
    states in a healthy install; flagging them is noise."""
    states = [
        _state("automation.broken_one", "unavailable", hours_ago=100),
        _state("script.broken_two", "unavailable", hours_ago=100),
        _state("scene.broken_three", "unavailable", hours_ago=100),
        _state("zone.broken_four", "unavailable", hours_ago=100),
        _state("sun.sun", "unknown", hours_ago=100),
    ]
    insights = await UnavailableDeviceFixItDetector().scan(_ctx(states))
    assert insights == []


# ---------- Payload structure ---------------------------------------


@pytest.mark.asyncio
async def test_payload_includes_diagnostic_fields() -> None:
    states = [_state("light.hallway", "unavailable", hours_ago=100, friendly="Hall Light")]
    insights = await UnavailableDeviceFixItDetector().scan(_ctx(states))
    assert len(insights) == 1
    p = insights[0].payload
    assert p["kind"] == "unavailable_device_fixit"
    assert p["entity_id"] == "light.hallway"
    assert p["friendly_name"] == "Hall Light"
    assert p["current_state"] == "unavailable"
    assert p["hours_unavailable"] == 100
    assert p["threshold_hours"] == 48
    assert isinstance(p["suggested_actions"], list)
    assert len(p["suggested_actions"]) >= 3
    assert isinstance(p["observations"], list)
    assert p["observations"][0]["kind"] == "unavailable_duration"


@pytest.mark.asyncio
async def test_fingerprint_dedupes_repeat_scans() -> None:
    """Same entity in two scans should produce same insight id."""
    states = [_state("sensor.x", "unavailable", hours_ago=100)]
    first = await UnavailableDeviceFixItDetector().scan(_ctx(states))
    second = await UnavailableDeviceFixItDetector().scan(_ctx(states))
    assert first[0].id == second[0].id


# ---------- Suggested actions helper -------------------------------


def test_suggested_actions_cloud_integration() -> None:
    actions = _suggested_actions(
        domain="sensor",
        integration="nest",
        iot_class="cloud_push",
    )
    assert any("Cloud integration" in a for a in actions)
    assert any("nest" in a for a in actions)


def test_suggested_actions_local_integration() -> None:
    actions = _suggested_actions(
        domain="light",
        integration="zha",
        iot_class="local_push",
    )
    assert any("Local integration" in a for a in actions)
    assert any("zha" in a for a in actions)


def test_suggested_actions_device_tracker_gets_companion_hint() -> None:
    actions = _suggested_actions(
        domain="device_tracker",
        integration="mobile_app",
        iot_class="local_push",
    )
    assert any("Companion" in a for a in actions)


def test_suggested_actions_no_integration_falls_back_to_generic() -> None:
    actions = _suggested_actions(domain="sensor", integration=None, iot_class=None)
    assert any("[integration]" in a for a in actions)


def test_suggested_actions_always_includes_powered_check() -> None:
    actions = _suggested_actions(domain="sensor", integration="zha", iot_class="local_push")
    assert any("powered" in a.lower() for a in actions)


# ---------- v1.14.8 recorder-fallback path --------------------------


@pytest.mark.asyncio
async def test_recorder_fallback_rescues_post_restart_entity(
    monkeypatch,
) -> None:
    """Live last_changed is fresh (post-restart), but recorder shows
    the entity was non-unavailable >48h ago and unavailable ever since.
    Detector should USE the recorder timestamp and emit."""
    from custom_components.ha_insights.detectors import (
        unavailable_device_fixit as mod,
    )

    fresh_live_ts = datetime.now(tz=UTC) - timedelta(minutes=30)
    states = [
        _FakeState(
            entity_id="sensor.dead_for_weeks",
            state="unavailable",
            last_changed=fresh_live_ts,
            attributes={"friendly_name": "Dead For Weeks"},
        ),
    ]

    true_unavail_since = datetime.now(tz=UTC) - timedelta(days=10)

    async def _fake_recorder(_hass, eids, *, lookback_days, now):
        # Verify the helper got called with the right entity
        assert "sensor.dead_for_weeks" in eids
        return {"sensor.dead_for_weeks": true_unavail_since}

    monkeypatch.setattr(mod, "_recorder_unavailable_since", _fake_recorder)
    insights = await UnavailableDeviceFixItDetector().scan(_ctx(states))

    assert len(insights) == 1
    # 10 days * 24 hours = 240 hours → 720+ bucket would be 30 days,
    # so 168-720h bucket → 0.88 confidence.
    assert insights[0].confidence == pytest.approx(0.88)
    # 240 hours since recorder said it was last alive
    assert insights[0].payload["hours_unavailable"] == pytest.approx(240, abs=2)


@pytest.mark.asyncio
async def test_recorder_fallback_only_runs_for_suspect_entities(
    monkeypatch,
) -> None:
    """Entities whose live last_changed is already >48h ago do NOT
    need a recorder query; the helper is called only with the suspect
    set."""
    from custom_components.ha_insights.detectors import (
        unavailable_device_fixit as mod,
    )

    states = [
        _state("sensor.really_old", "unavailable", hours_ago=100),  # not suspect
        _state("sensor.fresh", "unavailable", hours_ago=10),  # suspect
    ]

    called_with: dict = {}

    async def _fake_recorder(_hass, eids, *, lookback_days, now):
        called_with["eids"] = list(eids)
        return {}

    monkeypatch.setattr(mod, "_recorder_unavailable_since", _fake_recorder)
    await UnavailableDeviceFixItDetector().scan(_ctx(states))
    assert called_with["eids"] == ["sensor.fresh"]


@pytest.mark.asyncio
async def test_recorder_returns_nothing_falls_back_to_live(
    monkeypatch,
) -> None:
    """If the recorder helper returns an empty dict (no data, query
    failed, etc.), the detector uses the live last_changed value
    unchanged — old behaviour preserved."""
    from custom_components.ha_insights.detectors import (
        unavailable_device_fixit as mod,
    )

    states = [_state("sensor.fresh", "unavailable", hours_ago=10)]

    async def _fake_recorder(_hass, eids, *, lookback_days, now):
        return {}

    monkeypatch.setattr(mod, "_recorder_unavailable_since", _fake_recorder)
    insights = await UnavailableDeviceFixItDetector().scan(_ctx(states))
    # 10h < 48h cutoff, no recorder rescue → no emission
    assert insights == []


@pytest.mark.asyncio
async def test_recorder_says_recently_alive_does_not_emit(
    monkeypatch,
) -> None:
    """Live last_changed says fresh, recorder confirms the entity
    was alive ~12 hours ago (so it really only just went unavailable).
    Detector should NOT emit — entity isn't stuck yet."""
    from custom_components.ha_insights.detectors import (
        unavailable_device_fixit as mod,
    )

    states = [_state("sensor.recent_drop", "unavailable", hours_ago=2)]
    recent_good = datetime.now(tz=UTC) - timedelta(hours=12)

    async def _fake_recorder(_hass, eids, *, lookback_days, now):
        return {"sensor.recent_drop": recent_good}

    monkeypatch.setattr(mod, "_recorder_unavailable_since", _fake_recorder)
    insights = await UnavailableDeviceFixItDetector().scan(_ctx(states))
    assert insights == []


@pytest.mark.asyncio
async def test_uses_min_of_live_and_recorder_timestamps(
    monkeypatch,
) -> None:
    """When both timestamps disagree, prefer the older one (entity was
    unavailable for at least as long as the earliest evidence)."""
    from custom_components.ha_insights.detectors import (
        unavailable_device_fixit as mod,
    )

    # Live says 20h ago, recorder says 100h ago → use 100h
    live_ts = datetime.now(tz=UTC) - timedelta(hours=20)
    recorder_ts = datetime.now(tz=UTC) - timedelta(hours=100)
    states = [
        _FakeState(
            entity_id="sensor.x",
            state="unavailable",
            last_changed=live_ts,
        ),
    ]

    async def _fake_recorder(_hass, eids, *, lookback_days, now):
        return {"sensor.x": recorder_ts}

    monkeypatch.setattr(mod, "_recorder_unavailable_since", _fake_recorder)
    insights = await UnavailableDeviceFixItDetector().scan(_ctx(states))
    assert len(insights) == 1
    # 100h falls in 72-168 bucket → 0.78
    assert insights[0].confidence == pytest.approx(0.78)
    assert insights[0].payload["hours_unavailable"] == pytest.approx(100, abs=1)
