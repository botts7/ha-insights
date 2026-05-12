"""AutomationAuditDetector — the v1.1 marquee feature.

Reads every existing automation and emits AUTOMATION_IMPROVEMENT
insights enriched with deterministic observations + HA-trace-derived
ground truth. The Phase C LLM layer turns those observations into
concrete YAML edits, but the deterministic layer alone is useful
even at privacy mode = off.

Skip rules (respect user privacy / scope):
  - Label `ha_insights:no-audit` on an automation → fully skipped
  - All entities in the automation are in `blocked_entities` →
    empty packet → no insight
  - Packet has zero observations → no insight (silence is default)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ..audit.fixes import apply_deterministic_fixes
from ..audit.packet import (
    AuditPacket,
    Observation,
    build_audit_packet,
)
from ..audit.traces import (
    TraceAggregates,
    fetch_trace_aggregates,
)
from ..insight import Insight, InsightKind
from .base import Detector, DetectorContext, register_detector

if TYPE_CHECKING:
    pass

_LOGGER = logging.getLogger(__name__)

# How many automations we audit per scan. Each one triggers a trace
# fetch (small WS round-trip × N traces) — bounded so a huge install
# doesn't blow up the scan budget. Rotates oldest-first across scans.
_AUDIT_PER_SCAN_CAP = 25

_SKIP_LABEL = "ha_insights:no-audit"


@register_detector
class AutomationAuditDetector(Detector):
    """Per-automation audit: combines short-term buffer observations +
    HA trace ground truth + hierarchy structural checks + recent
    detector findings into one consolidated AUTOMATION_IMPROVEMENT
    insight per automation that has anything worth saying.

    Runs LAST in the scan order so it can join the just-emitted
    insights from other detectors. Ordering enforced by the scan
    runner via the `name` field (alphabetical late suffix would be
    ideal; relying on registration order today).
    """

    name = "automation_audit"
    kind = InsightKind.AUTOMATION_IMPROVEMENT
    requires_recorder = False

    async def scan(self, ctx: DetectorContext) -> list[Insight]:
        if not ctx.existing_automations:
            return []

        # Pull the store's currently-active insights so we can join
        # them into each packet by entity_id. Tolerate failure — the
        # join is enrichment, not a hard dependency.
        recent_insights = await self._load_recent_insights(ctx)

        # Pre-fetch trace aggregates on the event loop for every
        # automation we plan to audit. Cheap per call; bounded by
        # _AUDIT_PER_SCAN_CAP.
        audit_targets = self._select_audit_targets(ctx.existing_automations)

        trace_map: dict[str, TraceAggregates] = {}
        if audit_targets:
            trace_results = await asyncio.gather(
                *(
                    fetch_trace_aggregates(
                        ctx.hass,
                        auto.get("id") or auto.get("alias") or "",
                    )
                    for auto in audit_targets
                ),
                return_exceptions=True,
            )
            for auto, result in zip(
                audit_targets, trace_results, strict=False
            ):
                key = auto.get("id") or auto.get("alias") or ""
                if isinstance(result, TraceAggregates):
                    trace_map[key] = result

        # Pre-fetch rollup data for every entity we'll touch. Cheap
        # SELECT against the audit_rollups table. Empty dict per
        # entity if no rollup has been materialized yet (first-scan
        # installs degrade gracefully — short-term observations only).
        rollup_by_entity = await self._load_rollups(ctx, audit_targets)

        # Resolve the EFFECTIVE rollup window:
        #   configured (OptionsFlow) clamped to actual recorder
        #   retention. Observations need this number to avoid false
        #   positives like "1st-3rd of each month" claimed from a
        #   10-day data sample.
        try:
            from ..audit.rollup import _resolve_window_days

            configured_window_days = _resolve_window_days(ctx.hass)
        except Exception:  # pragma: no cover — fall back to default
            from ..audit.rollup import ROLLUP_WINDOW_DAYS

            configured_window_days = ROLLUP_WINDOW_DAYS

        # Probe recorder.keep_days — public attr, no I/O. The
        # observation pipeline uses min(configured, retention) so
        # we never claim multi-month patterns from a 10-day sample.
        try:
            from homeassistant.components.recorder import get_instance

            rec = get_instance(ctx.hass)
            recorder_keep_days = getattr(rec, "keep_days", None) or getattr(
                rec, "_keep_days", None
            )
        except Exception:  # noqa: BLE001
            recorder_keep_days = None

        if recorder_keep_days is not None:
            rollup_window_days = min(
                configured_window_days, int(recorder_keep_days)
            )
        else:
            rollup_window_days = configured_window_days

        # Snapshot HA's live state machine so the silent-entity
        # check has a source of truth that's independent of our
        # scan_areas / blocked_entities filtered buffer. Cheap dict
        # iteration on the event loop.
        live_states: dict[str, str] = {
            s.entity_id: s.state for s in ctx.hass.states.async_all()
        }

        # Build packets + emit insights. Pure / fast per automation.
        now = datetime.now(tz=UTC)
        insights: list[Insight] = []
        for auto in audit_targets:
            if self._should_skip(auto):
                continue
            packet = build_audit_packet(
                auto,
                buffer=ctx.event_buffer,
                hierarchy=ctx.hierarchy,
                recent_insights=recent_insights,
                blocked_entities=ctx.blocked_entities,
                trace_aggregates=trace_map.get(
                    auto.get("id") or auto.get("alias") or ""
                ),
                rollup_by_entity=rollup_by_entity,
                rollup_window_days=rollup_window_days,
                live_states=live_states,
                now=now,
            )
            if not packet.observations:
                continue
            insights.append(self._build_insight(packet, now=now))
        return insights

    async def _load_rollups(
        self,
        ctx: DetectorContext,
        audit_targets: list[dict[str, Any]],
    ) -> dict[str, dict[str, dict[int, int]]]:
        """Pull every audit-target entity's rollup buckets in one
        pass. Returns {} when no store is available — packet then
        skips rollup observations entirely."""
        try:
            from ..apply.conflict_scanner import _as_list, _extract_target_entities
            from ..const import DOMAIN

            store = None
            for entry_data in ctx.hass.data.get(DOMAIN, {}).values():
                if isinstance(entry_data, dict) and "store" in entry_data:
                    store = entry_data["store"]
                    break
            if store is None:
                return {}

            eids: set[str] = set()
            for auto in audit_targets:
                eids.update(_extract_target_entities(auto.get("action")))
                for trig in _as_list(auto.get("trigger")):
                    if not isinstance(trig, dict):
                        continue
                    tid = trig.get("entity_id")
                    if isinstance(tid, str):
                        eids.add(tid)
                    elif isinstance(tid, list):
                        eids.update(e for e in tid if isinstance(e, str))

            out: dict[str, dict[str, dict[int, int]]] = {}
            for eid in eids:
                rollups = await store.get_rollups_for_entity(eid)
                if rollups:
                    out[eid] = rollups
            return out
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("audit: rollup lookup failed: %s", err)
            return {}

    def _select_audit_targets(
        self,
        automations: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Cap the per-scan workload. Eligible = not labeled
        no-audit. Rotation across scans is implicit because the
        store retains audit insights with stable fingerprints — if a
        given automation's insight is already up-to-date, it stays;
        if not (new observations), the scan-time dedup replaces it.

        Dedup happens at the source (_load_existing_automations);
        no per-detector dedup needed here.
        """
        eligible = [
            a for a in automations if not self._should_skip(a)
        ]
        return eligible[:_AUDIT_PER_SCAN_CAP]

    @staticmethod
    def _should_skip(automation: dict[str, Any]) -> bool:
        """Honor `ha_insights:no-audit` skip label OR a top-level
        `audit: false` description hint. Either form opts the
        automation out of the audit."""
        # Label-based (preferred): HA 2024+ entity labels on the
        # automation entity. The YAML doesn't carry labels directly;
        # they live in the entity registry — but we don't have entity
        # registry access from the YAML alone. So we look for the
        # alternate inline hint first; the registry-label check lands
        # in Phase B2 once we plumb the entity_registry through.
        desc = automation.get("description")
        if isinstance(desc, str) and _SKIP_LABEL in desc.lower():
            return True
        # Alternate inline form: `ha_insights: {audit: false}` block
        ha_block = automation.get("ha_insights")
        if isinstance(ha_block, dict) and ha_block.get("audit") is False:
            return True
        return False

    async def _load_recent_insights(
        self, ctx: DetectorContext
    ) -> list[Insight]:
        """Pull the integration's currently-active insights from the
        store so the packet builder can join them by entity_id. Best-
        effort: failure returns empty list and packets just skip the
        join."""
        try:
            # Stored on hass.data by the integration setup. Mirrors
            # the path used in ws_api.ws_list.
            from ..const import DOMAIN

            for entry_data in ctx.hass.data.get(DOMAIN, {}).values():
                if isinstance(entry_data, dict) and "store" in entry_data:
                    store = entry_data["store"]
                    return await store.list_insights(
                        include_dismissed=False,
                        include_applied=False,
                        include_snoozed=False,
                    )
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug(
                "audit: failed to load recent insights for join: %s", err
            )
        return []

    def _build_insight(
        self, packet: AuditPacket, *, now: datetime
    ) -> Insight:
        """Construct the AUTOMATION_IMPROVEMENT insight from a packet."""
        obs_count = len(packet.observations)
        # Title prefers the highest-confidence observation's text so
        # the panel row leads with the most important finding.
        lead = max(packet.observations, key=lambda o: o.confidence)
        title = (
            f"Audit '{packet.automation_alias}' — {lead.text}"
            if obs_count == 1
            else (
                f"Audit '{packet.automation_alias}' "
                f"({obs_count} findings): {lead.text}"
            )
        )

        # Confidence: blend the observation confidences. Avg weighted
        # toward the max so a single high-confidence finding lifts
        # the row visibility.
        confidences = [o.confidence for o in packet.observations]
        confidence = round(
            0.6 * max(confidences) + 0.4 * (sum(confidences) / len(confidences)),
            3,
        )

        # Stable id: automation_id + sorted observation kinds so a
        # re-scan with the same findings produces the same id (dedupes
        # via the store).
        fingerprint: dict[str, Any] = {
            "automation_id": packet.automation_id,
            "kind": "automation_audit",
            "observation_kinds": sorted({o.kind for o in packet.observations}),
        }

        observation_payload = [
            {
                "kind": o.kind,
                "text": o.text,
                "confidence": o.confidence,
                "metrics": o.metrics,
            }
            for o in packet.observations
        ]

        # Phase B.5: try to build a deterministic YAML edit covering
        # one or more observations. When at least one fix lands, the
        # insight becomes apply-able WITHOUT calling the LLM. Saves
        # tokens for the cases that genuinely need them.
        refined_yaml, fix_summaries = apply_deterministic_fixes(
            packet.automation_yaml, observation_payload
        )

        if refined_yaml is not None and fix_summaries:
            # Pre-serialize the refined YAML so the card's 📋 Preview
            # button can render a proper YAML diff without doing its
            # own JSON.stringify (which produces hard-to-read prose).
            try:
                import yaml as _yaml

                refined_yaml_str = _yaml.safe_dump(
                    refined_yaml,
                    sort_keys=False,
                    default_flow_style=False,
                )
            except Exception:  # noqa: BLE001
                refined_yaml_str = ""

            # Build a full Apply-able automation payload. The card's
            # existing apply path validates + writes via the
            # AutomationWriter.
            payload: dict[str, Any] = {
                **refined_yaml,
                # Audit-specific metadata trails along on the payload
                # so the card can render the observations + fix list
                # alongside the YAML preview.
                "_audit": {
                    "automation_id": packet.automation_id,
                    "automation_alias": packet.automation_alias,
                    "observations": observation_payload,
                    "fix_summaries": fix_summaries,
                    "related_insight_ids": list(packet.related_insight_ids),
                    "deterministic": True,
                    "refined_yaml_text": refined_yaml_str,
                },
            }
            payload_format = "automation"
        else:
            # No deterministic fix; ship as report. Phase C's
            # 🤖 Suggest button will offer LLM refinement.
            payload = {
                "automation_id": packet.automation_id,
                "automation_alias": packet.automation_alias,
                "observations": observation_payload,
                "related_insight_ids": list(packet.related_insight_ids),
                "target_entities": sorted(packet.target_entities),
                "trigger_entities": sorted(packet.trigger_entities),
                "advice": (
                    "Observations only — no deterministic fix applies. "
                    "Use '🤖 Suggest improvements' to ask the LLM for "
                    "specific edits, or refine the automation manually."
                ),
            }
            payload_format = "report"

        return Insight(
            id=Insight.compute_id(InsightKind.AUTOMATION_IMPROVEMENT, fingerprint),
            kind=InsightKind.AUTOMATION_IMPROVEMENT,
            detector=self.name,
            area_id=None,
            title=title,
            confidence=confidence,
            fingerprint=fingerprint,
            payload=payload,
            payload_format=payload_format,
            created_at=now,
        )
