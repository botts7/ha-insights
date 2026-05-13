"""RoutineDetector — surface morning / evening / bedtime routines.

Where ManualHabitDetector flags a single entity the user toggles
manually every day, RoutineDetector finds CLUSTERS — multiple entities
the user manipulates within a short window across days. The classic
case: every morning around 07:00–07:30 the user turns on the kitchen
light, starts the coffee, and opens the bedroom blinds — three
distinct manual actions, but one mental "morning routine".

Output: a single multi-action automation YAML with all the entities
the user touches, ordered by typical sequence. The user can apply
it as-is or trim entities out before applying.

Algorithm sketch:
  1. Filter buffer to manual events (context_user_id is non-None).
  2. Bucket each event into a (local day, 30-min window) cell.
  3. Within each cell, collect the set of (entity_id, target_state).
  4. Find cells whose membership repeats: same trio (or more) across
     ≥ _MIN_ROUTINE_DAYS days, with ≥ _ROUTINE_PRESENCE_RATIO of
     those days having all the routine entities present.
  5. For each detected routine, compute the median start-time and
     build a single automation YAML with a `time:` trigger and an
     action per entity.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.util import dt as dt_util

from ..insight import Insight, InsightKind
from .base import Detector, DetectorContext, register_detector
from .manual_habit import _DOMAIN_SERVICE_MAP, _WEEKDAY_NAMES, _WEEKDAYS_ONLY

if TYPE_CHECKING:
    from ..observers.state_event_buffer import StateEvent


_LOOKBACK_DAYS = 14
# A routine needs ≥3 distinct entity-state pairs co-occurring. Two is
# coincidence; three starts to be a real mental grouping.
_MIN_ROUTINE_SIZE = 3
# Routine must show on at least this many days within the lookback.
_MIN_ROUTINE_DAYS = 5
# Within the window, this fraction of days must include EVERY entity
# in the routine. Allows occasional skip (e.g., one travel day) but
# rejects "user touched all three exactly twice".
_ROUTINE_PRESENCE_RATIO = 0.80
# Time bucket width for clustering events into "around the same time"
# groups. 30 min is loose enough for human variance, tight enough that
# 09:00 and 17:00 don't merge.
_BUCKET_MINUTES = 30


@register_detector
class RoutineDetector(Detector):
    """Detect manual co-occurring entity sequences (morning / bedtime routines)."""

    name = "routine"
    kind = InsightKind.AUTOMATION_PROPOSAL
    requires_recorder = False

    async def scan(self, ctx: DetectorContext) -> list[Insight]:
        if ctx.event_buffer is None:
            return []

        cutoff = datetime.now(tz=UTC) - timedelta(days=_LOOKBACK_DAYS)
        # {(day, bucket_idx): list of (entity_id, target_state, local_ts)}
        cells: dict[tuple[date, int], list[tuple[str, str, datetime]]] = (
            defaultdict(list)
        )
        for ev in ctx.event_buffer.query(since=cutoff):
            if not self._is_candidate_event(ev):
                continue
            assert ev.new_state is not None
            local_ts = dt_util.as_local(ev.timestamp)
            bucket = (
                local_ts.hour * 60 + local_ts.minute
            ) // _BUCKET_MINUTES
            cells[(local_ts.date(), bucket)].append(
                (ev.entity_id, ev.new_state, local_ts)
            )

        # Group cells by bucket-of-day (across days) to find recurring
        # multi-entity activity in the same time-of-day slot.
        by_bucket: dict[int, list[tuple[date, list[tuple[str, str, datetime]]]]] = (
            defaultdict(list)
        )
        for (day, bucket), members in cells.items():
            # De-duplicate (entity, state) within the day's cell so a
            # rapidly-toggled switch counts once.
            uniq = list({(e, s): (e, s, t) for (e, s, t) in members}.values())
            if not uniq:
                continue
            by_bucket[bucket].append((day, uniq))

        # Skip already-handled signatures to avoid suggesting duplicates.
        already_handled = self._signatures_of_existing_automations(ctx)

        insights: list[Insight] = []
        for bucket, day_cells in by_bucket.items():
            insight = self._evaluate_bucket(bucket, day_cells, already_handled)
            if insight is not None:
                insights.append(insight)
        return insights

    # -------- candidate filter --------

    def _is_candidate_event(self, ev: "StateEvent") -> bool:
        if ev.new_state is None or ev.new_state == ev.old_state:
            return False
        if ev.context_user_id is None:
            return False  # manual only
        if ev.domain in self.domains_default_blocked:
            return False
        if ev.domain not in _DOMAIN_SERVICE_MAP:
            return False
        if ev.new_state not in _DOMAIN_SERVICE_MAP[ev.domain]:
            return False
        return True

    # -------- evaluation --------

    def _evaluate_bucket(
        self,
        bucket: int,
        day_cells: list[tuple[date, list[tuple[str, str, datetime]]]],
        already_handled: set[tuple[str, str, int]],
    ) -> Insight | None:
        if len(day_cells) < _MIN_ROUTINE_DAYS:
            return None

        # Count (entity, state) appearances across days
        pair_counts: Counter[tuple[str, str]] = Counter()
        for _day, members in day_cells:
            for entity_id, target_state, _ts in members:
                pair_counts[(entity_id, target_state)] += 1

        # Promote pairs present in ≥ ratio of days.
        min_present = int(len(day_cells) * _ROUTINE_PRESENCE_RATIO)
        routine_pairs: list[tuple[str, str]] = [
            p for p, c in pair_counts.most_common() if c >= min_present
        ]
        if len(routine_pairs) < _MIN_ROUTINE_SIZE:
            return None

        # Find the days where ALL routine_pairs were present (the
        # "core days" — these define the trigger time + day-of-week
        # pattern).
        routine_set = set(routine_pairs)
        core_day_times: list[datetime] = []
        core_days: list[date] = []
        for day, members in day_cells:
            member_pairs = {(e, s) for e, s, _ in members}
            if routine_set <= member_pairs:
                # Use the EARLIEST timestamp in the routine as the
                # routine's start time for that day.
                earliest = min(
                    t for e, s, t in members if (e, s) in routine_set
                )
                core_day_times.append(earliest)
                core_days.append(day)

        if len(core_days) < _MIN_ROUTINE_DAYS:
            return None

        # Average start-time across core days (LOCAL TIME, already from
        # cells construction).
        minutes_past_midnight = [
            t.hour * 60 + t.minute + t.second / 60.0 for t in core_day_times
        ]
        avg = sum(minutes_past_midnight) / len(minutes_past_midnight)
        stddev = (
            sum((m - avg) ** 2 for m in minutes_past_midnight)
            / len(minutes_past_midnight)
        ) ** 0.5

        avg_minute = round(avg)
        avg_hour = avg_minute // 60
        avg_min_within = avg_minute % 60
        avg_time_str = time(
            hour=avg_hour, minute=avg_min_within
        ).strftime("%H:%M:%S")

        # Cross-reference: if EVERY entity in the routine is already
        # handled by an automation at this hour, suppress. Otherwise
        # we'd duplicate work the user has already done.
        bucket_hour = avg_hour  # 60-min bucket from manual_habit semantics
        if all(
            (eid, st, bucket_hour) in already_handled for eid, st in routine_pairs
        ):
            return None

        # Weekday-only?
        observed_weekdays: set[str] = {
            _WEEKDAY_NAMES[d.weekday()] for d in core_days
        }
        weekdays_only = observed_weekdays <= _WEEKDAYS_ONLY

        # Round trigger time to nearest 5 min for clean YAML
        trigger_minute = round(avg_min_within / 5) * 5
        if trigger_minute == 60:
            trigger_hour = (avg_hour + 1) % 24
            trigger_minute = 0
        else:
            trigger_hour = avg_hour
        trigger_time = f"{trigger_hour:02d}:{trigger_minute:02d}"

        # Routine name heuristic from time of day
        routine_label = self._routine_label(avg_hour)

        # Predictive scheduling — try sun-relative trigger first.
        # Morning routines often track sunrise; evening routines track
        # sunset. When the data fits, use that instead of a fixed time.
        sun_trigger_data: tuple[str, int] | None = None
        try:
            from .sun_relative import detect_sun_relative_trigger

            sun_trigger_data = detect_sun_relative_trigger(
                core_day_times, ctx.hass
            )
        except Exception:  # noqa: BLE001
            sun_trigger_data = None

        automation = self._build_routine_yaml(
            routine_pairs=routine_pairs,
            trigger_time=trigger_time,
            avg_time_str=avg_time_str,
            stddev_min=stddev,
            days_count=len(core_days),
            weekdays_only=weekdays_only,
            routine_label=routine_label,
            sun_trigger=sun_trigger_data,
        )

        # Confidence — primarily based on how many days exhibited the
        # full routine and how tight the timing is.
        confidence = round(
            min(1.0, len(core_days) / 10.0)
            * max(0.0, 1.0 - stddev / 90.0),
            3,
        )

        title = (
            f"{routine_label} routine detected: {len(routine_pairs)} actions "
            f"{len(core_days)} days at ~{avg_time_str[:5]} (±{int(round(stddev))} min). "
            "Bundle into one automation?"
        )

        fingerprint: dict[str, Any] = {
            "kind": "routine",
            "bucket": bucket,
            "entities_states": sorted(routine_pairs),
        }

        payload = {
            **automation,
            "_routine": {
                "entity_state_pairs": sorted(routine_pairs),
                "days_count": len(core_days),
                "avg_time": avg_time_str,
                "time_stddev_min": round(stddev, 1),
                "label": routine_label,
            },
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

    # -------- helpers --------

    @staticmethod
    def _routine_label(hour: int) -> str:
        """Friendly time-of-day label for the routine title + alias."""
        if 5 <= hour < 10:
            return "Morning"
        if 10 <= hour < 14:
            return "Midday"
        if 14 <= hour < 18:
            return "Afternoon"
        if 18 <= hour < 22:
            return "Evening"
        return "Late-night"

    def _build_routine_yaml(
        self,
        *,
        routine_pairs: list[tuple[str, str]],
        trigger_time: str,
        avg_time_str: str,
        stddev_min: float,
        days_count: int,
        weekdays_only: bool,
        routine_label: str,
        sun_trigger: tuple[str, int] | None = None,
    ) -> dict[str, Any]:
        actions: list[dict[str, Any]] = []
        for entity_id, target_state in routine_pairs:
            domain = entity_id.split(".", 1)[0]
            service = _DOMAIN_SERVICE_MAP[domain][target_state]
            actions.append(
                {
                    "service": service,
                    "target": {"entity_id": entity_id},
                }
            )

        if sun_trigger is not None:
            from .sun_relative import build_sun_trigger, format_sun_offset

            sun_event, sun_offset = sun_trigger
            trigger = [build_sun_trigger(sun_event, sun_offset)]
            alias = (
                f"HA Insights: {routine_label} routine "
                f"@ {sun_event}{format_sun_offset(sun_offset)}"
                + (" (weekdays)" if weekdays_only else "")
            )
            variance_note = (
                f"Predictive: your routine timing tracks {sun_event} more "
                f"tightly than the wall clock. Trigger fires "
                f"{format_sun_offset(sun_offset)} from {sun_event} — "
                "adapts with the seasons. (Clock-time variance was "
                f"±{int(round(stddev_min))} min around {avg_time_str[:5]}.) "
                "Each entity hit ≥80% of routine days — trim what doesn't "
                "belong before applying."
            )
        else:
            trigger = [{"platform": "time", "at": trigger_time}]
            alias = (
                f"HA Insights: {routine_label} routine @ {trigger_time}"
                + (" (weekdays)" if weekdays_only else "")
            )
            variance_note = (
                f"Observed variance was ±{int(round(stddev_min))} min around "
                f"{avg_time_str[:5]}. The trigger is set to {trigger_time}. "
                "Each entity's manual action across the lookback hit ≥80% "
                "of the routine days — feel free to trim entities that "
                "shouldn't be part of the bundle."
            )
        description = (
            f"Auto-suggested by HA Insights: a {routine_label.lower()} "
            f"routine with {len(routine_pairs)} actions you manually "
            f"performed together on {days_count} days "
            + ("(all weekdays) " if weekdays_only else "")
            + f"around {avg_time_str[:5]}.\n\n"
            + variance_note
            + "\n\nEdit / disable / delete freely."
        )
        conditions: list[dict[str, Any]] = []
        if weekdays_only:
            conditions.append(
                {
                    "condition": "time",
                    "weekday": ["mon", "tue", "wed", "thu", "fri"],
                }
            )
        return {
            "alias": alias,
            "description": description,
            "trigger": trigger,
            "condition": conditions,
            "action": actions,
            "mode": "single",
        }

    def _signatures_of_existing_automations(
        self, ctx: DetectorContext
    ) -> set[tuple[str, str, int]]:
        """Reuse ManualHabitDetector's shape — returns set of
        (entity_id, target_state, hour_bucket) tuples present in
        user's existing time-triggered automations."""
        from .manual_habit import ManualHabitDetector

        # Cheap reuse — pull the helper directly.
        helper = ManualHabitDetector()
        return helper._signatures_of_existing_automations(ctx)
