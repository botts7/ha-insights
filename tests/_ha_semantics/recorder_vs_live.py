"""Recorder vs live event-source fixtures.

The recorder applies significance filtering: numeric sensors round
to sane precision, similar-state writes are dropped, and only
"meaningful" changes get persisted. When ha-insights backfills
the buffer from recorder, it gets the filtered view. The live
event bus captures EVERY state_changed.

Without compensation, frequency_anomaly mixes a filtered baseline
(60-80% of true count) with an unfiltered today (100% of true
count), inflating ratios by ~25-67% systematically.

These fixtures let detector tests assert that the live/recorder
asymmetry is handled — events tagged source="recorder" should
get a baseline scale-up that brings them closer to live parity.

See docs/HA_EVENT_SEMANTICS.md Gotcha 8.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from custom_components.ha_insights.observers.state_event_buffer import (
        StateEvent,
        StateEventBuffer,
    )


def synth_recorder_baseline(
    buffer: StateEventBuffer,
    *,
    entity_id: str,
    start: datetime,
    days: int = 13,
    events_per_day: int = 4,
) -> list[StateEvent]:
    """Add `days × events_per_day` events tagged source="recorder",
    spaced uniformly across the days. Models a backfilled baseline
    period."""
    from custom_components.ha_insights.observers.state_event_buffer import (
        StateEvent,
    )

    out: list[StateEvent] = []
    domain = entity_id.split(".", 1)[0]
    for d in range(days):
        for i in range(events_per_day):
            # Spread across the day at non-clustered hours
            offset = timedelta(days=d, hours=6 + (i * 4))
            ev = StateEvent(
                timestamp=start + offset,
                entity_id=entity_id,
                domain=domain,
                area_id=None,
                old_state="off",
                new_state="on" if i % 2 == 0 else "off",
                source="recorder",
            )
            buffer.add(ev)
            out.append(ev)
    return out


def synth_live_today(
    buffer: StateEventBuffer,
    *,
    entity_id: str,
    today_start: datetime,
    event_count: int,
) -> list[StateEvent]:
    """Add today's live events (source defaults to "live").
    Used alongside synth_recorder_baseline to model the realistic
    mixed-source state of a running install."""
    from custom_components.ha_insights.observers.state_event_buffer import (
        StateEvent,
    )

    out: list[StateEvent] = []
    domain = entity_id.split(".", 1)[0]
    step = timedelta(minutes=max(1, (24 * 60) // max(1, event_count)))
    for i in range(event_count):
        ev = StateEvent(
            timestamp=today_start + step * i,
            entity_id=entity_id,
            domain=domain,
            area_id=None,
            old_state="off",
            new_state="on" if i % 2 == 0 else "off",
            source="live",
        )
        buffer.add(ev)
        out.append(ev)
    return out


__all__ = ["synth_live_today", "synth_recorder_baseline"]
