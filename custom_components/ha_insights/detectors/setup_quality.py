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
        # One-line action the user can act on without opening the
        # insight payload. Surfaced in the insight title.
        "next_step": "install the Home Assistant Companion App on your phone",
        # Deep-link the user lands on when they click the "Set this
        # up" button on the setup-guide card. Two flavours:
        #   - internal HA path → opens in same tab via <a href>
        #   - external URL     → external_url=True opens in new tab
        # Use `None` for features whose remedy is behavioural (no URL
        # is meaningful — e.g. "use HA for a week").
        "setup_url": "https://companion.home-assistant.io/",
        "setup_url_label": "Get the Companion App",
        "setup_url_external": True,
        # Concrete scenarios this feature would unlock at GOOD tier.
        # The user sees these in the insight explanation so they
        # know WHY it's worth fixing.
        "scenarios": [
            "Detect your typical sleep window from phone charge times",
            "Flag when you leave home and arrive home most days",
            "Suggest a charge reminder if you'd run flat before bedtime",
            "Trigger morning routines when you usually wake (after 7 days of data)",
        ],
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
        # NOTE: /config/areas/dashboard only LISTS areas — there's
        # no entity-assignment workflow from that page. The correct
        # path is /config/devices: setting an Area on a device
        # cascades to every entity that device owns, so a few
        # clicks covers dozens of entities. Per-entity assignment
        # exists at /config/entities but is slower.
        "next_step": "set an Area on each device under Settings → Devices & Services → Devices (it cascades to all that device's entities)",
        "setup_url": "/config/devices/dashboard",
        "setup_url_label": "Assign devices to areas",
        "setup_url_external": False,
        "scenarios": [
            "Detect 'you're usually in the kitchen at 07:15 on weekdays'",
            "Flag rooms that haven't been used in the lookback window",
            "Suggest area-scoped automations (kitchen presence → kitchen lights)",
            "Power room-by-room energy and activity dashboards",
        ],
        "tiers": [
            ("USELESS", [_has_area_coverage], "Most entities aren't tagged with an Area. Open Settings → Devices & Services → Devices and set an Area on each device — every entity that device owns inherits it, so this is the fastest path. Per-entity overrides live under Settings → Entities. Without area tags the detector can't infer where the user is."),
            ("LIMITED", [_has_area_coverage], "Some areas covered — presence inference will fire but only for tagged rooms. Tag the rest for full-house coverage."),
            ("GOOD", [_has_area_coverage, _has_many_areas], "Healthy area + entity coverage — presence inference will produce reliable room-level insights."),
            ("GREAT", [_has_area_coverage, _has_many_areas, _has_recorder_retention], "Area coverage + 30d+ recorder = stable seasonal-pattern detection at room granularity."),
        ],
    },
    {
        "name": "Manual habits & routines",
        "feature_key": "manual_habit",
        "next_step": "toggle entities from the dashboard / app for a week so HA records the user context",
        # No URL — the remedy is behavioural ("use HA for a week").
        # Frontend renders next_step as plain text in this case.
        "setup_url": None,
        "setup_url_label": None,
        "setup_url_external": False,
        "scenarios": [
            "Spot 'you toggle the lounge lamp manually at 18:42 on weeknights'",
            "Bundle related actions into a multi-entity 'evening routine'",
            "Suggest automating the manual steps you keep doing yourself",
            "Distinguish your habits from automation noise in the timeline",
        ],
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
        "next_step": 'add goals JSON in Configure → Advanced (e.g. {"bedtime_by": "22:30"})',
        # v1.5.17: /config/integrations/integration/<domain> rendered
        # blank on some HA versions. The canonical dashboard URL
        # /config/integrations works everywhere — user clicks the
        # HA Insights tile, then Configure. One extra click but
        # zero confusion.
        "setup_url": "/config/integrations",
        "setup_url_label": "Open HA Integrations (click the HA Insights tile → Configure)",
        "setup_url_external": False,
        "scenarios": [
            "Track 'you make it to bedtime by 22:30 on 4 of 7 nights'",
            "Score how often you leave for work on time",
            "Tell you when a goal is trending up (or slipping)",
            "Trigger a nudge automation when you're at risk of missing a goal",
        ],
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
        # Carry recipe + advice along with the tier so the rollup can
        # surface USELESS gaps inline (the per-feature card path
        # intentionally skips USELESS — see _build_feature_insight).
        per_feature_full: list[tuple[dict[str, Any], str, str]] = []
        for recipe in _RECIPES:
            tier, advice, details = self._evaluate_recipe(ctx, recipe)
            per_feature_tiers.append((recipe["name"], tier))
            per_feature_full.append((recipe, tier, advice))
            insight = self._build_feature_insight(
                recipe=recipe,
                tier=tier,
                advice=advice,
                details=details,
            )
            if insight is not None:
                insights.append(insight)

        # Roll-up summary — receives full eval so it can list the
        # USELESS gaps inline (since those are no longer their own
        # cards). This is the ONE place a brand-new install will see
        # what's worth setting up.
        summary = self._build_summary_insight(
            per_feature_tiers, per_feature_full
        )
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
        # Skip emitting GREAT (no actionable advice) AND USELESS
        # (folded into the rollup so the panel doesn't get spammed
        # with "fix this" cards for features the user hasn't enabled
        # yet). LIMITED + GOOD still get per-feature cards — they're
        # progress signals worth seeing on their own.
        if tier in ("GREAT", "USELESS"):
            return None
        tier_emoji = {
            "USELESS": "🔴",
            "LIMITED": "🟠",
            "GOOD": "🟢",
        }.get(tier, "⚪")
        next_step = recipe.get("next_step", "")
        scenarios: list[str] = list(recipe.get("scenarios", []))
        # Title: tier badge + feature name + one-line action so the
        # user sees what to do at a glance, without expanding the
        # payload. The action is omitted for GOOD/LIMITED tiers
        # where nothing's urgent.
        if tier == "USELESS" and next_step:
            title = (
                f"{tier_emoji} {recipe['name']}: USELESS — {next_step}"
            )
        else:
            title = f"{tier_emoji} {recipe['name']}: {tier}"
        # Explanation: full advice + concrete scenarios this feature
        # would unlock. Renders under the title without a click so the
        # user understands WHY this is worth fixing.
        explanation_parts: list[str] = [advice]
        if scenarios and tier != "GOOD":
            explanation_parts.append("")
            explanation_parts.append("What this unlocks:")
            for s in scenarios:
                explanation_parts.append(f"  • {s}")
        explanation = "\n".join(explanation_parts)
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
            "next_step": next_step,
            "scenarios_unlocked": scenarios,
            # v1.5.11: structured deep-link so the setup-guide card
            # can render a real button instead of leaving the user
            # to navigate by prose.
            "setup_url": recipe.get("setup_url"),
            "setup_url_label": recipe.get("setup_url_label"),
            "setup_url_external": bool(recipe.get("setup_url_external")),
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
            explanation=explanation,
            created_at=datetime.now(tz=UTC),
        )

    def _build_summary_insight(
        self,
        per_feature_tiers: list[tuple[str, str]],
        per_feature_full: list[tuple[dict[str, Any], str, str]] | None = None,
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

        # If everything is GREAT, suppress the rollup entirely — there's
        # nothing actionable here, and the panel doesn't need a "100%
        # all good" badge cluttering it.
        if counts["USELESS"] == 0 and counts["LIMITED"] == 0:
            return None

        # USELESS items are no longer their own cards. Surface them
        # INLINE in the rollup so the user sees the actionable
        # next-steps in one place.
        useless_items: list[tuple[str, str]] = []  # (feature, next_step)
        # v1.5.11: structured per-feature data for the setup-guide
        # frontend body. The dialog renders each entry as a card
        # with tier badge, scenarios, next-step text + deeplink
        # button. Includes ALL features (not just USELESS) so the
        # user sees what's already wired AND what to add.
        setup_steps: list[dict[str, Any]] = []
        if per_feature_full:
            for recipe, tier, advice in per_feature_full:
                if tier == "USELESS":
                    useless_items.append(
                        (recipe["name"], recipe.get("next_step", ""))
                    )
                setup_steps.append(
                    {
                        "feature": recipe["name"],
                        "feature_key": recipe["feature_key"],
                        "tier": tier,
                        "advice": advice,
                        "next_step": recipe.get("next_step", ""),
                        "scenarios": list(recipe.get("scenarios", [])),
                        "setup_url": recipe.get("setup_url"),
                        "setup_url_label": recipe.get("setup_url_label"),
                        "setup_url_external": bool(
                            recipe.get("setup_url_external")
                        ),
                    }
                )

        # Title leads with the count of fixable gaps — most actionable
        # framing. Falls back to the old score-only title when nothing
        # is fixable (LIMITED-only setups).
        #
        # Wording note: "Setup completeness" not "Setup health".
        # USELESS in this detector means "optional integration not
        # wired", not "your install is broken". A user with 1 GREAT
        # feature and 3 USELESS sees 25% — labelling that "health"
        # made the install look unwell when it was actually fine and
        # just missing optional add-ons. followup.
        wired = counts["GOOD"] + counts["GREAT"]
        partial = counts["LIMITED"]
        if useless_items:
            title = (
                f"⚙️ Setup completeness {score*100:.0f}% — "
                f"{wired} of {n} wired, {len(useless_items)} setup step"
                f"{'s' if len(useless_items) > 1 else ''} would unlock more."
            )
        else:
            title = (
                f"⚙️ Setup completeness {score*100:.0f}% — "
                f"{wired} of {n} wired, {partial} could be improved."
            )

        # Explanation leads with WHAT'S WORKING (so the user doesn't
        # read "25%" and assume their install is broken), then lists
        # the unlock steps for unconfigured features.
        lines: list[str] = []
        wired_count = counts["GOOD"] + counts["GREAT"]
        if wired_count:
            lines.append(
                f"Working: {wired_count} feature"
                f"{'s' if wired_count > 1 else ''} wired and producing "
                "insights."
            )
        if counts["LIMITED"]:
            if lines:
                lines.append("")
            lines.append(
                f"In progress: {counts['LIMITED']} feature"
                f"{'s' if counts['LIMITED'] > 1 else ''} "
                "(see the per-feature card below for next step)."
            )
        if useless_items:
            if lines:
                lines.append("")
            lines.append(
                "Optional add-ons not yet configured "
                "(each is one setup step):"
            )
            for feature, step in useless_items:
                if step:
                    lines.append(f"  • {feature} — {step}")
                else:
                    lines.append(f"  • {feature}")
        explanation = "\n".join(lines)

        fingerprint = {"kind": "setup_quality_summary"}
        payload = {
            "score": round(score, 3),
            "tier_counts": counts,
            "features": [
                {"feature": name, "tier": tier}
                for name, tier in per_feature_tiers
            ],
            "useless_next_steps": [
                {"feature": f, "next_step": s} for f, s in useless_items
            ],
            # v1.5.11: full per-feature setup-guide data. The
            # frontend's setup_quality-specific dialog body renders
            # this as a guided checklist with deeplink buttons.
            "setup_steps": setup_steps,
            "advice": (
                "Setup completeness scores the OPTIONAL add-ons that "
                "unlock additional detectors — not the health of your "
                "current install. Your wired features are producing "
                "insights normally; each 'Optional add-ons' item below "
                "is a one-step change that would activate another "
                "detector family."
            ),
        }
        return Insight(
            id=Insight.compute_id(InsightKind.PATTERN_OBSERVATION, fingerprint),
            kind=InsightKind.PATTERN_OBSERVATION,
            detector=self.name,
            area_id=None,
            title=title,
            # Slightly lower than the per-feature confidence so the
            # rollup sorts BELOW any LIMITED/GOOD per-feature cards
            # when sorted by confidence (those are more actionable).
            confidence=0.6 if useless_items else 0.4,
            fingerprint=fingerprint,
            payload=payload,
            payload_format="report",
            explanation=explanation,
            created_at=datetime.now(tz=UTC),
        )
