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
from ..lib.cooccurrence_likelihood import DEFAULT_WINDOW_SECONDS as COOCC_WINDOW
from ..lib.event_filters import (
    is_after_long_silence,
    is_from_unavailable_state,
    pattern_value,
)
from ..lib.human_likelihood import assess_human_likelihood
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
        # v1.5.25: drop post-long-silence events (BYD car overnight,
        # sleepy BLE, cloud-polled idle). See lib/event_filters.py.
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
            # v1.6: event.* entities group by event_type, others by new_state
            value = pattern_value(ev)
            if value is None:
                continue
            groups[(ev.entity_id, value)].append(ev)

        insights: list[Insight] = []
        for (entity_id, new_state), events in groups.items():
            insight = self._evaluate_group(entity_id, new_state, events, ctx)
            if insight is not None:
                insights.append(insight)
        return insights

    def _is_candidate_event(self, ev: StateEvent) -> bool:
        # v1.6: pattern_value() resolves event_type for event.*, new_state
        # otherwise. event.* entities fire with unique timestamps, so the
        # no-op transition guard never matches and shouldn't.
        value = pattern_value(ev)
        if value is None:
            return False
        if ev.domain != "event" and ev.new_state == ev.old_state:
            return False
        if ev.domain in self.domains_default_blocked:
            return False
        if not self._is_enum_state(value):
            return False
        # v1.5.16: drop FROM-unavailable transitions. Skipped for event.*
        # (old_state is always a timestamp, never an unavailable sentinel).
        if ev.domain != "event" and is_from_unavailable_state(ev.old_state):
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
        self,
        entity_id: str,
        new_state: str,
        events: list[StateEvent],
        ctx: DetectorContext,
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

        # v1.5.38: composite human-likelihood assessment. Bundles
        # the timing / co-occurrence / persistence grader libs into
        # one call. Pre-v1.5.38 this was 3 separate assess + 3
        # apply_to_confidence calls; the composite collapses to one
        # so future grader libs (transition_entropy v1.5.39+) drop
        # into lib/human_likelihood.py and detectors don't change.
        # Behavior is byte-for-byte equivalent to the v1.5.37 chain —
        # see tests/test_lib_human_likelihood.py.
        integration = (
            ctx.hierarchy.integration_of.get(entity_id)
            if ctx.hierarchy is not None
            else None
        )
        iot_class = (
            ctx.iot_class_by_integration.get(integration)
            if integration
            else None
        )
        # Buffer queries: nearby-event counts within ±5s, and per-event
        # duration-in-state. Same logic as pre-v1.5.38, lifted out of
        # the apply chain so the composite call is the only line that
        # changes when grader libs are added later.
        nearby_counts: list[int] = []
        distinct_entity_counts: list[int] = []
        durations: list[float] = []
        prev_durations: list[float] = []
        if ctx.event_buffer is not None:
            from bisect import bisect_left as _bl
            from bisect import bisect_right as _br
            from datetime import timedelta as _td

            window = _td(seconds=COOCC_WINDOW)
            for ev in events:
                hits = 0
                distinct: set[str] = set()
                for other in ctx.event_buffer.query(
                    since=ev.timestamp - window,
                    until=ev.timestamp + window,
                ):
                    if other.entity_id != entity_id:
                        hits += 1
                        distinct.add(other.entity_id)
                nearby_counts.append(hits)
                distinct_entity_counts.append(len(distinct))
            # Persistence: snapshot per-entity timeline once, then for
            # each cluster event:
            #   forward  — how long it stays in the NEW state (bisect
            #              right finds next event after this one)
            #   backward — how long it was in the PREVIOUS state
            #              (bisect left finds the prior event)
            # v1.5.39: both directions feed assess_persistence; the lib
            # picks whichever has lower CV. Catches things like the
            # toothbrush OFF event where the brushing-session length
            # (backward) is the device fingerprint, not the time-until-
            # next-brushing (forward, varies daily).
            all_for_entity = sorted(
                (
                    ev for ev in ctx.event_buffer.query(entity_id=entity_id)
                    if not ev.from_bootstrap
                ),
                key=lambda ev: ev.timestamp,
            )
            ts_list = [ev.timestamp for ev in all_for_entity]
            for ev in events:
                idx_fwd = _br(ts_list, ev.timestamp)
                if idx_fwd < len(ts_list):
                    durations.append(
                        (ts_list[idx_fwd] - ev.timestamp).total_seconds()
                    )
                idx_bwd = _bl(ts_list, ev.timestamp)
                if idx_bwd > 0:
                    prev_durations.append(
                        (ev.timestamp - ts_list[idx_bwd - 1]).total_seconds()
                    )

        features = assess_human_likelihood(
            timestamps=[dt_util.as_local(ev.timestamp) for ev in events],
            nearby_counts=nearby_counts,
            durations_seconds=durations,
            previous_state_durations_seconds=prev_durations,
            distinct_entity_counts=distinct_entity_counts,
            iot_class=iot_class,
        )

        base_confidence = (
            min(1.0, len(minutes) / 14.0)
            * consistency
            * max(0.0, 1.0 - stddev / 15.0)
        )
        confidence = features.apply_to(base_confidence)

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

        # v1.5.26: sun-relative trigger detection. Same rationale as
        # streak — a "weekdays at 17:23" schedule that's really tied
        # to sunset will drift across the year and generate
        # automations that no longer match the user's actual behaviour
        # by summer. detect_sun_relative_trigger picks sun-relative
        # only when it's a meaningfully tighter fit than wall clock.
        sun_trigger_data: tuple[str, int] | None = None
        try:
            from .sun_relative import (
                build_sun_trigger,
                detect_sun_relative_trigger,
            )

            in_set_times_local = [
                dt_util.as_local(ev.timestamp)
                for ev in events
                if dt_util.as_local(ev.timestamp).weekday() in weekday_set
            ]
            sun_trigger_data = detect_sun_relative_trigger(
                in_set_times_local, ctx.hass
            )
        except Exception:
            sun_trigger_data = None

        description = f"Auto-detected routine: {weekday_label} at {time_str}"
        if sun_trigger_data is not None:
            trigger_block = [build_sun_trigger(*sun_trigger_data)]
            description += (
                f" — actually tracks {sun_trigger_data[0]} "
                f"({sun_trigger_data[1]:+d}min); using sun trigger so the "
                "schedule shifts with the seasons."
            )
        else:
            trigger_block = [{"platform": "time", "at": f"{time_str}:00"}]

        payload = {
            "alias": f"HA Insights: {weekday_label.lower()} {entity_id} {new_state}",
            "description": description,
            "trigger": trigger_block,
            "condition": [{"condition": "time", "weekday": weekdays_yaml}],
            "action": [{"service": service, "target": {"entity_id": entity_id}}],
            "mode": "single",
            # v1.5.38: composite payload merge. Adds all three
            # grader assessments at once. Future libs added to
            # HumanLikelihoodFeatures show up here automatically.
            # Underscore-prefixed → automation_writer strips before
            # automations.yaml write.
            **features.payload_keys(),
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
