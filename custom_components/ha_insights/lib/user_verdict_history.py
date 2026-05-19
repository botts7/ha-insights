"""Pure abstraction over the apply/dismiss/retire/snooze verdict timeline.

v1.14.3a (May 2026). Foundation lib for [[ha_insights_v2_presence_and_adaptive]]:

  - v1.14.3 ``AdaptiveFeedbackDetector`` — re-suggest patterns the user
    previously dismissed when the *environmental* context changes
    (e.g. they deleted the automation they were already using, or
    added a sensor that changes our analysis).
  - v2.0 per-person presence — needs verdict history per pattern so
    each resident's apply-rate can be tracked.

## What today's store does

`InsightStore` tracks the **current** verdict state on each insight:
``dismissed_at``, ``retired_at``, ``applied_at``, ``snoozed_until``.
Each verdict OVERWRITES its predecessor — you can't ask "was this
dismissed 3 months ago, re-suggested, then applied last week?"

## What this lib adds

The TIMELINE — every verdict transition for every insight,
plus an **environmental fingerprint** captured at the moment of
each verdict so AdaptiveFeedback can detect:

  - User dismissed "lights on no motion" → later deleted the
    competing automation → fingerprint diff says "automation
    `foo` no longer present" → re-suggest the pattern.
  - User retired "weekday morning routine" 4 months ago. Today
    they added a motion sensor in the bedroom. The fingerprint
    diff says "new sensor in `bedroom`" → re-suggest with
    higher detail.

## Architecture

This module is **pure**: no HA imports, no DB imports. It defines:

  1. The data model (``VerdictKind``, ``EnvironmentalFingerprint``,
     ``Verdict``, ``VerdictHistory``).
  2. Comparison primitives (``diff_fingerprints``).
  3. The AdaptiveFeedback decision (``should_re_suggest``).
  4. Detector-quality stats (``apply_rate``, ``dismiss_rate``).

v1.14.3b will add the persistence layer (SQLite migration + WS hooks
that capture fingerprints at verdict time + AdaptiveFeedbackDetector
that consumes histories).

## Why pure-function

Same rationale as `lib/changepoint_detection.py`, `lib/transfer_entropy.py`,
`lib/coupling_strength.py`: the algorithmic core has nothing to do
with HA primitives, is easy to test, easy to reason about, and is
upstream-PR friendly if the patterns are ever donated to HA core.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum


class VerdictKind(StrEnum):
    """The set of verdict transitions InsightStore already fires.

    Matches the store-listener event names so callers can pass them
    through unchanged. ``CLEAR_APPLIED`` covers the "undo apply" path
    where the user reverted an automation within the undo window.
    """

    APPLY = "applied"
    DISMISS = "dismissed"
    RETIRE = "retired"
    UNRETIRE = "unretired"
    SNOOZE = "snoozed"
    UNDO = "undone"
    CLEAR_APPLIED = "clear_applied"


# How long after a re-suggest before we'll re-suggest the SAME pattern
# again. Prevents AdaptiveFeedback from spamming the same dismissed
# insight every scan when the environmental fingerprint keeps drifting.
_RE_SUGGEST_COOLDOWN = timedelta(days=30)

# Verdicts that count as "user said no" for AdaptiveFeedback purposes.
# DISMISS = "not now"; RETIRE = "permanently no". Both should be
# eligible for re-suggest when the environment changes — the latter
# at a higher confidence bar (handled in `should_re_suggest`).
_NEGATIVE_VERDICTS = frozenset({VerdictKind.DISMISS, VerdictKind.RETIRE})


@dataclass(frozen=True)
class EnvironmentalFingerprint:
    """Compact snapshot of HA state relevant to "did the situation
    that informed this verdict change?".

    Designed to be small (<200 bytes after JSON serialization) so
    storing one per verdict is cheap even for users with 10k+
    insights over years of use.

    Fields:
      automation_ids: frozenset of automation entity_ids currently
        enabled. AdaptiveFeedback cares because users often dismiss
        an insight ("I already have a routine for that") and then
        later delete the routine — at which point the original
        pattern is worth re-surfacing.

      sensors_per_area: per-area count of device_class categories.
        Maps area_id to a {device_class: count} dict. When a new
        sensor appears in an area, AdaptiveFeedback can re-suggest
        patterns it previously suppressed for lacking-data reasons.

      active_integrations: frozenset of integration names currently
        loaded. A user adding "google_calendar" might change whether
        a schedule-related dismissed insight is worth re-suggesting.
    """

    automation_ids: frozenset[str] = field(default_factory=frozenset)
    sensors_per_area: dict[str, dict[str, int]] = field(default_factory=dict)
    active_integrations: frozenset[str] = field(default_factory=frozenset)

    def __hash__(self) -> int:
        # Required because dict fields make the default unhashable.
        # Hash on the bits that are most likely to differ.
        sensors_repr = tuple(
            (aid, tuple(sorted(classes.items())))
            for aid, classes in sorted(self.sensors_per_area.items())
        )
        return hash(
            (self.automation_ids, sensors_repr, self.active_integrations)
        )


@dataclass(frozen=True)
class FingerprintDelta:
    """What changed between two ``EnvironmentalFingerprint``s.

    All fields are derived; the dataclass exists so callers can pattern-
    match on "what kind of change happened?" without re-deriving.
    """

    automations_added: frozenset[str] = field(default_factory=frozenset)
    automations_removed: frozenset[str] = field(default_factory=frozenset)
    # Per-area changes: area_id → {device_class: count_delta}
    sensors_added_per_area: dict[str, dict[str, int]] = field(default_factory=dict)
    sensors_removed_per_area: dict[str, dict[str, int]] = field(default_factory=dict)
    integrations_added: frozenset[str] = field(default_factory=frozenset)
    integrations_removed: frozenset[str] = field(default_factory=frozenset)

    @property
    def is_empty(self) -> bool:
        """True when nothing changed between the two fingerprints."""
        return not (
            self.automations_added
            or self.automations_removed
            or self.sensors_added_per_area
            or self.sensors_removed_per_area
            or self.integrations_added
            or self.integrations_removed
        )

    @property
    def is_substantial(self) -> bool:
        """True when the delta is large enough to justify re-suggesting.

        Heuristic: ANY automation change, OR any new sensor anywhere,
        OR a new integration. Removed sensors don't count (the user
        actively reduced their data) and removed integrations are
        usually transient (user troubleshooting).

        The AdaptiveFeedback detector applies this filter before
        considering whether to re-suggest a previously-dismissed
        insight.
        """
        if self.automations_added or self.automations_removed:
            return True
        if self.sensors_added_per_area:
            return True
        if self.integrations_added:
            return True
        return False


@dataclass(frozen=True)
class Verdict:
    """One user-decision event on one insight.

    Fields:
      insight_id: the stable hash from ``Insight.compute_id``.
      kind: which transition.
      timestamp: when the user did it (UTC).
      fingerprint: HA state at the moment of the verdict.
      user_id_hash: opaque hash of the HA user who acted. Used by
        v2.0 per-person attribution; v1.14.3 ignores it. None when
        the verdict came from a non-user source (automation-driven
        snooze, undo-window expiry, etc.).
    """

    insight_id: str
    kind: VerdictKind
    timestamp: datetime
    fingerprint: EnvironmentalFingerprint
    user_id_hash: str | None = None


@dataclass(frozen=True)
class VerdictHistory:
    """The full timeline of verdicts for one insight.

    Wrapper around a list of ``Verdict`` instances sorted by
    timestamp ascending. The wrapper exists to give the consumers
    a stable API (``.latest()``, ``.verdicts_of_kind()``,
    ``.most_recent_re_suggest()``) without exposing list-mutation.
    """

    insight_id: str
    verdicts: tuple[Verdict, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        # Verify sort order. Cheap O(n) check; callers expect ascending.
        for i in range(1, len(self.verdicts)):
            if self.verdicts[i].timestamp < self.verdicts[i - 1].timestamp:
                raise ValueError(
                    "VerdictHistory verdicts must be timestamp-ascending"
                )

    def latest(self) -> Verdict | None:
        return self.verdicts[-1] if self.verdicts else None

    def latest_of_kind(self, kind: VerdictKind) -> Verdict | None:
        """Return the most recent verdict matching `kind`, or None."""
        for v in reversed(self.verdicts):
            if v.kind == kind:
                return v
        return None

    def latest_negative(self) -> Verdict | None:
        """Most recent DISMISS or RETIRE. Returns None if neither exists."""
        for v in reversed(self.verdicts):
            if v.kind in _NEGATIVE_VERDICTS:
                return v
        return None


# ---------- Pure-function operations --------------------------------


def diff_fingerprints(
    old: EnvironmentalFingerprint,
    new: EnvironmentalFingerprint,
) -> FingerprintDelta:
    """Compute (old → new) delta. Pure function."""
    automations_added = new.automation_ids - old.automation_ids
    automations_removed = old.automation_ids - new.automation_ids
    integrations_added = new.active_integrations - old.active_integrations
    integrations_removed = (
        old.active_integrations - new.active_integrations
    )

    sensors_added_per_area: dict[str, dict[str, int]] = {}
    sensors_removed_per_area: dict[str, dict[str, int]] = {}
    all_area_ids = set(old.sensors_per_area) | set(new.sensors_per_area)
    for aid in all_area_ids:
        old_classes = old.sensors_per_area.get(aid, {})
        new_classes = new.sensors_per_area.get(aid, {})
        all_classes = set(old_classes) | set(new_classes)
        for dc in all_classes:
            delta = new_classes.get(dc, 0) - old_classes.get(dc, 0)
            if delta > 0:
                sensors_added_per_area.setdefault(aid, {})[dc] = delta
            elif delta < 0:
                sensors_removed_per_area.setdefault(aid, {})[dc] = -delta

    return FingerprintDelta(
        automations_added=frozenset(automations_added),
        automations_removed=frozenset(automations_removed),
        sensors_added_per_area=sensors_added_per_area,
        sensors_removed_per_area=sensors_removed_per_area,
        integrations_added=frozenset(integrations_added),
        integrations_removed=frozenset(integrations_removed),
    )


def should_re_suggest(
    history: VerdictHistory,
    current_fingerprint: EnvironmentalFingerprint,
    *,
    now: datetime,
    cooldown: timedelta = _RE_SUGGEST_COOLDOWN,
) -> bool:
    """Should AdaptiveFeedback re-surface the dismissed/retired insight?

    Decision rules:

      1. There must be a negative verdict (DISMISS or RETIRE) in the
         history. If the user never said no, there's nothing to
         re-surface — the regular detector pipeline handles it.

      2. The most recent verdict must STILL be negative. If the user
         dismissed, then we re-suggested, then they applied — they
         already engaged. Don't pester.

      3. The environmental fingerprint must have changed in a
         **substantial** way since the negative verdict
         (``FingerprintDelta.is_substantial``).

      4. Cooldown — at least ``cooldown`` since the most recent
         APPLY/DISMISS/RETIRE/UNRETIRE verdict. Prevents thrashing
         when fingerprints drift continuously (a user installing
         devices over a week shouldn't get re-suggested 5x).

      5. RETIRE bar is higher than DISMISS. ``RETIRE`` means
         "permanent no" — only re-suggest on **automation_removed**
         deltas (the user took explicit action that suggests their
         original reasoning may have shifted). Other substantial
         deltas don't override a RETIRE.

    Returns True iff all conditions pass. Pure function.
    """
    if not history.verdicts:
        return False

    last = history.verdicts[-1]
    if last.kind not in _NEGATIVE_VERDICTS:
        # User's most recent action was positive (applied) or
        # neutral (snoozed); not our place to override.
        return False

    if now - last.timestamp < cooldown:
        return False

    delta = diff_fingerprints(last.fingerprint, current_fingerprint)
    if not delta.is_substantial:
        return False

    if last.kind == VerdictKind.RETIRE:
        # Higher bar: only automation-removal can override a retire.
        # New sensors / new integrations alone aren't enough; the
        # user said "permanent no" and we need a strong reason.
        return bool(delta.automations_removed)

    return True


def apply_rate(verdicts: tuple[Verdict, ...]) -> float:
    """Fraction of (APPLY+DISMISS+RETIRE) verdicts that were APPLY.

    Snoozes, undos, and clear-applied are ignored — they're transient
    states. The detector-quality penalty system uses this rate to
    demote detectors whose suggestions users consistently reject.

    Returns 0.0 on empty input (no opinion yet) — callers that want
    to treat "no data" differently from "rejected" should check
    `len(verdicts)` directly.
    """
    if not verdicts:
        return 0.0
    decisive = [
        v
        for v in verdicts
        if v.kind in (VerdictKind.APPLY, VerdictKind.DISMISS, VerdictKind.RETIRE)
    ]
    if not decisive:
        return 0.0
    applies = sum(1 for v in decisive if v.kind == VerdictKind.APPLY)
    return applies / len(decisive)


def dismiss_rate(verdicts: tuple[Verdict, ...]) -> float:
    """Fraction of decisive verdicts that were DISMISS.

    Like ``apply_rate`` but inverted. RETIREs are excluded from this
    measure: a user who retires an insight has made a *permanent*
    decision, not a "not now" dismissal; conflating the two would
    inflate dismiss_rate beyond what the detector should be
    penalized for. Returns 0.0 on empty input.
    """
    if not verdicts:
        return 0.0
    decisive = [
        v
        for v in verdicts
        if v.kind in (VerdictKind.APPLY, VerdictKind.DISMISS)
    ]
    if not decisive:
        return 0.0
    dismisses = sum(1 for v in decisive if v.kind == VerdictKind.DISMISS)
    return dismisses / len(decisive)


__all__ = [
    "EnvironmentalFingerprint",
    "FingerprintDelta",
    "Verdict",
    "VerdictHistory",
    "VerdictKind",
    "apply_rate",
    "diff_fingerprints",
    "dismiss_rate",
    "should_re_suggest",
]
