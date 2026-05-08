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
    """A single state-change event."""

    timestamp: datetime
    entity_id: str
    domain: str
    area_id: str | None
    old_state: str | None
    new_state: str | None


class StateEventBuffer:
    """Rolling in-memory buffer of state-change events.

    Bounded by `max_age` (default 7 days). Per-area filtering at add() keeps
    the buffer scoped to user-selected areas. O(n) prune and O(n) query where
    n = events currently buffered. For larger installs, indexed persistence
    lands at step 7.
    """

    DEFAULT_MAX_AGE = timedelta(days=7)

    def __init__(
        self,
        *,
        max_age: timedelta | None = None,
        area_filter: frozenset[str] | None = None,
    ) -> None:
        self._max_age = max_age if max_age is not None else self.DEFAULT_MAX_AGE
        self._area_filter = area_filter if area_filter is not None else frozenset()
        self._events: deque[StateEvent] = deque()

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
        """
        if self._area_filter and event.area_id not in self._area_filter:
            return False
        self._events.append(event)
        return True

    def query(
        self,
        *,
        entity_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> Iterator[StateEvent]:
        """Yield events matching the filter (left-inclusive, right-exclusive on time)."""
        for ev in self._events:
            if entity_id is not None and ev.entity_id != entity_id:
                continue
            if since is not None and ev.timestamp < since:
                continue
            if until is not None and ev.timestamp >= until:
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
                rebuilt.append(
                    StateEvent(
                        timestamp=ev.timestamp,
                        entity_id=new_id,
                        domain=ev.domain,
                        area_id=ev.area_id,
                        old_state=ev.old_state,
                        new_state=ev.new_state,
                    )
                )
                count += 1
            else:
                rebuilt.append(ev)
        self._events = rebuilt
        return count

    def __len__(self) -> int:
        return len(self._events)
