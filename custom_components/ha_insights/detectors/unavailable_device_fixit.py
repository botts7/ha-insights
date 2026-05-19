"""UnavailableDeviceFixItDetector — surface entities stuck unavailable/unknown.

v1.14.0 (May 2026). Pairs with [[ha_insights_connectivity_health]] roadmap.

## What it flags

Any entity whose current state is ``"unavailable"`` or ``"unknown"`` and
whose ``last_changed`` is ≥ 48 hours ago. That combination means the
entity entered the diagnostic state, and it's still there — not a
transient outage. The detector emits one anomaly insight per stuck
entity with structured diagnostic guidance: how long it's been stuck,
which integration owns it, plus a deeplink to the integration's
configuration page and a tiered suggested-action list.

## Why now (not just rely on HA's own UI)

HA shows entities in their unavailable state, but does NOT surface
the *duration* prominently. A motion sensor that's been dead for 6
weeks looks identical to one that just flickered offline. This
detector turns "you have 47 unavailable entities" into "8 of them
have been broken for >1 month — here's where to start."

## Confidence tiers

  - 48–72 h:  0.65 (might be a transient outage / power glitch)
  - 72–168 h: 0.78 (3–7 days; user has clearly not noticed)
  - 168–720 h: 0.88 (1–4 weeks; almost certainly broken)
  - 720+ h:   0.95 (4+ weeks; abandoned device or dead hardware)

## Excluded domains

Domains where unavailable/unknown is expected or where the detector
would just add noise. Keep this list short; users can blocklist
specific entities through the existing privacy controls.

  - ``automation`` / ``script`` / ``scene`` / ``zone`` — never have
    these states; if they do, HA is broken, not the device.
  - ``sun`` — derived; transient unknown is a calculation lag.
  - ``persistent_notification`` — UI scaffolding.

``device_tracker`` and ``person`` are NOT excluded — phones going
genuinely "unavailable" (vs not_home / unknown) usually means the
companion app stopped reporting, which IS actionable.

## Skip rules

  - Entity in ``ctx.blocked_entities`` → skipped
  - Entity registry says ``disabled_by`` is set → skipped
    (user already disabled it)
  - Entity registry says ``hidden_by`` is set → skipped
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from ..insight import Insight, InsightKind
from .base import Detector, DetectorContext, Maturity, register_detector

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, State

_LOGGER = logging.getLogger(__name__)

# Trip the detector at 48 hours stuck. Tunable later if real-install
# feedback says lots of legitimate devices have brief multi-hour
# outages (cloud APIs, ISP flaps, etc.).
_HOURS_THRESHOLD = 48

# Confidence tiers by hours-stuck bucket.
_CONFIDENCE_48_72 = 0.65
_CONFIDENCE_72_168 = 0.78
_CONFIDENCE_168_720 = 0.88
_CONFIDENCE_720_PLUS = 0.95

# States that indicate "device is not reporting cleanly". These come
# from HA Core's STATE_UNAVAILABLE / STATE_UNKNOWN constants — copying
# the string values rather than importing to avoid a fragile Core
# import path.
_DIAGNOSTIC_STATES = frozenset({"unavailable", "unknown"})

# Domains where unavailable/unknown is expected behaviour. See module
# docstring for rationale.
_EXCLUDED_DOMAINS = frozenset({
    "automation",
    "script",
    "scene",
    "zone",
    "sun",
    "persistent_notification",
})


@register_detector
class UnavailableDeviceFixItDetector(Detector):
    """Emit one ANOMALY insight per entity stuck unavailable ≥48h."""

    name = "unavailable_device_fixit"
    kind = InsightKind.ANOMALY
    requires_recorder = False
    # v1.14: EXPERIMENTAL until we have real-install data on what a
    # reasonable threshold is + how often integrations legitimately
    # leave entities unavailable for >48 h.
    maturity = Maturity.EXPERIMENTAL
    description = (
        "Flag entities stuck in 'unavailable' or 'unknown' for 48+ hours "
        "with diagnostic guidance — integration, deeplink, suggested "
        "actions. Turns 'you have 47 unavailable entities' into 'here "
        "are the 8 that have been broken for >1 month, start with these.'"
    )

    async def scan(self, ctx: DetectorContext) -> list[Insight]:
        now = datetime.now(tz=UTC)
        cutoff = now - timedelta(hours=_HOURS_THRESHOLD)
        insights: list[Insight] = []

        e_reg = _try_entity_registry(ctx.hass)

        for state in ctx.hass.states.async_all():
            if state.state not in _DIAGNOSTIC_STATES:
                continue
            entity_id = state.entity_id
            if entity_id in ctx.blocked_entities:
                continue
            domain = entity_id.split(".", 1)[0]
            if domain in _EXCLUDED_DOMAINS:
                continue
            # Skip if user already disabled / hidden the entity — they
            # already know it's gone.
            if e_reg is not None:
                entry = e_reg.async_get(entity_id)
                if entry is not None and (
                    entry.disabled_by is not None
                    or entry.hidden_by is not None
                ):
                    continue
            last_changed = getattr(state, "last_changed", None)
            if last_changed is None or last_changed > cutoff:
                continue

            insight = self._build_insight(
                state=state,
                last_changed=last_changed,
                now=now,
                ctx=ctx,
                e_reg=e_reg,
            )
            if insight is not None:
                insights.append(insight)

        if insights:
            _LOGGER.debug(
                "UnavailableDeviceFixItDetector emitted %d insights",
                len(insights),
            )
        return insights

    def _build_insight(
        self,
        *,
        state: State,
        last_changed: datetime,
        now: datetime,
        ctx: DetectorContext,
        e_reg,
    ) -> Insight | None:
        entity_id = state.entity_id
        friendly = state.attributes.get("friendly_name") or entity_id
        hours_stuck = int((now - last_changed).total_seconds() // 3600)

        if hours_stuck >= 720:
            confidence = _CONFIDENCE_720_PLUS
            severity_label = f"unavailable for {hours_stuck // 24} days"
        elif hours_stuck >= 168:
            confidence = _CONFIDENCE_168_720
            severity_label = f"unavailable for {hours_stuck // 24} days"
        elif hours_stuck >= 72:
            confidence = _CONFIDENCE_72_168
            severity_label = f"unavailable for {hours_stuck // 24} days"
        else:
            confidence = _CONFIDENCE_48_72
            severity_label = f"unavailable for {hours_stuck} hours"

        # Integration / area lookups — best-effort, all guarded.
        integration = _integration_for_entity(e_reg, entity_id)
        iot_class = (
            ctx.iot_class_by_integration.get(integration)
            if integration
            else None
        )
        area_id = _area_for_entity(e_reg, entity_id)

        title = f"`{friendly}` {severity_label} — diagnose connection"

        payload = {
            "kind": "unavailable_device_fixit",
            "entity_id": entity_id,
            "friendly_name": friendly,
            "current_state": state.state,
            "last_changed_iso": last_changed.isoformat(),
            "hours_unavailable": hours_stuck,
            "integration": integration,
            "iot_class": iot_class,
            "threshold_hours": _HOURS_THRESHOLD,
            "deeplink_url": (
                f"/config/integrations/integration/{integration}"
                if integration
                else None
            ),
            "deeplink_label": (
                f"Open {integration} integration"
                if integration
                else None
            ),
            "suggested_actions": _suggested_actions(
                domain=entity_id.split(".", 1)[0],
                integration=integration,
                iot_class=iot_class,
            ),
            "observations": [
                {
                    "kind": "unavailable_duration",
                    "summary": severity_label,
                    "hours_unavailable": hours_stuck,
                    "current_state": state.state,
                },
            ],
        }

        fingerprint = {
            "kind": "unavailable_device_fixit",
            "entity_id": entity_id,
        }

        return Insight(
            id=Insight.compute_id(InsightKind.ANOMALY, fingerprint),
            kind=InsightKind.ANOMALY,
            detector=self.name,
            area_id=area_id,
            title=title,
            confidence=confidence,
            fingerprint=fingerprint,
            payload=payload,
            payload_format="report",
            created_at=now,
        )


def _try_entity_registry(hass: HomeAssistant):
    """Return the entity registry or None if HA isn't fully set up.

    Defensive — same reasoning as in physical_device_link.py: tests
    feed MagicMock hass objects and registry calls would blow up.
    """
    try:
        from homeassistant.helpers import entity_registry as er

        return er.async_get(hass)
    except (ImportError, AttributeError, TypeError):
        return None


def _integration_for_entity(e_reg, entity_id: str) -> str | None:
    """Return the integration domain for an entity, e.g. 'zha', 'mqtt'."""
    if e_reg is None:
        return None
    try:
        entry = e_reg.async_get(entity_id)
        if entry is None:
            return None
        platform = getattr(entry, "platform", None)
        return platform if isinstance(platform, str) else None
    except (AttributeError, TypeError):
        return None


def _area_for_entity(e_reg, entity_id: str) -> str | None:
    if e_reg is None:
        return None
    try:
        entry = e_reg.async_get(entity_id)
        if entry is None:
            return None
        aid = getattr(entry, "area_id", None)
        return aid if isinstance(aid, str) else None
    except (AttributeError, TypeError):
        return None


def _suggested_actions(
    *,
    domain: str,
    integration: str | None,
    iot_class: str | None,
) -> list[str]:
    """Tiered action list. Generic-first, then more specific based on
    integration class. Order matters — the card surfaces the top
    suggestion most prominently.
    """
    actions: list[str] = []

    # Universal first step.
    actions.append("Check the physical device — is it powered, charged, in range?")

    # IoT-class specific guidance.
    if iot_class == "cloud_push" or iot_class == "cloud_polling":
        actions.append(
            "Cloud integration — check the vendor's status page and "
            "your internet connection."
        )
    elif iot_class == "local_push" or iot_class == "local_polling":
        actions.append(
            "Local integration — check the device is on the same "
            "network segment and reachable."
        )

    # Domain-specific hints.
    if domain == "device_tracker" or domain == "person":
        actions.append(
            "If this is a phone, check the Home Assistant Companion "
            "app is running and has background permissions."
        )
    elif domain == "climate" or domain == "humidifier":
        actions.append(
            "HVAC devices often unavailability when their hub or "
            "bridge loses power — check the hub first."
        )

    # Integration restart — works for nearly everything.
    if integration:
        actions.append(
            f"Restart the integration: Settings → Devices & Services "
            f"→ {integration} → ⋮ → Reload."
        )
    else:
        actions.append(
            "Reload the entity's integration: Settings → Devices & "
            "Services → [integration] → ⋮ → Reload."
        )

    # Last resort.
    actions.append(
        "If the device is gone for good, remove the entity from the "
        "device's page so it stops cluttering your dashboards."
    )

    return actions
