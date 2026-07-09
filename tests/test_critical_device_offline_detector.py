"""Tests for CriticalDeviceOfflineDetector — v1.24.0.

Covers: full-device outage detection at the 60-minute gate, the
load-bearing criticality gate (automated vs actuator vs neither),
partial-outage skip, offline-since = newest last_changed, blocked
entities, deviceless entities, fingerprint stability, and payload
structure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from custom_components.ha_insights.detectors.base import DetectorContext
from custom_components.ha_insights.detectors.critical_device_offline import (
    CriticalDeviceOfflineDetector,
)
from custom_components.ha_insights.insight import InsightKind

# ---------- Fake HA state machine ------------------------------------


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


def _state(eid: str, value: str, minutes_ago: float) -> _FakeState:
    return _FakeState(
        entity_id=eid,
        state=value,
        last_changed=datetime.now(tz=UTC) - timedelta(minutes=minutes_ago),
    )


def _ctx(
    states: list[_FakeState],
    device_map: dict[str, str | None],
    automated: frozenset[str] = frozenset(),
    blocked: frozenset[str] = frozenset(),
) -> DetectorContext:
    return DetectorContext(
        hass=_FakeHass(states),
        device_id_by_entity=dict(device_map),
        entities_already_automated=automated,
        blocked_entities=blocked,
    )


# A wall switch device: relay (actuator) + a diagnostic sensor.
_SWITCH_DEV = "dev_wall_switch"
_SWITCH_MAP = {
    "switch.entrance_relay": _SWITCH_DEV,
    "sensor.entrance_power": _SWITCH_DEV,
}


def _switch_states(minutes_ago: float, value: str = "unavailable"):
    return [
        _state("switch.entrance_relay", value, minutes_ago),
        _state("sensor.entrance_power", value, minutes_ago),
    ]


# ---------- Positive cases -------------------------------------------


@pytest.mark.asyncio
async def test_actuator_device_offline_90min_emits() -> None:
    insights = await CriticalDeviceOfflineDetector().scan(
        _ctx(_switch_states(minutes_ago=90), _SWITCH_MAP)
    )
    assert len(insights) == 1
    ins = insights[0]
    assert ins.kind == InsightKind.ANOMALY
    assert ins.confidence == pytest.approx(0.80)
    assert ins.fingerprint == {
        "kind": "critical_device_offline",
        "device_id": _SWITCH_DEV,
    }
    assert ins.payload["minutes_offline"] >= 89
    assert "switch.entrance_relay" in ins.payload["entity_ids"]


@pytest.mark.asyncio
async def test_automation_linked_device_gets_higher_confidence() -> None:
    insights = await CriticalDeviceOfflineDetector().scan(
        _ctx(
            _switch_states(minutes_ago=90),
            _SWITCH_MAP,
            automated=frozenset({"switch.entrance_relay"}),
        )
    )
    assert len(insights) == 1
    assert insights[0].confidence == pytest.approx(0.90)
    assert insights[0].payload["automation_linked_entity_ids"] == [
        "switch.entrance_relay"
    ]


@pytest.mark.asyncio
async def test_sensor_only_device_flagged_when_automated() -> None:
    """No actuator, but an automation depends on it — load-bearing."""
    states = [_state("sensor.mailbox_battery", "unavailable", 120)]
    insights = await CriticalDeviceOfflineDetector().scan(
        _ctx(
            states,
            {"sensor.mailbox_battery": "dev_mailbox"},
            automated=frozenset({"sensor.mailbox_battery"}),
        )
    )
    assert len(insights) == 1
    assert insights[0].confidence == pytest.approx(0.90)


# ---------- Negative cases -------------------------------------------


@pytest.mark.asyncio
async def test_under_threshold_not_flagged() -> None:
    insights = await CriticalDeviceOfflineDetector().scan(
        _ctx(_switch_states(minutes_ago=30), _SWITCH_MAP)
    )
    assert insights == []


@pytest.mark.asyncio
async def test_partial_outage_not_flagged() -> None:
    """One entity still reporting → integration bug, not an outage."""
    states = [
        _state("switch.entrance_relay", "unavailable", 90),
        _state("sensor.entrance_power", "2.3", 5),
    ]
    insights = await CriticalDeviceOfflineDetector().scan(
        _ctx(states, _SWITCH_MAP)
    )
    assert insights == []


@pytest.mark.asyncio
async def test_sensor_only_unautomated_device_left_to_slow_path() -> None:
    states = [_state("sensor.spare_temp", "unavailable", 300)]
    insights = await CriticalDeviceOfflineDetector().scan(
        _ctx(states, {"sensor.spare_temp": "dev_spare"})
    )
    assert insights == []


@pytest.mark.asyncio
async def test_online_device_not_flagged() -> None:
    insights = await CriticalDeviceOfflineDetector().scan(
        _ctx(_switch_states(minutes_ago=90, value="on"), _SWITCH_MAP)
    )
    assert insights == []


@pytest.mark.asyncio
async def test_unknown_state_does_not_count_as_offline() -> None:
    insights = await CriticalDeviceOfflineDetector().scan(
        _ctx(_switch_states(minutes_ago=90, value="unknown"), _SWITCH_MAP)
    )
    assert insights == []


@pytest.mark.asyncio
async def test_deviceless_entities_ignored() -> None:
    states = [_state("switch.template_helper", "unavailable", 120)]
    insights = await CriticalDeviceOfflineDetector().scan(
        _ctx(states, {"switch.template_helper": None})
    )
    assert insights == []


@pytest.mark.asyncio
async def test_blocked_entity_excluded_from_device() -> None:
    """Blocking the only actuator removes the load-bearing signal."""
    states = [_state("switch.entrance_relay", "unavailable", 90)]
    insights = await CriticalDeviceOfflineDetector().scan(
        _ctx(
            states,
            {"switch.entrance_relay": _SWITCH_DEV},
            blocked=frozenset({"switch.entrance_relay"}),
        )
    )
    assert insights == []


# ---------- Edge cases -----------------------------------------------


@pytest.mark.asyncio
async def test_offline_since_is_newest_last_changed() -> None:
    """Sensor died 5 h ago, relay 30 min ago → device offline 30 min →
    under threshold, no insight yet."""
    states = [
        _state("switch.entrance_relay", "unavailable", 30),
        _state("sensor.entrance_power", "unavailable", 300),
    ]
    insights = await CriticalDeviceOfflineDetector().scan(
        _ctx(states, _SWITCH_MAP)
    )
    assert insights == []


@pytest.mark.asyncio
async def test_exactly_at_threshold_emits() -> None:
    insights = await CriticalDeviceOfflineDetector().scan(
        _ctx(_switch_states(minutes_ago=61), _SWITCH_MAP)
    )
    assert len(insights) == 1


@pytest.mark.asyncio
async def test_fingerprint_stable_across_rescans() -> None:
    det = CriticalDeviceOfflineDetector()
    first = await det.scan(_ctx(_switch_states(90), _SWITCH_MAP))
    second = await det.scan(_ctx(_switch_states(150), _SWITCH_MAP))
    assert first[0].id == second[0].id


@pytest.mark.asyncio
async def test_two_devices_two_insights() -> None:
    states = [
        *_switch_states(90),
        _state("light.garage_batten", "unavailable", 200),
    ]
    dev_map = dict(_SWITCH_MAP)
    dev_map["light.garage_batten"] = "dev_garage"
    insights = await CriticalDeviceOfflineDetector().scan(
        _ctx(states, dev_map)
    )
    assert len(insights) == 2
    assert {i.fingerprint["device_id"] for i in insights} == {
        _SWITCH_DEV,
        "dev_garage",
    }


@pytest.mark.asyncio
async def test_duration_rendering_in_title() -> None:
    insights = await CriticalDeviceOfflineDetector().scan(
        _ctx(_switch_states(minutes_ago=90), _SWITCH_MAP)
    )
    assert "90 minutes" in insights[0].title

    insights = await CriticalDeviceOfflineDetector().scan(
        _ctx(_switch_states(minutes_ago=60 * 26), _SWITCH_MAP)
    )
    assert "26 hours" in insights[0].title

    insights = await CriticalDeviceOfflineDetector().scan(
        _ctx(_switch_states(minutes_ago=60 * 24 * 3), _SWITCH_MAP)
    )
    assert "3 days" in insights[0].title
