"""PresenceInferenceDetector — infer where the user is from activity concentration.

Most HA users don't have presence sensors in every room. But state-
change events leak presence anyway: when the user is in the kitchen
cooking, the kitchen lights toggle, the fan turns on, motion sensors
fire. The rest of the house is quiet.

This detector looks for time-of-day windows where activity is
concentrated in a SINGLE area (≥70% of all events). Across 5+ days,
that's a strong signal that the user is "in the kitchen 18:30–20:00"
or "in the bedroom 22:00–07:00".

Output is a `PATTERN_OBSERVATION` insight — not directly apply-able
but the user gains:
  1. Awareness — "huh, I do spend every weekday evening in the kitchen"
  2. Automation primitives — they can build presence-aware automations
     using the inferred windows ("don't dim the bedroom while I'm
     awake in the kitchen")
  3. Foundation for future detectors — RoutineDetector + PresenceInference
     together suggest area-scoped automations

Algorithm:
  1. Walk the buffer, bucket events by (local-day, 30-min window, area_id).
  2. For each (window, area) pair, compute activity share — events in
     this area divided by total events in this window.
  3. Promote (window, area) where share ≥ 0.70 across ≥ 5 days within
     the lookback.
  4. Coalesce adjacent windows into a single time-range insight
     ("kitchen 18:30–20:30" not two separate "18:30–19:00" / "19:00–
     19:30" rows).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.util import dt as dt_util

from ..insight import Insight, InsightKind
from .base import Detector, DetectorContext, register_detector
from .manual_habit import _WEEKDAY_NAMES, _WEEKDAYS_ONLY

if TYPE_CHECKING:
    from ..observers.state_event_buffer import StateEvent


_LOOKBACK_DAYS = 14
# Share of activity that must belong to ONE area for it to count as
# "the user is here". 0.70 = the area has 70%+ of events in this
# window across all areas combined.
_AREA_DOMINANCE_RATIO = 0.70
# Minimum activity in the window to even consider; otherwise we'd
# call sleeping-overnight "presence in bedroom" purely because a
# single sensor fires.
_MIN_EVENTS_PER_WINDOW = 5
# Need this many days where the same area dominates the same window.
_MIN_DAYS_FOR_INSIGHT = 5
# Adjacent windows collapse into one range insight. 30-min buckets =
# 0=00:00 1=00:30 ... 47=23:30.
_BUCKET_MINUTES = 30
_BUCKETS_PER_DAY = 48


@register_detector
class PresenceInferenceDetector(Detector):
    """Infer user presence in specific rooms by activity concentration."""

    name = "presence_inference"
    kind = InsightKind.PATTERN_OBSERVATION
    requires_recorder = False

    async def scan(self, ctx: DetectorContext) -> list[Insight]:
        if ctx.event_buffer is None:
            return []

        cutoff = datetime.now(tz=UTC) - timedelta(days=_LOOKBACK_DAYS)
        # {(day, bucket): {area_id: event_count}}
        windows: dict[tuple[date, int], Counter[str]] = defaultdict(Counter)
        for ev in ctx.event_buffer.query(since=cutoff):
            if not self._is_candidate_event(ev):
                continue
            assert ev.area_id is not None
            local_ts = dt_util.as_local(ev.timestamp)
            bucket = (
                local_ts.hour * 60 + local_ts.minute
            ) // _BUCKET_MINUTES
            windows[(local_ts.date(), bucket)][ev.area_id] += 1

        # Per-bucket: which area dominated on each day?
        # {bucket: {area_id: list of days where it dominated}}
        bucket_dominance: dict[int, dict[str, list[date]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for (day, bucket), counter in windows.items():
            total = sum(counter.values())
            if total < _MIN_EVENTS_PER_WINDOW:
                continue
            top_area, top_count = counter.most_common(1)[0]
            if top_count / total >= _AREA_DOMINANCE_RATIO:
                bucket_dominance[bucket][top_area].append(day)

        # Find (bucket, area) pairs that recur on enough days
        recurring: dict[tuple[int, str], list[date]] = {}
        for bucket, areas in bucket_dominance.items():
            for area_id, days in areas.items():
                if len(days) >= _MIN_DAYS_FOR_INSIGHT:
                    recurring[(bucket, area_id)] = days

        # Coalesce adjacent buckets of the same area into ranges
        ranges = self._coalesce_ranges(recurring)

        # Build insights
        insights: list[Insight] = []
        area_name_by_id = self._area_name_map(ctx)
        for (start_bucket, end_bucket, area_id), days in ranges:
            insight = self._build_insight(
                start_bucket=start_bucket,
                end_bucket=end_bucket,
                area_id=area_id,
                area_name=area_name_by_id.get(area_id, area_id),
                days=days,
            )
            if insight is not None:
                insights.append(insight)
        return insights

    def _is_candidate_event(self, ev: "StateEvent") -> bool:
        # Need an area to attribute activity. Untagged entities are
        # useless for presence inference.
        if ev.area_id is None:
            return False
        if ev.new_state is None or ev.new_state == ev.old_state:
            return False
        # Skip noisy passive domains that fire from polling, not user
        # activity. Climate / sensor would dominate any window simply
        # because they update every minute.
        if ev.domain in {"sensor", "climate", "weather", "sun"}:
            return False
        return True

    def _coalesce_ranges(
        self,
        recurring: dict[tuple[int, str], list[date]],
    ) -> list[tuple[tuple[int, int, str], list[date]]]:
        """Merge adjacent (bucket, area) pairs into ranges.

        Two buckets coalesce when:
          - same area_id
          - bucket numbers are consecutive (mod _BUCKETS_PER_DAY)
          - the day-sets overlap by ≥50% (so 06:00 kitchen and 06:30
            kitchen merge even if a few days only had one or the other)
        """
        if not recurring:
            return []
        # Group by area; sort by bucket within each area
        by_area: dict[str, list[tuple[int, list[date]]]] = defaultdict(list)
        for (bucket, area_id), days in recurring.items():
            by_area[area_id].append((bucket, days))
        out: list[tuple[tuple[int, int, str], list[date]]] = []
        for area_id, items in by_area.items():
            items.sort()
            cur_start, cur_end, cur_days = None, None, []
            for bucket, days in items:
                if cur_start is None:
                    cur_start, cur_end, cur_days = bucket, bucket, list(days)
                    continue
                day_overlap = len(set(cur_days) & set(days))
                day_union = len(set(cur_days) | set(days))
                overlap_ratio = day_overlap / day_union if day_union else 0
                if bucket == cur_end + 1 and overlap_ratio >= 0.5:
                    cur_end = bucket
                    cur_days = sorted(set(cur_days) | set(days))
                else:
                    out.append(((cur_start, cur_end, area_id), cur_days))
                    cur_start, cur_end, cur_days = bucket, bucket, list(days)
            if cur_start is not None:
                out.append(((cur_start, cur_end, area_id), cur_days))
        return out

    def _build_insight(
        self,
        *,
        start_bucket: int,
        end_bucket: int,
        area_id: str,
        area_name: str,
        days: list[date],
    ) -> Insight | None:
        if len(days) < _MIN_DAYS_FOR_INSIGHT:
            return None
        start_min = start_bucket * _BUCKET_MINUTES
        end_min = (end_bucket + 1) * _BUCKET_MINUTES
        start_time = time(hour=start_min // 60, minute=start_min % 60)
        end_hour = (end_min // 60) % 24
        end_time = time(hour=end_hour, minute=end_min % 60)
        time_range = f"{start_time.strftime('%H:%M')}–{end_time.strftime('%H:%M')}"

        observed_weekdays = {_WEEKDAY_NAMES[d.weekday()] for d in days}
        weekdays_only = observed_weekdays <= _WEEKDAYS_ONLY
        weekday_suffix = " (weekdays)" if weekdays_only else ""

        confidence = round(
            min(1.0, len(days) / 10.0)
            * min(1.0, (end_bucket - start_bucket + 1) / 3.0),
            3,
        )

        title = (
            f"You're typically in the {area_name} between {time_range}"
            f"{weekday_suffix} ({len(days)} of last 14 days)."
        )

        fingerprint: dict[str, Any] = {
            "kind": "presence_inference",
            "area_id": area_id,
            "start_bucket": start_bucket,
            "end_bucket": end_bucket,
        }

        payload = {
            "area_id": area_id,
            "area_name": area_name,
            "time_range": time_range,
            "start_time": start_time.strftime("%H:%M"),
            "end_time": end_time.strftime("%H:%M"),
            "days_count": len(days),
            "weekdays_only": weekdays_only,
            "observed_dates": [d.isoformat() for d in days],
            "advice": (
                "Pattern observation — not directly applyable. Useful as "
                "a primitive for presence-aware automations: e.g., "
                f"'don't run noisy automations elsewhere while user is in "
                f"the {area_name}', 'auto-trigger lighting only when "
                f"user's typical-presence window is active'. Future "
                "RoutineDetector enhancements can use this to scope "
                "suggested automations to the right area."
            ),
        }

        return Insight(
            id=Insight.compute_id(InsightKind.PATTERN_OBSERVATION, fingerprint),
            kind=InsightKind.PATTERN_OBSERVATION,
            detector=self.name,
            area_id=area_id,
            title=title,
            confidence=confidence,
            fingerprint=fingerprint,
            payload=payload,
            payload_format="report",
            created_at=datetime.now(tz=UTC),
        )

    def _area_name_map(self, ctx: DetectorContext) -> dict[str, str]:
        """Return {area_id: friendly_name} from the registry. Falls
        back to the id when the registry isn't loaded yet."""
        try:
            from homeassistant.helpers import area_registry as ar

            reg = ar.async_get(ctx.hass)
            return {area.id: area.name for area in reg.async_list_areas()}
        except Exception:  # noqa: BLE001
            return {}
