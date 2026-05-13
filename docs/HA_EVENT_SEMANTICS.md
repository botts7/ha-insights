# Home Assistant State-Change Event Semantics — Ground Truth

Reference for HA Insights detector authors. Source: direct reading of
home-assistant/core at `the HA core checkout` (cloned
2026-05-13, HA dev branch).

This document tells you EXACTLY when HA fires `state_changed` events
and how the resulting stream differs from a naive "every state change
is independent" model. Every false-positive class our detectors have
hit traces to one of the gotchas below.

---

## Gotcha 1 — Group fan-out

**Behaviour:** When a group entity (e.g. `light.living_room_group`)
is toggled, the group does NOT emit state_changed events for its
members directly. Instead it forwards the service call to each
member via `hass.services.async_call(blocking=True, context=...)`.
Each member then fires its own state_changed independently. All
member events share the same `context.id`.

The group entity itself emits state_changed AFTER members report
back, based on its computed aggregate state.

**Source:** `homeassistant/components/group/light.py:171-186`
```python
await self.hass.services.async_call(
    light.DOMAIN, SERVICE_TURN_ON, data,
    blocking=True, context=self._context,
)
```

**Correlation key:** `context.id` is shared across all member
state_changed events from a single group toggle.

**Implication for detectors:** A burst of N entities all changing
within a few ms with the SAME `context.id` is one logical operation.
frequency_anomaly should treat this as ONE event, not N.
orphan_device should NOT flag a member that's been silent
individually if the group has been active (the member may be
slaved and not propagating its own events — see Gotcha 4).

---

## Gotcha 2 — Scene activation

**Behaviour:** Scene `turn_on` fires ONE state_changed for the
scene entity itself (timestamp update), then forwards target
service calls. Each target fires its own state_changed
asynchronously. context.id is shared across scene + target events.

**Source:** `homeassistant/components/scene/__init__.py:148-156`
```python
self._async_record_activation()    # timestamp update
self.async_write_ha_state()        # scene state_changed fires
await self.async_activate(**kwargs) # target service calls
```

**Edge case:** Scene state is stateless — only `last_activated`
timestamp. The scene's "state" doesn't reflect target outcomes.

**Implication for detectors:** Same as group fan-out — context.id
groups the operation. ManualHabitDetector should NOT flag each
target individually as a habit; the user's intent was "activate
scene X".

---

## Gotcha 3 — Script execution

**Behaviour:** A script's actions are processed sequentially (by
default) or in parallel (`mode: parallel`). Each action that
results in a state change fires its own state_changed. The script
entity itself does NOT fire state_changed unless the script
*entity* is toggled directly. All state_changed events from a
single script run share the same `context.id`.

**Source:** `homeassistant/components/script/__init__.py` →
`homeassistant/helpers/script.py`

**context.user_id behaviour:**
- Caller is a user → user_id is that user
- Caller is an automation → user_id is None, parent_id chains back
- Caller is a schedule / system → user_id is None

**Implication for detectors:** Use `context.user_id` to discriminate
manual habits from automation noise — but check `context.parent_id`
to see if the call chain originated from an automation that runs
*because* of a user action (still automated, not a habit).

---

## Gotcha 4 — Template entities (CRITICAL FOR FALSE POSITIVES)

**Behaviour:** Template entities fire state_changed ONLY when the
computed value changes. If the source entity updates but the
template result stays the same (boolean templates with multiple
sources hitting the same OR result), NO state_changed fires for
the template entity.

When the computed value IS the same as previous, HA fires
`EVENT_STATE_REPORTED` instead — a different event we don't
currently observe.

**Source:** `homeassistant/components/template/template_entity.py:90-143`
+ `homeassistant/core.py:2341` (same_state and same_attr check
that re-routes to STATE_REPORTED).

**Edge case:** `force_update: true` does NOT bypass this. HA's
state machine enforces same-state-no-event globally.

**Implication for detectors:**
- cooccurrence: a template entity that "follows" its source by
  definition will appear MORE correlated than physical entities.
  Pair detection should drop pairs where one entity's
  `attributes.source` or `attributes.entity_id` lists the other.
- orphan_device: a template entity going silent is meaningful
  (the computed value is stable, not that the device is offline).
  Don't flag template-domain entities as orphans.
- frequency_anomaly: same — templates can't run-away in the
  "stuck loop" sense; they just compute.

---

## Gotcha 5 — HA restart / bootstrap (CRITICAL FOR FALSE POSITIVES)

**Behaviour:** When HA boots, every entity platform calls
`_async_write_ha_state()` as it adds entities. Each call fires
state_changed with `old_state=None` and `new_state=<restored>`.
For a 500-entity install, that's 500 state_changed events
within the bootstrap window (~5 seconds).

**Source:** `homeassistant/core.py:2313-2402` (`async_set_internal`)
The check `old_state is None` sets `state.is_fresh = True`.

**Boundary marker:** `homeassistant_started` event fires once,
synchronously, AFTER all entity platforms are loaded.

**Implication for detectors:** Every restart looks like a
correlated burst. Without a filter:
- cooccurrence flags every "B follows A within seconds" pair
- frequency_anomaly might flag the burst day
- streak / schedule detect "midnight startup routine"

**Filter rule:** Drop state_changed events where `old_state is None`
unless the timestamp is more than 5 seconds after the most recent
`homeassistant_started`. HA's own automation state trigger has
this guard built in — we should mirror it.

---

## Gotcha 6 — `unavailable` state transitions

