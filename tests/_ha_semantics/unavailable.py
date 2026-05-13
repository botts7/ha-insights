"""`unavailable` transition fixtures.

Synthesizes the state_changed stream HA produces when an entity
loses + regains availability (network drop, MQTT reconnect, etc.)
per docs/HA_EVENT_SEMANTICS.md Gotcha 6.

Mechanism in HA:
  - Integration sets `available=False` → entity's _stringify_state
    returns STATE_UNAVAILABLE → state_changed fires with
    new_state.state="unavailable".
  - When the integration recovers, available=True → real value
    returns → state_changed fires "unavailable → X".

A flapping entity (lossy WiFi, intermittent Zigbee) can produce
dozens of these per hour. Without filtering, frequency_anomaly
sees a 30× spike and orphan_device sees a recently-active entity.
Both are wrong — the device is broken/struggling, not running
away or working fine.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from custom_components.ha_insights.observers.state_event_buffer import (
        StateEvent,
        StateEventBuffer,
    )

STATE_UNAVAILABLE = "unavailable"  # matches homeassistant.const.STATE_UNAVAILABLE


def synth_unavailable_flap(
    buffer: "StateEventBuffer",
    *,
    entity_id: str,
    start: datetime,
    cycles: int = 5,
    cycle_minutes: int = 5,
    online_state: str = "on",
) -> list["StateEvent"]:
    """Add `cycles` rounds of online → unavailable → online events.
    Default 5 cycles spaced 5 minutes apart = a typical "flaky
    WiFi node" pattern.

    Returns the list of events added so tests can inspect them.
    """
    from custom_components.ha_insights.observers.state_event_buffer import (
        StateEvent,
    )

    domain = entity_id.split(".", 1)[0]
    out: list[StateEvent] = []
    for i in range(cycles):
        base = start + timedelta(minutes=cycle_minutes * i)
        # Online → unavailable
        ev_down = StateEvent(
            timestamp=base,
            entity_id=entity_id,
            domain=domain,
            area_id=None,
            old_state=online_state,
            new_state=STATE_UNAVAILABLE,
        )
        buffer.add(ev_down)
        out.append(ev_down)
        # Unavailable → online (10 seconds later)
        ev_up = StateEvent(
            timestamp=base + timedelta(seconds=10),
            entity_id=entity_id,
            domain=domain,
            area_id=None,
            old_state=STATE_UNAVAILABLE,
            new_state=online_state,
        )
        buffer.add(ev_up)
        out.append(ev_up)
    return out


def is_availability_transition(event: "StateEvent") -> bool:
    """True iff this event is a transition INTO or OUT OF the
    unavailable state. Detector filters use this to skip the
    event when computing rate / silence / co-occurrence."""
    return (
        event.old_state == STATE_UNAVAILABLE
        or event.new_state == STATE_UNAVAILABLE
    )


__all__ = [
    "STATE_UNAVAILABLE",
    "synth_unavailable_flap",
    "is_availability_transition",
]
