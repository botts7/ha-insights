"""context.id batch fan-out fixtures.

Synthesizes the state_changed streams HA produces for the three
batch operations that share a context.id across all member events
(docs/HA_EVENT_SEMANTICS.md Gotchas 1-3):

  - Group toggle: light.living_room → fans out to members
  - Scene activation: scene.evening → fans out to scene targets
  - Script run: script.bedtime → fans out to script actions

Used by detector tests to assert that the batch correlator
collapses these into ONE logical operation (not N independent
events).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from custom_components.ha_insights.observers.state_event_buffer import (
        StateEvent,
        StateEventBuffer,
    )


def synth_group_toggle(
    buffer: StateEventBuffer,
    *,
    at: datetime,
    member_entities: list[str],
    new_state: str = "on",
    member_spread_ms: int = 50,
    context_id: str | None = None,
    context_user_id: str | None = None,
) -> tuple[str, list[StateEvent]]:
    """Synthesize a group toggle: each member fires state_changed
    with the SAME context_id, spread across a tight window (HA
    service calls complete in <200ms typically; default 50ms*N
    keeps the synthesized stream realistic).

    Returns (context_id_used, events_added) for tests to assert on.
    """
    from custom_components.ha_insights.observers.state_event_buffer import (
        StateEvent,
    )

    ctx = context_id or uuid.uuid4().hex
    added: list[StateEvent] = []
    for i, eid in enumerate(member_entities):
        ts = at + timedelta(milliseconds=member_spread_ms * i)
        domain = eid.split(".", 1)[0]
        ev = StateEvent(
            timestamp=ts,
            entity_id=eid,
            domain=domain,
            area_id=None,
            old_state="off",
            new_state=new_state,
            context_user_id=context_user_id,
            context_id=ctx,
        )
        buffer.add(ev)
        added.append(ev)
    return ctx, added


def synth_scene_activation(
    buffer: StateEventBuffer,
    *,
    at: datetime,
    target_entities: list[str],
    context_user_id: str | None = None,
) -> tuple[str, list[StateEvent]]:
    """Same shape as a group toggle — each target gets its own
    state_changed with the shared scene context. The scene entity
    itself fires too (HA records a `last_activated` timestamp update)
    but we omit it here since our detectors don't watch scene.*
    entities.
    """
    return synth_group_toggle(
        buffer,
        at=at,
        member_entities=target_entities,
        context_user_id=context_user_id,
    )


def synth_script_run(
    buffer: StateEventBuffer,
    *,
    at: datetime,
    action_entities: list[str],
    sequential: bool = True,
    step_ms: int = 100,
    context_user_id: str | None = None,
) -> tuple[str, list[StateEvent]]:
    """Script with N actions, each touching one entity. `sequential=True`
    spreads events across step_ms*N (typical default-mode script);
    `sequential=False` collapses them within step_ms (parallel-mode).

    All events share the script's context_id.
    """
    spread_ms = step_ms if sequential else step_ms // max(1, len(action_entities))
    return synth_group_toggle(
        buffer,
        at=at,
        member_entities=action_entities,
        member_spread_ms=spread_ms,
        context_user_id=context_user_id,
    )


__all__ = [
    "synth_group_toggle",
    "synth_scene_activation",
    "synth_script_run",
]
