"""SeasonalityDetector — weekly-cadence routines (e.g. "every Friday at 7pm").

Sibling to ScheduleDetector but tuned for *single-weekday* patterns.
ScheduleDetector requires >=10 events in 14 days with a multi-day weekday
classifier (weekdays / weekends / daily), so a strict Friday-only routine
is invisible to it — 4 weeks gives at most 4 firings, an order of
magnitude under the schedule threshold.

Algorithm:
  1. Look back 28 days (4 occurrences of each weekday)
  2. Group state events by (entity_id, new_state)
  3. For each group, build a weekday histogram
  4. Find the dominant weekday: must be >=70% of all events for the group
     AND must have fired >=3 of the 4 possible occurrences in the window
  5. Compute mean time-of-day across that weekday's firings; stddev <= 30 min
  6. Emit AUTOMATION_PROPOSAL with `time:` trigger + `condition: time` weekday
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from ..insight import Insight, InsightKind
from .base import Detector, DetectorContext, register_detector

if TYPE_CHECKING:
    from ..observers.state_event_buffer import StateEvent


_WEEKDAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_WEEKDAY_LABELS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


@register_detector
class SeasonalityDetector(Detector):
    """Detect weekly routines tied to a single dominant weekday."""

    name = "seasonality"
    kind = InsightKind.AUTOMATION_PROPOSAL
    requires_recorder = False

    LOOKBACK_DAYS = 28
    # Need this many firings on the target weekday across the window
    # (4 weeks => at most 4 occurrences). 3 of 4 catches strong patterns
    # while tolerating one missed week (vacation, sick day, missed event).
    MIN_DOMINANT_HITS = 3
    # Dominant weekday must account for this fraction of all events for
    # the (entity, state) group. 0.7 lets the user occasionally do the
    # same routine on a different day without breaking the pattern.
    DOMINANCE_RATIO_MIN = 0.7
    # Max time-of-day stddev (minutes). Looser than ScheduleDetector's 8min
    # because weekly events naturally drift more than daily ones.
    TIME_STDDEV_MAX_MIN = 30.0

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
        return True

    @staticmethod
    def _is_enum_state(state: str) -> bool:
        if not state or len(state) > 20:
            return False
        if "." in state or state in {"unavailable", "unknown", "none"}:
            return False
        return True

    def _evaluate_group(
        self, entity_id: str, new_state: str, events: list[StateEvent]
    ) -> Insight | None:
        if len(events) < self.MIN_DOMINANT_HITS:
            return None

        per_weekday: Counter[int] = Counter(ev.timestamp.weekday() for ev in events)
        dominant_weekday, dominant_count = per_weekday.most_common(1)[0]
        if dominant_count < self.MIN_DOMINANT_HITS:
            return None
        if dominant_count / len(events) < self.DOMINANCE_RATIO_MIN:
            return None

        # Time stats over the dominant weekday's events only — the rest
        # might be drift/exceptions and would skew the mean.
        dominant_events = [
            ev for ev in events if ev.timestamp.weekday() == dominant_weekday
        ]
        minutes = [self._minute_of_day(ev.timestamp) for ev in dominant_events]
        avg_min = sum(minutes) / len(minutes)
        variance = sum((m - avg_min) ** 2 for m in minutes) / len(minutes)
        stddev = math.sqrt(variance)
        if stddev > self.TIME_STDDEV_MAX_MIN:
            return None

        # Confidence: hits scale (max at 4 of 4) * dominance ratio * tightness.
        confidence = (
            min(1.0, dominant_count / 4.0)
            * (dominant_count / len(events))
            * max(0.3, 1.0 - stddev / 60.0)
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
            "dominant_weekday": dominant_weekday,
            # Quantize the time so re-scans within 5 min produce the same id
            "time_bucket": round(avg_min / 5) * 5,
        }

        weekday_label = _WEEKDAY_LABELS[dominant_weekday]
        title = (
            f"Every {weekday_label} at ~{time_str}, {entity_id} -> {new_state} "
            f"({dominant_count} of last 4 {weekday_label}s)"
        )

        domain = entity_id.split(".", 1)[0] if "." in entity_id else "homeassistant"
        service = self._domain_to_service(domain, new_state)

        payload = {
            "alias": f"HA Insights: {weekday_label.lower()} {entity_id} {new_state}",
            "description": (
                f"Auto-detected weekly routine: every {weekday_label} at "
                f"approximately {time_str}."
            ),
            "trigger": [{"platform": "time", "at": f"{time_str}:00"}],
            "condition": [
                {"condition": "time", "weekday": [_WEEKDAY_NAMES[dominant_weekday]]}
            ],
            "action": [{"service": service, "target": {"entity_id": entity_id}}],
            "mode": "single",
        }

        area_id = dominant_events[0].area_id if dominant_events else None
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
    def _domain_to_service(domain: str, state: str) -> str:
        if state in {"on", "off"}:
            return f"{domain}.turn_{state}"
        return f"{domain}.turn_on"