**Behaviour:** When an entity loses its source (network drop, MQTT
disconnect), the integration sets `available=False` and calls
`async_write_ha_state()`, which fires state_changed with
`new_state.state="unavailable"`. When the entity recovers, the
same mechanism fires state_changed back to the actual value.

**Source:** `homeassistant/helpers/entity.py:1056-1069`
```python
if not available:
    return STATE_UNAVAILABLE
```

**Edge case:** A flapping entity (lossy WiFi) can fire dozens of
`X → unavailable → X` events per hour. This is a REAL signal for
diagnostics but is noise for habit/schedule detection.

**Implication for detectors:**
- orphan_device: an entity whose LAST event was a transition TO
  `unavailable` is reporting a NETWORK issue, not a dead battery.
  Re-frame the insight.
- frequency_anomaly: filter out `unavailable ↔ X` transition
  events when computing baseline + today's count. Otherwise a
  device flapping at 50×/hr falsely looks like a runaway
  automation.
- All habit/routine detectors: skip events where
  `old_state == 'unavailable' OR new_state == 'unavailable'`.

---

## Gotcha 7 — Automation triggers on bootstrap

**Behaviour:** HA's `platform: state` trigger has a built-in guard
to ignore state_changed events where `old_state is None` (the
bootstrap fan-out). Users who explicitly set `from: null` opt
INTO bootstrap-triggered runs.

**Source:** `homeassistant/components/automation/__init__.py` →
`homeassistant/helpers/trigger.py`

**Implication for detectors:** This is a SIGNAL — if HA's own
state trigger filters bootstrap events, we should too. The fact
that core does this confirms our filter rule from Gotcha 5.

---

## Gotcha 8 — Recorder semantics

**Behaviour:** Recorder persists ONLY "significant" state changes.
The significance threshold is integration-specific: numeric
sensors round to a sane precision, binary states are always
significant. `get_significant_states` returns this filtered view,
not every single state_changed.

**Source:** `homeassistant/components/recorder/__init__.py` +
`recorder/history.py`

**Implication for detectors:** Backfill from recorder gives a
LOWER event count than live observation. Detectors that count
events (frequency_anomaly, streak) must distinguish:
- `today_count` from the live buffer (every event)
- `baseline_count` from recorder (significant events only)
Mixing the two inflates ratios. Currently we don't make this
distinction — worth a follow-up audit.

---

## Mentioned briefly

**`homeassistant_started` event:** Fires once after bootstrap. Use
as the bootstrap-window boundary for Gotcha 5 filter.

**device_tracker:** Fires state_changed on ZONE transitions, not
every GPS coordinate. So "home → not_home → home" is what we see,
not the underlying GPS jitter. Good — fewer false positives for
commute pattern detection.

**person.\*:** Derives state from device_trackers. Fires
state_changed when the computed person state changes (any tracker
moves the dial). Useful for presence inference; downstream of
device_tracker zone transitions.

---

## Top 3 broadest false-positive sources

1. **Bootstrap fan-out** (Gotcha 5): every HA restart looks like a
   correlated state burst. Every detector that counts events or
   detects correlation false-positives without an `old_state is
   None` filter.

2. **context.id batch correlation** (Gotchas 1-3): groups, scenes,
   and scripts produce N state_changed events for ONE logical
   user/automation intent. Without context.id grouping, every
   batch operation false-multiplies into N separate insights.

3. **Template entity false-correlation** (Gotcha 4): templates that
   compute from other entities will appear correlated with their
   sources by definition. Pair-discovery in cooccurrence /
   lagged_correlation must drop pairs where one is a template
   computed from the other.

---

## What we filter today (audit)

| Filter | Source code | Covers gotchas |
|---|---|---|
| Same-device dedup (frequency_anomaly) | `frequency_anomaly.py` device_id_by_entity | Partial — only entities on the SAME HA device |
| Symmetric dep map (cooccurrence) | `detectors/__init__.py` _build_entity_dependencies | Partial Gotcha 4 (parent↔child + sibling for small groups) |
| Container-to-members (RedundantTargetDetector) | `_build_container_map` | Partial Gotcha 1 (structural; doesn't use context.id) |
| Group-member orphan skip (v1.4.8) | `orphan_device._has_active_parent` | NEW — covers slaved-members per Gotcha 1 |
| Group-fanout candidate skip (v1.4.8) | `frequency_anomaly` parent-of map | NEW — covers fan-out per Gotcha 1 (but via structural map, not context.id — see TODO below) |
| `unavailable` filter | NOT IMPLEMENTED | Gotcha 6 missing — TODO |
| Bootstrap window filter | NOT IMPLEMENTED | Gotcha 5 missing — TODO |
| context.id batch correlator | NOT IMPLEMENTED | Gotchas 1-3 missing — TODO |
| Template-domain orphan skip | NOT IMPLEMENTED | Gotcha 4 missing — TODO |
| Recorder vs live distinction | NOT IMPLEMENTED | Gotcha 8 missing — TODO |

---

## Action items derived from this audit

The "TODO" rows above become the test-harness fixture set and the
filter work for the v1.5 line. Priority:

1. **Bootstrap-window filter** (Gotcha 5 — broadest impact)
2. **context.id batch correlation** (Gotchas 1-3 — applies across
   most detectors)
3. **`unavailable` transition filter** (Gotcha 6 — false alarms in
   orphan_device + frequency_anomaly)
4. **Template-source pair drop** (Gotcha 4 — cooccurrence /
   lagged_correlation cleanups)
5. **Recorder vs live distinction** (Gotcha 8 — quieter but
   inflates everything that mixes today vs baseline)

Each item is a fixture in `tests/_ha_semantics/` + filter code +
smoke-test regression.
