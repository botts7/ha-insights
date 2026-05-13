"""OrphanDeviceDetector — flag entities that have gone silent.

If an entity hasn't reported in N days but used to report regularly, it
likely means: dead battery, network drop, device removed but not yet
unregistered, automation disabled, etc. Surfaces an ANOMALY insight
with a "notify when back online" automation so the user can decide
whether to apply it (passive surfacing) or dismiss.

Requires at least one prior event in the buffer to know the entity
existed — orphans without history are HA's responsibility, not ours.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from ..insight import Insight, InsightKind
from .base import Detector, DetectorContext, register_detector

if TYPE_CHECKING:
    from ..observers.state_event_buffer import StateEvent


# Domains worth checking. Some entities (sun, scene, automation) are
# expected to "report" rarely or never, so we skip them.
_DEFAULT_DOMAINS: frozenset[str] = frozenset(
    {
        "binary_sensor",
        "sensor",
        "switch",
        "light",
        "fan",
        "climate",
        "cover",
        "lock",
        "media_player",
        "device_tracker",
        "vacuum",
    }
)


@register_detector
class OrphanDeviceDetector(Detector):
    """Detect entities that haven't reported in over N days."""

    name = "orphan_device"
    kind = InsightKind.ANOMALY
    requires_recorder = False

    LOOKBACK_DAYS = 14
    # Anything stale for >= STALE_THRESHOLD_DAYS triggers an insight.
    # 7 days is the floor — most device polling intervals are <24h, so
    # a week of silence is unambiguous.
    STALE_THRESHOLD_DAYS = 7
    # We require at least this many prior events in the lookback window so
    # we don't fire on devices that never had history (recently added).
    MIN_PRIOR_EVENTS = 3

    async def scan(self, ctx: DetectorContext) -> list[Insight]:
        if ctx.event_buffer is None:
            return []

        now = datetime.now(tz=UTC).replace(microsecond=0)
        cutoff = now - timedelta(days=self.LOOKBACK_DAYS)
        stale_threshold = now - timedelta(days=self.STALE_THRESHOLD_DAYS)

        events = sorted(
            ctx.event_buffer.query(since=cutoff), key=lambda e: e.timestamp
        )
        if not events:
            return []

        # Group by entity_id, capturing count + latest timestamp.
        per_entity: dict[str, list[StateEvent]] = defaultdict(list)
        for ev in events:
            per_entity[ev.entity_id].append(ev)

        # v1.4: track the latest timestamp per entity for the group-
        # membership false-positive filter below. An entity that's
        # gone silent BUT whose parent group is firing recently is
        # probably just a slaved member (template light, ESPHome
        # group, Hue group) that doesn't propagate state to members
        # individually. Flagging it as "battery dead" is wrong.
        latest_by_entity: dict[str, datetime] = {
            eid: evs[-1].timestamp for eid, evs in per_entity.items()
        }

        insights: list[Insight] = []
        for entity_id, entity_events in per_entity.items():
            domain = entity_id.split(".", 1)[0] if "." in entity_id else ""
            if domain not in _DEFAULT_DOMAINS:
                continue
            if domain in self.domains_default_blocked:
                continue
            if len(entity_events) < self.MIN_PRIOR_EVENTS:
                continue
            latest = entity_events[-1].timestamp
            if latest >= stale_threshold:
                continue  # still reporting recently
            # Group-membership false-positive filter: if this entity
            # is a member of a container that DID fire recently, the
            # entity is just slaved to a group whose state-change
            # propagation skips the members. Not a real orphan.
            if self._has_active_parent(
                entity_id, latest_by_entity, ctx, stale_threshold
            ):
                continue
            silence_days = max(1, round((now - latest).total_seconds() / 86400))
            insight = self._build_insight(entity_id, latest, silence_days)
            if insight is not None:
                insights.append(insight)
        return insights

    def _has_active_parent(
        self,
        entity_id: str,
        latest_by_entity: dict[str, datetime],
        ctx: DetectorContext,
        stale_threshold: datetime,
    ) -> bool:
        """True iff `entity_id` is a member of a container whose
        latest state-change is more recent than `stale_threshold`.
        Such entities are probably slaved members of an active group
        (template light, ESPHome group, Hue group) that doesn't
        propagate state to members individually."""
        if not ctx.container_to_members:
            return False
        for parent_eid, members in ctx.container_to_members.items():
            if entity_id not in members:
                continue
            parent_latest = latest_by_entity.get(parent_eid)
            if parent_latest is not None and parent_latest >= stale_threshold:
                return True
        return False

    def _build_insight(
        self,
        entity_id: str,
        last_seen: datetime,
        silence_days: int,
    ) -> Insight | None:
        # Confidence scales with how stale the entity is, capped at 14d.
        confidence = round(
            min(1.0, silence_days / self.LOOKBACK_DAYS),
            3,
        )

        title = (
            f"{entity_id} hasn't reported in {silence_days}d. "
            "Battery dead, network drop, or device removed?"
        )

        fingerprint = {
            "entity_id": entity_id,
            "kind": "orphan_device",
            # Use silence_days bucket (rounded count of days the entity
            # has been silent) instead of last_seen.date() — same
            # idempotency (re-scans on the same day produce the same
            # bucket) AND lets the dedup helper merge entities that all
            # went offline at the same time. Previously, two entities
            # whose last_seen straddled midnight got DIFFERENT
            # last_seen_day values, defeating the dedup and producing
            # one insight per entity even when 33 entities on the same
            # NVR all dropped together.
            "silence_days_bucket": silence_days,
        }

        # Compose a notify-when-back-online automation. Apply-able for
        # users who want to know when the device comes back; otherwise
        # they can Dismiss the insight.
        payload = {
            "alias": f"HA Insights: alert when {entity_id} comes back online",
            "description": (
                f"Auto-detected orphan: {entity_id} has been silent for "
                f"{silence_days} days. This automation pings you with a "
                "persistent_notification when the entity reports again."
            ),
            "trigger": [
                {
                    "platform": "state",
                    "entity_id": entity_id,
                    "from": "unavailable",
                }
            ],
            "action": [
                {
                    "service": "persistent_notification.create",
                    "data": {
                        "title": "HA Insights",
                        "message": (
                            f"{entity_id} is back online "
                            f"(was silent for {silence_days}+ days)."
                        ),
                    },
                }
            ],
            "mode": "single",
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
            payload_format="automation",
            created_at=datetime.now(tz=UTC),
        )
