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

from homeassistant.util import dt as dt_util

from ..insight import Insight, InsightKind
from ..lib.timing_likelihood import (
    apply_to_confidence,
    assess_timing,
)
from ..lib.cooccurrence_likelihood import (
    DEFAULT_WINDOW_SECONDS as COOCC_WINDOW,
    apply_to_confidence as apply_coocc_to_confidence,
    assess_cooccurrence,
)
from ..lib.persistence_likelihood import (
    apply_to_confidence as apply_pers_to_confidence,
    assess_persistence,
)
from ..lib.event_filters import (
    is_after_long_silence,
    is_from_unavailable_state,
    pattern_value,
)
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
        # v1.5.25: track the previous event timestamp per entity so we
        # can drop "post-long-silence" events — implicit poll wake-ups
        # that look like real transitions but are just the integration
        # finally reporting state after going dark for hours. BYD car,
        # sleepy BLE devices, cloud-polled APIs.
        last_seen_at: dict[str, datetime] = {}
        for ev in ctx.event_buffer.query(since=cutoff):
            prior_ts = last_seen_at.get(ev.entity_id)
            last_seen_at[ev.entity_id] = ev.timestamp
            if (
                ev.domain != "event"
                and is_after_long_silence(ev.timestamp, prior_ts)
            ):
                # Post-silence wake-up: skip. Don't update last_seen
                # AGAIN — already set above so the NEXT event still
                # has the right anchor for gap detection.
                continue
            if not self._is_candidate_event(ev):
                continue
            # v1.6: pattern_value() returns event_type for event.*
            # entities, new_state for everything else. Grouping by the
            # right value is what makes button presses (which all share
            # the same event_type per kind but have unique timestamps
            # as state) cluster into a single pattern row.
            value = pattern_value(ev)
            if value is None:
                continue
            groups[(ev.entity_id, value)].append(ev)

        insights: list[Insight] = []
        for (entity_id, new_state), events in groups.items():
            # v1.5.26: pass ctx through so the per-group evaluator can
            # query HA's astral data for sun-relative trigger detection.
            insight = self._evaluate_group(entity_id, new_state, events, ctx)
            if insight is not None:
                insights.append(insight)
        return insights

    def _is_candidate_event(self, ev: StateEvent) -> bool:
        # v1.6: event.* entities fire with new_state = unique timestamp,
        # so the "no-op transition" guard (new_state == old_state) never
        # triggers and shouldn't — every event fire IS a new event. Use
        # the pattern_value indirection so the same code path works for
        # both regular entities and event entities.
        value = pattern_value(ev)
        if value is None:
            return False
        if ev.domain != "event" and ev.new_state == ev.old_state:
            return False
        if ev.domain in self.domains_default_blocked:
            return False
        if not self._is_enum_state(value):
            return False
        # v1.5.14 (extracted to lib/event_filters.py in v1.5.16):
        # drop transitions where the PREVIOUS state was
        # unavailable/unknown/none — poll-cycle wake-ups, not real
        # behaviour. Skipped for event.* entities (their old_state is
        # always a timestamp, never unavailable).
        if ev.domain != "event" and is_from_unavailable_state(ev.old_state):
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
        ctx: DetectorContext,
    ) -> Insight | None:
        # All time-of-day arithmetic happens in HA-LOCAL time. Buffer
        # timestamps are UTC; using .date()/.hour/.minute on them
        # produced wrong-day bucketing AND wrong-time titles for every
        # non-UTC user. A user in UTC+12 reported "evening" lights
        # showing as "07:34" — that's the UTC equivalent of 19:34 local.
        per_day: dict[date, datetime] = {}
        for ev in events:
            local_ts = dt_util.as_local(ev.timestamp)
            day = local_ts.date()
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

        # Compute time-of-day stddev within the streak's events.
        # IMPORTANT: convert each timestamp to LOCAL before extracting
        # hour/minute. Used to read .hour/.minute on UTC datetimes which
        # showed evening events as morning times for users east of UTC.
        streak_times_local = [
            dt_util.as_local(per_day[d]) for d in longest_run
        ]
        minutes_past_midnight = [
            t.hour * 60 + t.minute + t.second / 60.0
            for t in streak_times_local
        ]
        avg = sum(minutes_past_midnight) / len(minutes_past_midnight)
        stddev = math.sqrt(
            sum((m - avg) ** 2 for m in minutes_past_midnight)
            / len(minutes_past_midnight)
        )
        if stddev > _TIME_STDDEV_MAX_MIN:
            return None

        # If ScheduleDetector would also fire on this group, skip — let
        # the stronger detector own it. Same local-time conversion
        # applies here so the comparison metric matches.
        all_minutes = [
            (
                dt_util.as_local(ev.timestamp).hour * 60
                + dt_util.as_local(ev.timestamp).minute
            )
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

        # v1.5.35: timing-likelihood scoring. Same lib + math as
        # schedule.py — demote streaks whose timing is statistically
        # too tight to be human (likely a device internal timer or
        # platform schedule firing on a cron). See
        # `lib/timing_likelihood.py` for the iot_class-aware threshold
        # tables and stddev / range math.
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
        timing = assess_timing(
            timestamps=streak_times_local,
            iot_class=iot_class,
        )
        # v1.5.36: co-occurrence — count other-entity activity within
        # ±5s of each streak event. Streaks that fire in isolation are
        # device-timer signature; multimodal context = human action.
        nearby_counts: list[int] = []
        if ctx.event_buffer is not None:
            window = timedelta(seconds=COOCC_WINDOW)
            for ts_local in streak_times_local:
                hits = sum(
                    1
                    for other in ctx.event_buffer.query(
                        since=ts_local - window,
                        until=ts_local + window,
                    )
                    if other.entity_id != entity_id
                )
                nearby_counts.append(hits)
        cooccurrence = assess_cooccurrence(nearby_counts)

        # v1.5.37: persistence — fixed-cycle session lengths are device
        # timers (toothbrush 2-min, NVR hourly profile). Per cluster
        # event, look up the next state-change for this entity and
        # record the gap. Sessions still open at buffer's edge are
        # omitted so we don't bias toward shorter durations.
        durations: list[float] = []
        if ctx.event_buffer is not None:
            from bisect import bisect_right as _br

            all_for_entity = sorted(
                (
                    ev for ev in ctx.event_buffer.query(entity_id=entity_id)
                    if not ev.from_bootstrap
                ),
                key=lambda ev: ev.timestamp,
            )
            ts_list = [ev.timestamp for ev in all_for_entity]
            for d in longest_run:
                ev_ts = per_day[d]
                idx = _br(ts_list, ev_ts)
                if idx < len(ts_list):
                    durations.append(
                        (ts_list[idx] - ev_ts).total_seconds()
                    )
        persistence = assess_persistence(durations)

        base_confidence = min(1.0, len(longest_run) / 7.0) * max(
            0.0, 1.0 - stddev / 60.0,
        )
        confidence = apply_to_confidence(base_confidence, timing)
        confidence = apply_coocc_to_confidence(confidence, cooccurrence)
        confidence = apply_pers_to_confidence(confidence, persistence)
        confidence = round(confidence, 3)

        title = (
            f"{entity_id} -> {new_state} "
            f"{len(longest_run)} days in a row at ~{avg_time[:5]}. "
            "Build automation?"
        )

        fingerprint = {
            "entity_id": entity_id,
            "new_state": new_state,
            "kind": "streak",
            "streak_length": len(longest_run),
        }

        domain = entity_id.split(".", 1)[0] if "." in entity_id else "homeassistant"
        service = self._domain_to_service(domain, new_state)

        # v1.5.26: check if the pattern correlates better with sunset
        # or sunrise than with the wall clock. A streak that fires at
        # ~17:30 in December and ~21:30 in June would have huge
        # clock-time stddev but a tight offset from sunset. Generating
        # a `platform: time, at: '17:30'` automation for it would be
        # season-broken — drifts away from the user's actual pattern
        # as the year progresses. Sun-relative trigger fixes that.
        # Returns None if clock is the better fit OR fewer than 3
        # observations OR offset > ±2 hours. See sun_relative.py.
        sun_trigger_data: tuple[str, int] | None = None
        try:
            from .sun_relative import (
                build_sun_trigger,
                detect_sun_relative_trigger,
            )

            sun_trigger_data = detect_sun_relative_trigger(
                streak_times_local, ctx.hass
            )
        except Exception:  # noqa: BLE001
            sun_trigger_data = None

        if sun_trigger_data is not None:
            trigger_block = [build_sun_trigger(*sun_trigger_data)]
            description_extra = (
                f" Trigger uses HA's sun platform "
                f"({sun_trigger_data[0]} offset {sun_trigger_data[1]:+d}min) "
                "so the automation tracks the user's real pattern across "
                "the year instead of drifting with the seasons."
            )
        else:
            trigger_block = [{"platform": "time", "at": avg_time}]
            description_extra = ""

        payload = {
            "alias": (
                f"HA Insights: streak {entity_id} -> {new_state} at "
                f"{avg_time[:5]}"
            ),
            "description": (
                f"Auto-detected streak: {entity_id} entered '{new_state}' "
                f"on {len(longest_run)} consecutive days at ~{avg_time[:5]}. "
                "Confidence is moderate — verify before applying."
                f"{description_extra}"
            ),
            "trigger": trigger_block,
            "action": [
                {"service": service, "target": {"entity_id": entity_id}}
            ],
            "mode": "single",
            # v1.5.35: timing assessment for card tooltip + LLM context.
            # Underscore-prefixed so automation_writer strips it
            # before the YAML hits automations.yaml.
            "_timing_assessment": timing.to_dict(),
            # v1.5.36: co-occurrence assessment — surrounding-event
            # density per streak event.
            "_cooccurrence_assessment": cooccurrence.to_dict(),
            # v1.5.37: persistence — duration-in-state distribution.
            # CV < 5% = device cycle.
            "_persistence_assessment": persistence.to_dict(),
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
