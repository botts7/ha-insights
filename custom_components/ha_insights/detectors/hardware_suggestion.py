"""HardwareSuggestionDetector — surface per-area sensor gaps.

v1.14.2 (May 2026). Meta-detector that fires when an area has the
*infrastructure* to use a sensor category but lacks the sensor itself.
Distinct from :mod:`setup_quality` which reports home-wide coverage
percentages: this detector says "*this specific* kitchen has 4 lights
and no motion sensor — consider adding one."

## Non-commercial commitment

**Hard rules** (see [[ha_insights_hardware_gap_detector]]):

  - **NO brand names.** No "Aqara", "Hue", "Shelly", "IKEA Trådfri",
    etc. We suggest the device-class CATEGORY only.
  - **NO affiliate links.**
  - **NO buy URLs.**
  - **NO specific product recommendations.**

The user picks the brand. Our job is to identify the GAP. The
suggested-action strings refer to "a motion sensor" or "an
illuminance sensor", not to vendors.

## Recipes (per-area gap rules)

The detector iterates over every area and evaluates each recipe in
order. A recipe fires when its `gap_predicate(area_id, ctx)` is True
AND the area has the prerequisite "infrastructure" (lights, climate
entities, etc.) for the suggestion to make sense.

  1. **motion_sensor_for_active_area** — area has ≥3 light/switch/
     media_player entities AND no motion/occupancy/presence sensor.
     Unlocks: presence-based lighting, occupancy detection,
     "lights on, nobody home" notifications.

  2. **illuminance_sensor_for_lit_area** — area has ≥2 light
     entities AND no illuminance sensor. Unlocks: automatic
     daylight-aware lighting, sunset/sunrise overrides that
     respect actual indoor brightness rather than just sun
     elevation.

  3. **temperature_sensor_for_climate_area** — area has a climate
     entity (thermostat) AND no standalone temperature sensor.
     Unlocks: cross-validation of thermostat readings, room-vs-
     thermostat differential, HVAC-failure detection.

  4. **contact_sensor_for_entry_area** — area name matches an
     entry pattern (entry / foyer / garage / front / back / mudroom /
     hallway) AND no door/window/opening contact sensor. Unlocks:
     arrival/departure detection, away-mode triggers, doorbell-
     correlation.

Confidence is a flat 0.70 across recipes: these are suggestions, not
high-confidence anomalies. The user weighs each one against their
budget and patience.

## Skip rules

  - Area with no actuators (no lights / switches / media_players)
    skipped entirely — no point suggesting sensors for an empty room.
  - Areas in `ctx.area_filter` are honored.
  - The recipe-specific predicates also bail on missing prerequisites
    (e.g. illuminance recipe needs ≥2 lights, not just 1).
  - Per-recipe entity-class checks ignore blocked entities so the
    privacy blocklist doesn't accidentally make a real motion sensor
    look absent.

## Why this isn't just setup_quality

`setup_quality.py` measures *home-wide* coverage ("33% of areas have
motion") and emits one insight per recipe regardless of which areas
are affected. This detector emits **one insight per (area, recipe)
gap**, so the user sees actionable per-area suggestions in the area
filter / group_by view.

The two are complementary: setup_quality answers "how complete is my
setup overall?"; HardwareSuggestion answers "which specific rooms
should I add what to?".
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ..insight import Insight, InsightKind
from .base import Detector, DetectorContext, Maturity, register_detector

if TYPE_CHECKING:
    pass

_LOGGER = logging.getLogger(__name__)

# Confidence used by every recipe. Suggestions are intentionally
# medium-confidence — the user picks; we just identify the gap.
_CONFIDENCE = 0.70

# Device-class sets we look for. Lowercased for consistent matching.
_MOTION_CLASSES = frozenset({"motion", "occupancy", "presence"})
_ILLUMINANCE_CLASSES = frozenset({"illuminance"})
_TEMPERATURE_CLASSES = frozenset({"temperature"})
_CONTACT_CLASSES = frozenset({"door", "window", "opening", "garage_door"})

# Actuator domains — domains a user "controls" rather than "observes".
# Drives the per-area activity threshold below; an area with these is
# one where automation can actually do something.
_ACTUATOR_DOMAINS = frozenset({
    "light",
    "switch",
    "fan",
    "media_player",
    "climate",
    "cover",
    "humidifier",
    "vacuum",
})

# Area-name patterns that suggest an "entry" zone. Match against the
# lowercased area name. Heuristic — happy false-positives (it's just
# a suggestion the user can dismiss) but no false-suggestions in
# rooms that aren't entry-like.
_ENTRY_PATTERNS = (
    "entry",
    "entryway",
    "foyer",
    "garage",
    "front",
    "back",
    "mudroom",
    "mud room",
    "hall",
    "hallway",
    "porch",
)


@dataclass(frozen=True)
class _Recipe:
    """One per-area gap rule."""

    name: str
    # Human-readable hardware CATEGORY (no brands). Surfaced in
    # the insight title and payload.
    category: str
    # Short tag for the payload kind / fingerprint.
    payload_kind: str
    # Predicate: True iff this area HAS the gap (i.e. should suggest).
    # Signature: (area_id, ctx, area_entities, present_classes) → bool.
    gap_predicate: Callable[
        [str, DetectorContext, frozenset[str], frozenset[str]],
        bool,
    ]
    # Scenarios this hardware would unlock. Surfaced as a bullet list.
    unlocks: tuple[str, ...]
    # Human-readable rationale shown above the unlocks list.
    rationale: str


def _has_n_actuators(area_entities: frozenset[str], n: int) -> bool:
    count = 0
    for eid in area_entities:
        if eid.split(".", 1)[0] in _ACTUATOR_DOMAINS:
            count += 1
            if count >= n:
                return True
    return False


def _has_class_in_area(
    present_classes: frozenset[str], classes: frozenset[str]
) -> bool:
    return bool(present_classes & classes)


def _motion_gap_predicate(
    area_id: str,
    ctx: DetectorContext,
    area_entities: frozenset[str],
    present_classes: frozenset[str],
) -> bool:
    if _has_class_in_area(present_classes, _MOTION_CLASSES):
        return False
    return _has_n_actuators(area_entities, 3)


def _illuminance_gap_predicate(
    area_id: str,
    ctx: DetectorContext,
    area_entities: frozenset[str],
    present_classes: frozenset[str],
) -> bool:
    if _has_class_in_area(present_classes, _ILLUMINANCE_CLASSES):
        return False
    lights = sum(1 for e in area_entities if e.startswith("light."))
    return lights >= 2


def _temperature_gap_predicate(
    area_id: str,
    ctx: DetectorContext,
    area_entities: frozenset[str],
    present_classes: frozenset[str],
) -> bool:
    if _has_class_in_area(present_classes, _TEMPERATURE_CLASSES):
        return False
    return any(e.startswith("climate.") for e in area_entities)


def _contact_gap_predicate(
    area_id: str,
    ctx: DetectorContext,
    area_entities: frozenset[str],
    present_classes: frozenset[str],
) -> bool:
    if _has_class_in_area(present_classes, _CONTACT_CLASSES):
        return False
    hierarchy = ctx.hierarchy
    if hierarchy is None:
        return False
    area_name = (hierarchy.area_name_by_id.get(area_id) or area_id).lower()
    if not any(pat in area_name for pat in _ENTRY_PATTERNS):
        return False
    # Only suggest if there's at least one actuator — empty rooms
    # don't need contact sensors either.
    return _has_n_actuators(area_entities, 1)


_RECIPES: tuple[_Recipe, ...] = (
    _Recipe(
        name="motion_sensor_for_active_area",
        category="motion or occupancy sensor",
        payload_kind="hardware_gap_motion",
        gap_predicate=_motion_gap_predicate,
        unlocks=(
            "Presence-aware lighting (lights on when you walk in, off when you leave)",
            "\"Lights on, nobody home\" notifications",
            "Occupancy-based HVAC overrides",
            "Better signal for cooccurrence and schedule detectors in this area",
        ),
        rationale=(
            "This area has multiple controllable devices but no way "
            "to detect whether anyone is in the room."
        ),
    ),
    _Recipe(
        name="illuminance_sensor_for_lit_area",
        category="illuminance (lux) sensor",
        payload_kind="hardware_gap_illuminance",
        gap_predicate=_illuminance_gap_predicate,
        unlocks=(
            "Daylight-aware lighting (don't turn on lights when it's already bright)",
            "Sunset/sunrise automations that respect actual indoor brightness",
            "Reduced false-positive 'lights on in daytime' suggestions",
        ),
        rationale=(
            "This area has multiple lights but no measurement of how "
            "bright the room actually is."
        ),
    ),
    _Recipe(
        name="temperature_sensor_for_climate_area",
        category="standalone temperature sensor",
        payload_kind="hardware_gap_temperature",
        gap_predicate=_temperature_gap_predicate,
        unlocks=(
            "Cross-validation of thermostat readings against actual room temperature",
            "Cold-spot and hot-spot detection",
            "HVAC-failure alerts when the room diverges from setpoint",
        ),
        rationale=(
            "This area has a climate entity but no separate sensor to "
            "verify the thermostat's reading."
        ),
    ),
    _Recipe(
        name="contact_sensor_for_entry_area",
        category="door/window contact sensor",
        payload_kind="hardware_gap_contact",
        gap_predicate=_contact_gap_predicate,
        unlocks=(
            "Arrival/departure detection without needing a phone presence sensor",
            "Away-mode triggers (last door closes → arm alarm, set away thermostat)",
            "Doorbell / package-delivery correlation",
        ),
        rationale=(
            "Entry areas benefit a lot from a contact sensor — it's "
            "the most reliable signal for who's home and when."
        ),
    ),
)


@register_detector
class HardwareSuggestionDetector(Detector):
    """Emit one PATTERN_OBSERVATION insight per (area, gap-recipe)."""

    name = "hardware_suggestion"
    kind = InsightKind.PATTERN_OBSERVATION
    requires_recorder = False
    # v1.14: EXPERIMENTAL. Recipe thresholds and entry-name patterns
    # are first guesses; real-install feedback will tune them.
    maturity = Maturity.EXPERIMENTAL
    description = (
        "Surface per-area sensor gaps — 'this kitchen has 4 lights "
        "but no motion sensor; consider adding one.' Complements "
        "SetupQuality (which measures home-wide coverage) with "
        "actionable per-room suggestions. Never recommends brands."
    )

    async def scan(self, ctx: DetectorContext) -> list[Insight]:
        hierarchy = ctx.hierarchy
        if hierarchy is None:
            return []

        now = datetime.now(tz=UTC)
        insights: list[Insight] = []

        # Pre-compute which device_classes are present in each area,
        # ignoring blocked / disabled / hidden entities. One pass over
        # entities instead of one per recipe.
        classes_by_area: dict[str, set[str]] = {}
        for eid, area_id in hierarchy.area_of.items():
            if area_id is None:
                continue
            if eid in ctx.blocked_entities:
                continue
            if eid in hierarchy.disabled or eid in hierarchy.hidden:
                continue
            dc = hierarchy.device_class_of.get(eid)
            if isinstance(dc, str):
                classes_by_area.setdefault(area_id, set()).add(dc.lower())

        for area_id, area_entities in hierarchy.entities_in_area.items():
            if ctx.area_filter and area_id not in ctx.area_filter:
                continue
            # Filter the area's entities by privacy blocklist + disabled
            # status so a recipe doesn't get confused by ghost entities.
            visible = frozenset(
                eid
                for eid in area_entities
                if eid not in ctx.blocked_entities
                and eid not in hierarchy.disabled
                and eid not in hierarchy.hidden
            )
            if not visible:
                continue
            present_classes = frozenset(classes_by_area.get(area_id, set()))
            for recipe in _RECIPES:
                if not recipe.gap_predicate(
                    area_id, ctx, visible, present_classes
                ):
                    continue
                insight = self._build_insight(
                    recipe=recipe,
                    area_id=area_id,
                    hierarchy=hierarchy,
                    now=now,
                )
                if insight is not None:
                    insights.append(insight)

        if insights:
            _LOGGER.debug(
                "HardwareSuggestionDetector emitted %d insights", len(insights)
            )
        return insights

    def _build_insight(
        self,
        *,
        recipe: _Recipe,
        area_id: str,
        hierarchy,
        now: datetime,
    ) -> Insight | None:
        area_name = hierarchy.area_name_by_id.get(area_id) or area_id

        title = (
            f"Consider adding a {recipe.category} to `{area_name}`"
        )

        payload = {
            "kind": recipe.payload_kind,
            "area_id": area_id,
            "area_name": area_name,
            "hardware_category": recipe.category,
            "rationale": recipe.rationale,
            "unlocks": list(recipe.unlocks),
            "non_commercial_disclaimer": (
                "HA Insights never recommends specific products or "
                "brands. The category above is just a starting point — "
                "pick what fits your home and budget."
            ),
            "observations": [
                {
                    "kind": "hardware_gap",
                    "summary": recipe.rationale,
                    "category": recipe.category,
                },
            ],
        }

        fingerprint = {
            "kind": "hardware_suggestion",
            "recipe": recipe.name,
            "area_id": area_id,
        }

        return Insight(
            id=Insight.compute_id(InsightKind.PATTERN_OBSERVATION, fingerprint),
            kind=InsightKind.PATTERN_OBSERVATION,
            detector=self.name,
            area_id=area_id,
            title=title,
            confidence=_CONFIDENCE,
            fingerprint=fingerprint,
            payload=payload,
            payload_format="report",
            created_at=now,
        )
