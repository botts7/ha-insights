"""HA-semantic event filters — standalone, HA-core-adoptable helpers.

This module collects the filters every HA-state-event consumer needs to
apply but most reinvent (or live with the false positives from skipping).
Every helper here is a pure function over the event's primitives — no
dependency on our integration's buffer, store, or detector base. The
module is designed to be **liftable straight into HA core**:

  custom_components/ha_insights/lib/event_filters.py
      → homeassistant/helpers/event_filters.py

with no edits beyond removing the docstring's relative-path examples.

---

## What goes wrong without these filters

Each filter corresponds to a documented Gotcha from
`docs/HA_EVENT_SEMANTICS.md`. Skipping any of them produces a specific
class of false positive in any detector / dashboard / automation
trigger that listens to `state_changed`:

| Gotcha # | Without the filter | This module's helper |
|---|---|---|
| Gotcha 1-3 | Same context.id fans out into N "independent" events — group toggle counted N times | `batch_correlator.py` (sibling module) |
| Gotcha 4 | Template / statistics / utility_meter entities correlate trivially with their source | `is_template_or_derived`, `COMPUTED_FROM_OTHER_PLATFORMS` |
| Gotcha 6 | Flaky devices emit `unavailable ↔ X` transitions that look like real state changes | `is_unavailable_transition`, `is_from_unavailable_state`, `UNAVAILABLE_STATES` |
| Gotcha 7 | First 2 seconds after HA start fan out 100s of `unknown → X` events | `is_bootstrap_event`, `BOOTSTRAP_FANOUT_SECONDS` |
| Gotcha 8 | Recorder-backfilled events have different rate-distribution than live ones; baselines drift | `is_recorder_sourced` (Protocol-based) |

---

## How to use

Most detectors want one of three composable predicates:

```python
from custom_components.ha_insights.lib.event_filters import (
    is_unavailable_transition,
    is_template_or_derived,
)

def is_candidate(ev) -> bool:
    if is_unavailable_transition(ev.old_state, ev.new_state):
        return False
    if is_template_or_derived(integration_of.get(ev.entity_id)):
        return False
    return True
```

For broader filtering (e.g. a buffer that pre-drops events), use the
default chain:

```python
from custom_components.ha_insights.lib.event_filters import default_event_filter
keep = default_event_filter(platform_of=integration_of.get)
events = [e for e in raw if keep(e)]
```
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, Protocol, runtime_checkable

# ---------- Constants -------------------------------------------------------

#: State values HA uses to mean "no data". A transition where EITHER
#: side is in this set is rarely "real behaviour" — it usually means
#: the integration just learned about the entity (or stopped knowing).
#: Detectors that look for behavioural patterns should drop these.
UNAVAILABLE_STATES: frozenset[str] = frozenset({
    "unavailable",
    "unknown",
    "none",
})

#: Integration platforms whose entities are COMPUTED from other
#: entities. Their state changes are structural — derived by definition
#: from the source. Treating them as independent observations makes
#: any cooccurrence/correlation detector produce trivially-true
#: results: `binary_sensor.template_motion` correlates 100% with its
#: source `binary_sensor.real_motion` because that's literally how it
#: was defined.
COMPUTED_FROM_OTHER_PLATFORMS: frozenset[str] = frozenset({
    "template",        # binary_sensor/sensor/light/switch.template
    "group",           # group.* derived from members
    "statistics",      # rolling stats over a source sensor
    "utility_meter",   # cumulative meter on a source
    "integration",     # integral of source over time
    "derivative",      # derivative of source
    "filter",          # smoothed source
    "min_max",         # aggregate over source set
    "threshold",       # binary derived from threshold check
    "trend",           # rising/falling state of source
    "history_stats",   # stats over source history
})

#: HA fires a flood of state_changed events in the first ~2 seconds
#: after startup as every entity transitions from "unknown" to its
#: persisted state. Counting those as real events spikes baselines.
#: Window is conservative; most installs settle within 1.5s.
BOOTSTRAP_FANOUT_SECONDS: float = 2.0


# ---------- Typed Protocol for state events --------------------------------


@runtime_checkable
class StateEventLike(Protocol):
    """Minimal shape any state event must satisfy for these helpers to
    operate on it. Lets the module work against our own `StateEvent`,
    HA's `Event` payload dict, recorder rows, or test fakes — anything
    with the right attributes.

    Attributes used:
      - `entity_id: str`
      - `old_state: str | None` (None for "added" events)
      - `new_state: str | None` (None for "removed" events)
      - `timestamp: datetime` (UTC preferred)
      - `from_bootstrap: bool` (optional — defaults to False if absent)
      - `source: str` (optional — "live" | "recorder"; default "live")
    """
    entity_id: str
    old_state: str | None
    new_state: str | None
    timestamp: datetime


# ---------- Atomic predicates ----------------------------------------------


def is_unavailable_state(state: str | None) -> bool:
    """True iff `state` is one of HA's "no data" sentinels.

    `unavailable` means the integration knows the entity exists but
    can't reach it. `unknown` means HA never received a real state.
    `none` is uncommon but appears for some templates that return
    `None`. All three are non-behavioural and should be filtered
    from any pattern-detection pipeline.

    `None` (the Python value) is NOT considered unavailable — it
    represents "the event has no old/new state" (e.g. an added or
    removed entity), which detectors handle separately.
    """
    return state is not None and state in UNAVAILABLE_STATES


def is_unavailable_transition(
    old_state: str | None,
    new_state: str | None,
) -> bool:
    """True iff EITHER side of this transition is an unavailable-ish
    state. The strict form — use this when ANY brush with unavailable
    should disqualify the event (frequency_anomaly, cooccurrence, etc.).
    """
    return is_unavailable_state(old_state) or is_unavailable_state(new_state)


def is_from_unavailable_state(old_state: str | None) -> bool:
    """True iff the PREVIOUS state was unavailable-ish. The lenient form
    — keeps real `X → unavailable` events (which signal "this thing is
    going offline") but drops the wake-up half (`unavailable → X`,
    which is just "we learned the state").

    Use this for daily-cadence detectors (streak, schedule,
    seasonality) where the wake-up pattern is the primary false-positive
    source (vehicle integrations, BLE proxies, sleepy Z-Wave devices).
    """
    return is_unavailable_state(old_state)


def is_template_or_derived(platform: str | None) -> bool:
    """True iff `platform` is one of the integration platforms whose
    entities are computed from other entities. See
    `COMPUTED_FROM_OTHER_PLATFORMS`."""
    return platform is not None and platform in COMPUTED_FROM_OTHER_PLATFORMS


def is_bootstrap_event(
    event_time: datetime,
    ha_start_time: datetime,
    window_seconds: float = BOOTSTRAP_FANOUT_SECONDS,
) -> bool:
    """True iff `event_time` falls within the bootstrap fan-out window
    after `ha_start_time`. Detectors should drop these — they're not
    behavioural events, they're "HA learning the state of the world
    after a restart".

    Both timestamps should be in the same timezone (UTC preferred).
    """
    delta = (event_time - ha_start_time).total_seconds()
    return 0.0 <= delta <= window_seconds


def is_recorder_sourced(ev: Any) -> bool:
    """True iff this event was loaded from recorder backfill (as
    opposed to being captured live). Returns False when the attribute
    is missing — events with no provenance are treated as live, which
    is the safe default.

    Detectors that compute rates (frequency_anomaly) should scale
    recorder-sourced events differently from live events: recorder
    rows are sampled at recorder commit cadence, which can compact or
    skip rapid-fire events that the live stream would have captured.
    """
    return getattr(ev, "source", "live") == "recorder"


# ---------- Pattern-value extraction ---------------------------------------


def pattern_value(ev: Any) -> str | None:
    """Return the value a pattern-matching detector should group/match on.

    For HA's native `event.*` platform entities, the *meaningful* value
    is `ev.event_type` (the attribute carrying "single_press" /
    "long_press" / "rotate_clockwise_step_3" / etc.). The entity's
    `state` is just a unique-per-fire timestamp — using it as the
    grouping key would make every fire its own group, defeating any
    streak / schedule / cooccurrence detection on event entities.

    For everything else, the value is `ev.new_state` (the entity's
    actual state — "on", "playing", "locked", etc.).

    Returns None when the value is missing or unusable:
      - event entity with no `event_type` attribute (older HA versions
        or misconfigured entities) — None
      - any entity with new_state == None (added/removed transitions
        we don't have a target value for) — None

    Caller must None-check; returning None lets detectors skip
    cleanly instead of grouping on a sentinel.
    """
    if getattr(ev, "domain", None) == "event":
        return getattr(ev, "event_type", None)
    return getattr(ev, "new_state", None)


# ---------- Composable filter chains ---------------------------------------


def default_event_filter(
    platform_of: Callable[[str], str | None] | None = None,
    *,
    drop_unavailable_transitions: bool = True,
    drop_template_derived: bool = True,
    drop_bootstrap: bool = True,
) -> Callable[[StateEventLike], bool]:
    """Build a `keep(event) -> bool` predicate composing the most-common
    filters. Each filter is enabled by default; pass `False` to disable.

    `platform_of` is an entity_id → platform lookup. Required only when
    `drop_template_derived=True`. Pass `None` and `drop_template_derived=False`
    if you don't have a hierarchy / entity registry available.

    Example:
        keep = default_event_filter(
            platform_of=hierarchy.integration_of.get,
        )
        events = [e for e in raw_events if keep(e)]
    """
    def keep(ev: StateEventLike) -> bool:
        if drop_unavailable_transitions and is_unavailable_transition(
            ev.old_state, ev.new_state
        ):
            return False
        if drop_template_derived and platform_of is not None:
            platform = platform_of(ev.entity_id)
            if is_template_or_derived(platform):
                return False
        if drop_bootstrap and getattr(ev, "from_bootstrap", False):
            return False
        return True

    return keep


def daily_pattern_filter(
    platform_of: Callable[[str], str | None] | None = None,
) -> Callable[[StateEventLike], bool]:
    """Stricter filter for daily-cadence detectors (streak, schedule,
    seasonality). Differs from `default_event_filter` by also dropping
    `unavailable → X` wake-up transitions (poll-cycle artifacts) AND
    `X → X` no-op transitions.

    Use this where same-time-every-day false positives are most
    damaging — vehicle integrations, sleepy BLE / Z-Wave devices,
    cloud-polled APIs.
    """
    base = default_event_filter(platform_of=platform_of)

    def keep(ev: StateEventLike) -> bool:
        if not base(ev):
            return False
        # Drop no-op transitions — old == new isn't a state change for
        # pattern purposes, even if HA fired the event (attribute-only
        # updates can do this).
        if ev.new_state is not None and ev.new_state == ev.old_state:
            return False
        # Drop FROM-unavailable wake-ups (the lenient unavailable
        # filter — already handled by default_event_filter's
        # both-sides check, but listed here for clarity if someone
        # disables that branch).
        if is_from_unavailable_state(ev.old_state):
            return False
        return True

    return keep


__all__ = [
    # Constants
    "BOOTSTRAP_FANOUT_SECONDS",
    "COMPUTED_FROM_OTHER_PLATFORMS",
    "UNAVAILABLE_STATES",
    # Protocols
    "StateEventLike",
    # Atomic predicates
    "is_bootstrap_event",
    "is_from_unavailable_state",
    "is_recorder_sourced",
    "is_template_or_derived",
    "is_unavailable_state",
    "is_unavailable_transition",
    # Pattern-value extraction (event.* aware)
    "pattern_value",
    # Composers
    "daily_pattern_filter",
    "default_event_filter",
]
