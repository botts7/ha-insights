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

from homeassistant.util import dt as dt_util

from ..insight import Insight, InsightKind
from ..lib.event_filters import (
    is_after_long_silence,
    is_from_unavailable_state,
)
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
    # v1.12.12 — lower bound on plausible human variance. Same rationale
    # as ManualHabitDetector: across 3+ weeks, real human routines have
    # >=15s jitter (tablet taps, voice latency, walking to a switch).
    # Below that = automation / vendor weekly schedule (Tuya Monday-
    # morning timer, Z-Wave central-scene weekly routine, Hue
    # circadian). The detector doesn't check context.user_id at all, so
    # without this gate, every device-side weekly schedule would emit
    # at high confidence.
    TIME_STDDEV_MIN_MIN = 0.25

    # v1.23.2 — Discussion #104: seasonality detection needs at least
    # two cycles of the seasonal pattern to be statistically meaningful.
    # For weekly seasonality (the only kind we detect today) that's
    # 14 days. Below that, every event looks "seasonal" relative to
    # an empty baseline.
    MIN_DATA_DAYS_FOR_EMIT = 14

    async def scan(self, ctx: DetectorContext) -> list[Insight]:
        if ctx.event_buffer is None:
            return []

        # v1.23.2 warmup gate (see SeasonalityDetector.MIN_DATA_DAYS_FOR_EMIT).
        if hasattr(ctx.event_buffer, "data_span_days"):
            span = ctx.event_buffer.data_span_days()
            if (
                isinstance(span, (int, float))
                and span < self.MIN_DATA_DAYS_FOR_EMIT
            ):
                return []

        cutoff = datetime.now(tz=UTC) - timedelta(days=self.LOOKBACK_DAYS)
        groups: dict[tuple[str, str], list[StateEvent]] = defaultdict(list)
        # v1.5.25: drop post-long-silence events (poll wake-ups).
        last_seen_at: dict[str, datetime] = {}
        for ev in ctx.event_buffer.query(since=cutoff):
            prior_ts = last_seen_at.get(ev.entity_id)
            last_seen_at[ev.entity_id] = ev.timestamp
            if (
                ev.domain != "event"
                and is_after_long_silence(ev.timestamp, prior_ts)
            ):
                continue
            if not self._is_candidate_event(ev):
                continue
            # Skip transient device-passing-through states (media_player
            # buffering, cover opening/closing, etc) — patterning over
            # them is detecting the device's animation, not the user's
            # decision. See Detector.TRANSIENT_STATES_BY_DOMAIN.
            transient = self.TRANSIENT_STATES_BY_DOMAIN.get(ev.domain, frozenset())
            if ev.new_state in transient:
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
        # transitions — poll-cycle wake-ups, not seasonal behaviour.
        if is_from_unavailable_state(ev.old_state):
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

        # Convert to HA's local timezone before computing weekday — see
        # v1.0 review #2. A "Friday 7pm" routine in PST is Saturday 03:00
        # UTC; bucketing on UTC weekday classifies it wrong and emits an
        # automation with the wrong day name.
        per_weekday: Counter[int] = Counter(
            dt_util.as_local(ev.timestamp).weekday() for ev in events
        )
        dominant_weekday, dominant_event_count = per_weekday.most_common(1)[0]
        if dominant_event_count / len(events) < self.DOMINANCE_RATIO_MIN:
            return None

        # Pull events on the dominant weekday only — the rest are drift /
        # exceptions and would skew time-of-day stats.
        dominant_events = [
            ev
            for ev in events
            if dt_util.as_local(ev.timestamp).weekday() == dominant_weekday
        ]

        # MIN_DOMINANT_HITS is now interpreted as DISTINCT calendar dates
        # the pattern fired on, not raw event count. Was emitting things
        # like "8 of last 4 Thursdays" — nonsensical because 8 events on
        # 4 Thursdays read as 200%. Now we count UNIQUE Thursdays the
        # pattern fired on, which is bounded 0..4 and matches the user's
        # natural reading of "fired on N of the last 4 Thursdays".
        distinct_dates = {
            dt_util.as_local(ev.timestamp).date() for ev in dominant_events
        }
        distinct_date_count = len(distinct_dates)
        if distinct_date_count < self.MIN_DOMINANT_HITS:
            return None

        minutes = [
            self._minute_of_day(dt_util.as_local(ev.timestamp))
            for ev in dominant_events
        ]
        avg_min = sum(minutes) / len(minutes)
        variance = sum((m - avg_min) ** 2 for m in minutes) / len(minutes)
        stddev = math.sqrt(variance)
        if stddev > self.TIME_STDDEV_MAX_MIN:
            return None
        if stddev < self.TIME_STDDEV_MIN_MIN:
            # v1.12.12 robotic-precision gate. The detector doesn't
            # filter on context.user_id, so a Tuya / Hue / Z-Wave
            # device-side weekly schedule with ±0 min stddev across
            # 3+ Tuesdays would otherwise emit as a high-confidence
            # "automate this!" suggestion that the user can't apply
            # (the source already runs the schedule on the vendor
            # device). Match ManualHabitDetector's floor.
            return None

        # Confidence: how much of the 4-week window the pattern hit
        # (distinct-date scale) × dominance ratio × timing tightness.
        confidence = (
            min(1.0, distinct_date_count / 4.0)
            * (dominant_event_count / len(events))
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
            f"(fired on {distinct_date_count} of last 4 {weekday_label}s)"
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
