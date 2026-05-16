"""Candidate-entity discovery for LLM Refine.

When a user asks the Refine LLM *"are there other lights I should add?"*,
the LLM can only suggest entities it knows about. Pre-v1.5.44, the prompt
listed ONLY the entities already in the automation, so the LLM had no
options — additions were impossible.

This module assembles a **bag of candidate entities** the LLM may add,
each tagged with the reason it's a candidate. Four signals:

- **Area-mate**: same `area_id` as any existing target. Strong signal —
  "you have a motion + light in the kitchen; the kitchen also has a
  ceiling fan and a sink-area sensor."
- **Device-mate**: same device as an existing target (e.g. RGB strip
  with sub-entities, multi-channel switch). Strong signal — the device
  ships them as a cluster.
- **Domain-sibling**: same `domain.*` as existing targets, anywhere on
  the install. Weaker signal — "you have 14 lights total." Capped
  tightly to prevent prompt bloat.
- **Coactivator**: entity that fired within ±5 s of the existing
  trigger across multiple days in the 14-day buffer. Cheapest signal
  to assemble (reuses the cooccurrence detector's existing logic) and
  often the most useful — "every time the front door opens, the
  porch light AND the hallway light fire together; maybe automate
  both."

Privacy contract:
- Honors the per-entity blocklist (`blocked_entity_ids` set) — blocked
  entities never appear in candidates.
- Candidates flow through the same pseudonymization redactor as the
  required entity_list before reaching the LLM.

HA-core-adoptable: no HA imports. The caller pre-resolves hierarchy +
coactivation data and passes them in as plain dicts. Unit-testable.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class CandidateEntity:
    """A single suggested entity the LLM may add to the refined automation.

    `reasons` is a small list of human-readable strings that explain WHY
    this entity is a candidate. The LLM reads these to make sensible
    additions instead of hallucinating relationships. Always at least
    one reason; multiple when an entity scores on more than one signal
    (e.g. both area-mate AND coactivator).
    """

    entity_id: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class CandidateEntities:
    """Bag of candidate suggestions for an LLM refinement, grouped by signal.

    Each list is already deduplicated against `required_entity_ids` and
    against the blocklist. Ordering within each list is deterministic
    (sorted by entity_id) so successive Refine calls present the same
    options.
    """

    area_mates: list[CandidateEntity] = field(default_factory=list)
    device_mates: list[CandidateEntity] = field(default_factory=list)
    domain_siblings: list[CandidateEntity] = field(default_factory=list)
    coactivators: list[CandidateEntity] = field(default_factory=list)

    @property
    def total_count(self) -> int:
        return (
            len(self.area_mates)
            + len(self.device_mates)
            + len(self.domain_siblings)
            + len(self.coactivators)
        )

    @property
    def is_empty(self) -> bool:
        return self.total_count == 0

    def all_entity_ids(self) -> set[str]:
        """Every candidate entity_id across all categories — for entity-
        validation downstream (the LLM may emit any of these in addition
        to the required set)."""
        out: set[str] = set()
        for group in (
            self.area_mates,
            self.device_mates,
            self.domain_siblings,
            self.coactivators,
        ):
            for c in group:
                out.add(c.entity_id)
        return out

    def format_for_prompt(self) -> str:
        """Render as a tight block the LLM can read.

        Empty string when no candidates. The caller decides whether to
        include the "Candidates" header — keeps the block elidable when
        the LLM has nothing to draw from.

        Format per line:
            light.kitchen_under_cabinet  (same area as light.kitchen_main)
        """
        if self.is_empty:
            return ""
        lines: list[str] = []
        for label, group in (
            ("area-mate", self.area_mates),
            ("device-mate", self.device_mates),
            ("domain-sibling", self.domain_siblings),
            ("coactivator", self.coactivators),
        ):
            for c in group:
                reasons_str = ", ".join(c.reasons)
                lines.append(f"  {c.entity_id}  ({reasons_str})")
        return "\n".join(lines)


# Caps prevent prompt-bloat. Domain-siblings is the noisiest signal —
# a house with 30 lights doesn't help the LLM by listing all 30. Keep
# tight; the other signals get a more generous budget because they
# carry more semantic weight.
_DEFAULT_CAPS = {
    "area_mates": 8,
    "device_mates": 8,
    "domain_siblings": 5,
    "coactivators": 8,
}


def build_candidate_entities(
    *,
    required_entity_ids: set[str],
    area_of: Mapping[str, str | None],
    device_of: Mapping[str, str | None],
    entities_in_area: Mapping[str, frozenset[str]],
    entities_on_device: Mapping[str, frozenset[str]],
    all_entity_ids: set[str] | None = None,
    coactivation_days: Mapping[str, int] | None = None,
    min_coactivation_days: int = 3,
    blocked_entity_ids: set[str] | None = None,
    caps: Mapping[str, int] | None = None,
) -> CandidateEntities:
    """Build candidate entities the LLM may add during refine.

    Args:
      required_entity_ids: entities the automation ALREADY targets. Never
        appear in candidates (they're required, not optional).
      area_of: full `entity_id → area_id` map (typically `Hierarchy.area_of`).
      device_of: full `entity_id → device_id` map (`Hierarchy.device_of`).
      entities_in_area: `area_id → frozenset[entity_id]` (`Hierarchy.entities_in_area`).
      entities_on_device: `device_id → frozenset[entity_id]`
        (`Hierarchy.entities_on_device`).
      all_entity_ids: optional full registry list used for domain-sibling
        matching. If None, domain-siblings are skipped (saves a pass).
      coactivation_days: optional `entity_id → days_co-fired_with_trigger`
        in the 14-day buffer. Built by the caller from the event buffer;
        skipped when None.
      min_coactivation_days: floor for the coactivation signal (default 3
        of 14 days). Below this, noise dominates.
      blocked_entity_ids: per-entity opt-out set. Members never appear
        in any candidate list, even pseudonymized.
      caps: optional override of per-category candidate count limits.

    Returns:
      CandidateEntities with at most `caps[category]` entries per group.
      All groups are deterministically sorted by entity_id.
    """
    blocked = blocked_entity_ids or set()
    use_caps = {**_DEFAULT_CAPS, **(caps or {})}

    # Reasons accumulate per-entity across signals — an entity may be
    # both an area-mate AND a coactivator, in which case both reasons
    # are surfaced under whichever category it lands in (area-mate wins
    # by priority order below).
    reasons_by_entity: dict[str, list[str]] = defaultdict(list)

    def _add_reason(eid: str, reason: str) -> None:
        if reason not in reasons_by_entity[eid]:
            reasons_by_entity[eid].append(reason)

    # --- 1. Area-mates -----------------------------------------------------
    # For each required entity's area, list other entities in that area.
    area_mate_eids: set[str] = set()
    for req_eid in required_entity_ids:
        area_id = area_of.get(req_eid)
        if not area_id:
            continue
        mates = entities_in_area.get(area_id, frozenset())
        for eid in mates:
            if eid in required_entity_ids or eid in blocked:
                continue
            area_mate_eids.add(eid)
            _add_reason(eid, f"same area as {req_eid}")

    # --- 2. Device-mates ---------------------------------------------------
    device_mate_eids: set[str] = set()
    for req_eid in required_entity_ids:
        device_id = device_of.get(req_eid)
        if not device_id:
            continue
        mates = entities_on_device.get(device_id, frozenset())
        for eid in mates:
            if eid in required_entity_ids or eid in blocked:
                continue
            # An entity that's BOTH a device-mate and an area-mate is
            # categorized as a device-mate (stronger signal: the device
            # itself ships them as a cluster). Move it out of the
            # area-mate bucket.
            area_mate_eids.discard(eid)
            device_mate_eids.add(eid)
            _add_reason(eid, f"same device as {req_eid}")

    # --- 3. Coactivators ---------------------------------------------------
    coactivator_eids: set[str] = set()
    if coactivation_days:
        for eid, days in coactivation_days.items():
            if eid in required_entity_ids or eid in blocked:
                continue
            if days < min_coactivation_days:
                continue
            # Coactivators outrank area-mates and device-mates — observed
            # behavior is a stronger signal than topology. If an entity
            # is both an area-mate AND a coactivator, it goes in the
            # coactivator bucket so the LLM sees the "actually fires
            # together" reason first.
            area_mate_eids.discard(eid)
            device_mate_eids.discard(eid)
            coactivator_eids.add(eid)
            _add_reason(
                eid, f"fired within ±5 s of trigger on {days} of 14 days"
            )

    # --- 4. Domain-siblings ------------------------------------------------
    # Cheapest signal, capped tightest. We only suggest entities that
    # share a domain with at least one required entity AND don't already
    # appear in a stronger bucket.
    domain_sibling_eids: set[str] = set()
    if all_entity_ids is not None:
        required_domains = {
            eid.split(".", 1)[0] for eid in required_entity_ids if "." in eid
        }
        consumed = (
            required_entity_ids
            | area_mate_eids
            | device_mate_eids
            | coactivator_eids
            | blocked
        )
        for eid in all_entity_ids:
            if eid in consumed:
                continue
            if "." not in eid:
                continue
            dom = eid.split(".", 1)[0]
            if dom not in required_domains:
                continue
            domain_sibling_eids.add(eid)
            _add_reason(eid, f"same domain ({dom}.*) as automation targets")

    # Domain-affinity: which domains are the automation's existing
    # targets in? Candidates whose domain ISN'T in this set are
    # cross-domain — they may still be relevant (motion → light AND
    # speaker for arrival ambience), but the LLM should treat them as
    # weaker suggestions. We surface this with both a sort-priority
    # (same-domain first within each category) and an explicit reason
    # tag the LLM can read.
    required_domains = {
        eid.split(".", 1)[0] for eid in required_entity_ids if "." in eid
    }

    def _domain_of(eid: str) -> str:
        return eid.split(".", 1)[0] if "." in eid else ""

    def _is_cross_domain(eid: str) -> bool:
        return _domain_of(eid) not in required_domains

    # Tag cross-domain candidates so the LLM sees the mismatch upfront.
    # Same-domain candidates don't get a tag — silence is the default.
    for bucket in (area_mate_eids, device_mate_eids, coactivator_eids):
        for eid in bucket:
            if _is_cross_domain(eid):
                _add_reason(eid, f"different domain ({_domain_of(eid)}.*)")

    # Materialize the final lists with caps + deterministic ordering.
    # Sort key: (cross_domain_flag, entity_id) — same-domain entries
    # sort to the front, ties broken by alphabetic. This means when the
    # cap clips the list, cross-domain candidates are the first to drop.
    def _materialize(eids: set[str], cap: int) -> list[CandidateEntity]:
        sorted_eids = sorted(eids, key=lambda e: (_is_cross_domain(e), e))[:cap]
        return [
            CandidateEntity(
                entity_id=eid,
                reasons=tuple(reasons_by_entity.get(eid, [])),
            )
            for eid in sorted_eids
        ]

    return CandidateEntities(
        area_mates=_materialize(area_mate_eids, use_caps["area_mates"]),
        device_mates=_materialize(device_mate_eids, use_caps["device_mates"]),
        domain_siblings=_materialize(
            domain_sibling_eids, use_caps["domain_siblings"]
        ),
        coactivators=_materialize(coactivator_eids, use_caps["coactivators"]),
    )


__all__ = [
    "CandidateEntity",
    "CandidateEntities",
    "build_candidate_entities",
]
