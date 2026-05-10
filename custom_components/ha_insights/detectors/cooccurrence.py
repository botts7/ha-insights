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
    # Pairs closer than this don't count. Two state changes <0.5s apart
    # are virtually always two views of the same physical event (relay
    # channels firing together, multi-endpoint Zigbee, sensor packs)
    # rather than user-decided causation. Real cause→effect on the HA
    # event bus has at minimum a few hundred ms of latency. Subclasses
    # (LaggedCorrelationDetector) raise this further to carve out their
    # "delayed reaction" niche without double-firing on cooccurrence.
    MIN_DELTA_SECONDS = 0.5
    # Raised from 5 → 15 after the user reported 3000+ noisy cooccurrence
    # insights on a 1000-entity install. Five co-occurrences in 14 days is
    # genuinely just coincidence on a busy install; 15 is "this is probably
    # a real pattern." Tunable via subclass override.
    MIN_OCCURRENCES = 15
    # Tightened from 12s → 6s. Co-occurrences whose timing is loose are
    # almost always coincidence, not causal. Requiring tight timing
    # consistency (stddev under 6s) culls the long tail of spurious pairs.
    DELTA_STDDEV_MAX_SECONDS = 6.0
    MAX_LOOKBACK_EVENTS = 200  # cap pair search per follower for perf
    # Floor for emitted insight confidence — anything below this is
    # dropped at scan time. Stops insights with `confidence=0.32` from
    # spamming the panel; users sort by confidence anyway.
    MIN_CONFIDENCE_TO_EMIT = 0.55
    # Hard cap on insights emitted per scan, sorted by confidence
    # descending. Prevents a 3000-pair explosion on installs with high
    # entity churn. Users can raise via subclass if they really want
    # the long tail.
    MAX_INSIGHTS_PER_SCAN = 50
    # Maximum unique followers per leader before treating the whole
    # leader as a "cascade event" (HA restart, scene activation,
    # integration reload). One leader → 40 followers is system noise,
    # not user-decided causation. Real automations target 1-3 entities;
    # a "leave home" scene targets ~5-8. 10 is a safe upper bound that
    # admits multi-target scenes without admitting full restart waves.
    MAX_FANOUT_PER_LEADER = 10

    async def scan(self, ctx: DetectorContext) -> list[Insight]:
        if ctx.event_buffer is None:
            return []

        cutoff = datetime.now(tz=UTC) - timedelta(days=self.LOOKBACK_DAYS)
        events = sorted(ctx.event_buffer.query(since=cutoff), key=lambda e: e.timestamp)
        if len(events) < self.MIN_OCCURRENCES * 2:
            return []

        # Pre-filter: an entity that fires fewer than MIN_OCCURRENCES times
        # over the whole lookback window can't possibly be the leader OR
        # follower of a confirmed pattern (the threshold requires that many
        # co-occurrences). Computing the per-entity histogram once and
        # skipping non-busy entities at iteration time is the cheap fix
        # that makes real-world installs (with skewed entity activity)
        # finish in single-digit seconds. On installs where every entity
        # is busy (synthetic stress tests), this filter is a no-op — that
        # case is handled by the buffer-size auto-skip threshold instead.
        entity_change_counts: dict[str, int] = defaultdict(int)
        for ev in events:
            if ev.new_state is None or ev.new_state == ev.old_state:
                continue
            entity_change_counts[ev.entity_id] += 1
        busy_entities = frozenset(
            eid
            for eid, count in entity_change_counts.items()
            if count >= self.MIN_OCCURRENCES
        )

        pairs: dict[
            tuple[str, str, str, str], list[float]
        ] = defaultdict(list)  # (leader_eid, leader_state, follower_eid, follower_state) -> deltas

        # Same-device pair filter — pulls (entity_id -> device_id) from
        # ctx (populated once at scan start). Pairs whose entities share
        # a device_id are virtually always two views of the same physical
        # hardware event (relay board with input + relay channel,
        # multi-endpoint Zigbee, sensor pack reporting all readings
        # together). Filter at pair-discovery time so they never even
        # reach the dedup dict.
        device_id_by_entity = ctx.device_id_by_entity
        # Entity dependency map (groups, derived sensors, aggregates) —
        # see docstring on DetectorContext.entity_dependencies. Pairs
        # connected by any dependency edge are dropped: they aren't
        # "responding to" each other, they're reflecting the same
        # underlying event.
        entity_dependencies = ctx.entity_dependencies

        for i, follower in enumerate(events):
            if follower.entity_id not in busy_entities:
                continue
            if not self._is_candidate(follower):
                continue
            window_start = follower.timestamp - timedelta(seconds=self.WINDOW_SECONDS)
            follower_device = device_id_by_entity.get(follower.entity_id)
            for j in range(i - 1, max(-1, i - self.MAX_LOOKBACK_EVENTS), -1):
                leader = events[j]
                if leader.timestamp < window_start:
                    break
                if leader.entity_id == follower.entity_id:
                    continue
                if leader.entity_id not in busy_entities:
                    continue
                if not self._is_candidate(leader):
                    continue
                # Same-device skip: applies only when both entities have
                # a non-None device_id AND they match. Two unrelated
                # devices both with `device_id=None` would still pair.
                leader_device = device_id_by_entity.get(leader.entity_id)
                if (
                    leader_device is not None
                    and follower_device is not None
                    and leader_device == follower_device
                ):
                    continue
                # Dependency-graph skip: parent group fires its members,
                # member fires sibling members, derived sensor reflects
                # source. None of these are useful "B follows A" patterns.
                if (
                    follower.entity_id
                    in entity_dependencies.get(leader.entity_id, frozenset())
                ):
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

        # Precompute leader fire counts ONCE in O(N) so _evaluate_pair can
        # do O(1) lookups instead of re-scanning the full buffer per pair.
        # Was the dominant cost at scale: with ~1000 candidate pairs and a
        # 340K-event buffer, the old per-pair scan was 340M+ comparisons,
        # which blew past the 30s detector watchdog. Now it's a single
        # 340K-pass + per-pair dict.get(), well within budget.
        leader_counts: dict[tuple[str, str], int] = defaultdict(int)
        for ev in events:
            if not self._is_candidate(ev):
                continue
            leader_counts[(ev.entity_id, str(ev.new_state))] += 1

        insights: list[Insight] = []
        for key, deltas in pairs.items():
            if len(deltas) < self.MIN_OCCURRENCES:
                continue
            insight = self._evaluate_pair(key, deltas, events, leader_counts)
            if insight is None:
                continue
            if insight.confidence < self.MIN_CONFIDENCE_TO_EMIT:
                continue
            insights.append(insight)
        # Cascade-event filter: when a single leader fans out to many
        # distinct followers in the same window, that's a system event
        # (HA restart, scene activation, integration reload) — not a
        # causal pattern. A real automation rarely targets 10+ unrelated
        # entities; a "everything goes off" macro is one user action,
        # not 40 independent suggestions to make. Drop all pairs whose
        # leader exceeds the fan-out threshold.
        leader_followers: dict[tuple[str, str], set[tuple[str, str]]] = (
            defaultdict(set)
        )
        for (l_eid, l_state, f_eid, f_state), _ in pairs.items():
            leader_followers[(l_eid, l_state)].add((f_eid, f_state))
        cascade_leaders = {
            ls
            for ls, fs in leader_followers.items()
            if len(fs) > self.MAX_FANOUT_PER_LEADER
        }
        if cascade_leaders:
            import logging as _logging
            _logging.getLogger(__name__).info(
                "Cooccurrence: dropping %d cascade leaders with >%d followers "
                "(likely HA restart / scene / system event, not causation)",
                len(cascade_leaders),
                self.MAX_FANOUT_PER_LEADER,
            )

        # Cap by confidence — keep top N, drop the rest. Users sort by
        # confidence anyway; the 51st-most-confident insight is rarely
        # worth the panel real estate.
        insights = [
            i
            for i in insights
            if (i.fingerprint["leader_entity_id"], i.fingerprint["leader_state"])
            not in cascade_leaders
        ]
        insights.sort(key=lambda i: i.confidence, reverse=True)
        return insights[: self.MAX_INSIGHTS_PER_SCAN]

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
        leader_counts: dict[tuple[str, str], int] | None = None,
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
        # follower follows >=70% of the time, surface as a routine. Prefer
        # the precomputed `leader_counts` dict (O(1) lookup) over a full
        # buffer scan; the fallback exists so unit tests can call
        # _evaluate_pair directly without setting up the full pipeline.
        if leader_counts is not None:
            leader_total = leader_counts.get((leader_eid, leader_state), 0)
        else:
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
