"""Display-time insight de-duplication (pure logic, no HA imports).

Extracted from ws_api so it's testable without the HA stack. The
ws_api side is now a thin wrapper that walks the entity_registry
to build `device_id_by_entity`, then calls into `display_time_dedup`.

Algorithm
---------
1. Bucket enriched insights by signature: (kind, detector,
   normalized_title, domain). The domain key prevents mixed-domain
   buckets — a previous regression had 35 binary_sensors + 11
   switches with the same normalized title falling into one
   bucket that couldn't form a cohort label.

2. For each bucket with 2+ rows:
   a. Collect every entity_id mentioned across the bucket.
   b. Compute a `cohort_label`: shared-device → longest common
      entity-id prefix; else same-domain `domain.* (cohort)`.
   c. Pick the highest-confidence row as the representative;
      annotate with `(+N similar entities: <label>)` suffix and
      `cohort_members` / `cohort_label` payload.
3. Singletons + label-less groups pass through unchanged.

Idempotent — re-running on the output produces the same output
(suffix is detected and not re-applied).
"""
from __future__ import annotations

import re as _re
from collections import defaultdict
from typing import Any, Mapping


def normalize_title_for_dedup(
    title: str, eids: list[str]
) -> str:
    """Strip per-entity tokens from a title so two insights that
    differ only in their entity name produce the same signature.

    `binary_sensor.home_nvr_x hasn't reported in 8d. …`
      → `<E> hasn't reported in 8d. …`

    Numeric tokens (durations, counts) are preserved because they
    ARE the signal — two entities silent for different durations
    shouldn't merge.
    """
    out = title
    for eid in eids:
        out = out.replace(eid, "<E>")
    # Strip any leftover bare entity_id-like tokens (matches domain.name)
    out = _re.sub(r"\b[a-z_]+\.[A-Za-z0-9_]+\b", "<E>", out)
    return out


def display_time_dedup(
    enriched: list[dict[str, Any]],
    device_id_by_entity: Mapping[str, str | None],
) -> list[dict[str, Any]]:
    """Bucket-and-collapse the enriched insight list.

    `device_id_by_entity` — caller-built dict from HA's entity
    registry. Empty dict is fine; the same-domain fallback path
    handles it.

    Returns a new list. Does NOT mutate the inputs (representatives
    are deep-copied before modification).
    """
    if not enriched:
        return list(enriched)

    buckets: dict[tuple[str, str, str, str], list[dict[str, Any]]] = (
        defaultdict(list)
    )
    for d in enriched:
        eids = d.get("_eids_for_dedup") or []
        sig = (
            d.get("kind") or "",
            d.get("detector") or "",
            normalize_title_for_dedup(d.get("title") or "", eids),
            d.get("domain") or "",
        )
        buckets[sig].append(d)

    result: list[dict[str, Any]] = []
    for bucket in buckets.values():
        if len(bucket) < 2:
            for d in bucket:
                # Strip internal helper field on the way out.
                d.pop("_eids_for_dedup", None)
                result.append(d)
            continue
        # Collect every entity_id mentioned across the bucket.
        all_eids: list[str] = []
        for d in bucket:
            all_eids.extend(d.get("_eids_for_dedup") or [])
        all_eids = sorted(set(all_eids))
        if len(all_eids) < 2:
            for d in bucket:
                d.pop("_eids_for_dedup", None)
                result.append(d)
            continue
        cohort_label = resolve_cohort_label(all_eids, device_id_by_entity)
        if cohort_label is None:
            for d in bucket:
                d.pop("_eids_for_dedup", None)
                result.append(d)
            continue
        rep = max(bucket, key=lambda d: float(d.get("confidence") or 0))
        rep = dict(rep)  # shallow copy to avoid mutating the source dict
        rep.pop("_eids_for_dedup", None)
        others = len(bucket) - 1
        # Idempotent: if a previous pass (scan-time merge or earlier
        # display-time call) already added the suffix, don't append
        # again on re-runs.
        title = rep.get("title") or ""
        if "similar entities" not in title:
            rep["title"] = (
                f"{title} (+{others} similar entities: {cohort_label})"
            )
        rep["cohort_members"] = all_eids
        rep["cohort_label"] = cohort_label
        result.append(rep)
    return result


def resolve_cohort_label(
    entity_ids: list[str],
    device_id_by_entity: Mapping[str, str | None],
) -> str | None:
    """Friendly label for a cohort: shared-device prefix → entity-id
    longest common prefix; else same-domain `domain.* (cohort)`."""
    # Shared device → longest common entity-id prefix.
    device_ids = {device_id_by_entity.get(e) for e in entity_ids}
    device_ids.discard(None)
    if len(device_ids) == 1:
        prefix = longest_common_entity_prefix(entity_ids)
        if prefix:
            return prefix
    # Same-domain fallback. Works even when device_id_by_entity is
    # empty (e.g. entities not in the registry).
    domains = {e.split(".", 1)[0] for e in entity_ids if "." in e}
    if len(domains) == 1:
        return f"{next(iter(domains))}.* (cohort)"
    return None


def longest_common_entity_prefix(entity_ids: list[str]) -> str | None:
    """Return `domain.prefix_*` when all entity_ids share a domain
    AND a name prefix of >= 4 chars. Returns None otherwise."""
    if len(entity_ids) < 2:
        return None
    domains = {e.split(".", 1)[0] for e in entity_ids if "." in e}
    if len(domains) != 1:
        return None
    domain = next(iter(domains))
    names = [e.split(".", 1)[1] for e in entity_ids if "." in e]
    if not names:
        return None
    prefix = names[0]
    for n in names[1:]:
        while prefix and not n.startswith(prefix):
            prefix = prefix[:-1]
        if not prefix:
            return None
    prefix = prefix.rstrip("_")
    if len(prefix) < 4:
        return None
    return f"{domain}.{prefix}_*"
