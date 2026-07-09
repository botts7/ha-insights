"""CriticalDeviceOfflineDetector — fast-path alert for load-bearing devices.

v1.24.0 (July 2026). Field-motivated: on 2026-07-09 a Shelly 2.5 wall
switch (ESPHome, decoupled mode) wedged overnight. Its relay stayed
latched ON so the lights kept working from HA — but the physical wall
button, whose single-click is forwarded through the HA API, silently
died. The user discovered it by flipping the switch and nothing
happening. [[unavailable_device_fixit]] would have flagged it — 47
hours later. This detector exists to close that gap.

## What it flags

A DEVICE (not entity) that is fully offline — every one of its
eligible entities is ``"unavailable"`` — for ≥ 1 hour, when the device
is *load-bearing*:

  - one or more of its entities is acted on by an existing automation
    (``ctx.entities_already_automated``), or
  - it exposes an actuator entity (switch / light / cover / fan /
    climate / valve / humidifier / media_player / vacuum /
    water_heater) — i.e. something a human or physical control
    surface may depend on right now.

Devices that are neither (pure sensors nobody automates on) stay with
[[unavailable_device_fixit]]'s 48-hour slow path — a battery sensor
being quiet for a day is not an incident.

## Why device-level, not entity-level

``unavailable_device_fixit`` is per-entity because its job is
"here's your long-broken junk, start cleaning". This detector's job
is "something you rely on is down NOW" — and the unit users reason
about is the device ("the entrance switch"), not its 9 entities. One
insight per device, fingerprinted on the device_id, so re-scans
upsert instead of stacking.

## Confidence tiers

  - 0.90 — device has entities referenced by automations (an
    automation WILL misfire or silently no-op while this is down)
  - 0.80 — actuator device with no automation references (physical /
    dashboard control impact only)

0.90 clears the default mobile-push floor so these can reach the
user's phone; 0.80 lands in the panel + persistent notification.

## Skip rules

  - Entity in ``ctx.blocked_entities`` → excluded from the device's
    eligibility set
  - Registry-disabled / hidden entities → excluded (they are not in
    the state machine anyway, but guard for direct ctx construction
    in tests)
  - Domains in ``_EXCLUDED_DOMAINS`` (mirrors unavailable_device_fixit)
    → excluded from the "all entities unavailable" test
  - Devices where ANY eligible entity is still reporting → skipped
    (partially-degraded devices are an integration bug, not an outage)

## Restart semantics

Live ``last_changed`` resets on HA restart, so a device that was
offline across a restart won't re-flag until the threshold elapses
again (≤ 1 h of added latency). Deliberate: no recorder round-trip
keeps this detector inside the 500 ms scan budget, and the companion
persistent notification from the previous scan survives restarts.
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

# Trip after a device has been fully offline this long. Short by design
# — this is the incident fast path; the 48 h slow path lives in
# unavailable_device_fixit.
_MINUTES_THRESHOLD = 60

# Confidence tiers — see module docstring.
_CONFIDENCE_AUTOMATED = 0.90
_CONFIDENCE_ACTUATOR = 0.80

# Same rationale as unavailable_device_fixit: domains where
# unavailable/unknown says nothing about the physical device.
_EXCLUDED_DOMAINS = frozenset({
    "automation",
    "script",
    "scene",
    "zone",
    "sun",
    "persistent_notification",
})

# Domains that represent a physical actuation surface. A device
# exposing one of these going dark means something a human (wall
# button, dashboard tile, voice) may try to use right now.
_ACTUATOR_DOMAINS = frozenset({
    "switch",
    "light",
    "cover",
    "fan",
    "climate",
    "valve",
    "humidifier",
    "media_player",
    "vacuum",
    "water_heater",
})

# Only "unavailable" counts. "unknown" is a value-level diagnostic
# (entity alive, no data yet) and would false-positive fresh helpers.
_OFFLINE_STATE = "unavailable"


@register_detector
class CriticalDeviceOfflineDetector(Detector):
    """Emit one ANOMALY insight per load-bearing device fully offline ≥1h."""

    name = "critical_device_offline"
    kind = InsightKind.ANOMALY
    requires_recorder = False
    # New in v1.24.0 — BETA per the maturity ladder: functionally
    # complete + tested, auto-enabled, badge until field-verified.
    maturity = Maturity.BETA
    description = (
        "Fast-path alert when a device that automations or physical "
        "controls depend on goes fully offline for 1+ hour. Complements "
        "unavailable_device_fixit, which waits 48 h before flagging."
    )
    # Each offline device is its own incident — merging "entrance
    # switch down" and "garage switch down" into a cohort would hide
    # exactly the detail the user needs (same reasoning as
    # frequency_anomaly).
    cohort_dedup = False

    async def scan(self, ctx: DetectorContext) -> list[Insight]:
        now = datetime.now(tz=UTC)
        threshold = timedelta(minutes=_MINUTES_THRESHOLD)

        e_reg = _try_entity_registry(ctx.hass)
        d_reg = _try_device_registry(ctx.hass)

        # Pass 1 — bucket every eligible entity's state by device.
        # eligible[device_id] = list[(entity_id, state_value, last_changed)]
        eligible: dict[str, list[tuple[str, str, datetime]]] = {}
        for state in ctx.hass.states.async_all():
            entity_id = state.entity_id
            if entity_id in ctx.blocked_entities:
                continue
            domain = entity_id.split(".", 1)[0]
            if domain in _EXCLUDED_DOMAINS:
                continue
            device_id = ctx.device_id_by_entity.get(entity_id)
            if device_id is None:
                continue  # helpers / templates — no physical device
            if e_reg is not None:
                entry = e_reg.async_get(entity_id)
                if entry is not None and (
                    entry.disabled_by is not None
                    or entry.hidden_by is not None
                ):
                    continue
            last_changed = getattr(state, "last_changed", None)
            if last_changed is None:
                continue
            eligible.setdefault(device_id, []).append(
                (entity_id, state.state, last_changed)
            )

        insights: list[Insight] = []
        for device_id, entities in eligible.items():
            offline = [e for e in entities if e[1] == _OFFLINE_STATE]
            if len(offline) != len(entities):
                continue  # something still reports — not a device outage
            # Device counts as offline only once its LAST entity went
            # dark → the newest last_changed is the honest offline-since.
            offline_since = max(lc for _, _, lc in offline)
            if now - offline_since < threshold:
                continue

            entity_ids = [eid for eid, _, _ in offline]
            automated = [
                eid for eid in entity_ids
                if eid in ctx.entities_already_automated
            ]
            has_actuator = any(
                eid.split(".", 1)[0] in _ACTUATOR_DOMAINS
                for eid in entity_ids
            )
            if not automated and not has_actuator:
                continue  # not load-bearing — slow path owns it

            insights.append(
                self._build_insight(
                    device_id=device_id,
                    entity_ids=entity_ids,
                    automated=automated,
                    offline_since=offline_since,
                    now=now,
                    d_reg=d_reg,
                )
            )

        if insights:
            _LOGGER.debug(
                "CriticalDeviceOfflineDetector emitted %d insights",
                len(insights),
            )
        return insights

    def _build_insight(
        self,
        *,
        device_id: str,
        entity_ids: list[str],
        automated: list[str],
        offline_since: datetime,
        now: datetime,
        d_reg,
    ) -> Insight:
        device_name, area_id, integration = _device_meta(d_reg, device_id)
        display = device_name or entity_ids[0].split(".", 1)[1]
        minutes_offline = int((now - offline_since).total_seconds() // 60)
        if minutes_offline >= 2880:
            duration = f"{minutes_offline // 1440} days"
        elif minutes_offline >= 120:
            duration = f"{minutes_offline // 60} hours"
        else:
            duration = f"{minutes_offline} minutes"

        confidence = (
            _CONFIDENCE_AUTOMATED if automated else _CONFIDENCE_ACTUATOR
        )
        impact = (
            f"{len(automated)} automation-linked entities are dark"
            if automated
            else "physical/dashboard controls on it are dead"
        )
        title = (
            f"`{display}` fully offline for {duration} — {impact}"
        )

        payload = {
            "kind": "critical_device_offline",
            "device_id": device_id,
            "device_name": display,
            "integration": integration,
            "offline_since_iso": offline_since.isoformat(),
            "minutes_offline": minutes_offline,
            "entity_ids": sorted(entity_ids),
            "automation_linked_entity_ids": sorted(automated),
            "threshold_minutes": _MINUTES_THRESHOLD,
            "deeplink_url": f"/config/devices/device/{device_id}",
            "deeplink_label": f"Open {display} device page",
            "suggested_actions": _suggested_actions(display),
            "observations": [
                {
                    "kind": "device_offline_duration",
                    "summary": f"offline for {duration}",
                    "minutes_offline": minutes_offline,
                    "entity_count": len(entity_ids),
                },
            ],
        }

        fingerprint = {
            "kind": "critical_device_offline",
            "device_id": device_id,
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


def _suggested_actions(display: str) -> list[str]:
    return [
        f"Check {display} has power — breaker, plug, or in-wall supply.",
        (
            "Check your router / controller: is the device associated "
            "to Wi-Fi (or the Zigbee/Z-Wave mesh) at all?"
        ),
        (
            "Associated but unreachable usually means a wedged network "
            "stack — power-cycle the device, leaving it off ~30 s."
        ),
        (
            "If it depends on a hub or bridge, check the hub first — "
            "one hub outage looks like many device outages."
        ),
        (
            "Back but flaky? Check signal strength / channel congestion "
            "on the device's network details page."
        ),
    ]


def _try_entity_registry(hass: HomeAssistant):
    """Entity registry or None — same defensive pattern as
    unavailable_device_fixit (MagicMock hass in tests)."""
    try:
        from homeassistant.helpers import entity_registry as er

        return er.async_get(hass)
    except (ImportError, AttributeError, TypeError):
        return None


def _try_device_registry(hass: HomeAssistant):
    try:
        from homeassistant.helpers import device_registry as dr

        return dr.async_get(hass)
    except (ImportError, AttributeError, TypeError):
        return None


def _device_meta(
    d_reg, device_id: str
) -> tuple[str | None, str | None, str | None]:
    """(name, area_id, integration) for a device — all best-effort."""
    if d_reg is None:
        return None, None, None
    try:
        entry = d_reg.async_get(device_id)
        if entry is None:
            return None, None, None
        name = getattr(entry, "name_by_user", None) or getattr(
            entry, "name", None
        )
        area_id = getattr(entry, "area_id", None)
        identifiers = getattr(entry, "identifiers", None) or set()
        integration = next(
            (i[0] for i in identifiers if isinstance(i, tuple) and i),
            None,
        )
        return (
            name if isinstance(name, str) else None,
            area_id if isinstance(area_id, str) else None,
            integration if isinstance(integration, str) else None,
        )
    except (AttributeError, TypeError):
        return None, None, None
