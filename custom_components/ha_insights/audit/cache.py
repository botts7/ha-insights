"""Content-hash cache for LLM audit suggestions.

The cache key is `sha256(canonical_yaml + sorted_observation_kinds)`.
If the same automation comes back with the same set of findings,
we already know what the LLM said — return the cached suggestion
without burning more tokens.

Stored alongside the existing audit log so the user can see "this
suggestion is from a cached LLM response, no new bytes sent" in
the trust UI. Backed by a new column on `outbound_calls` would
be cleaner long-term, but for Phase C we cache in-process only
(per HA-restart) so we don't grow the schema again. Phase D
promotes this to SQLite when the background LLM lands.

Privacy: the cache key is a digest, not the raw YAML. The cached
value (`refined_payload`, `rationale`, `diff_summary`) is the
output, not the input.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any

# 30-day TTL. Same as the planned SQLite TTL — keeps semantics
# consistent when the cache promotes to durable storage.
_TTL_SEC = 30 * 24 * 3600

# Bound on the in-process cache size. The LRU eviction below
# clamps memory growth on installs with thousands of automations.
_MAX_ENTRIES = 500


@dataclass(frozen=True)
class CachedSuggestion:
    """One cache hit. All output, no input."""

    refined_yaml: dict[str, Any]
    rationale: str | None
    diff_summary: list[str]
    cached_at: float


@dataclass
class _CacheState:
    entries: dict[str, CachedSuggestion] = field(default_factory=dict)
    # Insertion-order list for LRU eviction. Cheap on small sizes.
    order: list[str] = field(default_factory=list)


_CACHE: _CacheState = _CacheState()


def compute_cache_key(
    automation_yaml: dict[str, Any],
    observation_kinds: list[str],
) -> str:
    """sha256 of the canonical YAML + sorted observation kinds.

    Order-insensitive on observation_kinds and dict keys so trivial
    re-ordering doesn't break cache hits.
    """
    canonical_yaml = json.dumps(automation_yaml, sort_keys=True, default=str)
    canonical_obs = ",".join(sorted(set(observation_kinds)))
    digest = hashlib.sha256(
        f"{canonical_yaml}|{canonical_obs}".encode("utf-8")
    ).hexdigest()
    return digest


def get(key: str) -> CachedSuggestion | None:
    """Return cached suggestion if fresh (< TTL), else None.

    Also returns None when expired — the entry is dropped lazily so
    callers don't have to manage eviction.
    """
    entry = _CACHE.entries.get(key)
    if entry is None:
        return None
    if time.time() - entry.cached_at > _TTL_SEC:
        # Expired; drop
        _CACHE.entries.pop(key, None)
        try:
            _CACHE.order.remove(key)
        except ValueError:
            pass
        return None
    return entry


def put(
    key: str,
    *,
    refined_yaml: dict[str, Any],
    rationale: str | None,
    diff_summary: list[str],
) -> None:
    """Store a new suggestion. LRU-evicts when over capacity."""
    _CACHE.entries[key] = CachedSuggestion(
        refined_yaml=refined_yaml,
        rationale=rationale,
        diff_summary=list(diff_summary),
        cached_at=time.time(),
    )
    if key in _CACHE.order:
        _CACHE.order.remove(key)
    _CACHE.order.append(key)
    while len(_CACHE.entries) > _MAX_ENTRIES:
        oldest = _CACHE.order.pop(0)
        _CACHE.entries.pop(oldest, None)


def clear() -> int:
    """Wipe the in-process cache. Used by tests + Purge button.
    Returns count of entries removed."""
    n = len(_CACHE.entries)
    _CACHE.entries.clear()
    _CACHE.order.clear()
    return n


def stats() -> dict[str, int]:
    """For the audit panel — surface cache fill + capacity."""
    return {
        "entries": len(_CACHE.entries),
        "max_entries": _MAX_ENTRIES,
        "ttl_seconds": _TTL_SEC,
    }
