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

    Currently emitted by built-in detectors:
        AUTOMATION_PROPOSAL — ScheduleDetector, CooccurrenceDetector,
                              LongTailDetector, StreakDetector
        ANOMALY             — OrphanDeviceDetector

    Reserved for future detector kinds (no built-in detector emits these yet,
    but the value is part of the stable schema for community detectors and
    future built-ins):
        CARD_PROPOSAL, GROUP_PROPOSAL, DASHBOARD_CLEANUP, SCENE_PROPOSAL
    """

    AUTOMATION_PROPOSAL = "automation_proposal"
    CARD_PROPOSAL = "card_proposal"
    GROUP_PROPOSAL = "group_proposal"
    ANOMALY = "anomaly"
    DASHBOARD_CLEANUP = "dashboard_cleanup"
    SCENE_PROPOSAL = "scene_proposal"
    # v1.1: findings about EXISTING automations rather than proposals for
    # new ones. Trigger drift, dead actions, stale conditions — code-only
    # "automation linter" output. payload_format="report" or "automation"
    # depending on whether we just describe the issue or propose a fix.
    AUTOMATION_IMPROVEMENT = "automation_improvement"


# "report" — informational finding, payload describes the issue but isn't
# directly applicable. Used by the automation linter (trigger drift, etc).
_VALID_PAYLOAD_FORMATS = frozenset({"blueprint", "automation", "card", "group", "scene", "report"})


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
    # v0.8: applied state surfaced on the insight so cards can show
    # "applied <when>" + an Undo button without a separate lookup.
    applied_at: datetime | None = None
    applied_artifact_id: str | None = None
    undo_window_expires_at: datetime | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0.0, 1.0]; got {self.confidence}")
        if self.payload_format not in _VALID_PAYLOAD_FORMATS:
            raise ValueError(
                f"payload_format must be one of {sorted(_VALID_PAYLOAD_FORMATS)}; "
                f"got {self.payload_format!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict for WS / storage round-trip."""
        return {
            "id": self.id,
            "kind": self.kind.value,
            "detector": self.detector,
            "area_id": self.area_id,
            "title": self.title,
            "confidence": self.confidence,
            "fingerprint": self.fingerprint,
            "payload": self.payload,
            "payload_format": self.payload_format,
            "created_at": self.created_at.isoformat(),
            "snoozed_until": (
                self.snoozed_until.isoformat() if self.snoozed_until else None
            ),
            "explanation": self.explanation,
            "conflicts_with": list(self.conflicts_with),
            "applied_at": (
                self.applied_at.isoformat() if self.applied_at else None
            ),
            "applied_artifact_id": self.applied_artifact_id,
            "undo_window_expires_at": (
                self.undo_window_expires_at.isoformat()
                if self.undo_window_expires_at
                else None
            ),
        }

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
