"""In-memory rolling buffer of state-change events.

Default retention: 7 days; configurable. Pre-filtered to selected areas at
add() so unscoped domains never enter the buffer in the first place
(perf-critical on large installs per docs/ARCHITECTURE.md section
'Performance budget').

Persistence is opt-in (lands at step 7 with the SQLite store). Until then
this is the canonical event history that detectors query against.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


@dataclass(frozen=True)
class StateEvent:
    """A single state-change event.

    `context_user_id` is the HA user id that originated the change when
    the action came from the UI / voice assistant / mobile app, else
    None. Critical for ManualHabitDetector: a `user_id`-tagged change
    is a manual action; an untagged one is automation/system. The field
    is optional so backfilled events (from recorder, where the original
    context isn't fully reconstructible) can be stored with None.

    `from_bootstrap` flags state_changed events that fired during the
    HA boot fan-out (every entity platform writing its restored state
    within ~5s of EVENT_HOMEASSISTANT_STARTED with old_state=None).
    Detectors filter these by default — without it, every restart
    looks like a correlated burst and false-positives schedule /
    cooccurrence / frequency_anomaly. See docs/HA_EVENT_SEMANTICS.md
    Gotcha 5 for the full rationale.

    `context_id` is the correlation key for batch operations: a
    group toggle, scene activation, or script run produces N
    state_changed events that all share the SAME context_id.
    Detectors that want to detect "one logical user intent vs N
    independent events" group by this. See Gotchas 1-3.

    Upstream-PR candidate: HA core doesn't expose a stable
    "from_bootstrap" marker today. If this proves valuable across
    integrations, the StateEventBuffer pattern could be proposed
    upstream as `homeassistant.helpers.event.async_track_state_change_filtered`
    with a built-in bootstrap skip.
    """

    timestamp: datetime
    entity_id: str
    domain: str
    area_id: str | None
    old_state: str | None
    new_state: str | None
    context_user_id: str | None = None
    from_bootstrap: bool = False
    context_id: str | None = None
    # v1.5.18: parent_id distinguishes "automation chain" from "no
    # context at all". Combined with context_user_id and the entity's
    # integration locality (local vs cloud), this lets ManualHabit /
    # setup_quality count physical-switch presses as manual (they
    # have user_id=None AND parent_id=None AND come from local
    # integrations like zigbee2mqtt, esphome, mqtt, hue, etc.).
    # Cloud-app-managed entities (Tuya schedule, SmartThings routine)
    # stay excluded because their no-context signal is indistinguishable
    # from a real physical press to us.
    context_parent_id: str | None = None
    # v1.6: button-press attribution via HA's native `event` platform.
    # For domain == "event", `new_state` is a timestamp string (which
    # is unique per fire, useless for pattern matching). The MEANINGFUL
    # value is the `event_type` attribute — "single_press", "long_press",
    # "rotate_clockwise_step_3", etc. Captured here so detectors can
    # group by it instead of by the unique-per-fire timestamp state.
    # Populated only when domain == "event"; None for everything else.
    # See https://developers.home-assistant.io/docs/core/entity/event
    event_type: str | None = None
    # v1.5 (Gotcha 8): provenance — "live" (captured from the HA
    # event bus in real time) vs "recorder" (backfilled from
    # HA's recorder history). The two have different completeness:
    # recorder applies significance filters (numeric sensors round
    # to sane precision, similar-state writes are dropped), so an
    # entity that fires 100 state_changed events at the live bus
    # may show up as only 60-80 in recorder history. Detectors
    # that compare today_count (live) vs baseline_count (often
    # backfilled) need to be aware of the asymmetry or they
    # inflate ratios systematically.
    source: str = "live"


class StateEventBuffer:
    """Rolling in-memory buffer of state-change events.

    Bounded by `max_age` (default 7 days). Per-area filtering at add() keeps
    the buffer scoped to user-selected areas. O(n) prune and O(n) query where
    n = events currently buffered. For larger installs, indexed persistence
    lands at step 7.
    """

    DEFAULT_MAX_AGE = timedelta(days=7)
    # v1.0 review #13: hard count cap so a busy install (200+ entities at
    # 1 Hz state churn) can't OOM by accumulating state events faster
    # than `prune` runs. 500_000 events ≈ 50 MB of StateEvent objects in
    # CPython, which is well under what HA itself uses for recorder.
    # When the deque hits maxlen, deque.append silently drops the oldest;
    # we log a warning the first time we observe the cap engaging so the
    # user knows their lookback window is being trimmed by volume.
    DEFAULT_MAX_EVENTS = 500_000

    def __init__(
        self,
        *,
        max_age: timedelta | None = None,
        max_events: int | None = None,
        area_filter: frozenset[str] | None = None,
    ) -> None:
        self._max_age = max_age if max_age is not None else self.DEFAULT_MAX_AGE
        self._max_events = (
            max_events if max_events is not None else self.DEFAULT_MAX_EVENTS
        )
        self._area_filter = area_filter if area_filter is not None else frozenset()
        self._events: deque[StateEvent] = deque(maxlen=self._max_events)
        self._cap_warned: bool = False

    @property
    def max_age(self) -> timedelta:
        """Configured maximum age before events are pruned."""
        return self._max_age

    @property
    def area_filter(self) -> frozenset[str]:
        """Configured area filter; empty set means accept everything."""
        return self._area_filter

    def add(self, event: StateEvent) -> bool:
        """Add an event if it passes the area filter.

        Returns True if accepted, False if filtered out.

        When the buffer is at the count cap, deque.append drops the
        oldest event silently — the first time this happens we log a
        warning so the user knows their effective lookback window is
        being trimmed by volume rather than time.
        """
        if self._area_filter and event.area_id not in self._area_filter:
            return False
        if not self._cap_warned and len(self._events) >= self._max_events:
            import logging

            logging.getLogger(__name__).warning(
                "HA Insights state event buffer hit %d-event cap; oldest "
                "events will be dropped before they age out. Consider "
                "narrowing the area filter or shortening lookback_days.",
                self._max_events,
            )
            self._cap_warned = True
        self._events.append(event)
        return True

    def query(
        self,
        *,
        entity_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        include_bootstrap: bool = False,
    ) -> Iterator[StateEvent]:
        """Yield events matching the filter (left-inclusive, right-exclusive on time).

        `include_bootstrap=False` skips state_changed events that fired
        during HA's startup fan-out. See docs/HA_EVENT_SEMANTICS.md
        Gotcha 5 — every entity platform writes its restored state on
        boot with old_state=None, creating a correlated burst that
        false-positives most pattern detectors.
        """
        for ev in self._events:
            if entity_id is not None and ev.entity_id != entity_id:
                continue
            if since is not None and ev.timestamp < since:
                continue
            if until is not None and ev.timestamp >= until:
                continue
            if not include_bootstrap and ev.from_bootstrap:
                continue
            yield ev

    def prune(self, now: datetime | None = None) -> int:
        """Drop events older than max_age. Returns count removed.

        Assumes events were added in roughly chronological order (the common
        case from HA's event bus). Out-of-order older events past the cutoff
        will also be removed when prune walks past them.
        """
        if now is None:
            now = datetime.now(tz=UTC)
        cutoff = now - self._max_age
        removed = 0
        while self._events and self._events[0].timestamp < cutoff:
            self._events.popleft()
            removed += 1
        return removed

    def rename_entity(self, old_id: str, new_id: str) -> int:
        """Migrate buffered events from old_id to new_id. Returns count updated.

        Called by the entity-registry rename handler so a HA-side rename
        doesn't sever the history detectors rely on.
        """
        if old_id == new_id:
            return 0
        count = 0
        rebuilt: deque[StateEvent] = deque()
        for ev in self._events:
            if ev.entity_id == old_id:
                # v1.5 fix (ultrareview): preserve every StateEvent
                # field across rename, including v1.4/v1.5 additions
                # (context_user_id, from_bootstrap, context_id,
                # source). Original code only listed pre-v1.4 fields,
                # which silently zeroed the new ones on every rename
                # — breaking the bootstrap filter, batch correlator,
                # and recorder/live scaling for renamed entities.
                rebuilt.append(
                    StateEvent(
                        timestamp=ev.timestamp,
                        entity_id=new_id,
                        domain=ev.domain,
                        area_id=ev.area_id,
                        old_state=ev.old_state,
                        new_state=ev.new_state,
                        context_user_id=ev.context_user_id,
                        from_bootstrap=ev.from_bootstrap,
                        context_id=ev.context_id,
                        context_parent_id=ev.context_parent_id,
                        event_type=ev.event_type,
                        source=ev.source,
                    )
                )
                count += 1
            else:
                rebuilt.append(ev)
        self._events = rebuilt
        return count

    def clear(self) -> int:
        """Drop every event in the buffer. Returns count removed."""
        count = len(self._events)
        self._events.clear()
        return count

    def __len__(self) -> int:
        return len(self._events)

    def snapshot(self) -> tuple[StateEvent, ...]:
        """Return an immutable snapshot of every event currently buffered.

        Used by run_all_detectors to hand a frozen, thread-safe view to
        worker threads. The returned tuple is an O(n) copy at the moment
        of the call; concurrent add/prune calls afterward don't affect
        the snapshot. Cheap (single memcpy from deque to tuple) so it
        runs on the event loop before the heavy scan starts.
        """
        return tuple(self._events)
