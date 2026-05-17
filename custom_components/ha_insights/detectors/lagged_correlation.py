"""LaggedCorrelationDetector — delayed-reaction routines (1-10 min window).

Sibling to CooccurrenceDetector but tuned for patterns where the follower
trails the leader by minutes, not seconds. Examples:
  - "Front door opens after sunset -> kitchen light comes on within 5 min"
  - "Garage opens -> driveway light comes on 2-3 min later"
  - "Kid's bedroom door closes at night -> hallway nightlight a few min later"

CooccurrenceDetector's 30-second window misses these. We raise the
window to 10 min and add a 60-second floor so we don't double-fire on
patterns the cooccurrence detector already catches. The emitted
automation includes a `delay:` step so the action fires at the
observed lag, not immediately.

## v1.9.1: transfer-entropy direction check

Temporal ordering ("Y fires after X") is necessary but not sufficient
for "X causes Y." Two entities both triggered by sunset, by a manual
ritual, or by an unseen third factor will produce identical-looking
temporal-lag patterns. Transfer entropy (see `lib/transfer_entropy.py`)
quantifies directional information flow: TE(X→Y) measures whether
knowing X's past reduces uncertainty about Y's future, BEYOND what Y's
own past already tells you.

We compute TE both directions per pair and apply a multiplicative
demotion to the parent's confidence when the assessment shows:

  - Reversed direction (TE(Y→X) > TE(X→Y) by more than noise) → 0.5×
    — the proposal is backwards; the follower is actually the leader.
    Heavy demotion, often dropping below MIN_CONFIDENCE_TO_EMIT.
  - Symmetric flow with non-zero magnitude → 0.85× — both directions
    have flow, suggesting both are driven by a third factor.
  - Uninformative (both TEs below noise floor) → 1.0× — sparse data;
    don't penalize what we can't measure.
  - Confirmed direction (TE(X→Y) dominates) → 1.0× — direction OK.
"""
from __future__ import annotations

from datetime import UTC, datetime

from ..insight import Insight, InsightKind
from ..lib.transfer_entropy import (
    NOISE_FLOOR_BITS,
    TransferEntropyAssessment,
    discretize_event_stream,
    transfer_entropy,
)
from .base import DetectorContext, register_detector
from .cooccurrence import CooccurrenceDetector


