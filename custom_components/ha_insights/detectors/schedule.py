"""ScheduleDetector — strong time-of-day routines.

Detects routines like 'you do X every weekday at ~T' from the StateEventBuffer
and emits AUTOMATION_PROPOSAL insights with a ready-to-apply HA automation
payload. Runs heuristically on the rolling buffer; no recorder required.

Algorithm:
  1. Pull last LOOKBACK_DAYS of state changes
  2. Group by (entity_id, new_state); keep enum-like states only
  3. For each group: classify weekday set (weekdays / weekends / daily),
     require >= MIN_OCCURRENCES events, weekday consistency >= threshold,
     time-of-day stddev <= threshold
  4. Confidence = min(1, n/14) * weekday_consistency * (1 - stddev/15)
  5. Emit Insight with automation YAML payload

Blueprint emission as an alternative payload_format is on the roadmap but
not yet built; raw automation YAML is what's emitted today.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.util import dt as dt_util

from ..insight import Insight, InsightKind
from ..lib.event_filters import is_from_unavailable_state
from .base import Detector, DetectorContext, register_detector

if TYPE_CHECKING:
    from ..observers.state_event_buffer import StateEvent


_WEEKDAYS = frozenset({0, 1, 2, 3, 4})
_WEEKENDS = frozenset({5, 6})
_ALL_DAYS = frozenset({0, 1, 2, 3, 4, 5, 6})

_WEEKDAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@register_detector
class ScheduleDetector(Detector):
    """Detect repeating time-of-day routines."""

    name = "schedule"
    kind = InsightKind.AUTOMATION_PROPOSAL
    requires_recorder = False

    LOOKBACK_DAYS = 14
    # Real human routines aren't 100% consistent — sick days, vacations,
    # the kid's school holidays. 7 of 14 days catches genuine half-time
    # patterns the user identifies as "we usually do X" without losing
    # them to a few exceptions. (Was 10 — too strict; user reported real
    # patterns missing because they happened on 8 of 14 days.)
    MIN_OCCURRENCES = 7
    # Real wake-up routines vary 7:00 ± 5-10 min. 8min stddev was tight;
    # 12min lets us catch "I turn on the lights between 6:55 and 7:15"
    # which is what real humans actually do.
    TIME_STDDEV_MAX_MIN = 12.0
    WEEKDAY_CONSISTENCY_MIN = 0.75

    async def scan(self, ctx: DetectorContext) -> list[Insight]:
        if ctx.event_buffer is None:
            return []

        cutoff = datetime.now(tz=UTC) - timedelta(days=self.LOOKBACK_DAYS)
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
        # v1.5.16 (extracted to lib/event_filters.py): drop FROM-unavailable
        # transitions — poll-cycle wake-ups, not real schedule events.
        if is_from_unavailable_state(ev.old_state):
            return False
        return True

    @staticmethod
    def _is_enum_state(state: str) -> bool:
        """Heuristic: enum-like states are short, no decimal, no special markers."""
        if not state or len(state) > 20:
            return False
        if "." in state or state in {"unavailable", "unknown", "none"}:
            return False
        return True

    def _evaluate_group(
        self, entity_id: str, new_state: str, events: list[StateEvent]
    ) -> Insight | None:
        if len(events) < self.MIN_OCCURRENCES:
            return None

        # Convert to HA's local timezone before extracting weekday + time
        # of day. A "Friday 7pm" routine in PST fires at Saturday 03:00 UTC;
        # without this conversion the detector would classify it as
        # Saturday and emit the apply payload with the wrong weekday.
        # v1.0 review #2.
        weekday_minute = [
            (
                dt_util.as_local(ev.timestamp).weekday(),
                self._minute_of_day(dt_util.as_local(ev.timestamp)),
            )
            for ev in events
        ]
        weekday_set = self._classify_weekdays([d for d, _ in weekday_minute])
        if weekday_set is None:
            return None

        in_set = [(d, m) for d, m in weekday_minute if d in weekday_set]
        consistency = len(in_set) / len(weekday_minute)
        if consistency < self.WEEKDAY_CONSISTENCY_MIN:
            return None
        if len(in_set) < self.MIN_OCCURRENCES:
            return None

        minutes = [m for _, m in in_set]
        avg_min = sum(minutes) / len(minutes)
        variance = sum((m - avg_min) ** 2 for m in minutes) / len(minutes)
        stddev = math.sqrt(variance)
        if stddev > self.TIME_STDDEV_MAX_MIN:
            return None

        confidence = (
            min(1.0, len(minutes) / 14.0)
            * consistency
            * max(0.0, 1.0 - stddev / 15.0)
        )

        avg_h = int(avg_min // 60)
        avg_m_int = round(avg_min % 60)
        if avg_m_int == 60:
            avg_h += 1
            avg_m_int = 0
        time_str = f"{avg_h:02d}:{avg_m_int:02d}"

        fingerprint = {
            "entity_id": entity_id,
            "new_state": new_state,
            "weekday_set": sorted(weekday_set),
            "time_bucket": round(avg_min / 5) * 5,
        }

        weekday_label = self._weekday_label(weekday_set)
        title = (
            f"{weekday_label} at ~{time_str}, {entity_id} -> {new_state} "
            f"({len(minutes)} of {len(events)} days). Automate this?"
        )

        domain = entity_id.split(".", 1)[0] if "." in entity_id else "homeassistant"
        service = self._domain_to_service(domain, new_state)
        weekdays_yaml = [_WEEKDAY_NAMES[d] for d in sorted(weekday_set)]

        payload = {
            "alias": f"HA Insights: {weekday_label.lower()} {entity_id} {new_state}",
            "description": f"Auto-detected routine: {weekday_label} at {time_str}",
            "trigger": [{"platform": "time", "at": f"{time_str}:00"}],
            "condition": [{"condition": "time", "weekday": weekdays_yaml}],
            "action": [{"service": service, "target": {"entity_id": entity_id}}],
            "mode": "single",
        }

        area_id = events[0].area_id if events else None
        return Insight(
            id=Insight.compute_id(InsightKind.AUTOMATION_PROPOSAL, fingerprint),
            kind=InsightKind.AUTOMATION_PROPOSAL,
            detector=self.name,
            area_id=area_id,
            title=title,
            confidence=round(confidence, 3),
            fingerprint=fingerprint,
            payload=payload,
            payload_format="automation",
            created_at=datetime.now(tz=UTC),
        )

    @staticmethod
    def _minute_of_day(t: datetime) -> int:
        return t.hour * 60 + t.minute

    @staticmethod
    def _classify_weekdays(weekdays: list[int]) -> frozenset[int] | None:
        """Pick the smallest weekday set the events belong to."""
        unique = set(weekdays)
        if unique <= _WEEKDAYS and len(unique) >= 3:
            return _WEEKDAYS
        if unique <= _WEEKENDS and len(unique) >= 2:
            return _WEEKENDS
        if unique == _ALL_DAYS:
            return _ALL_DAYS
        return None

    @staticmethod
    def _weekday_label(weekday_set: frozenset[int]) -> str:
        if weekday_set == _WEEKDAYS:
            return "On weekdays"
        if weekday_set == _WEEKENDS:
            return "On weekends"
        if weekday_set == _ALL_DAYS:
            return "Every day"
        return "On selected days"

    @staticmethod
    def _domain_to_service(domain: str, state: str) -> str:
        if state in {"on", "off"}:
            return f"{domain}.turn_{state}"
        # Other enum states (e.g., 'home', 'away', 'opened') -> activate
        return f"{domain}.turn_on"
