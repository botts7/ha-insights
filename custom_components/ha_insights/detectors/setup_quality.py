"""SetupQualityDetector — what data the user has, what they could add.

Most of the detectors in this integration produce quality output that
scales with the user's HA setup completeness. A user with no Mobile
App + few area assignments gets useless results from PhoneActivity,
PresenceInference, and the goal tracker. The same detectors light up
brilliantly once those integrations are in place.

This detector inspects the user's HA setup and reports per-detector
quality tiers + the concrete next step that would unlock the next
tier. Output is one PATTERN_OBSERVATION per detector category, plus
one summary insight rolling up the overall setup health.

Quality tiers (per detector):
  - USELESS — required data sources don't exist, detector can't fire
  - LIMITED — minimum data exists, results will be sparse / shallow
  - GOOD    — typical setup, results are reliable
  - GREAT   — ideal setup, every signal the detector can use is wired

Each detector listed below has a `requirements` dict mapping tier
to a list of human-readable data-source descriptions. The checker
evaluates each in order and surfaces the highest tier reached + the
next-tier gap as actionable advice.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ..insight import Insight, InsightKind
from .base import Detector, DetectorContext, register_detector

if TYPE_CHECKING:
    pass


# Data-source predicates. Each is a function taking ctx and returning
# (bool present, str detail) so the advice text can include specifics
# (e.g., "found 12 areas" not just "areas exist").

def _has_mobile_app_gps(ctx: DetectorContext) -> tuple[bool, str]:
    n = 0
    for s in ctx.hass.states.async_all():
        if s.entity_id.startswith("device_tracker.") and (
            (s.attributes or {}).get("source_type") == "gps"
        ):
            n += 1
    return (n > 0, f"{n} GPS device_tracker(s)")


def _has_charging_sensor(ctx: DetectorContext) -> tuple[bool, str]:
    n = 0
    for s in ctx.hass.states.async_all():
        eid = s.entity_id
        if (
            eid.startswith("binary_sensor.") and eid.endswith("_charging")
        ) or (
            eid.startswith("sensor.") and eid.endswith("_battery_state")
        ):
            n += 1
    return (n > 0, f"{n} phone-charging sensor(s)")


def _has_activity_sensor(ctx: DetectorContext) -> tuple[bool, str]:
    n = 0
    for s in ctx.hass.states.async_all():
        if s.entity_id.startswith("sensor.") and s.entity_id.endswith(
            "_activity"
        ):
            n += 1
    return (n > 0, f"{n} phone activity sensor(s)")


def _has_area_coverage(ctx: DetectorContext) -> tuple[bool, str]:
    """≥ 50% of entities (non-system) have areas assigned."""
    total = 0
    with_area = 0
    try:
        from homeassistant.helpers import (
            area_registry as ar,
            entity_registry as er,
        )

        reg = er.async_get(ctx.hass)
        for entry in reg.entities.values():
            if entry.disabled_by or entry.hidden_by:
                continue
            total += 1
            if entry.area_id:
                with_area += 1
        area_reg = ar.async_get(ctx.hass)
        n_areas = len(list(area_reg.async_list_areas()))
    except Exception:  # noqa: BLE001
        return (False, "registry not available")
    if total == 0:
        return (False, "no entities")
    pct = with_area / total
    return (
        pct >= 0.5,
        f"{with_area}/{total} entities ({pct*100:.0f}%) tagged, "
        f"{n_areas} areas",
    )


def _has_many_areas(ctx: DetectorContext, threshold: int = 5) -> tuple[bool, str]:
    try:
        from homeassistant.helpers import area_registry as ar

        n = len(list(ar.async_get(ctx.hass).async_list_areas()))
    except Exception:  # noqa: BLE001
        return (False, "registry not available")
    return (n >= threshold, f"{n} areas defined")


def _has_recorder_retention(
    ctx: DetectorContext, min_days: int = 30
) -> tuple[bool, str]:
    try:
        from homeassistant.components.recorder import get_instance

        rec = get_instance(ctx.hass)
        keep = getattr(rec, "keep_days", None) or getattr(
            rec, "_keep_days", None
        )
    except Exception:  # noqa: BLE001
        return (False, "recorder not loaded")
    if keep is None:
        return (False, "keep_days unset")
    return (keep >= min_days, f"recorder.keep_days = {keep}")


def _has_goals_configured(ctx: DetectorContext) -> tuple[bool, str]:
    try:
        from ..const import DOMAIN

        for entry in ctx.hass.config_entries.async_entries(DOMAIN):
            raw = entry.options.get("goals_json") or entry.data.get(
                "goals_json"
            )
            if raw:
                import json

                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict) and parsed:
                        return (True, f"{len(parsed)} goal(s) set")
                except json.JSONDecodeError:
                    return (False, "goals_json present but malformed")
    except Exception:  # noqa: BLE001
        pass
    return (False, "no goals set")


def _has_user_context_events(ctx: DetectorContext) -> tuple[bool, str]:
    """Buffer must contain at least some events with context_user_id —
    proves the user actually clicks things in HA's UI / app, not just
    everything-via-automation."""
    if ctx.event_buffer is None:
        return (False, "buffer empty")
    n_manual = 0
    n_total = 0
    for ev in ctx.event_buffer.query():
        n_total += 1
        if ev.context_user_id is not None:
            n_manual += 1
    if n_total == 0:
        return (False, "buffer empty")
    pct = n_manual / n_total * 100
    return (n_manual >= 20, f"{n_manual}/{n_total} manual events ({pct:.0f}%)")


# Per-feature setup recipes. Order matters — checks evaluate top→bottom;
# first MET tier wins (with "great" requiring all earlier tiers' deps
# implicitly through cascade).

_RECIPES: list[dict[str, Any]] = [
    {
        "name": "Sleep & commute (PhoneActivityDetector)",
        "feature_key": "phone_activity",
        "tiers": [
            ("USELESS", [_has_mobile_app_gps], "No GPS-source device_tracker found. Install HA Companion App on your phone to unlock sleep + commute insights."),
            ("LIMITED", [_has_mobile_app_gps], "Mobile App GPS tracker detected — commute pattern (depart/return) can fire. For sleep window, also enable the 'Charging' sensor in the app's Manage Sensors screen."),
            ("GOOD", [_has_mobile_app_gps, _has_charging_sensor], "Both device tracker AND charging sensor present — sleep window + commute can be derived."),
            ("GREAT", [_has_mobile_app_gps, _has_charging_sensor, _has_activity_sensor], "All three signals (location + charging + activity) wired — full circadian rhythm + commute reliability available."),
        ],
    },
    {
        "name": "Room presence inference",
        "feature_key": "presence_inference",
        "tiers": [
            ("USELESS", [_has_area_coverage], "Most entities aren't tagged with an Area. Open Settings → Areas & Zones, assign rooms to lights / sensors / switches. Without area tags the detector can't infer where the user is."),
            ("LIMITED", [_has_area_coverage], "Some areas covered — presence inference will fire but only for tagged rooms. Tag the rest for full-house coverage."),
            ("GOOD", [_has_area_coverage, _has_many_areas], "Healthy area + entity coverage — presence inference will produce reliable room-level insights."),
            ("GREAT", [_has_area_coverage, _has_many_areas, _has_recorder_retention], "Area coverage + 30d+ recorder = stable seasonal-pattern detection at room granularity."),
        ],
    },
    {
        "name": "Manual habits & routines",
        "feature_key": "manual_habit",
        "tiers": [
            ("USELESS", [_has_user_context_events], "No recent manual UI / app interactions detected in the 14-day buffer. Either you automate everything (great problem to have), or HA hasn't seen enough activity yet. Toggle entities from the dashboard / app for a week."),
            ("LIMITED", [_has_user_context_events], "Some manual events present — ManualHabit and Routine detectors will fire on the clearest patterns."),
            ("GOOD", [_has_user_context_events, _has_area_coverage], "Manual events + area tagging — both detectors will surface high-quality suggestions with room context."),
            ("GREAT", [_has_user_context_events, _has_area_coverage, _has_recorder_retention], "All signals + 30d recorder retention — pattern detection benefits from longer history."),
        ],
    },
    {
        "name": "Goal tracking",
        "feature_key": "goal_tracker",
        "tiers": [
            ("USELESS", [_has_goals_configured], "No goals defined. Add JSON to Settings → HA Insights → Configure → goals_json. Example: `{\"bedtime_by\": \"22:30\", \"home_by\": \"18:30\"}`."),
            ("LIMITED", [_has_goals_configured], "Goals configured — adherence tracking will fire."),
            ("GOOD", [_has_goals_configured, _has_mobile_app_gps], "Goals + phone data — accurate hit/miss tracking against observed behavior."),
            ("GREAT", [_has_goals_configured, _has_mobile_app_gps, _has_charging_sensor], "Every goal type (commute + sleep) has the data source it needs."),
        ],
    },
]


@register_detector
class SetupQualityDetector(Detector):
    """Reports data-quality tiers per detector category + summary."""

    name = "setup_quality"
    kind = InsightKind.PATTERN_OBSERVATION
    requires_recorder = False

    async def scan(self, ctx: DetectorContext) -> list[Insight]:
        insights: list[Insight] = []
        per_feature_tiers: list[tuple[str, str]] = []
        for recipe in _RECIPES:
            tier, advice, details = self._evaluate_recipe(ctx, recipe)
            per_feature_tiers.append((recipe["name"], tier))
            insight = self._build_feature_insight(
                recipe=recipe,
                tier=tier,
                advice=advice,
                details=details,
            )
            if insight is not None:
                insights.append(insight)

        # Roll-up summary
        summary = self._build_summary_insight(per_feature_tiers)
        if summary is not None:
            insights.append(summary)
        return insights

    def _evaluate_recipe(
        self,
        ctx: DetectorContext,
        recipe: dict[str, Any],
    ) -> tuple[str, str, list[str]]:
        """Walk recipe tiers top→bottom, return highest tier whose
        dependencies are ALL met. Also return advice text + per-check
        details."""
        achieved_tier = "USELESS"
        achieved_advice = recipe["tiers"][0][2]
        details: list[str] = []
        for tier_name, checks, advice in recipe["tiers"]:
            tier_met = True
            tier_details: list[str] = []
            for check_fn in checks:
                ok, detail = check_fn(ctx)
                tier_details.append(detail)
                if not ok:
                    tier_met = False
                    break
            if tier_met:
                achieved_tier = tier_name
                achieved_advice = advice
                details = tier_details
        return achieved_tier, achieved_advice, details

    def _build_feature_insight(
        self,
        *,
        recipe: dict[str, Any],
        tier: str,
        advice: str,
        details: list[str],
    ) -> Insight | None:
        # Skip emitting GREAT (everything is fine — no actionable
        # advice). Users only need to see what needs improvement +
        # what's working at a baseline.
        if tier == "GREAT":
            return None
        tier_emoji = {
            "USELESS": "🔴",
            "LIMITED": "🟠",
            "GOOD": "🟢",
        }.get(tier, "⚪")
        title = f"{tier_emoji} {recipe['name']}: {tier}"
        confidence = {
            "USELESS": 0.95,  # we are sure this needs fixing
            "LIMITED": 0.7,
            "GOOD": 0.5,
        }.get(tier, 0.3)
        fingerprint = {
            "kind": "setup_quality_feature",
            "feature_key": recipe["feature_key"],
        }
        payload = {
            "feature": recipe["name"],
            "feature_key": recipe["feature_key"],
            "tier": tier,
            "details": details,
            "advice": advice,
        }
        return Insight(
            id=Insight.compute_id(InsightKind.PATTERN_OBSERVATION, fingerprint),
            kind=InsightKind.PATTERN_OBSERVATION,
            detector=self.name,
            area_id=None,
            title=title,
            confidence=round(confidence, 3),
            fingerprint=fingerprint,
            payload=payload,
            payload_format="report",
            created_at=datetime.now(tz=UTC),
        )

    def _build_summary_insight(
        self,
        per_feature_tiers: list[tuple[str, str]],
    ) -> Insight | None:
        if not per_feature_tiers:
            return None
        n = len(per_feature_tiers)
        counts = {"USELESS": 0, "LIMITED": 0, "GOOD": 0, "GREAT": 0}
        for _, tier in per_feature_tiers:
            counts[tier] = counts.get(tier, 0) + 1
        # Weighted score 0..1
        score = (
            counts["LIMITED"] * 0.33
            + counts["GOOD"] * 0.66
            + counts["GREAT"] * 1.0
        ) / max(1, n)
        title = (
            f"Setup quality: {counts['GREAT']} GREAT, {counts['GOOD']} GOOD, "
            f"{counts['LIMITED']} LIMITED, {counts['USELESS']} USELESS "
            f"(overall {score*100:.0f}%)"
        )
        fingerprint = {"kind": "setup_quality_summary"}
        payload = {
            "score": round(score, 3),
            "tier_counts": counts,
            "features": [
                {"feature": name, "tier": tier}
                for name, tier in per_feature_tiers
            ],
            "advice": (
                "Each feature has a per-tier breakdown above (LIMITED / "
                "USELESS rows). Address those first — they unlock the "
                "highest-impact detectors. GREAT tiers don't need anything."
            ),
        }
        return Insight(
            id=Insight.compute_id(InsightKind.PATTERN_OBSERVATION, fingerprint),
            kind=InsightKind.PATTERN_OBSERVATION,
            detector=self.name,
            area_id=None,
            title=title,
            confidence=0.9,
            fingerprint=fingerprint,
            payload=payload,
            payload_format="report",
            created_at=datetime.now(tz=UTC),
        )
