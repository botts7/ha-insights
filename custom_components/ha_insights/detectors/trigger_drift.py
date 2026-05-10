"""TriggerDriftDetector — flag time-triggered automations whose actual
target-entity transitions consistently happen at a different time than
the configured trigger.

Example: an automation triggers at 07:00 to turn on `light.bedroom`,
but on most days the light actually transitions to `on` at 07:08.
That suggests:
  - The user is reaching the bedroom around 07:08, not 07:00
  - OR the automation isn't actually firing (disabled? blocked by
    condition?) and the user manually flips the switch
Either way, the automation's trigger time is misaligned with the
user's behavior. Suggest moving it to match observed reality.

Algorithm:
  1. Iterate every existing automation that has a `time:` trigger and
     a direct `service: domain.turn_on/off` action with concrete target
     entity_ids (skip script calls, scene calls, template entities).
  2. For each (trigger_time, target_entity, target_state) tuple:
     a. Walk the buffer for that target_entity over LOOKBACK_DAYS.
     b. Per day, find the FIRST transition to target_state inside a
        window of ±DRIFT_WINDOW_MIN around the trigger time.
     c. Drop days with no observed transition (automation skipped /
        no recorder coverage).
  3. If we have ≥ MIN_OBSERVATIONS distinct days, compute mean delta
     (observed_minute_of_day − trigger_minute_of_day).
  4. If |mean_delta| ≥ DRIFT_THRESHOLD_MIN AND stddev is tight enough
     to be a real pattern, emit AUTOMATION_IMPROVEMENT insight.

Why this is a code-only detector (no LLM): the math is deterministic;
the suggestion ("move trigger to 07:08") is a numeric output, not
free text. LLM can be layered on later for plain-English rationale,
but the finding itself doesn't need it.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.util import dt as dt_util

from ..insight import Insight, InsightKind
from .base import Detector, DetectorContext, register_detector

if TYPE_CHECKING:
    from ..observers.state_event_buffer import StateEvent


@register_detector
class TriggerDriftDetector(Detector):
    """Detect time-triggered automations whose observed firing time has
    drifted from the configured trigger."""

    name = "trigger_drift"
    kind = InsightKind.AUTOMATION_IMPROVEMENT
    requires_recorder = False

    LOOKBACK_DAYS = 14
    # Minimum distinct calendar days we need to see the target entity
    # transition near the trigger time. Less than this and one or two
    # outlier days dominate the average.
    MIN_OBSERVATIONS = 5
    # Window around the trigger time we look for the target entity's
    # transition. Wide enough to catch genuine drift but narrow enough
    # that we don't pull in unrelated state changes from later in the
    # day. ±30 min is plenty for "wake up around 7" routines.
    DRIFT_WINDOW_MIN = 30
    # Don't bother emitting unless the drift is at least this big —
    # 1-2 minutes is just timer jitter / state-bus latency, not a real
    # misalignment. 3 min separates "automation works fine" from
    # "user's actual schedule is different."
    DRIFT_THRESHOLD_MIN = 3.0
    # Observed transitions must cluster — a high stddev means the user
    # ISN'T on a consistent schedule, so the automation's fixed trigger
    # is doing fine relative to noise. Only suggest a move when the
    # observations are tight enough that a different fixed time would
    # better match the pattern.
    OBSERVATION_STDDEV_MAX_MIN = 8.0

    async def scan(self, ctx: DetectorContext) -> list[Insight]:
        if ctx.event_buffer is None or not ctx.existing_automations:
            return []

        cutoff = datetime.now(tz=UTC) - timedelta(days=self.LOOKBACK_DAYS)
        insights: list[Insight] = []
        for automation in ctx.existing_automations:
            insights.extend(self._evaluate_automation(automation, ctx, cutoff))
        return insights

    def _evaluate_automation(
        self,
        automation: dict[str, Any],
        ctx: DetectorContext,
        cutoff: datetime,
    ) -> list[Insight]:
        triggers = _as_list(automation.get("trigger"))
        time_triggers = [
            t
            for t in triggers
            if isinstance(t, dict) and t.get("platform") == "time"
        ]
        if not time_triggers:
            return []

        # Resolve action targets + their expected post-action state.
        # service `light.turn_on` targeting `light.foo` → expect "on".
        # service `light.turn_off` → expect "off". Anything else (scene
        # call, script, automation.trigger) is too indirect to evaluate
        # for drift; skip silently.
        action_targets = _extract_actionable_targets(
            automation.get("action", [])
        )
        if not action_targets:
            return []

        results: list[Insight] = []
        automation_id = automation.get("id") or automation.get("alias") or "unknown"
        automation_alias = automation.get("alias") or automation_id

        for trigger in time_triggers:
            trigger_minute = _parse_at(trigger.get("at"))
            if trigger_minute is None:
                continue
            for target_eid, target_state in action_targets:
                insight = self._evaluate_target(
                    automation_id=automation_id,
                    automation_alias=automation_alias,
                    trigger_minute=trigger_minute,
                    target_eid=target_eid,
                    target_state=target_state,
                    ctx=ctx,
                    cutoff=cutoff,
                )
                if insight is not None:
                    results.append(insight)
        return results

    def _evaluate_target(
        self,
        *,
        automation_id: str,
        automation_alias: str,
        trigger_minute: int,
        target_eid: str,
        target_state: str,
        ctx: DetectorContext,
        cutoff: datetime,
    ) -> Insight | None:
        # First transition per day to target_state, in HA-local time, that
        # falls within ±DRIFT_WINDOW_MIN of the configured trigger.
        per_day: dict[date, int] = {}
        events: list[StateEvent] = list(
            ctx.event_buffer.query(entity_id=target_eid, since=cutoff)
        )
        for ev in events:
            if str(ev.new_state) != target_state:
                continue
            local = dt_util.as_local(ev.timestamp)
            ev_minute = local.hour * 60 + local.minute
            delta = _minute_diff(ev_minute, trigger_minute)
            if abs(delta) > self.DRIFT_WINDOW_MIN:
                continue
            local_date = local.date()
            if local_date not in per_day or ev_minute < per_day[local_date]:
                per_day[local_date] = ev_minute

        if len(per_day) < self.MIN_OBSERVATIONS:
            return None

        observed_minutes = list(per_day.values())
        deltas = [
            _minute_diff(m, trigger_minute) for m in observed_minutes
        ]
        avg_delta = sum(deltas) / len(deltas)
        if abs(avg_delta) < self.DRIFT_THRESHOLD_MIN:
            return None

        variance = sum((d - avg_delta) ** 2 for d in deltas) / len(deltas)
        stddev = math.sqrt(variance)
        if stddev > self.OBSERVATION_STDDEV_MAX_MIN:
            # The user's actual transitions are scattered — fixed trigger
            # is fine relative to noise; not a real drift to fix.
            return None

        # Suggested new trigger time = trigger + avg_delta, clamped to
        # legal HH:MM. Wraparound is rare for daily routines but defensive.
        suggested_minute = (trigger_minute + round(avg_delta)) % (24 * 60)
        suggested_h, suggested_m = divmod(suggested_minute, 60)
        suggested_time = f"{suggested_h:02d}:{suggested_m:02d}"
        current_h, current_m = divmod(trigger_minute, 60)
        current_time = f"{current_h:02d}:{current_m:02d}"

        direction = "later" if avg_delta > 0 else "earlier"
        magnitude = abs(round(avg_delta))

        confidence = round(
            min(1.0, len(per_day) / 10.0) * max(0.4, 1.0 - stddev / 15.0),
            3,
        )

        title = (
            f"Automation '{automation_alias}' triggers at {current_time} but "
            f"{target_eid} → {target_state} actually happens {magnitude} min "
            f"{direction} on average ({len(per_day)} of last "
            f"{self.LOOKBACK_DAYS} days). Move trigger to {suggested_time}?"
        )

        fingerprint = {
            "automation_id": automation_id,
            "trigger_at": current_time,
            "target_entity_id": target_eid,
            "target_state": target_state,
            "kind": "trigger_drift",
        }

        # payload is a "report" — informational. The card shows the
        # finding; we don't auto-replace the user's automation. Future
        # work: a one-click "apply suggested time" that edits the
        # existing automation in place.
        payload = {
            "automation_id": automation_id,
            "automation_alias": automation_alias,
            "current_trigger_time": current_time,
            "suggested_trigger_time": suggested_time,
            "drift_minutes": round(avg_delta, 1),
            "stddev_minutes": round(stddev, 1),
            "observations": len(per_day),
            "lookback_days": self.LOOKBACK_DAYS,
            "target_entity_id": target_eid,
            "target_state": target_state,
        }

        return Insight(
            id=Insight.compute_id(InsightKind.AUTOMATION_IMPROVEMENT, fingerprint),
            kind=InsightKind.AUTOMATION_IMPROVEMENT,
            detector=self.name,
            area_id=None,
            title=title,
            confidence=confidence,
            fingerprint=fingerprint,
            payload=payload,
            payload_format="report",
            created_at=datetime.now(tz=UTC),
        )


# --- Helpers (private to this module) ------------------------------------

def _as_list(value: Any) -> list[Any]:
    """HA YAML accepts a single dict or a list of dicts for trigger/action."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _parse_at(raw: Any) -> int | None:
    """Parse an HH:MM[:SS] string into minute-of-day. None if unparseable."""
    if not isinstance(raw, str):
        return None
    parts = raw.split(":")
    if len(parts) < 2:
        return None
    try:
        h = int(parts[0])
        m = int(parts[1])
    except ValueError:
        return None
    if not (0 <= h < 24 and 0 <= m < 60):
        return None
    return h * 60 + m


