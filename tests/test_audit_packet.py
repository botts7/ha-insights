"""Tests for audit/packet.py — observation generation.

Each test feeds a fake automation + buffer + hierarchy and asserts
the right Observations come out. Pure-logic except for the
StateEventBuffer mock (we feed events directly).
"""
from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))


class FakeBuffer:
    """Minimal stand-in for StateEventBuffer. Returns the events
    passed at construction, filtered by entity_id + since."""

    def __init__(self, events):
        self._events = list(events)

    def query(self, *, entity_id=None, since=None, until=None):
        for ev in self._events:
            if entity_id is not None and ev.entity_id != entity_id:
                continue
            if since is not None and ev.timestamp < since:
                continue
            if until is not None and ev.timestamp >= until:
                continue
            yield ev


def make_event(eid, ts, new_state):
    return SimpleNamespace(
        entity_id=eid,
        timestamp=ts,
        new_state=new_state,
        old_state=None,
        domain=eid.split(".", 1)[0],
    )


def test_long_on_duration_fires_when_observed_exceeds_for_clause():
    """Light stays on ~200 min on average; automation has for: 60 min.
    Expected: long_on_duration observation."""
    from custom_components.ha_insights.audit.packet import (
        OBS_LONG_ON_DURATION,
        build_audit_packet,
    )

    now = datetime(2026, 5, 11, 18, 0, tzinfo=UTC)
    # 6 on→off cycles, each lasting ~3.3h = 200 min
    events = []
    base = now - timedelta(days=6)
    for day in range(6):
        on_ts = base + timedelta(days=day, hours=8)
        off_ts = on_ts + timedelta(minutes=200)
        events.append(make_event("light.living_room", on_ts, "on"))
        events.append(make_event("light.living_room", off_ts, "off"))

    automation = {
        "id": "1",
        "alias": "Living room evening lights",
        "trigger": [{"platform": "state", "entity_id": "input_boolean.evening"}],
        "action": [
            {
                "service": "light.turn_on",
                "target": {"entity_id": "light.living_room"},
                "for": {"minutes": 60},
            },
        ],
    }

    packet = build_audit_packet(
        automation,
        buffer=FakeBuffer(events),
        hierarchy=None,
        recent_insights=None,
        now=now,
    )
    long_obs = [o for o in packet.observations if o.kind == OBS_LONG_ON_DURATION]
    assert long_obs, [o.kind for o in packet.observations]
    obs = long_obs[0]
    assert "light.living_room" in obs.text
    assert obs.metrics["mean_on_min"] >= 150
    assert obs.metrics["current_auto_off_min"] == 60


def test_silent_entity_fires_when_state_missing_from_machine():
    """`hass.states` has no entry for the target → silent observation."""
    from custom_components.ha_insights.audit.packet import (
        OBS_ENTITY_SILENT,
        build_audit_packet,
    )

    automation = {
        "id": "2",
        "alias": "Dead-entity reference",
        "trigger": [{"platform": "state", "entity_id": "binary_sensor.gone"}],
        "action": [{"service": "light.turn_on", "target": {"entity_id": "light.also_gone"}}],
    }
    packet = build_audit_packet(
        automation,
        buffer=FakeBuffer([]),
        hierarchy=None,
        live_states={},  # nothing in HA's state machine
        recent_insights=None,
        now=datetime(2026, 5, 11, tzinfo=UTC),
    )
    silent = [o for o in packet.observations if o.kind == OBS_ENTITY_SILENT]
    assert len(silent) >= 1, [o.kind for o in packet.observations]
    eids = {o.metrics["entity_id"] for o in silent}
    assert "binary_sensor.gone" in eids
    assert "light.also_gone" in eids


