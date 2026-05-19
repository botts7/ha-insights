"""HabitualOverrideDetector — surface automations the user keeps correcting.

When an automation sets `light.hallway` to `on` and within two minutes
the user manually flips it `off`, ONCE is noise. THREE TIMES across 14
days, on different days, is a habit — the automation likely needs
revising. The user is consistently telling the system "no, that's not
what I want."

Implementation reuses `lib.habitual_override.find_habitual_overrides`
for the algorithmic core (pure, HA-import-free, unit-tested at
test_lib_habitual_override.py). This module is the HA-side wrapper:
read the event buffer, run the analyzer, build Insight objects with
a payload that surfaces the override pattern as a `report` (not a
proposed automation — the user owns the fix for their own automation).
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..insight import Insight, InsightKind
from ..lib.habitual_override import (
    OverrideStat,
    find_habitual_overrides,
)
from .base import Detector, DetectorContext, Maturity, register_detector

# Detector knobs — exposed as class attributes (not constants) so a
# future OptionsFlow can let users tune them per-install. Defaults
# chosen to match the lib defaults documented in lib/habitual_override.py.
_WINDOW_SECONDS = 120.0
_LOOKBACK_DAYS = 14
_MIN_DAYS = 3


@register_detector
class HabitualOverrideDetector(Detector):
    """Detect automations whose effects the user habitually reverses.

    Emits one PATTERN_OBSERVATION per detected (entity, automation_state,
    manual_state) tuple where the user reverses the automation's
    effect within `_WINDOW_SECONDS` on at least `_MIN_DAYS` distinct
    days in the lookback window.

    NOT actionable as a one-click apply — the user owns their own
    automation and may want to remove the action entirely, gate it on
    a condition, change the target state, etc. We surface the
    observation; the user chooses the fix.
    """

    name = "habitual_override"
    kind = InsightKind.PATTERN_OBSERVATION
    requires_recorder = False
    maturity = Maturity.BETA
    description = (
        "Spots automations whose effects you keep manually reversing. "
        "If your hallway-light automation turns the lamp on and you "
        "switch it off within two minutes on 3+ days, the automation "
        "probably needs revising. Surfaces the pattern; you own the fix."
    )
    required_data = ("feature:event_buffer",)

    async def scan(self, ctx: DetectorContext) -> list[Insight]:
        if ctx.event_buffer is None:
            return []

        # v1.14.11: ctx.event_buffer is `_FrozenBufferView` in
        # production (per detectors/__init__.py), which exposes
        # `.query(...)` not `.snapshot()`. Materialize via query()
        # for cross-version compatibility — `find_habitual_overrides`
        # needs a sequence to iterate twice (or .__len__).
        events = tuple(ctx.event_buffer.query())
        stats = find_habitual_overrides(
            events,
            window_seconds=_WINDOW_SECONDS,
            lookback_days=_LOOKBACK_DAYS,
            min_days=_MIN_DAYS,
        )

        insights: list[Insight] = []
        for stat in stats:
            if stat.entity_id in ctx.blocked_entities:
                continue
            insights.append(self._build_insight(stat))
        return insights

    def _build_insight(self, stat: OverrideStat) -> Insight:
        """Build a PATTERN_OBSERVATION insight from one OverrideStat."""
        lag_str = (
            f"~{stat.median_lag_seconds:.0f}s"
            if stat.median_lag_seconds < 90
            else f"~{stat.median_lag_seconds / 60:.1f} min"
        )
        title = (
            f"You keep undoing an automation on {stat.entity_id}: "
            f"automation sets it {stat.automation_state.upper()}, you "
            f"change it to {stat.manual_state.upper()} within {lag_str} "
            f"on {stat.days_count} of {_LOOKBACK_DAYS} days. Review the "
            f"automation?"
        )

        # Confidence floor + ramp: at min_days=3 confidence is 0.5,
        # at days_count=14 it's 1.0. Linear in between.
        confidence_raw = (stat.days_count - _MIN_DAYS) / (
            _LOOKBACK_DAYS - _MIN_DAYS
        )
        confidence = round(0.5 + 0.5 * max(0.0, min(1.0, confidence_raw)), 3)

        fingerprint: dict[str, Any] = {
            "kind": "habitual_override",
            "entity_id": stat.entity_id,
            "automation_state": stat.automation_state,
            "manual_state": stat.manual_state,
        }

        payload = {
            "summary": title,
            "entity_id": stat.entity_id,
            "automation_state": stat.automation_state,
            "manual_state": stat.manual_state,
            "days_count": stat.days_count,
            "lookback_days": _LOOKBACK_DAYS,
            "median_lag_seconds": round(stat.median_lag_seconds, 1),
            "sample_pairs": stat.sample_pairs,
            "window_seconds": _WINDOW_SECONDS,
        }

        return Insight(
            id=Insight.compute_id(InsightKind.PATTERN_OBSERVATION, fingerprint),
            kind=InsightKind.PATTERN_OBSERVATION,
            detector=self.name,
            area_id=None,
            title=title,
            confidence=confidence,
            fingerprint=fingerprint,
            payload=payload,
            payload_format="report",
            explanation=(
                f"On {stat.days_count} of the last {_LOOKBACK_DAYS} days, "
                f"an automation set {stat.entity_id} to "
                f"{stat.automation_state.upper()} and within "
                f"{int(_WINDOW_SECONDS)} seconds you manually changed it "
                f"to {stat.manual_state.upper()}. Median delay before you "
                f"reversed it: {lag_str}. That's a strong signal the "
                f"automation isn't doing what you actually want — "
                f"consider removing the action, adding a condition, or "
                f"flipping the target state."
            ),
            created_at=datetime.now(tz=UTC),
        )
