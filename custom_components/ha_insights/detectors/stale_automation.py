"""StaleAutomationDetector — surface automations that haven't fired in N days.

Competitive-analysis driven (May 2026): Danm72/home-assistant-automation-
suggestions' most-praised feature is its 30-day stale-automation list.
Their version is a single hard threshold + UI; ours uses the same signal
but emits proper insights with confidence + apply-action so the
existing apply / dismiss / refine machinery just works.

## What counts as "stale"

An automation is stale when its `automation.<entity>` state machine
attribute ``last_triggered`` is either:

  - ``None`` (never fired since HA last restarted with this automation
    enabled — caveat below), OR
  - more than ``_STALE_DAYS_THRESHOLD`` (default 30) days in the past

## The HA-restart caveat

``last_triggered`` lives on the automation entity's state attributes,
which means HA persists it via the entity-state recorder. A fresh HA
restart re-loads automations and ``last_triggered`` resurfaces from
the last recorded state — but if the automation was JUST added and
hasn't fired yet, ``last_triggered`` is None regardless of how long
the automation has existed.

We mitigate that by requiring the automation to be **enabled** (state
== "on") AND skipping any automation younger than the stale threshold
itself. The age check uses the entity registry's ``created_at`` when
present (HA 2024.x+); falling back to "no creation timestamp = assume
old enough" preserves the v1.6+ behaviour for older HA installs.

## Skip rules

Same skip semantics as ``AutomationAuditDetector``:

  - Label ``ha_insights:no-audit`` on the automation → skipped
  - Automation entity in ``ctx.blocked_entities`` → skipped
  - Automation is currently disabled (state == "off") → skipped
    (user clearly intends it dormant; we'd just nag)
  - Automation is younger than the stale threshold → skipped
    (no signal yet)

## Confidence

Confidence scales with staleness:

  - 30–60 days stale: 0.65 (BETA-quality lead)
  - 60–120 days stale: 0.80
  - 120+ days stale: 0.92 (very confident it's truly unused)
  - Never fired (None) on an automation older than threshold: 0.75

## Payload

Each insight is a payload_format="report" — informational, not a
YAML automation. The card renders a "Delete automation" action that
calls the existing ``automation.remove_automation`` service for
GUI-defined automations, or shows the file path for YAML-defined
ones with manual-edit instructions.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from ..insight import Insight, InsightKind
from .base import Detector, DetectorContext, Maturity, register_detector

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Default stale threshold. v1.13 ships with 30 days to match Danm72.
# Future v1.x can expose this in OptionsFlow if users ask.
_STALE_DAYS_THRESHOLD = 30

# Skip label — shared semantics with AutomationAuditDetector.
_SKIP_LABEL = "ha_insights:no-audit"

# Confidence tiers by staleness bucket.
_CONFIDENCE_NEVER_FIRED = 0.75
_CONFIDENCE_30_60 = 0.65
_CONFIDENCE_60_120 = 0.80
_CONFIDENCE_120_PLUS = 0.92


@register_detector
class StaleAutomationDetector(Detector):
    """Emit one AUTOMATION_IMPROVEMENT insight per stale automation.

    Cheap detector — pure HA-state read, no buffer / recorder access.
    Safe to run every scan because the per-automation fingerprint
    dedupes across scans (same automation → same fingerprint → store
    sees it as an update, not a new insight).
    """

    name = "stale_automation"
    kind = InsightKind.AUTOMATION_IMPROVEMENT
    requires_recorder = False
    # v1.13: BETA until we have real-install dismiss/apply data.
    # Stale-automation feedback is well-trodden ground (Danm72 +
    # Spook do versions of this), so the false-positive rate should
    # be low — but enable / disable timing can produce surprises
    # (HA upgrade days, restored backups).
    maturity = Maturity.BETA
    description = (
        "Surface automations that haven't fired in 30+ days. Helps "
        "clean up automations that were experiments or got obsoleted "
        "by config changes."
    )

    async def scan(self, ctx: DetectorContext) -> list[Insight]:
        now = datetime.now(tz=UTC)
        cutoff = now - timedelta(days=_STALE_DAYS_THRESHOLD)
        insights: list[Insight] = []

        for entity_id in ctx.hass.states.async_entity_ids("automation"):
            if entity_id in ctx.blocked_entities:
                continue
            state = ctx.hass.states.get(entity_id)
            if state is None:
                continue
            if state.state != "on":
                # Disabled automation — user already intends it idle.
                continue
            if _has_skip_label(ctx.hass, entity_id):
                continue
            if _is_too_young(ctx.hass, entity_id, cutoff):
                continue

            last_triggered = _parse_last_triggered(state.attributes)
            never_fired = last_triggered is None
            if not never_fired and last_triggered > cutoff:
                # Fired recently — not stale.
                continue

            insight = self._build_insight(
                entity_id=entity_id,
                state_attrs=dict(state.attributes),
                last_triggered=last_triggered,
                now=now,
            )
            if insight is not None:
                insights.append(insight)

        if insights:
            _LOGGER.debug(
                "StaleAutomationDetector emitted %d insights", len(insights),
            )
        return insights

    def _build_insight(
        self,
        *,
        entity_id: str,
        state_attrs: dict,
        last_triggered: datetime | None,
        now: datetime,
    ) -> Insight | None:
        friendly = state_attrs.get("friendly_name") or entity_id
        never_fired = last_triggered is None
        if never_fired:
            days_stale = None
            staleness_label = "never fired since HA last loaded it"
            confidence = _CONFIDENCE_NEVER_FIRED
        else:
            delta = now - last_triggered
            days_stale = int(delta.total_seconds() // 86400)
            staleness_label = f"hasn't fired in {days_stale} days"
            if days_stale >= 120:
                confidence = _CONFIDENCE_120_PLUS
            elif days_stale >= 60:
                confidence = _CONFIDENCE_60_120
            else:
                confidence = _CONFIDENCE_30_60

        # Fingerprint is per-automation — re-scans of the same entity
        # update the existing insight rather than spamming new ones.
        # Includes the entity_id only; staleness severity changes are
        # surfaced via the title + payload, not a new insight.
        fingerprint = {
            "kind": "stale_automation",
            "entity_id": entity_id,
        }

        title = f"Automation `{friendly}` {staleness_label} — consider removing it"

        payload = {
            "kind": "stale_automation",
            "entity_id": entity_id,
            "friendly_name": friendly,
            "days_stale": days_stale,
            "never_fired": never_fired,
            "last_triggered_iso": (
                last_triggered.isoformat() if last_triggered else None
            ),
            "stale_threshold_days": _STALE_DAYS_THRESHOLD,
            "observations": [
                {
                    "kind": "stale",
                    "summary": staleness_label,
                    "days_stale": days_stale,
                    "never_fired": never_fired,
                },
            ],
            # Action the card surfaces. The actual "remove" is done via
            # HA's `automation.remove_automation` service (works on
            # GUI-defined automations); for YAML-defined automations
            # the card shows the file path + instructions.
            "actions": [
                {
                    "kind": "delete_automation",
                    "entity_id": entity_id,
                    "service": "automation.remove_automation",
                },
            ],
        }

        return Insight(
            id=Insight.compute_id(
                InsightKind.AUTOMATION_IMPROVEMENT, fingerprint,
            ),
            kind=InsightKind.AUTOMATION_IMPROVEMENT,
            detector=self.name,
            area_id=None,
            title=title,
            confidence=confidence,
            fingerprint=fingerprint,
            payload=payload,
            payload_format="report",
            created_at=datetime.now(tz=UTC),
        )


def _parse_last_triggered(attributes: dict) -> datetime | None:
    """Return the `last_triggered` attribute as a tz-aware datetime.

    HA stores `last_triggered` as a string ISO-8601 timestamp in
    state attributes. Returns None when the attribute is missing,
    null, or unparseable. Tolerates both UTC ISO + naive ISO (assumes
    UTC for naive)."""
    raw = attributes.get("last_triggered")
    if raw is None:
        return None
    if isinstance(raw, datetime):
        if raw.tzinfo is None:
            return raw.replace(tzinfo=UTC)
        return raw
    if not isinstance(raw, str) or not raw:
        return None
    try:
        # `fromisoformat` handles `2026-05-19T12:34:56+00:00` and the
        # naive `2026-05-19T12:34:56` form. Trailing 'Z' isn't accepted
        # by Python < 3.11; strip it.
        parsed = datetime.fromisoformat(raw.rstrip("Z"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _has_skip_label(hass: HomeAssistant, entity_id: str) -> bool:
    """True when the automation has the `ha_insights:no-audit` label.

    Labels are attached to entities via the entity registry. Tolerates
    failure — if registry lookup raises we treat the entity as not
    labelled (fail-open; the worst case is one extra dismissed insight).
    """
    try:
        from homeassistant.helpers import (
            entity_registry as er,
        )
        from homeassistant.helpers import (
            label_registry as lr,
        )

        ent_reg = er.async_get(hass)
        entry = ent_reg.async_get(entity_id)
        if entry is None or not entry.labels:
            return False
        label_reg = lr.async_get(hass)
        for label_id in entry.labels:
            label = label_reg.async_get_label(label_id)
            if label is not None and label.name == _SKIP_LABEL:
                return True
    except Exception:
        return False
    return False


def _is_too_young(
    hass: HomeAssistant, entity_id: str, cutoff: datetime,
) -> bool:
    """True when the automation was added LESS than `_STALE_DAYS_THRESHOLD`
    days ago — too young to be stale-flagged.

    Reads ``RegistryEntry.created_at`` (HA 2024.x+). Falls back to
    False (assume old enough) if the field is unavailable — older
    HA installs lose this guard but the disabled-state check still
    suppresses most false positives.
    """
    try:
        from homeassistant.helpers import entity_registry as er

        ent_reg = er.async_get(hass)
        entry = ent_reg.async_get(entity_id)
        if entry is None:
            return False
        created = getattr(entry, "created_at", None)
        if created is None:
            return False
        # Older HA versions may store created_at as a string.
        if isinstance(created, str):
            try:
                created = datetime.fromisoformat(created.rstrip("Z"))
            except ValueError:
                return False
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        return created > cutoff
    except Exception:
        return False
