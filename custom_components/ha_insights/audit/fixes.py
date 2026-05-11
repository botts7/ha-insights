"""Deterministic YAML-edit builders per Observation kind.

When an audit observation has a clearly-correct fix that doesn't
need a language model to express (delete a member, raise a numeric
timeout, swap a dead entity), we build the refined YAML right here
and ship the audit insight with `payload_format="automation"` so
Apply just works. No tokens spent.

Phase C / D still exist for the genuinely ambiguous cases:
restructuring trigger logic, suggesting conditions, choosing
between two competing intents. Those need the LLM. But the
common-case audits — redundant targets, dead entities, missing
timeouts — fit deterministic rules cleanly.

Each builder is pure: takes (automation_yaml, observation_metrics)
and returns (refined_yaml | None, summary_string). None means
"this observation can't be safely auto-fixed, defer to LLM".
"""
from __future__ import annotations

import copy
from typing import Any

from .packet import (
    OBS_ENTITY_SILENT,
    OBS_LONG_ON_DURATION,
    OBS_REDUNDANT_TARGET,
    OBS_TRIGGER_TIME_DRIFT,
)


def apply_deterministic_fixes(
    automation: dict[str, Any],
    observations: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[str]]:
    """Walk observations, apply the safe fix for each. Returns
    (refined_yaml, applied_summaries) or (None, []) if nothing
    deterministic applied.

    Each observation is a dict (the same shape used in the insight
    payload) with `kind`, `text`, `metrics`. We branch on kind.
    Operations are stacked on a deep copy so partial application
    doesn't mutate the original.
    """
    refined = copy.deepcopy(automation)
    summaries: list[str] = []

    for obs in observations:
        kind = obs.get("kind")
        metrics = obs.get("metrics") or {}
        applied: str | None = None

        if kind == OBS_REDUNDANT_TARGET:
            applied = _fix_redundant_target(refined, metrics)
        elif kind == OBS_LONG_ON_DURATION:
            applied = _fix_long_on_duration(refined, metrics)
        elif kind == OBS_TRIGGER_TIME_DRIFT:
            applied = _fix_trigger_time_drift(refined, metrics)
        elif kind == OBS_ENTITY_SILENT:
            # No safe deterministic fix — dead entity replacement
            # needs the user to choose the substitute. Surface as
            # a hint in the summary only.
            applied = None

        if applied:
            summaries.append(applied)

    if not summaries:
        return None, []
    return refined, summaries


# ---------------------------------------------------------------------------
# Per-kind builders. Each returns a one-line summary on success, None on
# "could not safely apply".
# ---------------------------------------------------------------------------


def _fix_redundant_target(
    automation: dict[str, Any], metrics: dict[str, Any]
) -> str | None:
    """Drop redundant member entries from the action target list.

    The observation's metrics include `container` (kept) and
    `redundant_members` (dropped). We walk every action that has a
    target containing the container, and remove the member entries
    from the same target's entity_id list. Idempotent on re-apply.
    """
    container = metrics.get("container")
    redundant_members = metrics.get("redundant_members") or []
    if not isinstance(container, str) or not redundant_members:
        return None

    actions = automation.get("action")
    if actions is None:
        return None
    if not isinstance(actions, list):
        actions = [actions]
        automation["action"] = actions

    redundant_set = set(redundant_members)
    dropped_count = 0
    for action in actions:
        if not isinstance(action, dict):
            continue
        target = action.get("target")
        if not isinstance(target, dict):
            continue
        target_eids = target.get("entity_id")
        if isinstance(target_eids, str):
            target_eids = [target_eids]
        if not isinstance(target_eids, list):
            continue
        # Only act on actions where the container is one of the targets
        if container not in target_eids:
            continue
        new_list = [e for e in target_eids if e not in redundant_set]
        if len(new_list) == len(target_eids):
            continue  # no change
        dropped = len(target_eids) - len(new_list)
        dropped_count += dropped
        # Collapse to scalar if only one survives — matches HA's
        # canonical YAML shape and avoids spurious diff noise.
        if len(new_list) == 1:
            target["entity_id"] = new_list[0]
        else:
            target["entity_id"] = new_list

    if dropped_count == 0:
        return None
    return (
        f"Removed {dropped_count} redundant member target"
        f"{'s' if dropped_count != 1 else ''} (covered by {container})."
    )


def _fix_long_on_duration(
    automation: dict[str, Any], metrics: dict[str, Any]
) -> str | None:
    """Raise the action's `for:` duration (or add one) so the
    automation's auto-off matches observed reality.

    Strategy: if an existing turn_off action has `for:`, bump it to
    `ceil(observed_mean * 1.2)` minutes — adds 20% headroom so we
    don't truncate the tail. If no `for:` exists, skip — adding one
    risks changing semantics in ways we can't verify without the
    full action context. Surface as LLM territory.
    """
    mean_on = metrics.get("mean_on_min")
    current = metrics.get("current_auto_off_min")
    if not isinstance(mean_on, (int, float)) or mean_on <= 0:
        return None
    suggested = int((mean_on * 1.2) + 0.5)
    if current is not None and suggested <= current:
        # Already big enough — nothing to do
        return None

    actions = automation.get("action")
    if actions is None:
        return None
    if not isinstance(actions, list):
        actions = [actions]
        automation["action"] = actions

    for action in actions:
        if not isinstance(action, dict):
            continue
        for_clause = action.get("for")
        if not isinstance(for_clause, dict):
            continue
        # Replace existing minutes/hours/seconds with the new value
        # in minutes form — keeps the YAML clean.
        for_clause.clear()
        for_clause["minutes"] = suggested
        return (
            f"Raised auto-off from {current or '∅'} min to "
            f"{suggested} min (matches observed mean of "
            f"{mean_on:.0f} min + 20% headroom)."
        )

    return None


def _fix_trigger_time_drift(
    automation: dict[str, Any], metrics: dict[str, Any]
) -> str | None:
    """Shift the `platform: time` trigger to match observed mean.

    Conservative: only shift by the rounded delta, not all the way
    to the exact mean — and only when the original trigger time +
    delta lands on a sensible 5-min boundary.
    """
    trigger_time = metrics.get("trigger_time")
    delta_min = metrics.get("delta_min")
    if not isinstance(trigger_time, str) or not isinstance(delta_min, (int, float)):
        return None
    try:
        h_str, m_str = trigger_time.split(":")[:2]
        orig_h, orig_m = int(h_str), int(m_str)
    except (ValueError, IndexError):
        return None

    # Round delta to nearest 5 to keep human-friendly times
    delta_rounded = int(round(delta_min / 5.0) * 5)
    if delta_rounded == 0:
        return None
    new_minute_of_day = orig_h * 60 + orig_m + delta_rounded
    new_minute_of_day = max(0, min(new_minute_of_day, 24 * 60 - 1))
    new_h, new_m = divmod(new_minute_of_day, 60)
    new_time = f"{new_h:02d}:{new_m:02d}"
    if new_time == trigger_time:
        return None

    triggers = automation.get("trigger")
    if triggers is None:
        return None
    if not isinstance(triggers, list):
        triggers = [triggers]
        automation["trigger"] = triggers

    changed = False
    for trig in triggers:
        if not isinstance(trig, dict):
            continue
        if trig.get("platform") != "time":
            continue
        if trig.get("at") == trigger_time:
            trig["at"] = new_time
            changed = True

    if not changed:
        return None
    return (
        f"Shifted trigger from {trigger_time} → {new_time} "
        f"(matches observed mean firing time within ±5 min)."
    )
