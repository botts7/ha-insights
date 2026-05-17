"""Static-signal physical-device deduplication.

HA's data model gives each integration its own ``device_id``. There's
no built-in concept of "the same physical thing seen through two
different integrations." But this is **common**:

| Scenario | Integrations involved |
|---|---|
| Tuya plug paired via Tuya cloud + same plug captured via BLE scanner | tuya + bluetooth |
| Govee bulb on Govee Cloud + Govee BLE | govee + govee_ble |
| Hue light via Hue Bridge + via Matter | hue + matter |
| Shelly Cloud + local API on same device | shelly_cloud + shelly |
| ESPHome reflash of a former cloud device | leftover + esphome |
| Zigbee2MQTT + ZHA during migrations | zigbee2mqtt + zha |

Result: ONE physical device produces N entities. The
bulk-area-assign dialog treats them as separate (user assigns area
twice); the v1.10 🔆 button suggests "flash 3 lights" when only 1
flashes. This lib closes that gap using **static identifiers
already in the registries** — no correlation math, no waiting
period.

## What it detects (cheap, deterministic)

| Signal | Source | Strength |
|---|---|---|
| Shared MAC | `device.connections` contains `("mac", "AA:BB:..")` | ⭐⭐⭐⭐⭐ |
| Shared BT address | `device.connections` `("bluetooth", "AA:BB:..")` | ⭐⭐⭐⭐⭐ |
| Shared IP / host | `state.attributes.ip_address` or `host` | ⭐⭐⭐⭐ |
| Shared IEEE (Zigbee) | `device.connections` contains `("zigbee", "0x00…")` | ⭐⭐⭐⭐⭐ |
| Manufacturer + model + via_device | exact `(mfr, model, via_device)` triple | ⭐⭐ |

Confidence is the highest-strength matching signal — we don't try
to multiply across signals because they're not independent (two
devices that share a MAC almost always share their other identifiers
too; piling on signals would falsely inflate confidence).

## What it does NOT detect (deferred to v1.11)

Correlation-based dedup ("two temp sensors with r=0.99 over 7 days
are the same physical sensor") needs the rolling event buffer, not
the registries. That's a meta-detector in v1.11
(`PhysicalDeviceLinkDetector`), not this lib.

## Architecture

Pure function — no HA imports, no side effects. Caller (`ws_api.py`)
assembles the input dicts from HA's registries and state machine,
then enriches the `identify_capability` WS response with a
``same_as`` field. The card renders a 🔗 pill so the user knows to
treat the pair as one physical thing for area assignment.

Per memory `ha_insights_find_my_device_roadmap`, this is the
**cheap, static-signal version** of physical-device dedup. The
correlation-based version (v1.11) addresses the cases this lib
misses (integrations that hide the underlying identifiers — Govee
BLE → Govee Cloud where each side only knows its own protocol's
view of the device).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DedupCandidate:
    """One other entity that looks like the same physical device.

    entity_id: the candidate's entity_id.
    reason: short human-readable label for the matching signal
        ("shared MAC", "shared IP", "shared Zigbee IEEE", "matching
        manufacturer + model + parent device"). Surfaced in the
        card pill's tooltip.
    confidence: 0.0-1.0, derived from the matching signal's strength.
        Card thresholds at 0.7 by default; lower values are
        too noisy to surface without more evidence.
    matched_value: the actual identifier value that matched
        (MAC string, IEEE address, etc.) — useful for debugging
        but not surfaced to users by default.
    """

    entity_id: str
    reason: str
    confidence: float
    matched_value: str = ""


@dataclass(frozen=True)
class EntityRecord:
    """Minimal entity-registry projection this lib needs."""

    entity_id: str
    device_id: str | None
    original_name: str | None = None


@dataclass(frozen=True)
class DeviceRecord:
    """Minimal device-registry projection.

    connections: list of (type, value) tuples. HA stores these as
        a set of frozenset-like things; flatten to a list of tuples
        for this lib. Common types: "mac", "bluetooth", "zigbee",
        "upnp", "usb".
    identifiers: list of (domain, id) tuples — the integration's
        internal device id. Two integrations sharing an identifier
        is rare but happens (Matter bridging exposes Hue identifiers
        for example).
    """

    device_id: str
    manufacturer: str | None = None
    model: str | None = None
    via_device_id: str | None = None
    connections: list[tuple[str, str]] = field(default_factory=list)
    identifiers: list[tuple[str, str]] = field(default_factory=list)


# Signal-strength table. Higher confidence = harder to fake by
# coincidence. MAC / IEEE / Bluetooth-address are unique-per-device
# at the protocol level; IP can be shared (NAT, IPv6) but is still
# strong; manufacturer+model+via_device is a weak heuristic that
# only fires when nothing better is available.
_CONFIDENCE_MAC: float = 0.95
_CONFIDENCE_BLUETOOTH: float = 0.95
_CONFIDENCE_ZIGBEE_IEEE: float = 0.95
_CONFIDENCE_IDENTIFIER: float = 0.90
_CONFIDENCE_IP_HOST: float = 0.75
_CONFIDENCE_MFR_MODEL_VIA: float = 0.55

# Card / WS consumers default to threshold 0.7; this lib emits
# candidates above 0.5 so consumers can adjust.
EMIT_THRESHOLD: float = 0.5


def find_dedup_candidates(
    entity_id: str,
    *,
    entity_records: dict[str, EntityRecord],
    device_records: dict[str, DeviceRecord],
    state_attributes: dict[str, dict[str, Any]] | None = None,
    max_candidates: int = 5,
) -> list[DedupCandidate]:
    """Find other entities that look like the same physical device.

    Args:
      entity_id: the entity to find duplicates of.
      entity_records: map of entity_id → EntityRecord. Caller builds
        this once per scan from `entity_registry.entities`.
      device_records: map of device_id → DeviceRecord. Caller builds
        this once per scan from `device_registry.devices`.
      state_attributes: optional map of entity_id → state.attributes.
        When provided, enables the IP / host attribute signal.
        Skip-safe when omitted (just no IP signal).
      max_candidates: cap the output at this size.

    Returns:
      List of DedupCandidate, sorted by confidence descending, with
      duplicates de-duplicated by entity_id (keep highest-confidence
      reason per duplicate target).
    """
    me_entity = entity_records.get(entity_id)
    if me_entity is None or me_entity.device_id is None:
        # Entity not in the registry, or not attached to a device —
        # we can't compare device-level signals. Skip; IP-attribute
        # fallback would be unreliable on its own.
        return []
    me_device = device_records.get(me_entity.device_id)
    if me_device is None:
        return []

    candidates: dict[str, DedupCandidate] = {}

    # Build my own static signal set ONCE so the per-other-device
    # comparison is O(signals) rather than O(signals * connections).
    my_mac = _connection_value(me_device, "mac")
    my_bluetooth = _connection_value(me_device, "bluetooth")
    my_zigbee = _connection_value(me_device, "zigbee")
    my_identifiers: set[tuple[str, str]] = set(me_device.identifiers)
    my_ip = _ip_attribute_value(entity_id, state_attributes)
    my_mfr_model_via = (
        me_device.manufacturer,
        me_device.model,
        me_device.via_device_id,
    )

    for other_eid, other_entity in entity_records.items():
        if other_eid == entity_id:
            continue
        # Same device_id = different entity exposing the same device.
        # HA already treats those as one device — not a "duplicate
        # physical device" finding for our purposes.
        if (
            other_entity.device_id is None
            or other_entity.device_id == me_entity.device_id
        ):
            continue
        other_device = device_records.get(other_entity.device_id)
        if other_device is None:
            continue

        candidate = _compare_devices(
            other_eid=other_eid,
            other_device=other_device,
            other_attributes=(
                state_attributes.get(other_eid, {})
                if state_attributes is not None
                else {}
            ),
            my_mac=my_mac,
            my_bluetooth=my_bluetooth,
            my_zigbee=my_zigbee,
            my_identifiers=my_identifiers,
            my_ip=my_ip,
            my_mfr_model_via=my_mfr_model_via,
        )
        if candidate is None or candidate.confidence < EMIT_THRESHOLD:
            continue
        # Dedup by entity_id; keep the highest-confidence reason.
        existing = candidates.get(other_eid)
        if existing is None or candidate.confidence > existing.confidence:
            candidates[other_eid] = candidate

    sorted_candidates = sorted(
        candidates.values(),
        key=lambda c: c.confidence,
        reverse=True,
    )
    return sorted_candidates[:max_candidates]


def _connection_value(device: DeviceRecord, kind: str) -> str | None:
    """Find the first connection of the given type, normalized."""
    for ct, cv in device.connections:
        if ct == kind and cv:
            return cv.lower()
    return None


def _ip_attribute_value(
    entity_id: str,
    state_attributes: dict[str, dict[str, Any]] | None,
) -> str | None:
    """Return IP/host attribute value for this entity, if exposed.

    Some integrations put `ip_address` on the state, others use
    `host`. Both treated equivalently.
    """
    if state_attributes is None:
        return None
    attrs = state_attributes.get(entity_id, {})
    for key in ("ip_address", "host"):
        val = attrs.get(key)
        if isinstance(val, str) and val:
            return val.lower()
    return None


def _compare_devices(
    *,
    other_eid: str,
    other_device: DeviceRecord,
    other_attributes: dict[str, Any],
    my_mac: str | None,
    my_bluetooth: str | None,
    my_zigbee: str | None,
    my_identifiers: set[tuple[str, str]],
    my_ip: str | None,
    my_mfr_model_via: tuple[str | None, str | None, str | None],
) -> DedupCandidate | None:
    """Return the best DedupCandidate (or None) for one comparison."""
    # MAC — strongest signal.
    other_mac = _connection_value(other_device, "mac")
    if my_mac and other_mac and my_mac == other_mac:
        return DedupCandidate(
            entity_id=other_eid,
            reason="shared MAC address",
            confidence=_CONFIDENCE_MAC,
            matched_value=my_mac,
        )

    # Bluetooth address — equally strong.
    other_bluetooth = _connection_value(other_device, "bluetooth")
    if my_bluetooth and other_bluetooth and my_bluetooth == other_bluetooth:
        return DedupCandidate(
            entity_id=other_eid,
            reason="shared Bluetooth address",
            confidence=_CONFIDENCE_BLUETOOTH,
            matched_value=my_bluetooth,
        )

    # Zigbee IEEE — unique per radio.
    other_zigbee = _connection_value(other_device, "zigbee")
    if my_zigbee and other_zigbee and my_zigbee == other_zigbee:
        return DedupCandidate(
            entity_id=other_eid,
            reason="shared Zigbee IEEE",
            confidence=_CONFIDENCE_ZIGBEE_IEEE,
            matched_value=my_zigbee,
        )

    # Identifier overlap — Matter bridges, etc.
    other_identifiers = set(other_device.identifiers)
    overlap = my_identifiers & other_identifiers
    if overlap:
        domain, id_val = next(iter(overlap))
        return DedupCandidate(
            entity_id=other_eid,
            reason=f"shared {domain} identifier",
            confidence=_CONFIDENCE_IDENTIFIER,
            matched_value=id_val,
        )

    # IP / host attribute — usable but noisier (NAT, IPv6, dual-stack
    # devices). Strong enough to surface, not strong enough to act on
    # automatically.
    other_ip: str | None = None
    for key in ("ip_address", "host"):
        val = other_attributes.get(key)
        if isinstance(val, str) and val:
            other_ip = val.lower()
            break
    if my_ip and other_ip and my_ip == other_ip:
        return DedupCandidate(
            entity_id=other_eid,
            reason="shared IP / host",
            confidence=_CONFIDENCE_IP_HOST,
            matched_value=my_ip,
        )

    # Manufacturer + model + via_device — weak; only when nothing
    # better matches. via_device_id MUST match (so two Hue lights via
    # the same bridge ARE NOT flagged — they have different
    # via_device_ids only if one is via Hue and the other via Matter
    # bridging Hue, which is the case we want to catch).
    other_mfr_model_via = (
        other_device.manufacturer,
        other_device.model,
        other_device.via_device_id,
    )
    if (
        all(v is not None for v in my_mfr_model_via)
        and my_mfr_model_via == other_mfr_model_via
    ):
        return DedupCandidate(
            entity_id=other_eid,
            reason="matching manufacturer + model + parent device",
            confidence=_CONFIDENCE_MFR_MODEL_VIA,
            matched_value=(
                f"{my_mfr_model_via[0]}/{my_mfr_model_via[1]}"
            ),
        )

    return None


__all__ = [
    "EMIT_THRESHOLD",
    "DedupCandidate",
    "DeviceRecord",
    "EntityRecord",
    "find_dedup_candidates",
]
