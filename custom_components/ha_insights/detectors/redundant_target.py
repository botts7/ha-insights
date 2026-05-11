"""RedundantTargetDetector — flag automations targeting both a group AND
its members.

User-reported pattern: an automation YAML with action targeting both
`light.outdoor_group` (a group light) AND `light.front_garden_lights`
(a member of that group). Calling `light.turn_on` twice on entities
that both end up affected by the parent action wastes a service call,
clutters the YAML, and surprises future readers ("why is this entity
listed twice?").

Algorithm (deterministic, fully code-only):
  1. Iterate ctx.existing_automations.
  2. For each automation, extract action target entity_ids via the
     existing conflict_scanner helper.
  3. Build the set of redundant pairs (container, member) where
     `container ∈ targets AND member ∈ targets AND member ∈
     container_to_members[container]`.
  4. Emit one AUTOMATION_IMPROVEMENT insight per affected automation
     summarizing the redundant pairs.

Stable id from automation_id + sorted member list so re-scans dedup.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ..insight import Insight, InsightKind
from .base import Detector, DetectorContext, register_detector

if TYPE_CHECKING:
    pass


@register_detector
class RedundantTargetDetector(Detector):
    """Flag automations whose action targets contain both a group/scene/
    script and at least one of its own members.

    v1.1: AutomationAuditDetector now covers this same finding inside
    a consolidated per-automation audit row. Keeping this detector
    disabled-by-default avoids double-emission. Re-enable by setting
    `detector_config.legacy_emit = True` if you specifically want the
    standalone row.
    """

    name = "redundant_target"
    kind = InsightKind.AUTOMATION_IMPROVEMENT
    requires_recorder = False

    async def scan(self, ctx: DetectorContext) -> list[Insight]:
        if not ctx.existing_automations:
            return []
        # Suppressed by default — AutomationAuditDetector folds this
        # finding into its consolidated row. Opt back in via config
        # if a user wants the standalone view.
        if not ctx.detector_config.get("legacy_emit"):
            return []

        from ..apply.conflict_scanner import _extract_target_entities

        # Prefer the central hierarchy's strict parent→members map.
        # Fall back to the legacy container_to_members during migration.
        if ctx.hierarchy is not None and ctx.hierarchy.members_of:
            container_map = ctx.hierarchy.members_of
        elif ctx.container_to_members:
            container_map = ctx.container_to_members
        else:
            return []

        insights: list[Insight] = []

        for auto in ctx.existing_automations:
            targets = _extract_target_entities(auto.get("action"))
            if len(targets) < 2:
                continue

            # Find redundant pairs: a container in `targets` that also has
            # one or more of its members in `targets`.
            redundancies: list[tuple[str, list[str]]] = []
            for candidate in sorted(targets):
                members = container_map.get(candidate, frozenset())
                if not members:
                    continue
                overlapping_members = sorted(targets & members)
                if overlapping_members:
                    redundancies.append((candidate, overlapping_members))

            if not redundancies:
                continue

            insights.append(self._build_insight(auto, redundancies))

        return insights

    def _build_insight(
        self,
        auto: dict,
        redundancies: list[tuple[str, list[str]]],
    ) -> Insight:
        automation_id = auto.get("id") or auto.get("alias") or "unknown"
        automation_alias = auto.get("alias") or automation_id

        # Title: name the first redundant pair concisely; payload has full
        # detail for the user to inspect.
        first_container, first_members = redundancies[0]
        members_summary = (
            f"{first_members[0]}"
            if len(first_members) == 1
            else f"{first_members[0]} (+{len(first_members) - 1} more)"
        )
        title = (
            f"Automation '{automation_alias}' has redundant targets: "
            f"{first_container} already covers {members_summary}. "
            "Drop the redundant entries?"
        )
        if len(redundancies) > 1:
            title += f" (+{len(redundancies) - 1} more redundant groups)"

        # Stable id: automation_id + every redundant pair sorted.
        sorted_pairs = sorted((c, tuple(m)) for c, m in redundancies)
        fingerprint = {
            "automation_id": automation_id,
            "kind": "redundant_target",
            "redundant_pairs": [
                {"container": c, "members": list(m)} for c, m in sorted_pairs
            ],
        }

        # Confidence is high — this is a static-analysis finding, not a
        # statistical heuristic. 0.9 leaves some room for the rare case
        # where the redundancy is intentional (e.g., user wants the
        # group call AND a per-member service call with different args
        # — though that'd be in separate action blocks).
        confidence = 0.9

        # Payload: descriptive, not directly applicable. The user has to
        # decide which side to drop. payload_format="report" so the card
        # doesn't show an Apply button.
        payload = {
            "automation_id": automation_id,
            "automation_alias": automation_alias,
            "redundancies": [
                {"container": c, "members": list(m)} for c, m in sorted_pairs
            ],
            "advice": (
                "Each container target listed already affects all the named "
                "member entities. Removing the member entries (or removing "
                "the container entry) keeps the same effective behaviour "
                "with cleaner config."
            ),
        }

        return Insight(
            id=Insight.compute_id(InsightKind.AUTOMATION_IMPROVEMENT, fingerprint),
            kind=InsightKind.AUTOMATION_IMPROVEMENT,
            detector=self.name,
            area_id=None,
            title=title,
            confidence=confidence,
            fingerprint=fingerprint,
            payload=payload,
            payload_format="report",
            created_at=datetime.now(tz=UTC),
        )
