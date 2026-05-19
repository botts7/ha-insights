"""WifiFindDetector — passive location inference from Wi-Fi RSSI.

v1.18 entry in the "find my device" series. Companion to:
  v1.11.5 LocationProposalDetector (spatial-correlation area inference)
  v1.12.0 BLE live-find         (walking warmer/colder via phone scanner)

## Why "find" via Wi-Fi when BLE is the only walking-find signal?

The BLE capability docstring says it plainly: Wi-Fi RSSI is
device→AP, not phone→device. Walking around with your phone doesn't
change the RSSI a UniFi controller sees from your Wi-Fi-tag. So
Wi-Fi can't power BLE's metal-detector UX.

What Wi-Fi RSSI *can* do is **passive location inference**: a
device consistently strongly associated with one AP is probably
physically near that AP. Cross-reference the AP's area_id in the
device registry and you have a "last known room" signal — useful
for finding a misplaced wifi-tagged item or proposing an area
assignment for an unassigned device-tracker.

The "find" naming follows the v1.18-v1.20 task series for parity
with BLE find; readers should interpret it as "where was this last
seen / where does it usually live".

## What this detector emits

For each `device_tracker.*` entity with:

  1. A recognised Wi-Fi signal-strength attribute (`rx_rssi`,
     `signal_strength`, `signal`, …) with a plausible dBm reading.
  2. A recognised AP identifier attribute (`ap_mac`, `bssid`,
     `host`, …).
  3. An AP that resolves to a device with a non-None `area_id`.
  4. EITHER the entity has no `area_id` (proposal mode), OR the
     entity's `area_id` differs from the AP's (advisory: this
     wifi-tagged device hasn't moved to its assigned room).

…emit a PATTERN_OBSERVATION insight proposing/confirming the AP's
area as the entity's location. Confidence keys off signal strength:

  - >= -50 dBm  → 0.80  (very close — same room)
  - >= -65 dBm  → 0.60  (probably same area)
  - >= -75 dBm  → 0.45  (could be adjacent area)
  -  < -75 dBm  → skip   (signal too weak to be reliable)

## Caveats (surfaced in the insight explanation)

  - Single-AP installs: every device infers to the only AP's area.
    Detector skips when fewer than 2 APs have area_id assigned.
  - Wi-Fi roaming: device may have just briefly associated with an
    AP during a walk-by. The 0.80 ceiling reflects that we're
    looking at CURRENT state, not 24h-of-consistency.
  - Mesh/extender setups: the "AP" the device sees is sometimes a
    wired-back extender — the area_id of that node still works as
    a proxy for the device's room.

## Scope guard

Hard cap: max 10 insights per scan. Same convention as v1.11.5.
Never auto-applies — advisory only.

## Maturity: BETA

Real-install calibration needed; in particular the
signal-strength → confidence curve is industry-typical but not
validated against community installs yet.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ..insight import Insight, InsightKind
from ..lib.wifi_find_capability import (
    WifiFindCapability,
    wifi_find_capability_for,
)
from .base import Detector, DetectorContext, Maturity, register_detector

_LOGGER = logging.getLogger(__name__)

# Confidence curve. dBm thresholds → confidence floor at each tier.
# Stronger signal = higher confidence in the room-inference.
_CONFIDENCE_VERY_CLOSE_DBM = -50
_CONFIDENCE_PROBABLY_DBM = -65
_CONFIDENCE_MAYBE_DBM = -75

# Confidence values per tier. Capped at 0.80 even at -30 dBm: we
# can't be >0.80 confident from a single CURRENT-state snapshot —
# the device may have just briefly associated with this AP during
# a walk-by. Recorder-based "consistent for 24 h" would justify a
# higher cap; that's v1.18.1.
_CONFIDENCE_VERY_CLOSE = 0.80
_CONFIDENCE_PROBABLY = 0.60
_CONFIDENCE_MAYBE = 0.45

# Hard cap so a noisy UniFi install doesn't flood the panel.
_MAX_INSIGHTS_PER_SCAN = 10

# Domains where Wi-Fi inference makes sense. Most Wi-Fi-trackable
# things show up as device_tracker; some integrations also expose
# sensor.*_signal entities, which we ignore (the device_tracker is
# the canonical entity).
_RELEVANT_DOMAINS: frozenset[str] = frozenset({"device_tracker"})


def _signal_to_confidence(dbm: int) -> float | None:
    """Map signal strength (dBm) to a 0-1 confidence.

    Returns None when the signal is too weak to act on — caller
    skips the insight."""
    if dbm >= _CONFIDENCE_VERY_CLOSE_DBM:
        return _CONFIDENCE_VERY_CLOSE
    if dbm >= _CONFIDENCE_PROBABLY_DBM:
        return _CONFIDENCE_PROBABLY
    if dbm >= _CONFIDENCE_MAYBE_DBM:
        return _CONFIDENCE_MAYBE
    return None


def _confidence_tier(confidence: float) -> str:
    if confidence >= _CONFIDENCE_VERY_CLOSE - 0.01:
        return "very_close"
    if confidence >= _CONFIDENCE_PROBABLY - 0.01:
        return "probably"
    return "maybe"


@dataclass(frozen=True)
class WifiFindEntityFacts:
    """Pure inputs for one entity, captured on the event loop.

    Allows `_infer_locations` to be unit-tested without standing up
    real HA registries."""

    entity_id: str
    area_id: str | None
    attributes: dict[str, Any]


@dataclass(frozen=True)
class WifiFindInference:
    """A single propose-area inference, before Insight construction."""

    entity_id: str
    current_area_id: str | None
    proposed_area_id: str
    proposed_area_name: str
    ap_device_id: str
    ap_name: str
    capability: WifiFindCapability
    confidence: float


def _resolve_ap(
    ap_identifier: str,
    *,
    mac_to_device_id: dict[str, str],
    device_name: dict[str, str],
) -> str | None:
    """Resolve a Wi-Fi AP identifier to a device_id.

    Tries MAC lookup first (UniFi `ap_mac`, generic `bssid`), then
    falls back to substring-matching the AP friendly name (Asuswrt
    `host`, UniFi `ap_name`). Returns None when no device matches.
    """
    ap_key = ap_identifier.lower()
    direct = mac_to_device_id.get(ap_key)
    if direct is not None:
        return direct
    for dev_id, name in device_name.items():
        if name and ap_key and ap_key in name.lower():
            return dev_id
    return None


def _infer_locations(
    entities: list[WifiFindEntityFacts],
    *,
    mac_to_device_id: dict[str, str],
    device_area: dict[str, str | None],
    device_name: dict[str, str],
    area_name_by_id: dict[str, str],
    blocked_entities: frozenset[str] = frozenset(),
    max_insights: int = _MAX_INSIGHTS_PER_SCAN,
) -> list[WifiFindInference]:
    """Run the inference loop. Pure — no HA imports.

    Caller is responsible for assembling the lookup dicts on the
    event loop (where the device / entity / area registries live).
    """
    # Single-AP installs would propose the same area for everything
    # regardless of signal. Skip cleanly when fewer than 2 APs have
    # an area_id assigned.
    ap_devices_with_area = {
        dev_id
        for dev_id, area in device_area.items()
        if area is not None and dev_id in mac_to_device_id.values()
    }
    if len(ap_devices_with_area) < 2:
        return []

    inferences: list[WifiFindInference] = []
    for ent in entities:
        if len(inferences) >= max_insights:
            break
        if ent.entity_id in blocked_entities:
            continue
        domain = ent.entity_id.split(".", 1)[0]
        if domain not in _RELEVANT_DOMAINS:
            continue

        cap = wifi_find_capability_for(
            ent.entity_id, state_attributes=ent.attributes
        )
        if not cap.is_trackable or cap.signal_dbm is None:
            continue
        confidence = _signal_to_confidence(cap.signal_dbm)
        if confidence is None:
            continue

        ap_device_id = _resolve_ap(
            cap.ap_identifier or "",
            mac_to_device_id=mac_to_device_id,
            device_name=device_name,
        )
        if ap_device_id is None:
            continue

        proposed_area_id = device_area.get(ap_device_id)
        if proposed_area_id is None:
            continue

        if ent.area_id == proposed_area_id:
            # Already in the AP's area — nothing to propose. We
            # don't emit "confirmed" insights; that would just be
            # noise. Card surfaces capability separately via WS.
            continue

        ap_name = device_name.get(ap_device_id, ap_device_id)
        proposed_area_name = area_name_by_id.get(
            proposed_area_id, proposed_area_id
        )
        inferences.append(
            WifiFindInference(
                entity_id=ent.entity_id,
                current_area_id=ent.area_id,
                proposed_area_id=proposed_area_id,
                proposed_area_name=proposed_area_name,
                ap_device_id=ap_device_id,
                ap_name=ap_name,
                capability=cap,
                confidence=confidence,
            )
        )
    return inferences


@register_detector
class WifiFindDetector(Detector):
    """Propose / refine an entity's area_id by cross-referencing the
    AP it's currently associated with to that AP's device area."""

    name = "wifi_find"
    kind = InsightKind.PATTERN_OBSERVATION
    requires_recorder = False
    maturity = Maturity.BETA
    description = (
        "For each Wi-Fi-trackable device tracker, identifies which "
        "access point currently sees the strongest signal and "
        "cross-references that AP's area assignment in the device "
        "registry. Proposes (or confirms) the entity's location "
        "without ever auto-applying. Works with UniFi (rx_rssi + "
        "ap_mac), Asuswrt (signal + host), and most generic Wi-Fi "
        "tracker integrations."
    )
    required_data = ("entity_registry", "device_registry")
    optional_data = ()

    async def scan(self, ctx: DetectorContext) -> list[Insight]:
        try:
            from homeassistant.helpers import (
                area_registry as ar,
            )
            from homeassistant.helpers import (
                device_registry as dr,
            )
            from homeassistant.helpers import (
                entity_registry as er,
            )
        except ImportError:
            _LOGGER.debug("wifi_find: registry helpers unavailable; skip")
            return []

        e_reg = er.async_get(ctx.hass)
        d_reg = dr.async_get(ctx.hass)

        # Build mac → device_id, device_id → area_id, and
        # device_id → friendly_name lookups once.
        mac_to_device_id: dict[str, str] = {}
        device_area: dict[str, str | None] = {}
        device_name: dict[str, str] = {}
        for dev in d_reg.devices.values():
            device_area[dev.id] = dev.area_id
            device_name[dev.id] = (
                dev.name_by_user or dev.name or dev.id
            )
            for conn_type, conn_value in dev.connections:
                if conn_type == "mac" and conn_value:
                    mac_to_device_id[conn_value.lower()] = dev.id

        a_reg = ar.async_get(ctx.hass)
        area_name_by_id: dict[str, str] = {}
        for a in a_reg.async_list_areas():
            # v1.14.11: HA renamed AreaEntry.area_id → AreaEntry.id.
            # Tolerate both via getattr so we don't break on either
            # side of the rename.
            key = getattr(a, "id", None) or getattr(a, "area_id", None)
            if key:
                area_name_by_id[key] = a.name

        # Gather per-entity facts on the event loop.
        entities: list[WifiFindEntityFacts] = []
        for ent in e_reg.entities.values():
            if ent.disabled_by or ent.hidden_by:
                continue
            domain = ent.entity_id.split(".", 1)[0]
            if domain not in _RELEVANT_DOMAINS:
                continue
            state = ctx.hass.states.get(ent.entity_id)
            if state is None:
                continue
            entities.append(
                WifiFindEntityFacts(
                    entity_id=ent.entity_id,
                    area_id=ent.area_id,
                    attributes=dict(state.attributes),
                )
            )

        inferences = _infer_locations(
            entities,
            mac_to_device_id=mac_to_device_id,
            device_area=device_area,
            device_name=device_name,
            area_name_by_id=area_name_by_id,
            blocked_entities=ctx.blocked_entities,
        )

        return [self._build_insight(inf) for inf in inferences]

    def _build_insight(self, inf: WifiFindInference) -> Insight:
        action_phrase = (
            "Currently unassigned — propose"
            if inf.current_area_id is None
            else f"Currently in {inf.current_area_id}; AP suggests"
        )
        title = (
            f"{action_phrase} {inf.proposed_area_name}: "
            f"{inf.entity_id} sees {inf.ap_name} at "
            f"{inf.capability.signal_dbm} dBm"
        )

        fingerprint: dict[str, Any] = {
            "kind": "wifi_find",
            "entity_id": inf.entity_id,
            "proposed_area_id": inf.proposed_area_id,
            "ap_device_id": inf.ap_device_id,
        }

        payload: dict[str, Any] = {
            "type": "entities",
            "title": (
                f"Probably in {inf.proposed_area_name}: {inf.entity_id}"
            ),
            "entities": [inf.entity_id],
            "_wifi_find": {
                "entity_id": inf.entity_id,
                "current_area_id": inf.current_area_id,
                "proposed_area_id": inf.proposed_area_id,
                "proposed_area_name": inf.proposed_area_name,
                "ap_device_id": inf.ap_device_id,
                "ap_name": inf.ap_name,
                "signal_dbm": inf.capability.signal_dbm,
                "signal_attribute": inf.capability.signal_attribute,
                "ap_attribute": inf.capability.ap_attribute,
                "ap_identifier": inf.capability.ap_identifier,
                "confidence_tier": _confidence_tier(inf.confidence),
            },
        }

        explanation = "\n".join([
            (
                f"This entity is currently associated with "
                f"**{inf.ap_name}** (visible in "
                f"`{inf.capability.ap_attribute}`), which the device "
                f"registry places in area **{inf.proposed_area_name}**. "
                f"Current Wi-Fi signal: {inf.capability.signal_dbm} dBm "
                f"via `{inf.capability.signal_attribute}`."
            ),
            "",
            (
                "**How this works.** Wi-Fi RSSI is device→AP, so we "
                "can't tell you 'warmer/colder' as you walk around — "
                "but the AP it's CURRENTLY talking to is a strong "
                "hint about which room the device is in. Stronger "
                "signal = same room; weaker = same floor / next room."
            ),
            "",
            (
                "**Caveats.** Roaming clients can briefly associate "
                "with a non-local AP during walk-bys; if that happens "
                "around scan time, the inference is wrong. Confidence "
                "is capped at 0.80 from a single snapshot — future "
                "v1.18.x will use the recorder to require ≥ 24 h of "
                "consistent association before crossing 0.85."
            ),
            "",
            (
                "**Advisory only.** This detector never auto-applies. "
                "Open bulk-area-assign to confirm the suggestion or "
                "set a different area."
            ),
        ])

        return Insight(
            id=Insight.compute_id(InsightKind.PATTERN_OBSERVATION, fingerprint),
            kind=InsightKind.PATTERN_OBSERVATION,
            detector=self.name,
            area_id=inf.proposed_area_id,
            title=title,
            confidence=round(inf.confidence, 3),
            fingerprint=fingerprint,
            payload=payload,
            payload_format="card",
            explanation=explanation,
            created_at=datetime.now(tz=UTC),
        )
