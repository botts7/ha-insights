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

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from ..insight import Insight, InsightKind
from .base import Detector, DetectorContext, register_detector

# Domain whitelist mirrors OrphanDeviceDetector — high-cardinality status
# entities (sun/scene/automation) skew the math and aren't useful spikes
# even if they did go nuts.
_DEFAULT_DOMAINS: frozenset[str] = frozenset(
    {
        "binary_sensor",
        "sensor",
        "switch",
        "light",
        "fan",
        "cover",
        "media_player",
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

    LOOKBACK_DAYS = 14
    # An entity needs to have changed state at least this many times today for
    # us to consider it. A 1->5x jump on a sleepy entity is noise; on an
    # entity that already fires 30/day, 100/day is a real story.
    MIN_TODAY_COUNT = 10
    # Also require this many baseline events so we don't flag a brand-new
    # entity that didn't exist last week — its "baseline" is artificially low.
    MIN_BASELINE_EVENTS = 14
    # Today/baseline ratio threshold. 3x daily mean is well above sampling
    # noise for entities clearing the absolute floors above.
    RATIO_THRESHOLD = 3.0

    async def scan(self, ctx: DetectorContext) -> list[Insight]:
        if ctx.event_buffer is None:
            return []

        now = datetime.now(tz=UTC).replace(microsecond=0)
        # We bucket by midnight UTC. Baseline is the prior 13 days of the
        # 14-day window so today's bump is excluded from its own baseline.
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        baseline_start = today_start - timedelta(days=self.LOOKBACK_DAYS - 1)

        events = ctx.event_buffer.query(since=baseline_start)
        if not events:
            return []

        today_counts: dict[str, int] = defaultdict(int)
        baseline_counts: dict[str, int] = defaultdict(int)
        for ev in events:
            if ev.timestamp >= today_start:
                today_counts[ev.entity_id] += 1
            else:
                baseline_counts[ev.entity_id] += 1

        baseline_days = self.LOOKBACK_DAYS - 1
        insights: list[Insight] = []
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
            insights.append(
                self._build_insight(
                    entity_id=entity_id,
                    today_count=today_count,
                    baseline_per_day=baseline_per_day,
                    ratio=ratio,
                    today_date=today_start.date().isoformat(),
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
