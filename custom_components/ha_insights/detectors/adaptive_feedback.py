"""AdaptiveFeedbackDetector — re-surface dismissed patterns when context changes.

v1.14.6 (May 2026). The headline consumer of the v1.14.3a verdict-
history lib + v1.14.4 persistence + v1.14.5 capture pipeline.

## What it does

For every insight the user has previously dismissed or retired, this
detector compares the environmental fingerprint captured at the
moment of that verdict against the *current* fingerprint. If
[[user_verdict_history.should_re_suggest]] returns True, the
detector emits a fresh ``PATTERN_OBSERVATION`` insight nudging the
user to revisit the pattern. The most common trigger:

  - User dismissed "lights on no motion" because they already had
    ``automation.kitchen_lights_off``.
  - User later deleted that automation.
  - Fingerprint diff: ``automations_removed = {'automation.kitchen_lights_off'}``.
  - AdaptiveFeedback fires: "you dismissed this when X existed; X
    was removed — want to look again?"

Other triggers:

  - User dismissed because data was sparse → later added a motion
    sensor → re-suggest with stronger signal.
  - User retired but later removed the conflicting automation →
    higher bar, but does fire.

The detector NEVER duplicates the original insight — it emits a
distinct meta-insight that points at the original via
``original_insight_id`` in the payload. The original stays in its
dismissed/retired state; this is just a nudge.

## Cooldown

``should_re_suggest`` enforces a 30-day cooldown after each verdict.
Combined with the per-(insight,detector) fingerprint dedup, this
keeps AdaptiveFeedback from spamming the panel.

## Why a separate detector (vs hooking into ws_list)

Filter/sort/score logic for re-surfacing is non-trivial. Treating
it as a detector lets the user dismiss / retire / snooze the
re-surface itself, and the cohort-dedup / apply-rate machinery
just works.

## Skip rules

  - Original insight not in the store anymore → skip (cascading
    deletion or purge already cleaned up).
  - Insight currently in ``applied`` state → skip (user already
    engaged).
  - Insight currently snoozed AND snooze hasn't expired → skip
    (let the snooze run).
  - Original detector retired → skip (the rule that emitted it is
    gone; re-surfacing is moot).
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ..const import DOMAIN
from ..insight import Insight, InsightKind
from ..lib.environmental_fingerprint import (
    capture_environmental_fingerprint,
    dict_to_fingerprint,
)
from ..lib.user_verdict_history import (
    Verdict,
    VerdictHistory,
    VerdictKind,
    diff_fingerprints,
    should_re_suggest,
)
from .base import Detector, DetectorContext, Maturity, register_detector

if TYPE_CHECKING:
    from ..store import InsightStore

_LOGGER = logging.getLogger(__name__)

# Flat confidence — re-suggesting a previously-dismissed insight is
# a nudge, not a high-confidence anomaly. The user already said no
# once; we're noting that the situation changed. They get to weigh
# whether the change matters enough to revisit.
_CONFIDENCE = 0.70


@register_detector
class AdaptiveFeedbackDetector(Detector):
    """Emit a meta-insight per dismissed/retired insight that
    deserves a fresh look given environmental change."""

    name = "adaptive_feedback"
    kind = InsightKind.PATTERN_OBSERVATION
    requires_recorder = False
    # v1.14.6: EXPERIMENTAL. The 30-day cooldown + substantial-delta
    # gate should keep noise down, but real-install feedback will
    # tune the thresholds + the "substantial" definition itself.
    maturity = Maturity.EXPERIMENTAL
    description = (
        "Re-surface previously-dismissed insights when the environment "
        "changes — e.g. user deletes the automation they were using "
        "instead. Never re-emits the original; emits a fresh nudge "
        "the user can act on independently."
    )

    async def scan(self, ctx: DetectorContext) -> list[Insight]:
        store = _resolve_store(ctx)
        if store is None:
            return []

        try:
            histories_raw = await store.get_all_verdict_histories()
        except Exception:
            _LOGGER.debug(
                "AdaptiveFeedback failed to read verdict histories",
                exc_info=True,
            )
            return []

        if not histories_raw:
            return []

        current_fp = capture_environmental_fingerprint(ctx.hass)
        now = datetime.now(tz=UTC)
        insights: list[Insight] = []

        for insight_id, rows in histories_raw.items():
            history = _hydrate_history(insight_id, rows)
            if not history.verdicts:
                continue
            if not should_re_suggest(history, current_fp, now=now):
                continue

            # Fetch original insight for title + detector. Skip if
            # the original was purged / cascaded out.
            try:
                original = await store.get_insight(insight_id)
            except Exception:
                continue
            if original is None:
                continue
            if _should_skip_original(original, now):
                continue

            negative = history.latest_negative()
            if negative is None:
                continue
            delta = diff_fingerprints(negative.fingerprint, current_fp)

            insights.append(
                _build_insight(
                    original=original,
                    negative_verdict=negative,
                    delta=delta,
                    history=history,
                    now=now,
                )
            )

        if insights:
            _LOGGER.debug(
                "AdaptiveFeedbackDetector emitted %d re-surface insights",
                len(insights),
            )
        return insights


def _resolve_store(ctx: DetectorContext) -> InsightStore | None:
    """Walk hass.data[DOMAIN] for the first config entry's store.

    Same pattern as automation_audit.py. Multi-entry installs share
    one store per entry; for now we pick the first one we find. v2.0
    per-person presence can revisit (per-user-scoped stores).
    """
    try:
        for entry_data in ctx.hass.data.get(DOMAIN, {}).values():
            if isinstance(entry_data, dict) and "store" in entry_data:
                return entry_data["store"]
    except (AttributeError, TypeError):
        pass
    return None


def _hydrate_history(
    insight_id: str, rows: list[dict[str, object]]
) -> VerdictHistory:
    """Convert raw store dicts into a typed ``VerdictHistory``.

    Defensive against malformed rows (older schema, partial writes,
    etc.) — skip individual rows that don't parse rather than
    failing the whole history.
    """
    verdicts: list[Verdict] = []
    for row in rows:
        try:
            kind_str = row.get("kind")
            if not isinstance(kind_str, str):
                continue
            try:
                kind = VerdictKind(kind_str)
            except ValueError:
                # Unknown verdict kind in the DB — skip but don't
                # crash the scan.
                continue
            ts = row.get("timestamp")
            if not isinstance(ts, (int, float)):
                continue
            fp_dict = row.get("fingerprint")
            if not isinstance(fp_dict, dict):
                fp_dict = {}
            fp = dict_to_fingerprint(fp_dict)
            uid = row.get("user_id_hash")
            verdicts.append(
                Verdict(
                    insight_id=insight_id,
                    kind=kind,
                    timestamp=datetime.fromtimestamp(ts, tz=UTC),
                    fingerprint=fp,
                    user_id_hash=uid if isinstance(uid, str) else None,
                )
            )
        except Exception:
            continue
    # Sort defensively even though the store returns ASC already.
    verdicts.sort(key=lambda v: v.timestamp)
    return VerdictHistory(insight_id=insight_id, verdicts=tuple(verdicts))


def _should_skip_original(original: Insight, now: datetime) -> bool:
    """Skip if the original is currently applied / actively snoozed.

    Dismissed and retired are fine to re-surface — that's the point.
    But an applied insight (user engaged) shouldn't be re-nudged,
    nor should an unexpired snooze be overridden.
    """
    if getattr(original, "applied_at", None) is not None:
        return True
    snoozed_until = getattr(original, "snoozed_until", None)
    if isinstance(snoozed_until, datetime) and snoozed_until > now:
        return True
    return False


def _build_insight(
    *,
    original: Insight,
    negative_verdict: Verdict,
    delta,
    history: VerdictHistory,
    now: datetime,
) -> Insight:
    """Compose a meta-insight pointing at the original. Single
    fingerprint key is the original insight_id — dedup across scans
    so we don't spam the panel."""
    fingerprint = {
        "kind": "adaptive_feedback",
        "original_insight_id": original.id,
    }

    summary = _human_change_summary(delta)
    days_since = (now - negative_verdict.timestamp).days

    title = (
        f"Revisit: `{original.title}` — {summary}"
        if summary
        else f"Revisit: `{original.title}`"
    )

    verdict_summary = _verdict_summary(history)

    payload: dict[str, Any] = {
        "kind": "adaptive_feedback",
        "original_insight_id": original.id,
        "original_title": original.title,
        "original_detector": original.detector,
        "original_area_id": original.area_id,
        "negative_verdict_kind": negative_verdict.kind.value,
        "negative_verdict_iso": negative_verdict.timestamp.isoformat(),
        "days_since_negative_verdict": days_since,
        "what_changed": {
            "automations_added": sorted(delta.automations_added),
            "automations_removed": sorted(delta.automations_removed),
            "sensors_added_per_area": delta.sensors_added_per_area,
            "sensors_removed_per_area": delta.sensors_removed_per_area,
            "integrations_added": sorted(delta.integrations_added),
            "integrations_removed": sorted(delta.integrations_removed),
        },
        "human_summary": _full_explanation(
            original_title=original.title,
            negative_verdict=negative_verdict,
            days_since=days_since,
            summary=summary,
        ),
        "verdict_history_summary": verdict_summary,
    }

    return Insight(
        id=Insight.compute_id(InsightKind.PATTERN_OBSERVATION, fingerprint),
        kind=InsightKind.PATTERN_OBSERVATION,
        detector="adaptive_feedback",
        area_id=original.area_id,
        title=title,
        confidence=_CONFIDENCE,
        fingerprint=fingerprint,
        payload=payload,
        payload_format="report",
        created_at=now,
    )


