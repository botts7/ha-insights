"""LongTailDetector — find entities that stay `on` for too long.

Common case: porch light still on at 4am, fan running 6 hours into the
night, switch left on overnight. The detector walks the rolling state
buffer, finds spans where an entity was in an `on`-like state for
longer than the per-domain threshold, and surfaces a recurring pattern
as an AUTOMATION_PROPOSAL with an auto-off trigger.

Per-domain thresholds reflect realistic "is this unusual" expectations:
a light on for an hour might be intentional, on for three is probably
forgotten. Climate / cover / media_player are excluded because they're
usually expected to stay on.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from ..insight import Insight, InsightKind
from .base import Detector, DetectorContext, register_detector

if TYPE_CHECKING:
    from ..observers.state_event_buffer import StateEvent


# Per-domain "this is too long" thresholds in minutes.
# Domains absent from this map are not analyzed at all.
DEFAULT_DURATION_THRESHOLDS: dict[str, int] = {
    "light": 90,
    "switch": 120,
    "fan": 120,
    "media_player": 240,
    "input_boolean": 120,
}

# Treat these states as "active" / "on-like" for span calculation.
_ACTIVE_STATES: frozenset[str] = frozenset(
    {"on", "playing", "open", "unlocked", "active", "home"}
)


@register_detector
class LongTailDetector(Detector):
    """Detect entities that stay in an active state longer than expected."""

    name = "long_tail"
    kind = InsightKind.AUTOMATION_PROPOSAL
    requires_recorder = False

    LOOKBACK_DAYS = 14
    MIN_OCCURRENCES = 3
    # Cap span duration so a permanently-on entity doesn't produce a
    # one-shot multi-day "insight" before any state change at all.
    MAX_REASONABLE_HOURS = 48
    # Floor for emitted insight confidence — anything below is dropped.
    MIN_CONFIDENCE_TO_EMIT = 0.5
    # Hard cap per scan to keep the panel usable on large installs.
    # Sorted by confidence desc; the user's worst-offender entities
    # show first. Was producing 500+ "left on too long" insights on a
    # 1000-entity install before this cap.
    MAX_INSIGHTS_PER_SCAN = 30

    async def scan(self, ctx: DetectorContext) -> list[Insight]:
        if ctx.event_buffer is None:
            return []

        cutoff = datetime.now(tz=UTC) - timedelta(days=self.LOOKBACK_DAYS)
        events = sorted(ctx.event_buffer.query(since=cutoff), key=lambda e: e.timestamp)
        if not events:
            return []

        # Group events by entity_id so we can compute per-entity spans.
        per_entity: dict[str, list[StateEvent]] = defaultdict(list)
        for ev in events:
            per_entity[ev.entity_id].append(ev)

        insights: list[Insight] = []
        for entity_id, entity_events in per_entity.items():
            domain = (
                entity_id.split(".", 1)[0] if "." in entity_id else ""
            )
            if domain in self.domains_default_blocked:
                continue
            threshold_min = DEFAULT_DURATION_THRESHOLDS.get(domain)
            if threshold_min is None:
                continue
            spans = self._compute_active_spans(entity_events)
            long_spans = [
                seconds
                for seconds in spans
                if seconds >= threshold_min * 60
                and seconds <= self.MAX_REASONABLE_HOURS * 3600
            ]
            if len(long_spans) < self.MIN_OCCURRENCES:
                continue
            insight = self._build_insight(
                entity_id, domain, long_spans, threshold_min
            )
            if insight is None:
                continue
            if insight.confidence < self.MIN_CONFIDENCE_TO_EMIT:
                continue
            insights.append(insight)
        insights.sort(key=lambda i: i.confidence, reverse=True)
        return insights[: self.MAX_INSIGHTS_PER_SCAN]

    def _compute_active_spans(self, events: list[StateEvent]) -> list[float]:
        """Walk an entity's chronological event list, return active-span lengths.

        A span starts when the entity enters an active state and ends
        when it leaves (or when the buffer ends). Open spans at the end
        of the buffer are NOT included (they may be ongoing and we don't
        want to fire on currently-running cases).
        """
        spans: list[float] = []
        active_since: datetime | None = None
        for ev in events:
            new_state = (ev.new_state or "").lower()
            is_active = new_state in _ACTIVE_STATES
            if is_active and active_since is None:
                active_since = ev.timestamp
            elif not is_active and active_since is not None:
                spans.append((ev.timestamp - active_since).total_seconds())
                active_since = None
        return spans

    def _build_insight(
        self,
        entity_id: str,
        domain: str,
        long_spans: list[float],
        threshold_min: int,
    ) -> Insight | None:
        avg_minutes = round(sum(long_spans) / len(long_spans) / 60)
        max_minutes = round(max(long_spans) / 60)
        confidence = round(min(1.0, len(long_spans) / 10.0), 3)

        title = (
            f"{entity_id} stays active for ~{avg_minutes} min "
            f"({len(long_spans)} times in 14d, max {max_minutes} min). "
            f"Auto-off after {threshold_min} min?"
        )

        fingerprint = {
            "entity_id": entity_id,
            "kind": "long_tail",
            "threshold_min": threshold_min,
        }

        # Compose an auto-off automation: trigger when the entity has
        # been active for `threshold_min` minutes; action is the matching
        # turn_off service for the domain.
        service = "turn_off"
        if domain == "media_player":
            service = "turn_off"
        payload = {
            "alias": f"HA Insights: auto-off {entity_id} after {threshold_min}min",
            "description": (
                f"Auto-detected: {entity_id} stays active for ~{avg_minutes} "
                f"minutes on average; turning off after {threshold_min} "
                "minutes prevents the long tail."
            ),
            "trigger": [
                {
                    "platform": "state",
                    "entity_id": entity_id,
                    "to": "on",
                    "for": {"minutes": threshold_min},
                }
            ],
            "action": [
                {
                    "service": f"{domain}.{service}",
                    "target": {"entity_id": entity_id},
                }
            ],
            "mode": "single",
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
