"""Recorder-based backfill: populate StateEventBuffer from HA's history.

Day-one onboarding feature. Without this, fresh installs have to wait
1-2 weeks for live state events to accumulate before detectors see
enough data to surface insights. With it, the user opens the dashboard
seconds after install and insights are already there.

Honors privacy mode: this is local-only. No outbound network calls,
no LLM. We just read what HA's recorder already has.

Domain allowlist gates what we ingest — sensor noise (statistics,
diagnostics, signal_strength) doesn't help detectors and bloats the
buffer. Detectors filter further at scan time.
"""
from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from .state_event_buffer import StateEvent, StateEventBuffer

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, State

# Domains that are useful for routine detection. Excludes diagnostic /
# stats / weather entities that change too often or carry no behavioral
# signal. Users can extend later via config; for v0.4 first cut, fixed.
DEFAULT_DOMAINS: frozenset[str] = frozenset({
    "light",
    "switch",
    "binary_sensor",
    "fan",
    "climate",
    "cover",
    "lock",
    "media_player",
    "input_boolean",
    "input_select",
    "input_number",
    "scene",
    "script",
})


async def backfill(
    hass: HomeAssistant,
    buffer_: StateEventBuffer,
    *,
    lookback_days: int,
    allowed_domains: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Backfill the buffer from recorder history.

    Returns a summary: events_added, entities_seen, events_skipped, duration_seconds.
    Skipped events are typically ones outside the allowed domain list or with
    `unavailable` / `unknown` states (no behavioral signal).

    No-op if `lookback_days <= 0`.
    """
    if lookback_days <= 0:
        return {
            "events_added": 0,
            "entities_seen": 0,
            "events_skipped": 0,
            "duration_seconds": 0.0,
        }

    domains = allowed_domains if allowed_domains is not None else DEFAULT_DOMAINS
    end = datetime.now(tz=UTC).replace(microsecond=0)
    start = end - timedelta(days=lookback_days)

    # Resolve entity_id -> area_id once via the entity registry. Also use it
    # to enumerate which entities to query — modern recorder API requires
    # entity_ids to be passed explicitly (None is no longer accepted).
    from homeassistant.helpers import entity_registry as er

    entity_reg = er.async_get(hass)
    candidate_entity_ids = [
        entry.entity_id
        for entry in entity_reg.entities.values()
        if entry.entity_id.split(".", 1)[0] in domains
    ]
    # Also include states known to hass that aren't in the registry (yaml-only
    # entities) — they still appear in recorder.
    for state_eid in hass.states.async_entity_ids():
        if (
            state_eid not in entity_reg.entities
            and state_eid.split(".", 1)[0] in domains
        ):
            candidate_entity_ids.append(state_eid)

    if not candidate_entity_ids:
        return {
            "events_added": 0,
            "entities_seen": 0,
            "events_skipped": 0,
            "duration_seconds": 0.0,
            "lookback_days": lookback_days,
            "started_at": start.isoformat(),
        }

    started = time.monotonic()
    states_by_entity = await _fetch_history(hass, start, end, candidate_entity_ids)

    events_added = 0
    events_skipped = 0
    entities_seen = 0

    for entity_id, states in states_by_entity.items():
        domain = entity_id.split(".", 1)[0] if "." in entity_id else ""
        if domain not in domains:
            events_skipped += len(states)
            continue
        entities_seen += 1
        registry_entry = entity_reg.async_get(entity_id)
        area_id = registry_entry.area_id if registry_entry else None

        prior_state: str | None = None
        for state in states:
            new_state = state.state
            if new_state in {"unavailable", "unknown", "none", None}:
                events_skipped += 1
                prior_state = new_state
                continue
            ts = state.last_changed
            if ts is None:
                events_skipped += 1
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            event = StateEvent(
                timestamp=ts,
                entity_id=entity_id,
                domain=domain,
                area_id=area_id,
                old_state=prior_state,
                new_state=new_state,
                # v1.5 (Gotcha 8): tag provenance so detectors that
                # care about event-count parity can compensate for
                # recorder's significance filtering.
                source="recorder",
            )
            if buffer_.add(event):
                events_added += 1
            else:
                events_skipped += 1
            prior_state = new_state

    return {
        "events_added": events_added,
        "entities_seen": entities_seen,
        "events_skipped": events_skipped,
        "duration_seconds": round(time.monotonic() - started, 2),
        "lookback_days": lookback_days,
        "started_at": start.isoformat(),
    }


async def _fetch_history(
    hass: HomeAssistant,
    start: datetime,
    end: datetime,
    entity_ids: list[str],
) -> dict[str, list[State]]:
    """Pull significant states from the recorder, executor-bound.

    `get_significant_states` returns a dict keyed by entity_id with lists
    of State objects sorted by `last_changed`. Modern HA requires the
    entity_ids list to be explicit; the caller passes the domain-allowed
    set so recorder doesn't waste work on excluded entities.
    """
    from homeassistant.components.recorder import get_instance, history

    recorder = get_instance(hass)
    return await recorder.async_add_executor_job(
        history.get_significant_states,
        hass,
        start,
        end,
        entity_ids,
    )