@register_detector
class LaggedCorrelationDetector(CooccurrenceDetector):
    """Detect "B follows A by 1-10 min" delayed-reaction patterns."""

    name = "lagged_correlation"
    kind = InsightKind.AUTOMATION_PROPOSAL

    # Wider window than cooccurrence's 30s. 10 min covers most "I came home,
    # then a few minutes later I turned X on" patterns.
    WINDOW_SECONDS = 600
    # Floor so the parent's 0-30s territory is left alone.
    MIN_DELTA_SECONDS = 60.0
    # Lower occurrence floor than cooccurrence (5) — a 5-min event is
    # naturally less frequent than a 30s event, but we also tolerate one
    # missed week.
    MIN_OCCURRENCES = 4
    # Looser stddev — at minute scale, +/- 90s is still "consistent".
    DELTA_STDDEV_MAX_SECONDS = 90.0

    # Self-protective: 600s window × 14d lookback is super-linear at scale
    # even with the busy-entity pre-filter (a synthetic install where every
    # entity is busy still hits the watchdog). Skip on buffers larger than
    # this; force-enable via CONF_ENABLED_DETECTORS if you really want it
    # on a big install (and don't mind a slower scan). 100K events ≈ 4d
    # at typical busy-install rates, so most healthy installs run it; the
    # outliers (very busy / long lookback) get protection.
    max_buffer_for_full_scan = 100_000

    # v1.9.1: transfer-entropy direction check.
    # Bin width floor / ceiling for the per-entity discretized series.
    # Actual bin size is derived per-pair from the observed mean lag
    # (avg of `deltas`) so single-step TE — which only sees one bin of
    # history — can capture the coupling. A 180s lag with 60s bins
    # places leader and follower transitions in different bins three
    # steps apart, and single-step TE picks up nothing; matching the
    # bin width to the lag puts the related transitions one step apart.
    DIRECTIONALITY_BIN_MIN_SECONDS = 60.0
    DIRECTIONALITY_BIN_MAX_SECONDS = 300.0
    # Minimum TE assessment confidence before we trust the demotion.
    # Below this the underlying probability tables are too sparse to
    # read direction reliably.
    DIRECTIONALITY_MIN_CONFIDENCE = 0.3
    # Demotion factors per dominant_direction. Tuned so reversed
    # direction usually drops the insight below MIN_CONFIDENCE_TO_EMIT
    # (=0.55), while symmetric is just a hint to deprioritize.
    DIRECTIONALITY_DEMOTE_REVERSED = 0.5
    DIRECTIONALITY_DEMOTE_SYMMETRIC = 0.85

    async def scan(self, ctx: DetectorContext) -> list[Insight]:
        # Reset per-scan stream cache so a re-used detector instance
        # doesn't leak streams from the prior scan.
        self._entity_streams: dict[str, list[tuple[float, str]]] | None = None
        try:
            return await super().scan(ctx)
        finally:
            self._entity_streams = None

    def _evaluate_pair(
        self,
        key: tuple[str, str, str, str],
        deltas: list[float],
        events: list[object],
        leader_counts: dict[tuple[str, str], int] | None = None,
    ) -> Insight | None:
        # Reuse parent's stats / consistency / confidence shape, then rebuild
        # the title and payload to reflect the lag. Forward leader_counts
        # so the parent can do its O(1) lookup instead of re-scanning the
        # full buffer per pair (the cost that blew the 30s watchdog).
        base = super()._evaluate_pair(key, deltas, events, leader_counts)
        if base is None:
            return None

        leader_eid, leader_state, follower_eid, follower_state = key
        avg_delta = sum(deltas) / len(deltas)
        avg_delta_int = round(avg_delta)

        # v1.9.1: directionality check. Build per-entity event streams
        # ONCE on first pair (cached on self for the remainder of the
        # scan), then compute transfer entropy for this pair. Bin width
        # is matched to the observed lag so single-step TE picks up
        # the coupling.
        if self._entity_streams is None:
            self._entity_streams = self._build_entity_streams(events)
        bin_seconds = max(
            self.DIRECTIONALITY_BIN_MIN_SECONDS,
            min(self.DIRECTIONALITY_BIN_MAX_SECONDS, avg_delta),
        )
        te_assessment = self._compute_directionality(
            key, self._entity_streams, bin_seconds=bin_seconds
        )
        te_factor = self._directionality_factor(te_assessment)
        # Whole-minute display when the lag is over a minute, otherwise seconds.
        if avg_delta_int >= 60:
            mins, secs = divmod(avg_delta_int, 60)
            lag_label = f"~{mins}m{secs}s" if secs else f"~{mins}m"
        else:
            lag_label = f"~{avg_delta_int}s"

        title = (
            f"After {leader_eid} -> {leader_state}, "
            f"{follower_eid} -> {follower_state} {lag_label} later "
            f"({len(deltas)} times)"
        )

        follower_domain = (
            follower_eid.split(".", 1)[0]
            if "." in follower_eid
            else "homeassistant"
        )
        service = self._domain_to_service(follower_domain, follower_state)

        alias = (
            f"HA Insights: when {leader_eid} {leader_state}, "
            f"{follower_eid} {follower_state} after {lag_label}"
        )
        description = (
            f"Auto-detected delayed correlation: {follower_eid} follows "
            f"{leader_eid} by {lag_label} (averaged across {len(deltas)} runs)."
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
            # `delay:` lets the action fire at the observed lag, not
            # immediately when the leader trips. HA accepts ISO-8601 durations
            # or hh:mm:ss; we use the latter for readability.
            "action": [
                {"delay": _format_hms(avg_delta_int)},
                {"service": service, "target": {"entity_id": follower_eid}},
            ],
            "mode": "single",
        }
        # v1.7: carry forward the coupling stamp the parent computed.
        # At lagged windows (>60s) tier is essentially always NONE —
        # nothing's "tightly coupled" with a multi-minute lag — but
        # surfacing it consistently lets the card make uniform rendering
        # decisions across detectors.
        base_coupling = (base.payload or {}).get("_coupling")
        if base_coupling is not None:
            payload["_coupling"] = base_coupling

        # v1.9.1: stamp directionality so the card can show a 🔀
        # indicator (verified direction) or flag a reversed/symmetric
        # finding. Always stamped (even when uninformative) so the
        # card has uniform structure to read.
        payload["_directionality"] = _directionality_payload(te_assessment)

        # Add a scale marker to the fingerprint so lagged + cooccurrence
        # can both fire on the same entity pair (different delta regimes)
        # without colliding on Insight.compute_id.
        fingerprint = {**base.fingerprint, "scale": "lagged"}
        return Insight(
            id=Insight.compute_id(InsightKind.AUTOMATION_PROPOSAL, fingerprint),
            kind=base.kind,
            detector=self.name,
            area_id=base.area_id,
            title=title,
            confidence=round(base.confidence * te_factor, 3),
            fingerprint=fingerprint,
            payload=payload,
            payload_format="automation",
            created_at=datetime.now(tz=UTC),
        )

    def _build_entity_streams(
        self, events: list[object]
    ) -> dict[str, list[tuple[float, str]]]:
        """One O(N) pass over the event list to group (ts_seconds, new_state)
        tuples by entity_id. Cached on self for the remainder of the scan
        so the next ~M pair evaluations don't each re-scan the buffer."""
        streams: dict[str, list[tuple[float, str]]] = {}
        for ev in events:
            # `events` is typed object for inheritance flexibility but
            # is actually list[StateEvent]; .timestamp / .entity_id /
            # .new_state are stable.
            eid = ev.entity_id  # type: ignore[attr-defined]
            new_state = ev.new_state  # type: ignore[attr-defined]
            ts = ev.timestamp  # type: ignore[attr-defined]
            if new_state is None:
                continue
            streams.setdefault(eid, []).append(
                (ts.timestamp(), str(new_state))
            )
        return streams

    def _compute_directionality(
        self,
        key: tuple[str, str, str, str],
        entity_streams: dict[str, list[tuple[float, str]]],
        bin_seconds: float,
    ) -> TransferEntropyAssessment | None:
        """Discretize the leader and follower event streams to parallel
        time-binned state sequences, then run transfer_entropy.

        Returns None when either entity is absent or there's no time
        span to discretize.
        """
        leader_eid, _leader_state, follower_eid, _follower_state = key
        leader_events = entity_streams.get(leader_eid, [])
        follower_events = entity_streams.get(follower_eid, [])
        if not leader_events or not follower_events:
            return None

        t0 = min(leader_events[0][0], follower_events[0][0])
        t_end = max(leader_events[-1][0], follower_events[-1][0])
        duration = t_end - t0
        if duration <= 0:
            return None
        # Normalize timestamps to start at 0 for the bin helper.
        leader_norm = [(t - t0, s) for t, s in leader_events]
        follower_norm = [(t - t0, s) for t, s in follower_events]

        leader_seq = discretize_event_stream(
            leader_norm,
            bin_size_seconds=bin_seconds,
            total_duration_seconds=duration,
        )
        follower_seq = discretize_event_stream(
            follower_norm,
            bin_size_seconds=bin_seconds,
            total_duration_seconds=duration,
        )
        # Need a minimum number of bins or TE is too sparse to be
        # meaningful. transfer_entropy() handles its own MIN_SAMPLES
        # check via confidence; we just guard against empty inputs.
        if not leader_seq or not follower_seq:
            return None
        return transfer_entropy(leader_seq, follower_seq)

    def _directionality_factor(
        self, assessment: TransferEntropyAssessment | None
    ) -> float:
        """Map a TE assessment to a confidence-multiplier in [0.5, 1.0].

        Conservative: only demote when the assessment is both
        confident AND informative (at least one direction above the
        noise floor). Sparse pairs that produce uninformative
        assessments are passed through unchanged so we don't penalize
        what we can't measure.
        """
        if assessment is None:
            return 1.0
        if assessment.confidence < self.DIRECTIONALITY_MIN_CONFIDENCE:
            return 1.0
        # Uninformative: both directions below noise. Don't demote.
        if (
            assessment.te_x_to_y < NOISE_FLOOR_BITS
            and assessment.te_y_to_x < NOISE_FLOOR_BITS
        ):
            return 1.0
        if assessment.dominant_direction == "y_to_x":
            return self.DIRECTIONALITY_DEMOTE_REVERSED
        if assessment.dominant_direction == "symmetric":
            return self.DIRECTIONALITY_DEMOTE_SYMMETRIC
        # "x_to_y" — direction confirmed.
        return 1.0


def _directionality_payload(
    assessment: TransferEntropyAssessment | None,
) -> dict[str, object]:
    """Card-facing structure for the 🔀 indicator. Always returns a dict
    with stable keys; `assessed: false` means "no signal, don't render
    a badge"."""
    if assessment is None:
        return {"assessed": False}
    return {
        "assessed": True,
        "direction": assessment.dominant_direction,
        "te_x_to_y": assessment.te_x_to_y,
        "te_y_to_x": assessment.te_y_to_x,
        "asymmetry": assessment.asymmetry,
        "confidence": assessment.confidence,
        "n_samples": assessment.n_samples,
    }


def _format_hms(seconds: int) -> str:
    """Format seconds as hh:mm:ss for HA's `delay:` field."""
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"
