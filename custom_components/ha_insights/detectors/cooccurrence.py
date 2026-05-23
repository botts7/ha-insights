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
from ..lib.coupling_strength import (
    apply_tier_demotion,
    compute_coupling,
    coupling_payload,
)
from ..lib.event_filters import (
    is_after_long_silence,
    is_from_unavailable_state,
    pattern_value,
)
from .base import Detector, DetectorContext, Maturity, register_detector

if TYPE_CHECKING:
    from ..observers.state_event_buffer import StateEvent


@register_detector
class CooccurrenceDetector(Detector):
    """Detect "B follows A within N seconds" co-occurrence patterns."""

    name = "cooccurrence"
    kind = InsightKind.AUTOMATION_PROPOSAL
    requires_recorder = False
    # v1.5: BETA until field-tested. The detector has strong
    # filtering (hierarchy.are_related catches structural pairs,
    # context.id batch filter catches group/scene/script
    # fan-out), but real-world installs have edge cases (one-off
    # scripts, complex automations) we haven't validated against.
    # LaggedCorrelation inherits this status. Promote when
    # community feedback confirms no surprise modes.
    maturity = Maturity.BETA

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
        # v1.5.25: drop post-long-silence events (poll wake-ups) up
        # front. Cooccurrence is especially vulnerable — when a sleepy
        # device wakes up, ALL its entities fire ~simultaneously, which
        # manufactures "B follows A within 1s" pairs across every
        # sibling. The long-silence filter catches this without the
        # entity having to literally report `unavailable`.
        #
        # v1.12.13: ALSO drop events with context.parent_id set —
        # those are downstream cascades from another HA event
        # (automation action, script execution, scene activation).
        # The v1.5.20 structural filter (_pair_is_related) catches
        # scene/script/group members; v1.5.16 context.id batch
        # correlator catches multi-target fan-outs. But a USER-created
        # automation like "when front_door opens, turn on lounge_light"
        # has no structural relationship — the follower light's
        # state_changed has parent_id set, the leader's doesn't, and
        # without this filter we'd surface a self-reinforcing
        # "automate this!" proposal for a pattern the user already
        # automated. parent_id=None preserves: user-driven manual
        # actions (user_id set, parent_id None), sensor-originated
        # device events (both None), and root-cause leaders. parent_id
        # set means "this is a CONSEQUENCE of another HA event" —
        # never a candidate for "user habit to automate."
        if events:
            filtered: list[StateEvent] = []
            last_seen_at: dict[str, datetime] = {}
            for ev in events:
                prior_ts = last_seen_at.get(ev.entity_id)
                last_seen_at[ev.entity_id] = ev.timestamp
                if (
                    ev.domain != "event"
                    and is_after_long_silence(ev.timestamp, prior_ts)
                ):
                    continue
                if ev.context_parent_id is not None:
                    continue
                filtered.append(ev)
            events = filtered
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

        # Pair-relatedness check via the central hierarchy. Replaces the
        # previous combo of (device_id_by_entity + entity_dependencies)
        # with a single query method that already knows about
        # device-sharing, group membership, source/derived sensors, and
        # small-group siblings. Falls back to the legacy maps when no
        # hierarchy is in the context (only happens during the migration
        # window if a non-standard caller built ctx by hand).
        hierarchy = ctx.hierarchy
        legacy_device_map = ctx.device_id_by_entity
        legacy_dep_map = ctx.entity_dependencies

        def _pair_is_related(eid_a: str, eid_b: str) -> bool:
            if hierarchy is not None:
                return hierarchy.are_related(eid_a, eid_b)
            # Legacy path
            da = legacy_device_map.get(eid_a)
            db = legacy_device_map.get(eid_b)
            if da is not None and da == db:
                return True
            if eid_b in legacy_dep_map.get(eid_a, frozenset()):
                return True
            return False

        for i, follower in enumerate(events):
            if follower.entity_id not in busy_entities:
                continue
            if not self._is_candidate(follower):
                continue
            window_start = follower.timestamp - timedelta(seconds=self.WINDOW_SECONDS)
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
                # Single relatedness check covers same-device, group
                # parent/child, sibling-in-small-group, source/derived,
                # AND script co-targeting — everything we filter out as
                # "same root event, not real causation."
                if _pair_is_related(leader.entity_id, follower.entity_id):
                    continue
                # v1.5: context.id batch filter. If leader + follower
                # share a non-null context.id, they're co-effects of
                # one logical operation (group toggle / scene / script
                # — see docs/HA_EVENT_SEMANTICS.md Gotchas 1-3). The
                # "follow within seconds" pattern is structural, not
                # behavioural. Filter complements the structural
                # _pair_is_related check above — that catches static
                # parent/child relationships; this catches dynamic
                # batch operations whose targets might not share any
                # registry link (e.g. an ad-hoc script with diverse
                # targets).
                leader_ctx = getattr(leader, "context_id", None)
                follower_ctx = getattr(follower, "context_id", None)
                if (
                    leader_ctx is not None
                    and leader_ctx == follower_ctx
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
            # v1.23.3 (Discussion #104 sweep): the proposal would
            # automate the follower entity when the leader fires. If
            # the follower is ALREADY acted on by an existing automation,
            # the user has presumably thought about how it should be
            # controlled — a duplicate suggestion is noise. key shape is
            # (leader_eid, leader_state, follower_eid, follower_state).
            follower_eid = key[2]
            if follower_eid in ctx.entities_already_automated:
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
        # v1.6 Phase 2: pattern_value() — event_type for event.* entities,
        # new_state otherwise. event.* entities fire with unique timestamps,
        # so the no-op transition guard never matches and shouldn't.
        # Pair-building logic (which uses new_state as the leader/follower
        # state key) still uses raw new_state — those event-entity pairs
        # land in Phase 4 with the cross-link detector.
        value = pattern_value(ev)
        if value is None:
            return False
        if ev.domain != "event" and ev.new_state == ev.old_state:
            return False
        if ev.domain in self.domains_default_blocked:
            return False
        if not self._is_enum_state(value):
            return False
        # v1.5.16: drop FROM-unavailable. Cooccurrence is especially
        # vulnerable — when an integration wakes up after a long sleep,
        # ALL its entities transition together, manufacturing bogus
        # "X co-occurs with Y" pairs. Skipped for event.* entities.
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

        # v1.7: coupling-strength badge. Tight-coupled pairs (sub-500ms
        # median, ≥90% consistency) are almost certainly device-internal
        # logic (ESPHome on_press, Z-Wave central scene, Zigbee binding)
        # OR a pre-existing HA automation — surfacing them as "automate
        # this!" is noise. Demote confidence so they rank below
        # uncoupled suggestions; the card renders a 🔗 badge so the
        # user knows why. See lib/coupling_strength.py.
        coupling = compute_coupling(
            deltas_seconds=deltas, leader_count=leader_total
        )
        confidence = apply_tier_demotion(confidence, coupling.tier)

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
            # v1.7: coupling tier for the card's 🔗 badge. Always
            # stamped (even NONE) so the card can display "decoupled"
            # state too if it ever wants to.
            "_coupling": coupling_payload(coupling),
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
