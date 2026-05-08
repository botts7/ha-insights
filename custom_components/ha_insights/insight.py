"""Insight contract — load-bearing community-facing data type.

Every detector returns Insight objects. Schema is semver-stable from v0.1.
See docs/ARCHITECTURE.md section 'Load-bearing contracts'.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class InsightKind(StrEnum):
    """Discrete kinds of insight a detector can emit.

    New kinds may be added across versions; existing kinds never change semantics.
    """

    AUTOMATION_PROPOSAL = "automation_proposal"   # v0.1 — ScheduleDetector hero
    CARD_PROPOSAL = "card_proposal"               # v0.2
    GROUP_PROPOSAL = "group_proposal"             # v0.3
    ANOMALY = "anomaly"                           # v0.4
    DASHBOARD_CLEANUP = "dashboard_cleanup"       # v0.3
    SCENE_PROPOSAL = "scene_proposal"             # v0.3+


_VALID_PAYLOAD_FORMATS = frozenset({"blueprint", "automation", "card", "group", "scene"})


@dataclass(frozen=True)
class Insight:
    """Result of a detector scan.

    Validation runs at construction; once built, an Insight is immutable.
    Storage and WS round-trip via JSON-serializable payload + fingerprint dicts.
    """

    id: str
    kind: InsightKind
    detector: str
    area_id: str | None
    title: str
    confidence: float
    fingerprint: dict[str, Any]
    payload: dict[str, Any]
    payload_format: str
    created_at: datetime
    snoozed_until: datetime | None = None
    explanation: str | None = None
    conflicts_with: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0.0, 1.0]; got {self.confidence}")
        if self.payload_format not in _VALID_PAYLOAD_FORMATS:
            raise ValueError(
                f"payload_format must be one of {sorted(_VALID_PAYLOAD_FORMATS)}; "
                f"got {self.payload_format!r}"
            )

    @classmethod
    def compute_id(cls, kind: InsightKind, fingerprint: dict[str, Any]) -> str:
        """Stable id from (kind, fingerprint).

        Same (kind, fingerprint) always yields the same id, enabling dedup
        across re-scans. Fingerprint dicts are canonicalized via sort_keys.
        """
        canonical = json.dumps(
            {"kind": str(kind), "fingerprint": fingerprint},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.blake2b(canonical.encode("utf-8"), digest_size=12).hexdigest()
