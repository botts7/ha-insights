"""FrequencyAnomalyDetector — flag entities firing far above their baseline.

Complements OrphanDeviceDetector (which catches "gone silent"). Looks at
each entity's state-change count today and compares it to its rolling
daily mean over the lookback window. If today is >= 3x the baseline AND
the absolute count clears a noise floor, we emit an ANOMALY insight
with a card payload pointing at the entity's history graph.

Picked card payload (not automation) because spike causes are
context-specific — "loose contact in a binary_sensor", "manual
override loop", "child playing with a switch", etc. The user sees the
chart, decides whether to act, and snoozes / dismisses if it was
expected.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from homeassistant.util import dt as dt_util

from ..insight import Insight, InsightKind
from .base import Detector, DetectorContext, register_detector

_LOGGER = logging.getLogger(__name__)

# Domain whitelist mirrors OrphanDeviceDetector — high-cardinality status
# entities (sun/scene/automation) skew the math and aren't useful spikes
# even if they did go nuts.
#
# media_player, device_tracker, person REMOVED from the default set after
# field testing on a 1000-entity install. These domains are inherently
# bursty: a media player fires 10-30 state changes during a single session
# (idle → buffering → playing → paused → buffering → playing → idle …),
# and device_tracker / person fluctuate per movement. Their "anomaly today
# vs flat 14-day average" is dominated by whether the device was used at
# all on a given day, not by genuine stuck-loop / runaway behavior. Result
# pre-fix: 10+ frequency_anomaly insights every day for the user's
# normally-used media players. Post-fix: those domains never reach the
# detector. If the user genuinely wants media_player anomaly tracking,
# that's a future per-domain config flag.
_DEFAULT_DOMAINS: frozenset[str] = frozenset(
    {
        "binary_sensor",
        "sensor",
        "switch",
        "light",
        "fan",
        "cover",
        "input_boolean",
        "input_number",
        "input_select",
    }
)


@register_detector
class FrequencyAnomalyDetector(Detector):
    """Detect entities whose state-change rate today exceeds their baseline."""

    name = "frequency_anomaly"
    kind = InsightKind.ANOMALY
    requires_recorder = False
    # Per-entity runaway detection — merging two anomalies into a
    # "light.* (cohort)" card masks which entity is actually flapping.
    # Each spike is its own root cause to investigate.
    cohort_dedup = False

    LOOKBACK_DAYS = 14
    # An entity needs to have changed state at least this many times today for
    # us to consider it. A 1->5x jump on a sleepy entity is noise; on an
    # entity that already fires 30/day, 100/day is a real story.
    MIN_TODAY_COUNT = 10
    # Also require this many baseline events so we don't flag a brand-new
    # entity that didn't exist last week — its "baseline" is artificially low.
    MIN_BASELINE_EVENTS = 14
    # Today/baseline ratio threshold. 3x daily mean was well above sampling
    # noise BUT included normal "user used the device today" bursts on a
    # 1000-entity install — 49 false-positive insights for things like
    # "porch lights fired 15× today vs 2/day baseline." Bumped to 8× —
    # genuine stuck loops or runaway sensors are 10-30×, normal usage
    # rarely exceeds 7×. User feedback: the previous threshold made
    # this detector unusable as a panel signal.
    RATIO_THRESHOLD = 8.0
    # Cap to keep panel render fast even when many entities legitimately
    # spike. Sorted by ratio descending so the most extreme stick out.
    MAX_INSIGHTS_PER_SCAN = 15

    async def scan(self, ctx: DetectorContext) -> list[Insight]:
        if ctx.event_buffer is None:
            return []

        # Bucket by HA-local midnight, not UTC midnight — otherwise on the
        # west coast a 4 PM event lands "tomorrow" and a 9 PM event lands
        # "today" depending on which side of UTC midnight we are. v1.0
        # review #2 caught this: the today vs baseline split was wrong
        # for half the world.
        now_local = dt_util.as_local(datetime.now(tz=UTC).replace(microsecond=0))
        today_start_local = now_local.replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        # Compare against ev.timestamp by converting both to UTC.
        today_start_utc = today_start_local.astimezone(UTC)
        baseline_start = today_start_utc - timedelta(days=self.LOOKBACK_DAYS - 1)

        events = ctx.event_buffer.query(since=baseline_start)
        if not events:
            return []

        today_counts: dict[str, int] = defaultdict(int)
        baseline_counts: dict[str, int] = defaultdict(int)
        for ev in events:
            # v1.5: skip `unavailable` ↔ X transitions. HA fires
            # state_changed on every availability flip; a flaky
            # WiFi device hits 30+ events/hr without doing
            # anything. Counting those as state changes inflates
            # both today_counts and baseline_counts symmetrically
            # in steady-state, but a SUDDEN flap day (broken AP
            # this morning) shows as a runaway-automation false
            # positive. See docs/HA_EVENT_SEMANTICS.md Gotcha 6.
            if ev.old_state == "unavailable" or ev.new_state == "unavailable":
                continue
            if ev.timestamp >= today_start_utc:
                today_counts[ev.entity_id] += 1
            else:
                baseline_counts[ev.entity_id] += 1

        baseline_days = self.LOOKBACK_DAYS - 1
        # First pass: collect candidates per (device_id, entity) so we can
        # deduplicate same-device bursts. When you DRIVE the car today,
        # ~10 entities on it (windows, doors, locked, sentry_mode, etc.)
        # all fire 10-30x more than baseline. That's "you used the car
        # today", not 10 stuck loops. Group by device_id and keep only
        # the entity with the highest ratio per device.
        candidates: list[tuple[float, str, int, float]] = []  # (ratio, eid, today, baseline)
        for entity_id, today_count in today_counts.items():
            domain = entity_id.split(".", 1)[0] if "." in entity_id else ""
            if domain not in _DEFAULT_DOMAINS:
                continue
            if domain in self.domains_default_blocked:
                continue
            if today_count < self.MIN_TODAY_COUNT:
                continue
            baseline_count = baseline_counts.get(entity_id, 0)
            if baseline_count < self.MIN_BASELINE_EVENTS:
                continue
            baseline_per_day = baseline_count / baseline_days
            if baseline_per_day <= 0:
                continue
            ratio = today_count / baseline_per_day
            if ratio < self.RATIO_THRESHOLD:
                continue
            candidates.append((ratio, entity_id, today_count, baseline_per_day))

        # v1.4: group fan-out filter. When a group entity (e.g.
        # `light.living_room` containing `light.lamp_a` + `light.lamp_b`)
        # fires N times, every member ALSO fires N times — but it's
        # the SAME physical event, not N independent runaway automations.
        # Without this filter, a single high-frequency group toggle
        # creates one spurious card per member.
        #
        # Algorithm: build a set of candidate entity_ids. For each
        # candidate, check whether ANY of its parent containers is
        # also a candidate. If so, the member's events are likely
        # fan-out — drop it and keep only the parent.
        if ctx.container_to_members:
            candidate_eids = {c[1] for c in candidates}
            # Reverse the container_to_members map: entity → parents
            parent_of: dict[str, set[str]] = defaultdict(set)
            for parent_eid, members in ctx.container_to_members.items():
                for member in members:
                    parent_of[member].add(parent_eid)
            filtered: list[tuple[float, str, int, float]] = []
            dropped_for_fanout = 0
            for cand in candidates:
                _ratio, eid, _today, _baseline = cand
                parents = parent_of.get(eid, set())
                # Drop if ANY parent container is also flagged — that
                # parent gets the user's attention; the member is
                # noise. Keep the entity if its parents aren't in
                # the candidate set (genuine independent spike).
                if parents & candidate_eids:
                    dropped_for_fanout += 1
                    continue
                filtered.append(cand)
            if dropped_for_fanout:
                _LOGGER.debug(
                    "frequency_anomaly: filtered %d candidates that "
                    "are group members of other candidates (fan-out)",
                    dropped_for_fanout,
                )
            candidates = filtered

        # Same-device dedup: per device, keep only the highest-ratio entity.
        # Entities without a device_id (template sensors, helpers) keep all.
        # Uses ctx.hierarchy when available (v1.2 refactor), falls back
        # to the legacy map otherwise.
        def _device_of(eid: str) -> str | None:
            if ctx.hierarchy is not None:
                return ctx.hierarchy.device_of.get(eid)
            return ctx.device_id_by_entity.get(eid)

        per_device_best: dict[str, tuple[float, str, int, float]] = {}
        no_device: list[tuple[float, str, int, float]] = []
        for cand in candidates:
            ratio, eid, _today, _baseline = cand
            device_id = _device_of(eid)
            if device_id is None:
                no_device.append(cand)
                continue
            existing = per_device_best.get(device_id)
            if existing is None or cand[0] > existing[0]:
                per_device_best[device_id] = cand

        # Sort by ratio descending then cap to MAX_INSIGHTS_PER_SCAN —
        # the most extreme anomalies are the most likely to be real
        # stuck loops, the least extreme are most likely to be normal
        # use bursts.
        all_candidates = list(per_device_best.values()) + no_device
        all_candidates.sort(key=lambda c: c[0], reverse=True)
        all_candidates = all_candidates[: self.MAX_INSIGHTS_PER_SCAN]

        insights: list[Insight] = []
        for ratio, entity_id, today_count, baseline_per_day in all_candidates:
            insights.append(
                self._build_insight(
                    entity_id=entity_id,
                    today_count=today_count,
                    baseline_per_day=baseline_per_day,
                    ratio=ratio,
                    today_date=today_start_local.date().isoformat(),
                )
            )
        return insights

    def _build_insight(
        self,
        *,
        entity_id: str,
        today_count: int,
        baseline_per_day: float,
        ratio: float,
        today_date: str,
    ) -> Insight:
        # Confidence ramps from 0.6 at 3x to 1.0 at 10x and beyond. Anything
        # below 3x has already been filtered out above; we just clamp.
        confidence = round(
            max(0.6, min(1.0, 0.6 + (ratio - 3.0) / 17.5)),
            3,
        )

        title = (
            f"{entity_id} fired {today_count} times today "
            f"(~{baseline_per_day:.1f}/day baseline, {ratio:.1f}x). "
            "Stuck loop, manual override, or genuine event burst?"
        )

        fingerprint = {
            "entity_id": entity_id,
            "kind": "frequency_anomaly",
            # Date-stamped so re-scans within the same day dedupe; tomorrow's
            # spike (if it persists) lands as a fresh insight.
            "today_date": today_date,
        }

        # Card payload: a 48h history graph centered on the spike. Anomalies
        # rarely have a one-shot apply-able fix — the user reads the chart
        # and decides.
        payload = {
            "type": "history-graph",
            "title": f"Activity spike: {entity_id}",
            "entities": [entity_id],
            "hours_to_show": 48,
        }

        return Insight(
            id=Insight.compute_id(InsightKind.ANOMALY, fingerprint),
            kind=InsightKind.ANOMALY,
            detector=self.name,
            area_id=None,
            title=title,
            confidence=confidence,
            fingerprint=fingerprint,
            payload=payload,
            payload_format="card",
            created_at=datetime.now(tz=UTC),
        )
