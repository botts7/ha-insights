"""PhoneActivityDetector — derive sleep, commute, and presence patterns
from the HA Mobile App's exposed sensors.

Phone activity is the highest-fidelity human-state signal HA has access
to without dedicated wearables. The Mobile App integration exposes
roughly:

  - `binary_sensor.<phone>_charging`        — charging on/off
  - `sensor.<phone>_battery_level`          — % charge
  - `sensor.<phone>_battery_state`          — "charging" / "discharging"
  - `sensor.<phone>_activity`               — still / walking / driving (Android)
  - `device_tracker.<phone>`                — home / away / specific zone

This detector mines those entities for patterns that NO state-change-
on-light-switches detector could find:

  1. SLEEP WINDOW. Charging-on → charging-off transitions cluster
     into "user plugged in at 22:45, unplugged at 07:15." Across N
     days you get the user's actual sleep schedule, weekday vs
     weekend split.
  2. COMMUTE PATTERN. device_tracker zone transitions out of "home"
     and back. Across N days these cluster into the user's typical
     departure/return windows.
  3. ALARM/WAKE SIGNAL. First charging-off transition each morning
     anchors "user is up" — more precise than a kitchen-light-toggle
     guess.

Output is PATTERN_OBSERVATION (informational). Foundation for future
detectors that suggest area-scoped + presence-aware automations.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.util import dt as dt_util

from ..insight import Insight, InsightKind
from .base import Detector, DetectorContext, register_detector

if TYPE_CHECKING:
    from ..observers.state_event_buffer import StateEvent


_LOOKBACK_DAYS = 14
_MIN_DAYS_FOR_PATTERN = 5
# Cluster tolerance for charging-plug-in / unplug times (minutes).
# Sleep schedules drift more than light-switch routines, so this is
# wider than the 45 min in ManualHabitDetector.
_TIME_TOLERANCE_MIN = 60


@register_detector
class PhoneActivityDetector(Detector):
    """Auto-discovers phone entities + derives wake/sleep/commute patterns."""

    name = "phone_activity"
    kind = InsightKind.PATTERN_OBSERVATION
    requires_recorder = False

    async def scan(self, ctx: DetectorContext) -> list[Insight]:
        if ctx.event_buffer is None:
            return []

        # Auto-discover phone entities from the HA state machine.
        # Cheap one-shot dict walk; runs once per scan.
        charging_entities = self._find_charging_entities(ctx)
        tracker_entities = self._find_device_tracker_entities(ctx)

        cutoff = datetime.now(tz=UTC) - timedelta(days=_LOOKBACK_DAYS)
        insights: list[Insight] = []

        # Pattern A: Sleep window from charging on/off transitions
        for eid in charging_entities:
            sleep_insight = self._derive_sleep_window(
                eid, ctx.event_buffer.query(entity_id=eid, since=cutoff)
            )
            if sleep_insight is not None:
                insights.append(sleep_insight)

        # Pattern B: Commute pattern from device_tracker home/away transitions
        for eid in tracker_entities:
            commute_insight = self._derive_commute_pattern(
                eid, ctx.event_buffer.query(entity_id=eid, since=cutoff)
            )
            if commute_insight is not None:
                insights.append(commute_insight)

        return insights

    # -------- discovery --------

    def _find_charging_entities(self, ctx: DetectorContext) -> list[str]:
        """Heuristic match for phone-charging-state entities.

        Mobile App integration emits `binary_sensor.<phone>_charging` and
        `sensor.<phone>_battery_state` with values like "charging" /
        "discharging". The binary form is the cleanest signal; fall
        back to the string-state sensor when only that exists.
        """
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

    def _find_device_tracker_entities(
        self, ctx: DetectorContext
    ) -> list[str]:
        """Phone device_trackers — restricted to those whose state has
        been one of HA's zone names recently (avoids generic network
        scanner trackers that just return "home"/"not_home")."""
        out: list[str] = []
        try:
            for state in ctx.hass.states.async_all():
                if not state.entity_id.startswith("device_tracker."):
                    continue
                # Mobile app trackers carry source_type=gps; others
                # are router-based and less reliable for commute.
                attrs = state.attributes or {}
                if attrs.get("source_type") == "gps":
                    out.append(state.entity_id)
        except Exception:  # noqa: BLE001
            pass
        return out

    # -------- sleep window --------

    def _derive_sleep_window(
        self,
        entity_id: str,
        events: list["StateEvent"],
    ) -> Insight | None:
        """Map charging-on / charging-off transitions to bedtime / wake
        and look for a clustered pattern across days."""
        plug_in_times: list[datetime] = []
        unplug_times: list[datetime] = []
        for ev in events:
            old = (ev.old_state or "").lower()
            new = (ev.new_state or "").lower()
            # Both shapes — binary_sensor: "on"/"off"; sensor: "charging"/"discharging"
            now_charging = new in {"on", "charging"}
            was_charging = old in {"on", "charging"}
            if not was_charging and now_charging:
                plug_in_times.append(ev.timestamp)
            elif was_charging and not now_charging:
                unplug_times.append(ev.timestamp)

        if len(plug_in_times) < _MIN_DAYS_FOR_PATTERN:
            return None
        if len(unplug_times) < _MIN_DAYS_FOR_PATTERN:
            return None

        bedtime_avg, bedtime_stddev, bedtime_days = self._cluster_times(
            plug_in_times
        )
        wake_avg, wake_stddev, wake_days = self._cluster_times(unplug_times)
        if bedtime_avg is None or wake_avg is None:
            return None
        # Filter to plausible patterns: bedtime late evening / night,
        # wake early-to-mid morning. Reject the "charges all day at
        # the desk" case where the variance would be huge anyway.
        if bedtime_stddev > _TIME_TOLERANCE_MIN:
            return None
        if wake_stddev > _TIME_TOLERANCE_MIN:
            return None

        def _fmt(minutes_past_midnight: float) -> str:
            mins = int(round(minutes_past_midnight))
            return f"{mins // 60:02d}:{mins % 60:02d}"

        # Approximate sleep duration (handles wrap-around — if bedtime
        # is 22:30 and wake is 07:15, sleep duration is 8h 45min).
        sleep_minutes = (wake_avg - bedtime_avg) % (24 * 60)
        hrs = sleep_minutes // 60
        mins = int(round(sleep_minutes % 60))

        phone_label = self._phone_label(entity_id)

        title = (
            f"Sleep pattern from {phone_label}: bedtime ~{_fmt(bedtime_avg)} "
            f"(±{int(round(bedtime_stddev))} min), wake ~{_fmt(wake_avg)} "
            f"(±{int(round(wake_stddev))} min). ~{hrs}h {mins:02d}m typical."
        )

        confidence = round(
            min(1.0, min(bedtime_days, wake_days) / 10.0)
            * max(0.0, 1.0 - max(bedtime_stddev, wake_stddev) / 90.0),
            3,
        )

        fingerprint: dict[str, Any] = {
            "kind": "phone_sleep_window",
            "entity_id": entity_id,
        }
        payload = {
            "entity_id": entity_id,
            "phone_label": phone_label,
            "bedtime": _fmt(bedtime_avg),
            "bedtime_stddev_min": round(bedtime_stddev, 1),
            "wake": _fmt(wake_avg),
            "wake_stddev_min": round(wake_stddev, 1),
            "sleep_hours_approx": hrs + mins / 60.0,
            "bedtime_days_observed": bedtime_days,
            "wake_days_observed": wake_days,
            "advice": (
                "Use this as a foundation for sleep-aware automations: "
                f"silence notifications between {_fmt(bedtime_avg)} and "
                f"{_fmt(wake_avg)}, set bedroom temperature to night "
                "preset at bedtime, fire a 'morning routine' automation "
                "at the average wake time. Future RoutineDetector "
                "enhancements can scope to this window automatically."
            ),
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

    # -------- commute pattern --------

    def _derive_commute_pattern(
        self,
        entity_id: str,
        events: list["StateEvent"],
    ) -> Insight | None:
        """device_tracker state transitions: home→away (departure) and
        away→home (arrival). Cluster across days."""
        depart_times: list[datetime] = []
        arrive_times: list[datetime] = []
        for ev in events:
            old = (ev.old_state or "").lower()
            new = (ev.new_state or "").lower()
            # Reject when either is unknown — adds noise. Only consider
            # well-defined home/away/zone transitions.
            if old in {"unknown", "unavailable", "none", ""}:
                continue
            if new in {"unknown", "unavailable", "none", ""}:
                continue
            was_home = old == "home"
            now_home = new == "home"
            if was_home and not now_home:
                depart_times.append(ev.timestamp)
            elif not was_home and now_home:
                arrive_times.append(ev.timestamp)

        if len(depart_times) < _MIN_DAYS_FOR_PATTERN:
            return None
        if len(arrive_times) < _MIN_DAYS_FOR_PATTERN:
            return None

        depart_avg, depart_stddev, depart_days = self._cluster_times(
            depart_times
        )
        arrive_avg, arrive_stddev, arrive_days = self._cluster_times(
            arrive_times
        )
        if depart_avg is None or arrive_avg is None:
            return None
        if depart_stddev > _TIME_TOLERANCE_MIN * 1.5:
            return None
        if arrive_stddev > _TIME_TOLERANCE_MIN * 1.5:
            return None

        def _fmt(minutes_past_midnight: float) -> str:
            mins = int(round(minutes_past_midnight))
            return f"{mins // 60:02d}:{mins % 60:02d}"

        phone_label = self._phone_label(entity_id)
        title = (
            f"Commute pattern from {phone_label}: leaves home ~{_fmt(depart_avg)} "
            f"(±{int(round(depart_stddev))} min), returns ~{_fmt(arrive_avg)} "
            f"(±{int(round(arrive_stddev))} min)."
        )

        confidence = round(
            min(1.0, min(depart_days, arrive_days) / 10.0)
            * max(0.0, 1.0 - max(depart_stddev, arrive_stddev) / 120.0),
            3,
        )

        fingerprint: dict[str, Any] = {
            "kind": "phone_commute",
            "entity_id": entity_id,
        }
        payload = {
            "entity_id": entity_id,
            "phone_label": phone_label,
            "departure": _fmt(depart_avg),
            "departure_stddev_min": round(depart_stddev, 1),
            "arrival": _fmt(arrive_avg),
            "arrival_stddev_min": round(arrive_stddev, 1),
            "departure_days_observed": depart_days,
            "arrival_days_observed": arrive_days,
            "advice": (
                "Pre-arrival HVAC, departure-triggered armed mode, "
                "arrival-triggered welcome lighting all become natural "
                "automations against this window. Trigger 10–15 min "
                f"before your typical arrival of {_fmt(arrive_avg)} to "
                "have the house ready."
            ),
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

    # -------- helpers --------

    @staticmethod
    def _cluster_times(
        times: list[datetime],
    ) -> tuple[float | None, float, int]:
        """Reduce a list of datetimes to (avg minutes-past-midnight,
        stddev, distinct-days)."""
        if len(times) < _MIN_DAYS_FOR_PATTERN:
            return None, 0.0, 0
        # One reading per day — take the earliest
        per_day: dict[date, datetime] = {}
        for t in times:
            local_t = dt_util.as_local(t)
            day = local_t.date()
            if day not in per_day or t < per_day[day]:
                per_day[day] = t
        if len(per_day) < _MIN_DAYS_FOR_PATTERN:
            return None, 0.0, 0
        local_times = [dt_util.as_local(per_day[d]) for d in per_day]
        # Special handling: if events straddle midnight, unwrap to
        # negative minutes (e.g., 23:45 → -15) so the mean isn't a
        # nonsense midday. Detect span > 12h and shift.
        minutes = [t.hour * 60 + t.minute + t.second / 60.0 for t in local_times]
        if max(minutes) - min(minutes) > 12 * 60:
            minutes = [m - 24 * 60 if m > 12 * 60 else m for m in minutes]
        avg = sum(minutes) / len(minutes)
        stddev = (
            sum((m - avg) ** 2 for m in minutes) / len(minutes)
        ) ** 0.5
        avg_modular = avg % (24 * 60)
        return avg_modular, stddev, len(per_day)

    @staticmethod
    def _phone_label(entity_id: str) -> str:
        """Pretty-print a phone identifier from the entity_id slug."""
        slug = entity_id.split(".", 1)[-1]
        for suffix in ("_charging", "_battery_state", "_battery_level"):
            if slug.endswith(suffix):
                slug = slug[: -len(suffix)]
                break
        return slug.replace("_", " ").title()
