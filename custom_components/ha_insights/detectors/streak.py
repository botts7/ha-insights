"""StreakDetector — emerging routines (lower bar than ScheduleDetector).

Where ScheduleDetector waits for a strong statistical signal (10+
occurrences, tight time clustering across 14 days), StreakDetector
fires on consecutive-day runs of 3+ days. Catches routines that just
started forming and gives the user a chance to formalize them early.

We avoid double-emitting with ScheduleDetector by skipping any group
that already meets Schedule's bar — let the stronger detector own
those. StreakDetector owns the gap between "noise" and "obvious
schedule".
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from itertools import pairwise
from typing import TYPE_CHECKING

from ..insight import Insight, InsightKind
from .base import Detector, DetectorContext, register_detector

if TYPE_CHECKING:
    from ..observers.state_event_buffer import StateEvent


# Lower bar than schedule but still need _some_ time clustering.
_MIN_STREAK_DAYS = 3
_TIME_STDDEV_MAX_MIN = 30.0
_LOOKBACK_DAYS = 14

# To avoid stepping on ScheduleDetector's insights, skip groups that
# already meet its bar. Mirrored from schedule.py for clarity.
_SCHEDULE_MIN_OCCURRENCES = 10
_SCHEDULE_TIME_STDDEV_MAX_MIN = 8.0


@register_detector
class StreakDetector(Detector):
    """Detect emerging routines via consecutive-day streaks."""

    name = "streak"
    kind = InsightKind.AUTOMATION_PROPOSAL
    requires_recorder = False

    async def scan(self, ctx: DetectorContext) -> list[Insight]:
        if ctx.event_buffer is None:
            return []

        cutoff = datetime.now(tz=UTC) - timedelta(days=_LOOKBACK_DAYS)
        groups: dict[tuple[str, str], list[StateEvent]] = defaultdict(list)
        for ev in ctx.event_buffer.query(since=cutoff):
            if not self._is_candidate_event(ev):
                continue
            assert ev.new_state is not None
            groups[(ev.entity_id, ev.new_state)].append(ev)

        insights: list[Insight] = []
        for (entity_id, new_state), events in groups.items():
            insight = self._evaluate_group(entity_id, new_state, events)
            if insight is not None:
                insights.append(insight)
        return insights

    def _is_candidate_event(self, ev: StateEvent) -> bool:
        if ev.new_state is None or ev.new_state == ev.old_state:
            return False
        if ev.domain in self.domains_default_blocked:
            return False
        if not self._is_enum_state(ev.new_state):
            return False
        return True

    @staticmethod
    def _is_enum_state(state: str) -> bool:
        if not state or len(state) > 20:
            return False
        if "." in state or state in {"unavailable", "unknown", "none"}:
            return False
        return True

    def _evaluate_group(
        self,
        entity_id: str,
        new_state: str,
        events: list[StateEvent],
    ) -> Insight | None:
        # Map each event to its calendar date, keep the earliest per day.
        per_day: dict[date, datetime] = {}
        for ev in events:
            day = ev.timestamp.date()
            if day not in per_day or ev.timestamp < per_day[day]:
                per_day[day] = ev.timestamp

        if len(per_day) < _MIN_STREAK_DAYS:
            return None

        sorted_days = sorted(per_day.keys())
        # Find longest consecutive run + which days it spans.
        longest_run: list[date] = []
        current_run: list[date] = [sorted_days[0]]
        for prev, cur in pairwise(sorted_days):
            if (cur - prev).days == 1:
                current_run.append(cur)
            else:
                if len(current_run) > len(longest_run):
                    longest_run = current_run
                current_run = [cur]
        if len(current_run) > len(longest_run):
            longest_run = current_run

        if len(longest_run) < _MIN_STREAK_DAYS:
            return None

        # Compute time-of-day stddev within the streak's events
        streak_times = [per_day[d] for d in longest_run]
        minutes_past_midnight = [
            t.hour * 60 + t.minute + t.second / 60.0 for t in streak_times
        ]
        avg = sum(minutes_past_midnight) / len(minutes_past_midnight)
        stddev = math.sqrt(
            sum((m - avg) ** 2 for m in minutes_past_midnight)
            / len(minutes_past_midnight)
        )
        if stddev > _TIME_STDDEV_MAX_MIN:
            return None

        # If ScheduleDetector would also fire on this group, skip — let
        # the stronger detector own it.
        all_minutes = [
            ev.timestamp.hour * 60 + ev.timestamp.minute
            for ev in events
        ]
        all_avg = sum(all_minutes) / len(all_minutes)
        all_stddev = math.sqrt(
            sum((m - all_avg) ** 2 for m in all_minutes) / len(all_minutes)
        )
        if (
            len(events) >= _SCHEDULE_MIN_OCCURRENCES
            and all_stddev <= _SCHEDULE_TIME_STDDEV_MAX_MIN
        ):
            return None

        avg_minute = round(avg)
        avg_hour = avg_minute // 60
        avg_min_within = avg_minute % 60
        avg_time = time(hour=avg_hour, minute=avg_min_within).strftime("%H:%M:%S")

        confidence = round(
            min(1.0, len(longest_run) / 7.0)
            * max(0.0, 1.0 - stddev / 60.0),
            3,
        )

        title = (
            f"{entity_id} -> {new_state} "
            f"{len(longest_run)} days in a row at ~{avg_time[:5]}. "
            "Emerging routine?"
        )

        fingerprint = {
            "entity_id": entity_id,
            "new_state": new_state,
            "kind": "streak",
            "streak_length": len(longest_run),
        }

        domain = entity_id.split(".", 1)[0] if "." in entity_id else "homeassistant"
        service = self._domain_to_service(domain, new_state)

        payload = {
            "alias": (
                f"HA Insights: streak {entity_id} -> {new_state} at "
                f"{avg_time[:5]}"
            ),
            "description": (
                f"Auto-detected streak: {entity_id} entered '{new_state}' "
                f"on {len(longest_run)} consecutive days at ~{avg_time[:5]}. "
                "Confidence is moderate — verify before applying."
            ),
            "trigger": [{"platform": "time", "at": avg_time}],
            "action": [
                {"service": service, "target": {"entity_id": entity_id}}
            ],
            "mode": "single",
        }

        return Insight(
            id=Insight.compute_id(InsightKind.AUTOMATION_PROPOSAL, fingerprint),
            kind=InsightKind.AUTOMATION_PROPOSAL,
            detector=self.name,
            area_id=None,
            title=title,
            confidence=confidence,
            fingerprint=fingerprint,
            payload=payload,
            payload_format="automation",
            created_at=datetime.now(tz=UTC),
        )

    @staticmethod
    def _domain_to_service(domain: str, state: str) -> str:
        if state in {"on", "off"}:
            return f"{domain}.turn_{state}"
        return f"{domain}.turn_on"
