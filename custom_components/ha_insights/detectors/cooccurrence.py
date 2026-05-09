"""CooccurrenceDetector — find "entity B follows entity A within N seconds" patterns.

Common case: porch light comes on shortly after front door opens. The detector
walks the rolling state buffer, pairs each state change with prior state changes
within a configurable window, and surfaces pairs that occur frequently and
consistently as AUTOMATION_PROPOSAL insights.

The emitted automation uses HA's `state` trigger on the leader and a service
call on the follower. Users review and apply via the standard insight flow.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from ..insight import Insight, InsightKind
from .base import Detector, DetectorContext, register_detector

if TYPE_CHECKING:
    from ..observers.state_event_buffer import StateEvent


@register_detector
class CooccurrenceDetector(Detector):
    """Detect "B follows A within N seconds" co-occurrence patterns."""

    name = "cooccurrence"
    kind = InsightKind.AUTOMATION_PROPOSAL
    requires_recorder = False

    LOOKBACK_DAYS = 14
    WINDOW_SECONDS = 30
    # Pairs closer than this don't count. Subclasses (LaggedCorrelationDetector)
    # raise this to carve out their own "delayed reaction" niche without
    # double-firing on what cooccurrence already catches.
    MIN_DELTA_SECONDS = 0.0
    MIN_OCCURRENCES = 5
    DELTA_STDDEV_MAX_SECONDS = 12.0
    MAX_LOOKBACK_EVENTS = 200  # cap pair search per follower for perf

    async def scan(self, ctx: DetectorContext) -> list[Insight]:
        if ctx.event_buffer is None:
            return []

        cutoff = datetime.now(tz=UTC) - timedelta(days=self.LOOKBACK_DAYS)
        events = sorted(ctx.event_buffer.query(since=cutoff), key=lambda e: e.timestamp)
        if len(events) < self.MIN_OCCURRENCES * 2:
            return []

        pairs: dict[
            tuple[str, str, str, str], list[float]
        ] = defaultdict(list)  # (leader_eid, leader_state, follower_eid, follower_state) -> deltas

        for i, follower in enumerate(events):
            if not self._is_candidate(follower):
                continue
            window_start = follower.timestamp - timedelta(seconds=self.WINDOW_SECONDS)
            for j in range(i - 1, max(-1, i - self.MAX_LOOKBACK_EVENTS), -1):
                leader = events[j]
                if leader.timestamp < window_start:
                    break
                if leader.entity_id == follower.entity_id:
                    continue
                if not self._is_candidate(leader):
                    continue
                delta = (follower.timestamp - leader.timestamp).total_seconds()
                if delta <= 0:
                    continue
                if delta < self.MIN_DELTA_SECONDS:
                    continue
                key = (
                    leader.entity_id,
                    str(leader.new_state),
                    follower.entity_id,
                    str(follower.new_state),
                )
                pairs[key].append(delta)

        insights: list[Insight] = []
        for key, deltas in pairs.items():
            if len(deltas) < self.MIN_OCCURRENCES:
                continue
            insight = self._evaluate_pair(key, deltas, events)
            if insight is not None:
                insights.append(insight)
        return insights

    def _is_candidate(self, ev: StateEvent) -> bool:
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

    def _evaluate_pair(
        self,
        key: tuple[str, str, str, str],
        deltas: list[float],
        events: list[StateEvent],
    ) -> Insight | None:
        leader_eid, leader_state, follower_eid, follower_state = key

        # Timing consistency: require std-dev under threshold so we filter
        # accidental co-occurrence that's actually noise.
        avg_delta = sum(deltas) / len(deltas)
        variance = sum((d - avg_delta) ** 2 for d in deltas) / len(deltas)
        stddev = math.sqrt(variance)
        if stddev > self.DELTA_STDDEV_MAX_SECONDS:
            return None

        # How often does the leader fire WITHOUT a matching follower? If the
        # follower follows >=70% of the time, surface as a routine.
        leader_total = sum(
            1
            for ev in events
            if ev.entity_id == leader_eid and str(ev.new_state) == leader_state
        )
        if leader_total == 0:
            return None
        consistency = min(1.0, len(deltas) / leader_total)
        if consistency < 0.6:
            return None

        confidence = (
            min(1.0, len(deltas) / 10.0)
            * consistency
            * max(0.0, 1.0 - stddev / 20.0)
        )

        avg_delta_int = round(avg_delta)
        title = (
            f"When {leader_eid} -> {leader_state}, "
            f"{follower_eid} usually -> {follower_state} "
            f"~{avg_delta_int}s later "
            f"({len(deltas)} of {leader_total} times)"
        )

        fingerprint = {
            "leader_entity_id": leader_eid,
            "leader_state": leader_state,
            "follower_entity_id": follower_eid,
            "follower_state": follower_state,
        }

        # Build automation: state trigger on leader + service call on follower
        follower_domain = (
            follower_eid.split(".", 1)[0] if "." in follower_eid else "homeassistant"
        )
        service = self._domain_to_service(follower_domain, follower_state)

        alias = (
            f"HA Insights: when {leader_eid} {leader_state}, "
            f"{follower_eid} {follower_state}"
        )
        description = (
            f"Auto-detected co-occurrence: {follower_eid} follows "
            f"{leader_eid} by ~{avg_delta_int}s"
        )
        payload = {
            "alias": alias,
            "description": description,
            "trigger": [
                {
                    "platform": "state",
                    "entity_id": leader_eid,
                    "to": leader_state,
                }
            ],
            "action": [
                {"service": service, "target": {"entity_id": follower_eid}}
            ],
            "mode": "single",
        }

        return Insight(
            id=Insight.compute_id(InsightKind.AUTOMATION_PROPOSAL, fingerprint),
            kind=InsightKind.AUTOMATION_PROPOSAL,
            detector=self.name,
            area_id=None,
            title=title,
            confidence=round(confidence, 3),
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