def _human_change_summary(delta) -> str:
    """One-liner describing what changed since the verdict.

    Picks the most-actionable single change (automation removal
    wins) and ignores the rest in the summary; the payload still
    surfaces the full delta for the card to render.
    """
    if delta.automations_removed:
        if len(delta.automations_removed) == 1:
            name = next(iter(delta.automations_removed))
            return f"`{name}` was removed"
        return f"{len(delta.automations_removed)} automations were removed"
    if delta.sensors_added_per_area:
        first_area = next(iter(delta.sensors_added_per_area))
        first_classes = delta.sensors_added_per_area[first_area]
        if first_classes:
            first_class = next(iter(first_classes))
            return f"new {first_class} sensor in `{first_area}`"
    if delta.integrations_added:
        if len(delta.integrations_added) == 1:
            return f"`{next(iter(delta.integrations_added))}` integration added"
        return f"{len(delta.integrations_added)} integrations added"
    if delta.automations_added:
        if len(delta.automations_added) == 1:
            name = next(iter(delta.automations_added))
            return f"`{name}` was added"
    return ""


def _full_explanation(
    *,
    original_title: str,
    negative_verdict: Verdict,
    days_since: int,
    summary: str,
) -> str:
    verb = (
        "dismissed"
        if negative_verdict.kind == VerdictKind.DISMISS
        else "retired"
    )
    detail = f" because {summary}" if summary else ""
    return (
        f"You {verb} \"{original_title}\" "
        f"{days_since} day(s) ago. The situation changed since then"
        f"{detail} — consider whether the pattern is worth revisiting."
    )


def _verdict_summary(history: VerdictHistory) -> str:
    """One-line tally for the card: 'X applies, Y dismisses, Z retires'."""
    counts: dict[str, int] = {}
    for v in history.verdicts:
        counts[v.kind.value] = counts.get(v.kind.value, 0) + 1
    if not counts:
        return "no verdicts"
    bits = [f"{n} {kind}" for kind, n in sorted(counts.items())]
    return ", ".join(bits)
