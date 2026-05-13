"""GoalTrackerDetector — track user-defined targets against observed behavior.

The detectors so far observe what the user does. This one observes
what the user WANTS to do (a target time) and tells them how often
they actually hit it.

Goals are configured as a JSON object in the OptionsFlow under
`goals_json`, with keys naming the goal and values being HH:MM target
times. Recognized goals (case-insensitive, snake_case):

  - get_to_work_by      → device_tracker leaves home + arrives at
                          non-home zone before HH:MM
  - home_by             → device_tracker arrives back home before HH:MM
  - bedtime_by          → phone starts charging before HH:MM
  - wake_up_by          → phone stops charging before HH:MM
  - leave_home_by       → device_tracker leaves home zone before HH:MM

Each goal produces one PATTERN_OBSERVATION insight per scan with:
  - Adherence: "hit on N of last M (weekdays / days)"
  - Average performance vs target
  - 7-day trend (improving / steady / declining)
  - Concrete suggestion if missing the goal

Confidence reflects sample size + hit rate. The output is
informational — users tune their habits, not their automations,
from these.

For "leave_home_by" / "get_to_work_by" specifically, this is also
where commute reliability matters most: if departure variance is
huge, surface that as "your commute window is unpredictable
(±N min) — consider an earlier alarm to absorb traffic variance."
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.util import dt as dt_util

from ..insight import Insight, InsightKind
from .base import Detector, DetectorContext, register_detector
from .manual_habit import _WEEKDAY_NAMES, _WEEKDAYS_ONLY

if TYPE_CHECKING:
    from ..observers.state_event_buffer import StateEvent


_LOOKBACK_DAYS = 14
_MIN_DAYS = 5
# Goals where missing means LATER than target (most goals)
_LATE_IS_MISS = frozenset(
    {"get_to_work_by", "home_by", "bedtime_by", "leave_home_by"}
)
# Goals where missing means LATER than target as well, but the framing
# is gentler (it's a wake-up goal)
_WAKE_GOALS = frozenset({"wake_up_by"})


@register_detector
class GoalTrackerDetector(Detector):
    """Compare user-defined target times against observed phone activity."""

    name = "goal_tracker"
    kind = InsightKind.PATTERN_OBSERVATION
    requires_recorder = False

    async def scan(self, ctx: DetectorContext) -> list[Insight]:
        if ctx.event_buffer is None:
            return []
        goals = self._load_goals(ctx)
        if not goals:
            return []  # no goals configured — silent no-op

        cutoff = datetime.now(tz=UTC) - timedelta(days=_LOOKBACK_DAYS)
        insights: list[Insight] = []

        for goal_name, target_hhmm in goals.items():
            target = self._parse_target(target_hhmm)
            if target is None:
                continue
            observed = self._observe_for_goal(goal_name, ctx, cutoff)
            if not observed:
                continue
            insight = self._build_insight(
                goal_name=goal_name,
                target=target,
                target_str=target_hhmm,
                observed=observed,
            )
            if insight is not None:
                insights.append(insight)
        return insights

    # -------- config --------

    def _load_goals(self, ctx: DetectorContext) -> dict[str, str]:
        """Read goals_json from the entry's options. Tolerant — bad
        JSON returns empty dict, not an error."""
        try:
            from ..const import DOMAIN

            for entry in ctx.hass.config_entries.async_entries(DOMAIN):
                raw = entry.options.get("goals_json") or entry.data.get(
                    "goals_json"
                )
                if not raw:
                    continue
                try:
                    parsed = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue
                if not isinstance(parsed, dict):
                    continue
                # Normalize keys to lowercase snake_case
                norm: dict[str, str] = {}
                for k, v in parsed.items():
                    if not isinstance(k, str) or not isinstance(v, str):
                        continue
                    key = k.strip().lower().replace(" ", "_").replace("-", "_")
                    norm[key] = v.strip()
                return norm
        except Exception:  # noqa: BLE001
            pass
        return {}

    @staticmethod
    def _parse_target(value: str) -> time | None:
        """Accept HH:MM or HH:MM:SS; ignore everything else."""
        try:
            parts = value.split(":")
            hh = int(parts[0])
            mm = int(parts[1]) if len(parts) > 1 else 0
            if 0 <= hh < 24 and 0 <= mm < 60:
                return time(hour=hh, minute=mm)
        except (ValueError, IndexError):
            pass
        return None

    # -------- observation --------

    def _observe_for_goal(
        self,
        goal_name: str,
        ctx: DetectorContext,
        cutoff: datetime,
    ) -> list[datetime]:
        """Return the list of one-per-day timestamps relevant to this
        goal — what we'll compare against the target.

        For commute / location goals: device_tracker transitions.
        For sleep goals: charging-state transitions.
        """
        # Find relevant entities once per goal
        if goal_name in {"get_to_work_by", "home_by", "leave_home_by"}:
            entities = self._find_gps_trackers(ctx)
        elif goal_name in {"bedtime_by", "wake_up_by"}:
            entities = self._find_charging_entities(ctx)
        else:
            return []

        if ctx.event_buffer is None:
            return []
        per_day: dict[date, datetime] = {}
        for eid in entities:
            for ev in ctx.event_buffer.query(entity_id=eid, since=cutoff):
                marker = self._is_goal_event(ev, goal_name)
                if not marker:
                    continue
                local_ts = dt_util.as_local(ev.timestamp)
                day = local_ts.date()
                # Earliest event of the day for that goal-type wins.
                # (First "leave home", first "arrive home", etc.)
                if day not in per_day or ev.timestamp < per_day[day]:
                    per_day[day] = ev.timestamp
        return sorted(per_day.values())

    @staticmethod
    def _is_goal_event(ev: "StateEvent", goal_name: str) -> bool:
        old = (ev.old_state or "").lower()
        new = (ev.new_state or "").lower()
        if old in {"unknown", "unavailable", "none", ""}:
            return False
        if new in {"unknown", "unavailable", "none", ""}:
            return False
        if goal_name == "leave_home_by":
            return old == "home" and new != "home"
        if goal_name == "home_by":
            return old != "home" and new == "home"
        if goal_name == "get_to_work_by":
            # First non-home zone arrival of the day. We'll let any
            # non-home, non-unknown destination count — if user has
            # "Work" zone configured it'll be that; otherwise any
            # known away-zone.
            return old != new and new != "home"
        if goal_name == "bedtime_by":
            return old in {"off", "discharging"} and new in {
                "on",
                "charging",
            }
        if goal_name == "wake_up_by":
            return old in {"on", "charging"} and new in {
                "off",
                "discharging",
            }
        return False

    def _find_gps_trackers(self, ctx: DetectorContext) -> list[str]:
        out: list[str] = []
        try:
            for state in ctx.hass.states.async_all():
                if not state.entity_id.startswith("device_tracker."):
                    continue
                if (state.attributes or {}).get("source_type") == "gps":
                    out.append(state.entity_id)
        except Exception:  # noqa: BLE001
            pass
        return out

    def _find_charging_entities(self, ctx: DetectorContext) -> list[str]:
        out: list[str] = []
        try:
            for state in ctx.hass.states.async_all():
                eid = state.entity_id
                if eid.startswith("binary_sensor.") and eid.endswith(
                    "_charging"
                ):
                    out.append(eid)
                elif eid.startswith("sensor.") and eid.endswith(
                    "_battery_state"
                ):
                    out.append(eid)
        except Exception:  # noqa: BLE001
            pass
        return out

    # -------- evaluation --------

    def _build_insight(
        self,
        *,
        goal_name: str,
        target: time,
        target_str: str,
        observed: list[datetime],
    ) -> Insight | None:
        if len(observed) < _MIN_DAYS:
            return None

        target_min = target.hour * 60 + target.minute
        observed_local = [dt_util.as_local(t) for t in observed]
        # midnight wrap-around for evening
        # goals. A `bedtime_by: 22:30` observation at 00:15 means
        # the user is 1h45m LATE, not 22h15m EARLY. Map post-
        # midnight observations to target_day+1 by adding 24h when:
        #   - the goal's target is in the evening (≥ 16:00), AND
        #   - the observation's local time is before noon
        # That window catches genuine late-bedtime cases without
        # mis-classifying intentional 6am wake-up observations on
        # bedtime goals (those just look like a huge miss, which
        # is correct behaviour for someone who didn't go to bed).
        EVENING_GOAL_MIN = 16 * 60  # 16:00 local
        WRAP_DETECTION_MAX = 12 * 60  # observations before noon
        target_is_evening = target_min >= EVENING_GOAL_MIN
        observed_min: list[float] = []
        for t in observed_local:
            m = t.hour * 60 + t.minute + t.second / 60.0
            if target_is_evening and m < WRAP_DETECTION_MAX:
                m += 24 * 60  # rolled past midnight; add a full day
            observed_min.append(m)

        # Tally hits — for late-is-miss goals, "hit" means observed time
        # is <= target. wake_up_by also wants <= target (earlier wake
        # times beat the target).
        hits = sum(1 for m in observed_min if m <= target_min)
        misses = len(observed_min) - hits
        avg = sum(observed_min) / len(observed_min)
        stddev = (
            sum((m - avg) ** 2 for m in observed_min) / len(observed_min)
        ) ** 0.5

        avg_minute = int(round(avg))
        avg_hhmm = f"{avg_minute // 60:02d}:{avg_minute % 60:02d}"
        delta = avg - target_min  # +ve = on average LATER than target

        # Trend: compare first half of observation window to second half
        midpoint = len(observed_min) // 2
        if midpoint >= 2:
            early_avg = sum(observed_min[:midpoint]) / midpoint
            late_avg = sum(observed_min[midpoint:]) / (
                len(observed_min) - midpoint
            )
            if late_avg < early_avg - 3:
                trend = "improving ↗"
            elif late_avg > early_avg + 3:
                trend = "declining ↘"
            else:
                trend = "steady →"
        else:
            trend = "steady →"

        weekdays_only = (
            {_WEEKDAY_NAMES[t.weekday()] for t in observed_local}
            <= _WEEKDAYS_ONLY
        )
        weekday_note = " (weekdays only)" if weekdays_only else ""

        # Friendly goal label
        labels = {
            "get_to_work_by": "Get to work by",
            "home_by": "Home by",
            "leave_home_by": "Leave home by",
            "bedtime_by": "Bedtime by",
            "wake_up_by": "Wake up by",
        }
        goal_label = labels.get(goal_name, goal_name.replace("_", " ").title())

        delta_str = (
            f"+{int(round(delta))} min late"
            if delta > 0
            else f"{int(round(abs(delta)))} min early"
            if delta < -0.5
            else "on target"
        )

        title = (
            f"Goal: {goal_label} {target_str} — hit {hits}/{len(observed_min)} "
            f"days{weekday_note}, avg {avg_hhmm} ({delta_str}), trend {trend}"
        )

        # Suggestion text varies by goal type + hit rate
        hit_rate = hits / len(observed_min) if observed_min else 0.0
        if hit_rate >= 0.85:
            suggestion = "You're consistently hitting this goal. Nice."
        elif goal_name == "get_to_work_by" and stddev > 20:
            suggestion = (
                f"Commute timing varies by ±{int(round(stddev))} min — "
                "traffic or routine variance is the likely cause. Consider "
                "leaving 10-15 min earlier to absorb the spread."
            )
        elif goal_name == "bedtime_by":
            suggestion = (
                f"Average bedtime is {avg_hhmm}, about {int(round(delta))} "
                "min later than your goal. A bedroom-lights-fade automation "
                f"5 min before {target_str} can act as a nudge."
            )
        elif goal_name == "home_by":
            suggestion = (
                f"Average arrival is {avg_hhmm}, {int(round(delta))} min "
                "later than goal. Pre-arrival HVAC at that time would catch "
                "the typical arrival rather than the target."
            )
        else:
            suggestion = (
                f"Average is {avg_hhmm} vs target {target_str}. "
                f"Trend is {trend}."
            )

        confidence = round(
            min(1.0, len(observed_min) / 14.0) * (0.5 + hit_rate / 2.0),
            3,
        )

        fingerprint: dict[str, Any] = {
            "kind": "goal_tracker",
            "goal": goal_name,
            "target": target_str,
        }
        payload = {
            "goal": goal_name,
            "goal_label": goal_label,
            "target": target_str,
            "average_time": avg_hhmm,
            "average_delta_minutes": round(delta, 1),
            "stddev_minutes": round(stddev, 1),
            "hits": hits,
            "misses": misses,
            "total_days": len(observed_min),
            "hit_rate": round(hit_rate, 3),
            "trend": trend,
            "weekdays_only": weekdays_only,
            "advice": suggestion,
        }

        return Insight(
            id=Insight.compute_id(InsightKind.PATTERN_OBSERVATION, fingerprint),
            kind=InsightKind.PATTERN_OBSERVATION,
            detector=self.name,
            area_id=None,
            title=title,
            confidence=confidence,
            fingerprint=fingerprint,
            payload=payload,
            payload_format="report",
            created_at=datetime.now(tz=UTC),
        )