def test_silent_entity_does_NOT_fire_for_live_entities():
    """User-reported regression: silent_entity used to fire on entities
    that simply weren't in our scan_areas. Now it only fires when HA
    itself says the entity is missing or unavailable."""
    from custom_components.ha_insights.audit.packet import (
        OBS_ENTITY_SILENT,
        build_audit_packet,
    )

    automation = {
        "id": "3",
        "alias": "Healthy automation",
        "trigger": [{"platform": "state", "entity_id": "binary_sensor.motion"}],
        "action": [{"service": "light.turn_on", "target": {"entity_id": "light.x"}}],
    }
    live = {"binary_sensor.motion": "off", "light.x": "off"}
    packet = build_audit_packet(
        automation,
        buffer=FakeBuffer([]),
        hierarchy=None,
        live_states=live,
        recent_insights=None,
        now=datetime(2026, 5, 11, tzinfo=UTC),
    )
    silent = [o for o in packet.observations if o.kind == OBS_ENTITY_SILENT]
    assert not silent, (
        f"silent observation must NOT fire on live entities; got: "
        f"{[o.text for o in silent]}"
    )


def test_silent_entity_fires_when_unavailable_in_state_machine():
    """HA says state is `unavailable` → silent observation fires."""
    from custom_components.ha_insights.audit.packet import (
        OBS_ENTITY_SILENT,
        build_audit_packet,
    )

    automation = {
        "id": "4",
        "alias": "Sometimes-broken",
        "trigger": [{"platform": "state", "entity_id": "binary_sensor.broken"}],
        "action": [{"service": "light.turn_on", "target": {"entity_id": "light.x"}}],
    }
    live = {"binary_sensor.broken": "unavailable", "light.x": "off"}
    packet = build_audit_packet(
        automation,
        buffer=FakeBuffer([]),
        hierarchy=None,
        live_states=live,
        recent_insights=None,
        now=datetime(2026, 5, 11, tzinfo=UTC),
    )
    silent = [o for o in packet.observations if o.kind == OBS_ENTITY_SILENT]
    assert any(o.metrics.get("current_state") == "unavailable" for o in silent)


def test_silent_entity_skips_device_id_shaped_triggers():
    """Device_id-shaped trigger refs (32-char hex, no dot) are HA's
    `device_id:` triggers, not entity_ids. Don't flag them as dead."""
    from custom_components.ha_insights.audit.packet import (
        OBS_ENTITY_SILENT,
        build_audit_packet,
    )

    automation = {
        "id": "5",
        "alias": "Device trigger",
        "trigger": [
            {
                "platform": "device",
                "device_id": "d3b0e5d5317b2c325438bec38ffbe507",
            }
        ],
        "action": [
            {"service": "light.turn_on", "target": {"entity_id": "light.x"}}
        ],
    }
    packet = build_audit_packet(
        automation,
        buffer=FakeBuffer([]),
        hierarchy=None,
        live_states={"light.x": "off"},
        recent_insights=None,
        now=datetime(2026, 5, 11, tzinfo=UTC),
    )
    silent = [o for o in packet.observations if o.kind == OBS_ENTITY_SILENT]
    # The hex string was a device_id, NOT an entity_id — it should
    # never appear as a silent finding.
    assert not any(
        "d3b0e5d5" in (o.metrics.get("entity_id") or "")
        for o in silent
    )


def test_blocked_entities_short_circuit():
    """If every entity referenced by the automation is in the user's
    blocked_entities set, packet has zero observations (privacy opt-out)."""
    from custom_components.ha_insights.audit.packet import build_audit_packet

    automation = {
        "id": "6",
        "alias": "All-blocked",
        "trigger": [{"platform": "state", "entity_id": "binary_sensor.private"}],
        "action": [
            {"service": "light.turn_on", "target": {"entity_id": "light.private"}}
        ],
    }
    packet = build_audit_packet(
        automation,
        buffer=FakeBuffer([]),
        hierarchy=None,
        live_states={"binary_sensor.private": "off"},
        recent_insights=None,
        blocked_entities=frozenset(
            {"binary_sensor.private", "light.private"}
        ),
        now=datetime(2026, 5, 11, tzinfo=UTC),
    )
    assert packet.observations == []
