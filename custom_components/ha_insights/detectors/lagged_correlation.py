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
"""
from __future__ import annotations

from datetime import UTC, datetime

from ..insight import Insight, InsightKind
from .base import register_detector
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

    def _evaluate_pair(
        self,
        key: tuple[str, str, str, str],
        deltas: list[float],
        events: list[object],
    ) -> Insight | None:
        # Reuse parent's stats / consistency / confidence shape, then rebuild
        # the title and payload to reflect the lag.
        base = super()._evaluate_pair(key, deltas, events)
        if base is None:
            return None

        leader_eid, leader_state, follower_eid, follower_state = key
        avg_delta = sum(deltas) / len(deltas)
        avg_delta_int = round(avg_delta)
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
            confidence=base.confidence,
            fingerprint=fingerprint,
            payload=payload,
            payload_format="automation",
            created_at=datetime.now(tz=UTC),
        )


def _format_hms(seconds: int) -> str:
    """Format seconds as hh:mm:ss for HA's `delay:` field."""
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"
