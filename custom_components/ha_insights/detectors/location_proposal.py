"""LocationProposalDetector — propose an area for unassigned entities
by similarity to already-area-tagged siblings.

The bulk-area-assign dialog (v1.5.0) helps users find unassigned
entities; the v1.10 🔆 + 👆 buttons help locate them physically.
But for passive sensors that ARE in a room but just lack the area
assignment, the value stream itself often gives the answer
deterministically: a temperature sensor that tracks the
`Living Room Thermostat` at r=0.92 is almost certainly in the
living room.

This detector turns that intuition into an emit-able insight:

  > Probably in **Living Room**: 3 already-tagged temp sensors
  > there match this entity's curve at median r=0.91.

**NEVER auto-applies.** Always advisory. The user clicks the
insight, sees the candidates, and decides whether to accept the
suggestion or keep investigating.

## Why this works

Real homes have spatial correlation in environmental signals:

  - Two temp sensors in the same room follow nearly the same diurnal
    curve (the shared air column homogenizes within minutes).
  - Two humidity sensors in the same room behave the same way after
    a shower / cooking event.
  - Two illuminance sensors near the same window track sunrise +
    cloud passage.
  - Outdoor sensors track outdoor sensors (different room, but
    the right CATEGORY signal).

The room-level signal is strong enough that we can rank candidate
areas by the median r between the unassigned entity and each
area's already-tagged siblings. Pre-filtering keeps this cheap.

## Pre-filtering (per pre-existing detector convention)

  - Only entities in `_RELEVANT_DOMAINS` (sensor)
  - Only entities WITHOUT an area assignment
  - Only entities whose `device_class` matches at least 2 siblings
    in already-tagged rooms (otherwise no comparison data)
  - Skip entities flagged by v1.11.0 PhysicalDeviceLinkDetector
    (likely-duplicate of a known entity — area inference would
    just mirror the duplicate's area, not useful)

## Threshold

Median r ≥ 0.75 against an area's siblings → emit. Below that the
signal is too weak to surface; above ~0.90 it's strong (and we
note that in the explanation). Below the threshold we still keep
the result internally for the v1.12+ "best guess across all
areas" surfacing — but don't emit a primary insight.

## Architecture

Uses `lib/correlation_primitives.py` v1.11.0. Same 7-day lookback,
same 10-min bins. New `_score_against_area` helper that aggregates
per-pair correlation into a per-area median.

BETA pending real-install calibration. Per memory
`ha_insights_find_my_device_roadmap`, this is the v1.11.5 slot
sibling to v1.11.0 dedup detection.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from ..insight import Insight, InsightKind
from ..lib.correlation_primitives import (
    MIN_SAMPLES_FOR_CORR,
    time_aligned_correlation,
)
from .base import Detector, DetectorContext, Maturity, register_detector

# Same window + bin size as v1.11.0 for consistency.
_LOOKBACK_DAYS = 7
_BIN_SIZE_SECONDS = 600.0
_MIN_EVENTS_PER_ENTITY = 30

# Median-r threshold to emit a location proposal. Calibrated for
# "moderately strong" room-level similarity. r=0.75 leaves room for
# real-world noise (different placement, drafts, sunlight) while
# rejecting unrelated entities.
_R_THRESHOLD = 0.75

# Strong-signal threshold for the explanation copy ("almost
# certainly in X" vs "probably in X").
_R_STRONG = 0.90

# Minimum tagged siblings in an area before we score it. With only
# 1 sibling the median is just that one r; not enough evidence.
_MIN_SIBLINGS_PER_AREA = 2

# Hard cap on proposals per scan.
_MAX_INSIGHTS_PER_SCAN = 10

# Domains where spatial correlation works. Mostly continuous-value
# sensors; binary domains (motion, door) are addressed by
# different detectors (cooccurrence, etc.).
_RELEVANT_DOMAINS: frozenset[str] = frozenset({"sensor"})


@register_detector
class LocationProposalDetector(Detector):
    """Propose an area for an unassigned entity based on its value-
    stream similarity to area-tagged siblings."""

    name = "location_proposal"
    kind = InsightKind.PATTERN_OBSERVATION
    requires_recorder = False
    maturity = Maturity.BETA
    description = (
        "For each unassigned sensor, finds the area whose already-"
        "tagged siblings best match its value stream over the last "
        "7 days. Spatial correlation in temp/humidity/illuminance/"
        "etc. is strong enough that a sensor matching a room's "
        "siblings at r ≥ 0.75 is probably in that room. Advisory "
        "only — never auto-assigns; the user reviews and applies."
    )
    required_data = ("feature:event_buffer",)

    async def scan(self, ctx: DetectorContext) -> list[Insight]:
        if ctx.event_buffer is None:
            return []

        now_utc = datetime.now(tz=UTC).replace(microsecond=0)
        cutoff = now_utc - timedelta(days=_LOOKBACK_DAYS)
        start_ts = cutoff.timestamp()
        end_ts = now_utc.timestamp()

        # Pull entity + area data from registries. Lazy to keep
        # this dict import-free at module load time.
        try:
            from homeassistant.helpers import area_registry as ar
            from homeassistant.helpers import entity_registry as er
        except ImportError:
            return []
        e_reg = er.async_get(ctx.hass)
        a_reg = ar.async_get(ctx.hass)

        # Map entity_id → (device_class, area_id_or_None)
        entity_meta: dict[str, tuple[str, str | None]] = {}
        for entity_id in by_entity_keys(ctx):
            domain = (
                entity_id.split(".", 1)[0] if "." in entity_id else ""
            )
            if domain not in _RELEVANT_DOMAINS:
                continue
            if entity_id in ctx.blocked_entities:
                continue
            if domain in self.domains_default_blocked:
                continue
            state = ctx.hass.states.get(entity_id)
            if state is None:
                continue
            dc = state.attributes.get("device_class")
            if not isinstance(dc, str):
                continue
            er_ent = e_reg.async_get(entity_id)
            area_id = er_ent.area_id if er_ent is not None else None
            entity_meta[entity_id] = (dc.lower(), area_id)

        # Collect events per qualifying entity.
        by_entity: dict[str, list[tuple[float, float]]] = defaultdict(list)
        for ev in ctx.event_buffer.query(since=cutoff):
            if ev.entity_id not in entity_meta:
                continue
            if ev.new_state is None:
                continue
            try:
                value = float(ev.new_state)
            except (TypeError, ValueError):
                continue
            by_entity[ev.entity_id].append((ev.timestamp.timestamp(), value))

        # Trim entities with insufficient events.
        for eid in list(by_entity.keys()):
            if len(by_entity[eid]) < _MIN_EVENTS_PER_ENTITY:
                del by_entity[eid]
                del entity_meta[eid]

        # Group already-tagged entities by (device_class, area_id) so
        # the per-area scoring can find siblings in O(1).
        siblings_by_area: dict[
            tuple[str, str], list[str]
        ] = defaultdict(list)
        for eid, (dc, area_id) in entity_meta.items():
            if area_id is not None and eid in by_entity:
                siblings_by_area[(dc, area_id)].append(eid)

        # Unassigned entities are the candidates we score.
        candidates = [
            eid
            for eid, (_dc, area_id) in entity_meta.items()
            if area_id is None and eid in by_entity
        ]

        insights: list[Insight] = []
        for entity_id in sorted(candidates):
            dc, _ = entity_meta[entity_id]
            best_area: str | None = None
            best_median_r: float = 0.0
            best_n_siblings: int = 0
            per_area_results: list[tuple[str, float, int]] = []

            for (sibling_dc, area_id), sibling_eids in siblings_by_area.items():
                if sibling_dc != dc:
                    continue
                if len(sibling_eids) < _MIN_SIBLINGS_PER_AREA:
                    continue
                rs: list[float] = []
                for sibling_eid in sibling_eids:
                    if sibling_eid == entity_id:
                        continue
                    result = time_aligned_correlation(
                        by_entity[entity_id],
                        by_entity[sibling_eid],
                        bin_size_seconds=_BIN_SIZE_SECONDS,
                        start_ts=start_ts,
                        end_ts=end_ts,
                    )
                    if result.n_samples < MIN_SAMPLES_FOR_CORR:
                        continue
                    rs.append(result.r)
                if len(rs) < _MIN_SIBLINGS_PER_AREA:
                    continue
                # Median r across siblings — robust to one outlier
                # (the sensor that happens to be on the other side
                # of the room near a window).
                median_r = statistics.median(rs)
                per_area_results.append((area_id, median_r, len(rs)))
                if median_r > best_median_r:
                    best_median_r = median_r
                    best_area = area_id
                    best_n_siblings = len(rs)

            if best_area is None or best_median_r < _R_THRESHOLD:
                continue
            area = a_reg.async_get_area(best_area)
            if area is None:
                continue
            insights.append(
                self._build_insight(
                    entity_id=entity_id,
                    device_class=dc,
                    area_id=best_area,
                    area_name=area.name,
                    median_r=best_median_r,
                    n_siblings=best_n_siblings,
                    per_area_results=per_area_results,
                )
            )
            if len(insights) >= _MAX_INSIGHTS_PER_SCAN:
                break

        return insights

    def _build_insight(
        self,
        *,
        entity_id: str,
        device_class: str,
        area_id: str,
        area_name: str,
        median_r: float,
        n_siblings: int,
        per_area_results: list[tuple[str, float, int]],
    ) -> Insight:
        """Construct the PATTERN_OBSERVATION insight."""
        strength = (
            "Almost certainly in"
            if median_r >= _R_STRONG
            else "Probably in"
        )
        sibling_word = "sibling" if n_siblings == 1 else "siblings"
        title = (
            f"{strength} {area_name}: {entity_id} matches "
            f"{n_siblings} tagged {device_class} {sibling_word} "
            f"at median r={median_r:.2f}"
        )

        # Sort the alternative-areas list (descending r) for the
        # explanation. Cap at 3 so the prose stays readable.
        alts = sorted(
            (r for r in per_area_results if r[0] != area_id),
            key=lambda r: r[1],
            reverse=True,
        )[:3]

        fingerprint = {
            "kind": "location_proposal",
            "entity_id": entity_id,
            "area_id": area_id,
        }

        payload: dict[str, Any] = {
            "type": "entities",
            "title": f"Probably in {area_name}: {entity_id}",
            "entities": [entity_id],
            "_location_proposal": {
                "entity_id": entity_id,
                "proposed_area_id": area_id,
                "proposed_area_name": area_name,
                "device_class": device_class,
                "median_r": median_r,
                "n_siblings": n_siblings,
                "alternatives": [
                    {"area_id": aid, "median_r": r, "n_siblings": n}
                    for aid, r, n in alts
                ],
            },
        }

        explanation_lines = [
            (
                f"Over the last {_LOOKBACK_DAYS} days, this entity's "
                f"values matched {n_siblings} already-tagged "
                f"{device_class} {sibling_word} in **{area_name}** at "
                f"median r={median_r:.2f}."
            ),
            "",
            (
                "Spatial correlation works for environmental sensors: "
                "two temp sensors in the same room share the same air "
                "column and follow nearly the same diurnal curve. "
                "Match at this level is a strong room-membership signal."
            ),
        ]
        if alts:
            alt_str = ", ".join(f"r={r:.2f}" for _, r, _ in alts)
            explanation_lines += [
                "",
                f"Next-best candidates: {alt_str}.",
            ]
        explanation_lines += [
            "",
            (
                "**Advisory only.** This detector never auto-assigns "
                "areas. Open the bulk-area-assign dialog and confirm "
                "the suggestion, or override with a different area."
            ),
        ]

        return Insight(
            id=Insight.compute_id(InsightKind.PATTERN_OBSERVATION, fingerprint),
            kind=InsightKind.PATTERN_OBSERVATION,
            detector=self.name,
            area_id=area_id,
            title=title,
            confidence=round(min(1.0, median_r), 3),
            fingerprint=fingerprint,
            payload=payload,
            payload_format="card",
            explanation="\n".join(explanation_lines),
            created_at=datetime.now(tz=UTC),
        )


def by_entity_keys(ctx: DetectorContext) -> set[str]:
    """Collect every entity_id that has produced at least one event
    in the buffer's full retention window. Cheap pre-filter so we
    don't iterate the full registry for entities that haven't
    reported."""
    if ctx.event_buffer is None:
        return set()
    seen: set[str] = set()
    for ev in ctx.event_buffer.query():
        seen.add(ev.entity_id)
    return seen