def _minute_diff(a: int, b: int) -> int:
    """Signed minute-diff with wraparound: 23:55 vs 00:05 → +10, not -1430."""
    raw = a - b
    if raw > 12 * 60:
        return raw - 24 * 60
    if raw < -12 * 60:
        return raw + 24 * 60
    return raw


# Service names whose post-action state we can predict by looking at the
# service verb. For anything else (scene.turn_on, script.foo, etc.) we
# don't know what state to look for in the buffer, so we skip silently.
_SERVICE_STATE_MAP: dict[str, str] = {
    "turn_on": "on",
    "turn_off": "off",
}


def _extract_actionable_targets(actions: Any) -> list[tuple[str, str]]:
    """Pull (entity_id, expected_state) pairs from the action block.

    Only handles direct `service: domain.turn_on/off` calls with a
    concrete target.entity_id. Skips scenes, scripts, helper triggers —
    those can't be evaluated against state-change observations without
    tracing through whatever the indirect call eventually does, which
    is a much bigger problem than this detector tries to solve.
    """
    targets: list[tuple[str, str]] = []
    for action in _as_list(actions):
        if not isinstance(action, dict):
            continue
        service = action.get("service")
        if not isinstance(service, str) or "." not in service:
            continue
        _, verb = service.split(".", 1)
        expected_state = _SERVICE_STATE_MAP.get(verb)
        if expected_state is None:
            continue
        # target.entity_id (modern) OR action.entity_id (legacy)
        eids: list[str] = []
        target = action.get("target")
        if isinstance(target, dict):
            t_eid = target.get("entity_id")
            if isinstance(t_eid, str):
                eids.append(t_eid)
            elif isinstance(t_eid, list):
                eids.extend(e for e in t_eid if isinstance(e, str))
        legacy_eid = action.get("entity_id")
        if isinstance(legacy_eid, str):
            eids.append(legacy_eid)
        elif isinstance(legacy_eid, list):
            eids.extend(e for e in legacy_eid if isinstance(e, str))
        for eid in eids:
            if "." in eid:
                targets.append((eid, expected_state))
    return targets
