"""StateShiftDetector — surface routine shifts as their own insights.

When a user's life changes (new job, baby, school schedule shift),
the patterns of devices and sensors around them shift too. Without
flagging this, the schedule / streak / frequency detectors see the
post-shift data as polluted noise and emit weaker insights or none
at all. A user staring at the panel can't tell whether HA Insights
just stopped working or whether their pattern has genuinely shifted.

This detector solves the visibility problem: it emits one
PATTERN_OBSERVATION per entity that shows a recent changepoint in
its daily firing pattern. Cohort dedup naturally collapses
simultaneous shifts (10 lights all moving from 06:00 to 07:00 on
the same day → one merged insight, not 10).

Uses `lib/changepoint_detection.py` (v1.8.0). NOT an apply-able
insight — there's nothing to "automate"; the user sees the shift,
either confirms it (the routine is intentional and previous
insights are stale) or investigates (the device may be misbehaving).

**Maturity: BETA** until field-tested. Changepoint sensitivity
varies by entity-type and signal sparsity; thresholds need real-
world tuning before we promote to STABLE.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from ..insight import Insight, InsightKind
from ..lib.changepoint_detection import detect_changepoints
from ..lib.event_filters import is_unavailable_transition
from .base import Detector, DetectorContext, Maturity, register_detector

# Window matched to FrequencyAnomalyDetector for consistency. Older
# shifts are stable enough that re-flagging them adds noise.
_LOOKBACK_DAYS = 14
# Recency filter — only emit shifts that landed at least 2 days ago
# (we need post-shift stability) and within the last _LOOKBACK_DAYS - 4
# days (older shifts users have already noticed).
_MIN_DAYS_BACK = 2
_MAX_DAYS_BACK = 10
# Minimum total events in the lookback window before an entity is
# considered. Very sparse entities can't yield reliable changepoints
# (every shift looks like a single outlier).
_MIN_EVENTS_PER_ENTITY = 20
# Minimum magnitude (absolute mean difference) to emit. Filters out
# trivial wobbles. Tuned for daily-count series.
_MIN_MAGNITUDE = 5.0
# v1.12.7 — Data-window-aware suppression of false positives caused
# by start-of-collection. If the "pre-shift" segment has < this many
# days of history AND < this many events, the apparent "shift" is
# almost certainly "data started here." Set to require at least
# 5 days + 10 events before declaring a behavioural shift legitimate.
_MIN_PRE_SHIFT_DAYS = 5
_MIN_PRE_SHIFT_EVENTS = 10
# Cap to keep the panel usable when many entities shift simultaneously.
# Cohort dedup further reduces this; the cap is the last line.
_MAX_INSIGHTS_PER_SCAN = 10
# Domains where a shift in daily activity is meaningful. Excludes
# bursty-by-nature domains where the changepoint will fire on
# transient bursts and produce noise.
_RELEVANT_DOMAINS: frozenset[str] = frozenset(
    {
        "binary_sensor",
        "sensor",
        "switch",
        "light",
        "fan",
        "cover",
        "input_boolean",
        "input_select",
        "lock",
        "media_player",
        "climate",
    }
)


@register_detector
class StateShiftDetector(Detector):
    """Detect entities whose daily activity recently shifted."""

    name = "state_shift"
    kind = InsightKind.PATTERN_OBSERVATION
    requires_recorder = False
    maturity = Maturity.BETA
    description = (
        "Spots entities whose daily activity recently shifted — new "
        "job, schedule change, device misbehaviour. Surfaces the shift "
        "date and magnitude so you can confirm it's intentional or "
        "investigate before the schedule / streak detectors drift."
    )
    required_data = ("feature:event_buffer",)

    async def scan(self, ctx: DetectorContext) -> list[Insight]:
        if ctx.event_buffer is None:
            return []

        now_local = dt_util.as_local(datetime.now(tz=UTC).replace(microsecond=0))
        today_local_date = now_local.date()
        today_start_local = now_local.replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        today_start_utc = today_start_local.astimezone(UTC)
        baseline_start = today_start_utc - timedelta(days=_LOOKBACK_DAYS)

        events = ctx.event_buffer.query(since=baseline_start)
        if not events:
            return []

        # Per-entity daily-count buckets (excluding today — partial day
        # would skew the analysis).
        daily: dict[str, dict[date, int]] = defaultdict(lambda: defaultdict(int))
        total: dict[str, int] = defaultdict(int)
        for ev in events:
            if is_unavailable_transition(ev.old_state, ev.new_state):
                continue
            if ev.timestamp >= today_start_utc:
                continue  # exclude today
            domain = (
                ev.entity_id.split(".", 1)[0]
                if "." in ev.entity_id
                else ""
            )
            if domain not in _RELEVANT_DOMAINS:
                continue
            if domain in self.domains_default_blocked:
                continue
            local_d = dt_util.as_local(ev.timestamp).date()
            daily[ev.entity_id][local_d] += 1
            total[ev.entity_id] += 1

        # v1.12.7 — Determine the earliest event in the buffer for
        # the data-availability check below. A user-reported false
        # positive was: "Daily-count for light.main_bedroom averaged
        # ~0.0/day before 2026-05-07 and ~48.2/day since." The
        # device had just been added to the install; "before" was
        # the recorder's pre-existence window, not a real behavioral
        # shift. We need to suppress that class of false positive.
        earliest_event_ts: datetime | None = None
        for ev in events:
            if earliest_event_ts is None or ev.timestamp < earliest_event_ts:
                earliest_event_ts = ev.timestamp

        # Build per-entity (timestamps, values) and scan.
        insights: list[Insight] = []
        for entity_id, day_buckets in daily.items():
            if total[entity_id] < _MIN_EVENTS_PER_ENTITY:
                continue
            if entity_id in ctx.blocked_entities:
                continue
            timestamps, values = self._materialize_series(
                day_buckets, today_local_date
            )
            if not timestamps:
                continue
            changepoints = detect_changepoints(timestamps, values)
            if not changepoints:
                continue
            # Take the most recent qualifying changepoint. Older
            # shifts within the window are usually stale.
            recent = [
                cp
                for cp in changepoints
                if _MIN_DAYS_BACK
                <= (today_local_date - cp.detected_at.date()).days
                <= _MAX_DAYS_BACK
                and cp.magnitude >= _MIN_MAGNITUDE
            ]
            if not recent:
                continue
            cp = recent[-1]

            # v1.12.7 — Data-window suppression. If the "pre-shift"
            # segment has fewer than _MIN_PRE_SHIFT_DAYS days of
            # data ending BEFORE the changepoint, this is almost
            # certainly start-of-collection, not a real shift. Skip
            # the insight rather than mislead the user.
            #
            # Two checks (both must pass to suppress):
            #   1. The changepoint is suspiciously close to the
            #      earliest event timestamp (within a few days).
            #   2. The pre-shift period contains < _MIN_PRE_SHIFT_EVENTS
            #      events (legitimate flat-zero periods are rare for
            #      anything that's about to spike).
            if earliest_event_ts is not None:
                days_of_history_before_cp = (
                    cp.detected_at.date()
                    - dt_util.as_local(earliest_event_ts).date()
                ).days
                pre_shift_event_count = sum(
                    count
                    for d, count in day_buckets.items()
                    if d < cp.detected_at.date()
                )
                if (
                    days_of_history_before_cp < _MIN_PRE_SHIFT_DAYS
                    and pre_shift_event_count < _MIN_PRE_SHIFT_EVENTS
                ):
                    # "Shift" is the device's first observable
                    # activity, not a behavior change. Suppress.
                    continue
            insights.append(
                self._build_insight(
                    entity_id=entity_id,
                    cp_date=cp.detected_at.date(),
                    magnitude=cp.magnitude,
                    confidence=cp.confidence,
                    backend=str(cp.backend),
                    day_buckets=day_buckets,
                    today_local_date=today_local_date,
                )
            )
            if len(insights) >= _MAX_INSIGHTS_PER_SCAN:
                break

        return insights

    def _materialize_series(
        self,
        day_buckets: dict[date, int],
        today_local_date: date,
    ) -> tuple[list[datetime], list[float]]:
        """Build a contiguous (timestamps, values) tuple covering the
        full lookback window. Missing days fill as zero."""
        timestamps: list[datetime] = []
        values: list[float] = []
        for offset in range(_LOOKBACK_DAYS, 0, -1):
            d = today_local_date - timedelta(days=offset)
            timestamps.append(datetime(d.year, d.month, d.day, tzinfo=UTC))
            values.append(float(day_buckets.get(d, 0)))
        return timestamps, values

    def _build_insight(
        self,
        *,
        entity_id: str,
        cp_date: date,
        magnitude: float,
        confidence: float,
        backend: str,
        day_buckets: dict[date, int],
        today_local_date: date,
    ) -> Insight:
        """Construct the PATTERN_OBSERVATION insight."""
        # Compute pre- and post-shift means so the title can quote
        # actual numbers, not just "shifted."
        pre_shift = [
            count
            for d, count in day_buckets.items()
            if d < cp_date
        ]
        post_shift = [
            count
            for d, count in day_buckets.items()
            if d >= cp_date
        ]
        pre_mean = sum(pre_shift) / len(pre_shift) if pre_shift else 0.0
        post_mean = sum(post_shift) / len(post_shift) if post_shift else 0.0
        days_ago = (today_local_date - cp_date).days

        title = (
            f"{entity_id} activity shifted ~{days_ago} days ago "
            f"({cp_date.isoformat()}): ~{pre_mean:.1f}/day → "
            f"~{post_mean:.1f}/day."
        )

        fingerprint = {
            "kind": "state_shift",
            "entity_id": entity_id,
            "shift_date": cp_date.isoformat(),
        }

        payload: dict[str, Any] = {
            "type": "history-graph",
            "title": f"State shift: {entity_id}",
            "entities": [entity_id],
            "hours_to_show": 24 * _LOOKBACK_DAYS,
            "_state_shift": {
                "shift_date": cp_date.isoformat(),
                "pre_shift_mean_per_day": round(pre_mean, 2),
                "post_shift_mean_per_day": round(post_mean, 2),
                "magnitude": round(magnitude, 2),
                "days_ago": days_ago,
                "backend": backend,
            },
        }

        # Confidence: blend changepoint's own confidence with the
        # backend (PELT scores higher than fallback) and the days_ago
        # factor (more recent = more interesting).
        backend_factor = 1.0 if "ruptures" in backend else 0.85
        recency_factor = 1.0 - (days_ago - _MIN_DAYS_BACK) / (
            2 * (_MAX_DAYS_BACK - _MIN_DAYS_BACK)
        )
        confidence_final = round(
            max(0.0, min(1.0, confidence * backend_factor * recency_factor)),
            3,
        )

        return Insight(
            id=Insight.compute_id(InsightKind.PATTERN_OBSERVATION, fingerprint),
            kind=InsightKind.PATTERN_OBSERVATION,
            detector=self.name,
            area_id=None,
            title=title,
            confidence=confidence_final,
            fingerprint=fingerprint,
            payload=payload,
            payload_format="card",
            explanation=(
                f"Daily-count for {entity_id} averaged "
                f"~{pre_mean:.1f}/day before {cp_date.isoformat()} "
                f"and ~{post_mean:.1f}/day since. The {magnitude:.1f}-unit "
                f"shift {days_ago} days ago is large enough that schedule "
                f"and frequency detectors will treat the pre-shift data as "
                "noise. If this is intentional (new schedule, device added "
                "to a routine), confirm and dismiss; if not, the device "
                "may be misbehaving."
            ),
            created_at=datetime.now(tz=UTC),
        )
