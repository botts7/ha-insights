"""AuditPacket — structured observations about one existing automation.

Built from the 14-day live state buffer + entity hierarchy + recent
detector findings. NEVER queries the HA recorder inline — that's
the job of `audit/rollup.py` (Phase A2), which materializes
long-term aggregates into a cache the packet reads from cheaply.

Privacy invariants enforced here:
  - All observations are aggregate stats (counts, means, ratios).
    No raw timestamps. No per-event tuples.
  - Entity IDs are preserved in the structure but redacted by the
    LLM pipeline downstream (Redactor) — this module does not call
    the LLM and does not need to know about pseudonym mapping.
  - blocked_entities (the user's per-entity opt-out list) is
    honored: any automation whose targets/triggers all live in
    blocked_entities returns an empty packet.

Reuse: the Observation primitives in this file are the shared
vocabulary for the rest of the v1.1 detector roadmap (dormant,
condition_too_strict, energy_hog, weather, household_rhythm).
Add new primitives here; consume them from any detector.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..observers.state_event_buffer import StateEventBuffer
    from .._script_targets import collect_script_targets  # noqa: F401
    from ..detectors.hierarchy import EntityHierarchy
    from ..insight import Insight


# Observation kinds. Stable strings (not enum) so consumers — including
# the LLM prompt — can branch on them.
OBS_LONG_ON_DURATION = "long_on_duration"
OBS_TRIGGER_TIME_DRIFT = "trigger_time_drift"
OBS_ENTITY_SILENT = "entity_silent"
OBS_REDUNDANT_TARGET = "redundant_target"
OBS_HAS_RECENT_INSIGHTS = "has_recent_insights"
OBS_NEVER_FIRED = "never_fired_in_buffer"
OBS_INSUFFICIENT_DATA = "insufficient_data"


@dataclass(frozen=True)
class Observation:
    """One concrete, deterministic finding about an automation.

    `kind` — stable string identifier (see OBS_* constants).
    `text` — plain-English single sentence ready to render as a row.
    `confidence` — 0..1; combine into the parent insight's confidence.
    `metrics` — raw numbers backing the observation. The LLM prompt
                may reference these directly for precise edits.
    """

    kind: str
    text: str
    confidence: float
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AuditPacket:
    """Everything we know about one existing automation, structured.

    Consumed by:
      - AutomationAuditDetector (Phase B): renders as an
        AUTOMATION_IMPROVEMENT insight.
      - audit/llm.py (Phase C): serialized into the LLM prompt.

    A packet with no observations is silent — the detector should
    NOT emit an insight in that case (no story to tell).
    """

    automation_id: str
    automation_alias: str
    automation_yaml: dict[str, Any]
    observations: list[Observation] = field(default_factory=list)
    related_insight_ids: list[str] = field(default_factory=list)
    target_entities: frozenset[str] = field(default_factory=frozenset)
    trigger_entities: frozenset[str] = field(default_factory=frozenset)


# Thresholds for the deterministic observation primitives. Conservative
# — the goal is to surface things the user clearly cares about, not to
# nitpick every automation. Tunable later via OptionsFlow if needed.
_LONG_ON_MIN_OBS = 5  # need 5+ on-cycles to compute a mean
_LONG_ON_THRESHOLD_MIN = 60  # mean on-time >= 60 min is "long"
_TRIGGER_DRIFT_MIN_OBS = 5
_TRIGGER_DRIFT_THRESHOLD_MIN = 5  # >= 5 min difference
_SILENT_THRESHOLD_DAYS = 7  # no transitions in 7+ days = silent
_LOOKBACK_DAYS = 14


def build_audit_packet(
    automation: dict[str, Any],
    *,
    buffer: "StateEventBuffer | None",
    hierarchy: "EntityHierarchy | None",
    recent_insights: list["Insight"] | None = None,
    blocked_entities: frozenset[str] = frozenset(),
    trace_aggregates: Any | None = None,
    rollup_by_entity: dict[str, dict[str, dict[int, int]]] | None = None,
    live_states: dict[str, str] | None = None,
    now: datetime | None = None,
) -> AuditPacket:
    """Build an AuditPacket for one automation. Pure function.

    The caller has already loaded the automation YAML from HA's
    config + the live state buffer from the scan context. We just
    walk what's already in memory.

    Empty observations list means we have nothing to say about this
    automation — the detector should skip emitting an insight for it.
    """
    from ..apply.conflict_scanner import _as_list, _extract_target_entities

    if now is None:
        now = datetime.now(tz=UTC)

    automation_id = (
        automation.get("id") or automation.get("alias") or "unknown"
    )
    automation_alias = automation.get("alias") or automation_id

    # Extract target + trigger entities so future observation primitives
    # can iterate without re-parsing the YAML each time.
    target_entities: set[str] = _extract_target_entities(
        automation.get("action")
    )
    trigger_entities: set[str] = set()
    for trig in _as_list(automation.get("trigger")):
        if not isinstance(trig, dict):
            continue
        tid = trig.get("entity_id")
        if isinstance(tid, str):
            trigger_entities.add(tid)
        elif isinstance(tid, list):
            trigger_entities.update(e for e in tid if isinstance(e, str))

    # Privacy gate: if every entity touched by this automation is in
    # the user's blocklist, return an empty packet. The user already
    # said "don't look at these"; respect that for the audit too.
    all_entities = target_entities | trigger_entities
    if all_entities and all_entities <= blocked_entities:
        return AuditPacket(
            automation_id=automation_id,
            automation_alias=automation_alias,
            automation_yaml=automation,
            observations=[],
            target_entities=frozenset(target_entities),
            trigger_entities=frozenset(trigger_entities),
        )

    observations: list[Observation] = []

    # ---- Short-term observations from the live 14d buffer ----
    if buffer is not None and target_entities:
        observations.extend(
            _observe_long_on_duration(
                target_entities=target_entities,
                automation=automation,
                buffer=buffer,
                now=now,
            )
        )
        observations.extend(
            _observe_trigger_time_drift(
                automation=automation, buffer=buffer, now=now
            )
        )
        observations.extend(
            _observe_silent_entities(
                entities=target_entities | trigger_entities,
                buffer=buffer,
                live_states=live_states or {},
                now=now,
            )
        )

    # ---- Structural observation: redundant container/member targets ----
    if hierarchy is not None and len(target_entities) >= 2:
        observations.extend(
            _observe_redundant_targets(
                target_entities=target_entities,
                hierarchy=hierarchy,
            )
        )

    # ---- Trace-derived observations: ground truth from HA itself ----
    # Pre-fetched by the detector on the event loop and passed in.
    # Each entry is a dict {kind, text, confidence, metrics}; convert
    # to Observation here to keep the trace module decoupled from
    # this file (avoids circular imports).
    if trace_aggregates is not None:
        from .traces import observations_from_traces

        for obs_dict in observations_from_traces(trace_aggregates, now=now):
            observations.append(
                Observation(
                    kind=obs_dict["kind"],
                    text=obs_dict["text"],
                    confidence=obs_dict["confidence"],
                    metrics=obs_dict.get("metrics", {}),
                )
            )

    # ---- Long-term rollup observations (Phase A2) ----
    # Pre-fetched from the audit_rollups cache by the detector
    # (cheap SELECT, no recorder query). Skipped entirely when no
    # rollup exists yet — first-scan installs get only short-term
    # findings until the rollup scheduler catches up.
    if rollup_by_entity:
        from .rollup import observations_from_rollups

        for eid in sorted(all_entities):
            entity_rollups = rollup_by_entity.get(eid)
            if not entity_rollups:
                continue
            for obs_dict in observations_from_rollups(eid, entity_rollups):
                observations.append(
                    Observation(
                        kind=obs_dict["kind"],
                        text=obs_dict["text"],
                        confidence=obs_dict["confidence"],
                        metrics=obs_dict.get("metrics", {}),
                    )
                )

    # ---- Join: any recent insights touching these entities ----
    related_ids: list[str] = []
    if recent_insights and all_entities:
        for ins in recent_insights:
            # Pull primary entity ids from the insight's fingerprint.
            ins_eids: set[str] = set()
            fp = ins.fingerprint
            for key in (
                "entity_id",
                "leader_entity_id",
                "follower_entity_id",
                "target_entity_id",
            ):
                v = fp.get(key)
                if isinstance(v, str) and "." in v:
                    ins_eids.add(v)
            members = fp.get("_member_entities")
            if isinstance(members, (list, tuple)):
                ins_eids.update(
                    m for m in members if isinstance(m, str) and "." in m
                )
            if ins_eids & all_entities:
                related_ids.append(ins.id)
        if related_ids:
            observations.append(
                Observation(
                    kind=OBS_HAS_RECENT_INSIGHTS,
                    text=(
                        f"{len(related_ids)} recent detector finding"
                        f"{'s' if len(related_ids) != 1 else ''} "
                        "touch entities this automation uses — review "
                        "those for context before refining."
                    ),
                    confidence=0.7,
                    metrics={"count": len(related_ids)},
                )
            )

    return AuditPacket(
        automation_id=automation_id,
        automation_alias=automation_alias,
        automation_yaml=automation,
        observations=observations,
        related_insight_ids=related_ids,
        target_entities=frozenset(target_entities),
        trigger_entities=frozenset(trigger_entities),
    )


# ---------------------------------------------------------------------------
# Observation primitives. Each is a small pure function that returns 0+
# Observations. Keeping them separate makes them unit-testable and reusable.
# ---------------------------------------------------------------------------


def _observe_long_on_duration(
    *,
    target_entities: set[str],
    automation: dict[str, Any],
    buffer: "StateEventBuffer",
    now: datetime,
) -> list[Observation]:
    """If the automation's `turn_on` action runs for entities whose
    observed average on-time is much longer than any auto-off in the
    action chain, flag it. Pattern: user wrote `turn_on` but no
    `turn_off`, the lights stay on for hours."""
    from ..apply.conflict_scanner import _as_list

    # Only run when the automation has at least one turn_on / homeassistant.turn_on
    # action targeting any of these entities.
    has_turn_on = False
    has_auto_off_min: int | None = None
    for action in _as_list(automation.get("action")):
        if not isinstance(action, dict):
            continue
        svc = action.get("service") or ""
        if isinstance(svc, str) and svc.endswith(".turn_on"):
            has_turn_on = True
        # Look for a `delay` followed by turn_off, or a `for:` duration.
        # Skip the formal parsing — finding a relevant numeric duration
        # is a hint, not a guarantee.
        for_clause = action.get("for")
        if isinstance(for_clause, dict):
            mins = (
                for_clause.get("minutes", 0) * 1
                + for_clause.get("hours", 0) * 60
                + for_clause.get("seconds", 0) // 60
            )
            if mins > 0:
                has_auto_off_min = (
                    mins if has_auto_off_min is None else min(has_auto_off_min, mins)
                )
    if not has_turn_on:
        return []

    since = now - timedelta(days=_LOOKBACK_DAYS)
    out: list[Observation] = []
    for eid in sorted(target_entities):
        durations_min: list[float] = []
        last_on_ts: datetime | None = None
        for ev in buffer.query(entity_id=eid, since=since):
            new_state = (ev.new_state or "").lower()
            if new_state == "on" and last_on_ts is None:
                last_on_ts = ev.timestamp
            elif new_state != "on" and last_on_ts is not None:
                durations_min.append(
                    (ev.timestamp - last_on_ts).total_seconds() / 60.0
                )
                last_on_ts = None
        if len(durations_min) < _LONG_ON_MIN_OBS:
            continue
        mean_on = statistics.fmean(durations_min)
        if mean_on < _LONG_ON_THRESHOLD_MIN:
            continue
        # If the automation already has a `for:` that exceeds the
        # observed mean, the user has it covered.
        if has_auto_off_min is not None and has_auto_off_min >= mean_on:
            continue
        max_on = max(durations_min)
        n = len(durations_min)
        if has_auto_off_min is not None:
            text = (
                f"{eid} stays 'on' on average {mean_on:.0f} min "
                f"(max {max_on:.0f}, {n} cycles), but the automation's "
                f"auto-off is set to {has_auto_off_min} min. Consider "
                f"raising the timeout."
            )
        else:
            text = (
                f"{eid} stays 'on' on average {mean_on:.0f} min "
                f"(max {max_on:.0f}, {n} cycles) and the automation "
                "has no auto-off action. Add one to prevent forgotten "
                "lights / heaters."
            )
        out.append(
            Observation(
                kind=OBS_LONG_ON_DURATION,
                text=text,
                confidence=0.8,
                metrics={
                    "entity_id": eid,
                    "mean_on_min": round(mean_on, 1),
                    "max_on_min": round(max_on, 1),
                    "cycles": n,
                    "current_auto_off_min": has_auto_off_min,
                },
            )
        )
    return out


def _observe_trigger_time_drift(
    *,
    automation: dict[str, Any],
    buffer: "StateEventBuffer",
    now: datetime,
) -> list[Observation]:
    """If the automation has a `platform: time` trigger and the
    target entity's first daily transition consistently happens >=
    5 min off the trigger time, flag the drift."""
    from ..apply.conflict_scanner import _as_list, _extract_target_entities

    trigger_times: list[str] = []
    for trig in _as_list(automation.get("trigger")):
        if not isinstance(trig, dict):
            continue
        if trig.get("platform") != "time":
            continue
        at = trig.get("at")
        if isinstance(at, str):
            trigger_times.append(at)
    if not trigger_times:
        return []

    # We need a target entity AND a target state to know what
    # transition counts as "the automation fired".
    target_state: str | None = None
    for action in _as_list(automation.get("action")):
        if not isinstance(action, dict):
            continue
        svc = action.get("service") or ""
        if isinstance(svc, str):
            if svc.endswith(".turn_on"):
                target_state = "on"
                break
            if svc.endswith(".turn_off"):
                target_state = "off"
                break
    if target_state is None:
        return []

    targets = _extract_target_entities(automation.get("action"))
    if not targets:
        return []

    since = now - timedelta(days=_LOOKBACK_DAYS)
    out: list[Observation] = []

    for trigger_time in trigger_times:
        try:
            t_h, t_m = trigger_time.split(":")[:2]
            trigger_min_of_day = int(t_h) * 60 + int(t_m)
        except (ValueError, IndexError):
            continue
        # Per-day first-transition minute, averaged across the window.
        per_day: dict[Any, float] = {}
        for eid in targets:
            for ev in buffer.query(entity_id=eid, since=since):
                if (ev.new_state or "").lower() != target_state.lower():
                    continue
                local_ts = ev.timestamp.astimezone()
                day = local_ts.date()
                minute_of_day = local_ts.hour * 60 + local_ts.minute
                # First transition per day only
                if day not in per_day:
                    per_day[day] = minute_of_day
        if len(per_day) < _TRIGGER_DRIFT_MIN_OBS:
            continue
        observed = list(per_day.values())
        mean_obs = statistics.fmean(observed)
        delta = mean_obs - trigger_min_of_day
        if abs(delta) < _TRIGGER_DRIFT_THRESHOLD_MIN:
            continue
        std = (
            statistics.pstdev(observed)
            if len(observed) > 1
            else 0.0
        )
        # Reject high-variance signals — that's not a drift, it's noise.
        if std > 30.0:
            continue
        sign = "+" if delta > 0 else "-"
        out.append(
            Observation(
                kind=OBS_TRIGGER_TIME_DRIFT,
                text=(
                    f"Trigger fires at {trigger_time} but the observed "
                    f"target transition averages {sign}{abs(delta):.0f} min "
                    f"({_format_min_of_day(int(mean_obs))} across "
                    f"{len(observed)} days, ±{std:.0f} min). Consider "
                    f"updating the trigger to match reality."
                ),
                confidence=0.75,
                metrics={
                    "trigger_time": trigger_time,
                    "observed_mean_min_of_day": round(mean_obs, 1),
                    "delta_min": round(delta, 1),
                    "stdev_min": round(std, 1),
                    "days": len(observed),
                },
            )
        )
    return out


def _observe_silent_entities(
    *,
    entities: set[str],
    buffer: "StateEventBuffer",
    live_states: dict[str, str],
    now: datetime,
) -> list[Observation]:
    """An entity is "silent" only when HA itself thinks it's dead.

    Previously this fired on ANY entity missing from our 14-day
    buffer, but the buffer respects scan_areas + blocked_entities,
    so an entity outside the user's monitored set looked dead to
    us even though HA had a fresh state for it. Result on a real
    install: 8+ false-positive "no state changes" findings against
    perfectly live entities.

    New rule, much tighter:
      - Looks like a device_id (no dot) → skip; trigger refs that
        target a device aren't entities at all
      - hass.states has the entity AND it's not `unavailable`/
        `unknown` → live, skip silently
      - hass.states has the entity at `unavailable`/`unknown` →
        emit (HA itself says it's broken)
      - hass.states has NO entry for the entity → emit (renamed
        or removed)

    The buffer is no longer used for this signal — HA's own state
    machine is the source of truth for "is this entity alive."
    """
    if not entities:
        return []
    out: list[Observation] = []
    for eid in sorted(entities):
        # Skip device_id-shaped trigger refs (32-char hex). Those
        # are HA's `device_id:` trigger references, not entity_ids;
        # complaining about them as dead entities is wrong.
        if "." not in eid:
            continue
        # Skip platform.X service references like `script.foo` —
        # they're real entities but not the kind of thing that
        # "goes dead" in the usual sense.
        state = live_states.get(eid)
        if state is None:
            out.append(
                Observation(
                    kind=OBS_ENTITY_SILENT,
                    text=(
                        f"{eid} is not in Home Assistant's state machine. "
                        "The automation may be referring to a renamed or "
                        "removed entity — check the entity registry."
                    ),
                    confidence=0.9,
                    metrics={
                        "entity_id": eid,
                        "reason": "missing_from_state_machine",
                    },
                )
            )
            continue
        if state in {"unavailable", "unknown"}:
            out.append(
                Observation(
                    kind=OBS_ENTITY_SILENT,
                    text=(
                        f"{eid} is currently `{state}` in Home Assistant. "
                        "The automation will silently fail until the "
                        "entity comes back online."
                    ),
                    confidence=0.85,
                    metrics={
                        "entity_id": eid,
                        "current_state": state,
                    },
                )
            )
    return out


def _observe_redundant_targets(
    *,
    target_entities: set[str],
    hierarchy: "EntityHierarchy",
) -> list[Observation]:
    """Automation targets both a group/scene/script AND one of its
    members. Mirrors RedundantTargetDetector's logic but folded into
    the audit packet so a single audit insight covers it instead of
    spawning a second redundant_target row."""
    container_map = hierarchy.members_of
    if not container_map:
        return []
    out: list[Observation] = []
    for candidate in sorted(target_entities):
        members = container_map.get(candidate, frozenset())
        if not members:
            continue
        overlapping = sorted(target_entities & members)
        if not overlapping:
            continue
        if len(overlapping) == 1:
            text = (
                f"Action targets both {candidate} and its member "
                f"{overlapping[0]}. The member call is redundant."
            )
        else:
            text = (
                f"Action targets {candidate} AND {len(overlapping)} of "
                f"its members ({overlapping[0]} + {len(overlapping) - 1} "
                "more). Redundant — drop the member entries."
            )
        out.append(
            Observation(
                kind=OBS_REDUNDANT_TARGET,
                text=text,
                confidence=0.95,
                metrics={
                    "container": candidate,
                    "redundant_members": list(overlapping),
                },
            )
        )
    return out


def _format_min_of_day(minute_of_day: int) -> str:
    """24h HH:MM formatter for an int minute count."""
    h, m = divmod(minute_of_day, 60)
    return f"{h:02d}:{m:02d}"
