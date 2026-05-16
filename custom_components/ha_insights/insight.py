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
    # v1.3: observational findings that aren't directly actionable. Used
    # by detectors that describe a pattern the user might want to know
    # about but where the "what to do" is left to the user's judgement
    # (presence inference, sleep/wake windows, weekday habit deltas,
    # data-quality tier reports). payload_format is typically "report".
    PATTERN_OBSERVATION = "pattern_observation"


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
    # v1.4: optional vendor tag — None for built-in detectors,
    # "Schlage" / "Tesla" / "Aqara" / etc for manufacturer-provided
    # detectors loaded via the future vendor-detectors path. Cards
    # can group / badge insights by vendor and the directory page can
    # surface "this is from your Sonos vendor module" affordances.
    # Free-form string; the manifest validator on vendor module load
    # will pin it to a known set.
    vendor: str | None = None
    # v1.4: which HA user this insight is about, when the detector
    # can identify them. Set by detectors that derive per-user signals
    # (phone charge habits, presence inference, alarm wake times,
    # commute patterns). None = household-level / unattributable.
    # The mobile notifier routes pushes to ONLY this user's
    # `notify.mobile_app_*` service when set — otherwise broadcasts
    # to every configured target. Multi-user HA installs need this so
    # "your phone is about to die" reaches the phone's actual owner.
    target_user_id: str | None = None
    # v1.4: timestamp the insight was dismissed by the user, if any.
    # The store has had a `dismissed_at` column since v1 but the
    # Insight dataclass never exposed it — readers had to query the
    # store directly. Adaptive notification tuner needs this on the
    # dataclass so it can compute dismiss-rate without an extra
    # round-trip. None for active / applied insights.
    dismissed_at: datetime | None = None
    # v1.5.46: lifecycle status alongside Dismiss / Snooze.
    # Retired = the user has consciously decided NOT to automate
    # this pattern even though the detector keeps seeing it. Different
    # semantics from Dismiss (one-off "not relevant") — a Retire
    # decision should persist across re-detections of the same
    # fingerprint until the user explicitly un-retires.
    #
    # The card surfaces a "Retire" action alongside "Snooze" on
    # insights the user has reviewed multiple times. List endpoints
    # filter retired rows out by default; an explicit `include_retired`
    # flag surfaces them for the history / management view.
    retired_at: datetime | None = None
    # How confident the detector is that `target_user_id` is the
    # right owner of this pattern. Independent of the pattern's own
    # `confidence` field (which measures signal strength). Examples:
    #   1.0 — registry-grade attribution (HA user_id from mobile_app
    #         config entry; the phone IS that user's phone)
    #   0.8 — strong inference (only one human typically active at
    #         this time of day, single mobile_app installed)
    #   0.5 — weak inference (pattern overlaps multiple users)
    #   None — household / unattributable. Always paired with
    #          target_user_id = None.
    # The notifier uses this to decide whether to route to the user's
    # phone exclusively (high confidence) or broadcast as a
    # household nudge (low confidence). The card surfaces it so the
    # user can tell "your pattern (95%)" vs "someone in your
    # household".
    target_user_id_confidence: float | None = None

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
            "vendor": self.vendor,
            "target_user_id": self.target_user_id,
            "target_user_id_confidence": self.target_user_id_confidence,
            "dismissed_at": (
                self.dismissed_at.isoformat() if self.dismissed_at else None
            ),
            "retired_at": (
                self.retired_at.isoformat() if self.retired_at else None
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
