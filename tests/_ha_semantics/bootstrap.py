"""Bootstrap fan-out fixture.

Synthesizes the state_changed event stream HA produces on boot, per
docs/HA_EVENT_SEMANTICS.md Gotcha 5:
  - Every entity platform calls `_async_write_ha_state()` as it
    registers, firing state_changed with `old_state=None` and the
    restored state.
  - The burst happens within ~5 seconds of EVENT_HOMEASSISTANT_STARTED.
  - For a 500-entity install, that's 500 state_changed events in a
    tight window — which without filtering looks like a correlated
    routine to schedule / streak / cooccurrence / frequency_anomaly.

Usage in tests:
    buf = StateEventBuffer()
    synth_bootstrap_burst(
        buf,
        boot_at=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
        entities=["light.kitchen", "switch.outlet_1", "binary_sensor.door"],
    )
    # Default query skips all events
    assert list(buf.query()) == []
    # Opt-in returns them
    assert len(list(buf.query(include_bootstrap=True))) == 3
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from custom_components.ha_insights.observers.state_event_buffer import (
        StateEvent,
        StateEventBuffer,
    )


def synth_bootstrap_burst(
    buffer: "StateEventBuffer",
    *,
    boot_at: datetime,
    entities: list[str],
    restored_states: dict[str, str] | None = None,
    burst_duration: timedelta = timedelta(seconds=3),
) -> list["StateEvent"]:
    """Add a synthesized bootstrap fan-out to `buffer`.

    Args:
      boot_at: timestamp HA finishes booting (EVENT_HOMEASSISTANT_STARTED).
        The burst events are timestamped between `boot_at` and
        `boot_at + burst_duration`.
      entities: list of entity_ids that "appeared" during boot.
      restored_states: optional map of entity_id → restored value.
        Defaults to "on" for all (the value doesn't matter for
        bootstrap detection — old_state=None is what flags them).
      burst_duration: spread of the burst. HA typically completes
        in <5s; default of 3s gives realistic spacing without
        overlapping with potential mid-session events.

    Returns the list of StateEvents added so callers can inspect.
    """
    from custom_components.ha_insights.observers.state_event_buffer import (
        StateEvent,
    )

    restored = restored_states or {}
    added: list[StateEvent] = []
    if not entities:
        return added
    # Spread events uniformly across the burst duration. Mimics HA's
    # parallel-per-domain, serial-across-domains setup order.
    step = burst_duration / max(1, len(entities))
    for i, eid in enumerate(entities):
        ts = boot_at + (step * i)
        domain = eid.split(".", 1)[0]
        ev = StateEvent(
            timestamp=ts,
            entity_id=eid,
            domain=domain,
            area_id=None,
            old_state=None,  # ← the bootstrap marker
            new_state=restored.get(eid, "on"),
            from_bootstrap=True,
        )
        buffer.add(ev)
        added.append(ev)
    return added


def synth_normal_event(
    buffer: "StateEventBuffer",
    *,
    timestamp: datetime,
    entity_id: str,
    old_state: str = "off",
    new_state: str = "on",
    context_user_id: str | None = None,
    context_id: str | None = None,
) -> "StateEvent":
    """Add a single non-bootstrap event for control-group comparisons.
    `from_bootstrap` defaults to False so this is the "real activity"
    case that the bootstrap filter should NOT drop."""
    from custom_components.ha_insights.observers.state_event_buffer import (
        StateEvent,
    )

    domain = entity_id.split(".", 1)[0]
    ev = StateEvent(
        timestamp=timestamp,
        entity_id=entity_id,
        domain=domain,
        area_id=None,
        old_state=old_state,
        new_state=new_state,
        context_user_id=context_user_id,
        from_bootstrap=False,
        context_id=context_id,
    )
    buffer.add(ev)
    return ev


__all__ = ["synth_bootstrap_burst", "synth_normal_event"]
