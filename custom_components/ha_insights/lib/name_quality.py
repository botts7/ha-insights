"""Name-quality scoring for HA entities.

Integrations populate entity names from very different sources, so the
quality of a name varies wildly across a typical install:

| Source                               | Typical quality                  |
|--------------------------------------|----------------------------------|
| User-overridden in HA                | ⭐⭐⭐⭐⭐ "Kitchen Floor Lamp"   |
| Tuya / Hue / HomeKit cloud           | ⭐⭐⭐⭐⭐ "Office Desk Light"    |
| ESPHome friendly_name                | ⭐⭐⭐⭐  "Bedroom Air Quality"  |
| Matter product name                  | ⭐⭐⭐  "Inovelli Dimmer"        |
| ZHA / Zigbee2MQTT manufacturer+model | ⭐⭐   "Aqara WSDCGQ11LM"        |
| BLE scanner default                  | ⭐    "ATC_a4c138_temperature"  |
| MQTT default / domain.uuid           | ⭐    "sensor.0x00158d000a1b2c" |

The Find-My-Device feature (v1.10+) cares because:
  - High-quality names mean "you don't need to identify this — the
    name already tells you where it is" → no 🔆 button needed.
  - Low-quality names mean "the only way to know what this is is to
    make it announce itself or perturb it" → 🔆 / 👆 / 📡 are the
    primary affordance.

The dedup detector (v1.11) cares because:
  - Two high-quality names that overlap (`Kitchen Floor Lamp` and
    `Kitchen Lamp`) are strong evidence the user has the same
    physical device exposed by two integrations.

Location inference (v1.11) cares because:
  - A high-quality name often contains the area itself
    ("Kitchen Light" → kitchen). Free area inference, no
    correlation math needed.

## Architecture

Pure function — no HA imports, no side effects. Takes simple
strings + optional attributes. Caller (`ws_api.py`) assembles
these from HA's entity / device / config-entry registries.

Per memory `ha_insights_find_my_device_roadmap`, this is the
foundational lib that the v1.10+ Find-My-Device features all
sit on top of. Building it first means the 🔆 button (Phase A)
and the dedup hint (v1.10.1) appear in the right places from
launch instead of needing a polish pass.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class NameQualityTier(StrEnum):
    """Discrete quality tiers, mapped to score ranges."""

    USER_OVERRIDE = "user_override"      # 1.00
    CLOUD_AUTHORITATIVE = "cloud"        # 0.85 — Tuya/Hue/HomeKit-style
    FRIENDLY_SET = "friendly_set"        # 0.70 — ESPHome friendly_name
    MANUFACTURER_MODEL = "mfr_model"     # 0.50 — ZHA / Zigbee2MQTT default
    GENERIC_DOMAIN = "generic_domain"    # 0.25 — domain.<random> patterns
    MAC_PATTERN = "mac_pattern"          # 0.10 — hex-blob / BLE scanner
    UNKNOWN = "unknown"                  # 0.00 — empty / unusable


_TIER_SCORE: dict[NameQualityTier, float] = {
    NameQualityTier.USER_OVERRIDE: 1.00,
    NameQualityTier.CLOUD_AUTHORITATIVE: 0.85,
    NameQualityTier.FRIENDLY_SET: 0.70,
    NameQualityTier.MANUFACTURER_MODEL: 0.50,
    NameQualityTier.GENERIC_DOMAIN: 0.25,
    NameQualityTier.MAC_PATTERN: 0.10,
    NameQualityTier.UNKNOWN: 0.00,
}


@dataclass(frozen=True)
class NameQuality:
    """Assessment of an entity's name quality.

    tier: which `NameQualityTier` the entity falls into. Use this
        for routing decisions ("show identify button?", "trust the
        name's area hint?") — discrete is easier to threshold than
        a float.
    score: 0.0–1.0, derived from `tier`. Use for ranking ("show me
        the worst-named entities first").
    chosen_name: the actual string we judged. Caller can render this
        directly so the user sees what was scored.
    source: free-text label for WHERE the name came from
        ("user_override", "tuya integration", "MAC-pattern fallback").
        UI / log strings; do not switch on this — switch on `tier`.
    reason: one short sentence explaining the decision. Surfaced in
        tooltips when the score is surprising.
    """

    tier: NameQualityTier
    score: float
    chosen_name: str
    source: str
    reason: str


# Cloud / app-pulled integrations that typically populate
# authoritative human names. Detected by config_entry.domain.
_CLOUD_INTEGRATIONS: frozenset[str] = frozenset(
    {
        "tuya",
        "smartlife",
        "hue",
        "homekit_controller",
        "homekit",
        "lifx",
        "nest",
        "google_home",
        "ring",
        "wyze",
        "tplink_omada",
        "tplink",  # Kasa cloud
        "yeelight",
        "wemo",
        "harmony",
        "lutron_caseta",
        "lutron",
        "smartthings",
        "myq",
        "august",
        "blink",
        "abode",
        "vivint",
        "rachio",
        "rainmachine",
    }
)

# Integrations where the name source is mostly a hex/MAC blob
# advertised by the device, with no user-overrideable cloud name.
_LOW_NAME_INTEGRATIONS: frozenset[str] = frozenset(
    {
        "bluetooth",
        "bthome",
        "ble_monitor",
        "xiaomi_ble",
        "govee_ble",
        "switchbot",
        "inkbird",
    }
)

# Pattern for "user wrote this": at least two letter groups separated
# by space or underscore, where each group is a real-looking word
# (≥ 2 chars, not all hex, contains a vowel).
_WORD_RE = re.compile(r"[a-zA-Z]{2,}")
_VOWEL_RE = re.compile(r"[aeiouy]", re.IGNORECASE)
# 6+ contiguous hex digits — strong MAC / device-id signal.
_HEX_BLOB_RE = re.compile(r"[0-9a-f]{6,}", re.IGNORECASE)
# MAC-style `xx:xx` or `xx-xx` segments.
_MAC_SEGMENT_RE = re.compile(r"[0-9a-f]{2}[:_-][0-9a-f]{2}", re.IGNORECASE)


def score_name_quality(
    entity_id: str,
    *,
    name_by_user: str | None = None,
    original_name: str | None = None,
    friendly_name: str | None = None,
    manufacturer: str | None = None,
    model: str | None = None,
    integration_domain: str | None = None,
) -> NameQuality:
    """Score one entity's name.

    Args:
      entity_id: HA entity_id. The object_id portion is the last-ditch
        name source when nothing else is set.
      name_by_user: ``EntityRegistryEntry.name`` — the user's HA-side
        override. When set + non-empty, ALWAYS wins.
      original_name: ``EntityRegistryEntry.original_name`` — the
        integration's name. Most callers should pass this.
      friendly_name: ``state.attributes.get("friendly_name")``.
        Reflects the EFFECTIVE name HA renders; usually matches
        ``original_name`` or ``name_by_user`` but ESPHome / some
        custom integrations populate it independently.
      manufacturer / model: ``DeviceRegistryEntry`` fields. Used to
        recognize the ZHA / Zigbee2MQTT "manufacturer Model"
        pattern that warrants a mid-tier score.
      integration_domain: ``ConfigEntry.domain`` for the entity's
        config entry. Used to identify cloud-authoritative
        integrations and known low-name-quality ones.

    Returns:
      `NameQuality` with the chosen tier, score, and human-readable
      reasoning.
    """
    # Tier 5 — user override always wins.
    if name_by_user and name_by_user.strip():
        return NameQuality(
            tier=NameQualityTier.USER_OVERRIDE,
            score=_TIER_SCORE[NameQualityTier.USER_OVERRIDE],
            chosen_name=name_by_user.strip(),
            source="user_override",
            reason="User set this name in HA.",
        )

    chosen = (
        (original_name or friendly_name or "").strip()
        or _object_id(entity_id)
    )
    integration = (integration_domain or "").lower()

    # Tier 4 — cloud-authoritative integrations. Trust their name
    # UNLESS it looks MAC-ish (some misconfigured cloud entries
    # still get a bad name).
    if integration in _CLOUD_INTEGRATIONS and not _looks_mac_ish(chosen):
        return NameQuality(
            tier=NameQualityTier.CLOUD_AUTHORITATIVE,
            score=_TIER_SCORE[NameQualityTier.CLOUD_AUTHORITATIVE],
            chosen_name=chosen,
            source=f"{integration} integration",
            reason=(
                f"Imported from the {integration} cloud where the user "
                "named the device."
            ),
        )

    # Tier 3 — ESPHome / similar where friendly_name is set
    # independently and the name reads like real words.
    if friendly_name and _reads_like_words(friendly_name):
        return NameQuality(
            tier=NameQualityTier.FRIENDLY_SET,
            score=_TIER_SCORE[NameQualityTier.FRIENDLY_SET],
            chosen_name=friendly_name.strip(),
            source="friendly_name attribute",
            reason=(
                "Reads as human-written words. Likely set in YAML / "
                "device config."
            ),
        )

    # Tier 2 — manufacturer + model concatenation (ZHA / Zigbee2MQTT).
    if manufacturer and model and (manufacturer in chosen or model in chosen):
        return NameQuality(
            tier=NameQualityTier.MANUFACTURER_MODEL,
            score=_TIER_SCORE[NameQualityTier.MANUFACTURER_MODEL],
            chosen_name=chosen,
            source="manufacturer + model fallback",
            reason=(
                f"Name is the device's manufacturer ({manufacturer}) "
                f"and model ({model}) — better than a hex blob, but "
                "doesn't tell you which physical device it is."
            ),
        )

    # Tier 1 — MAC / hex blob patterns. Worst.
    if _looks_mac_ish(chosen):
        return NameQuality(
            tier=NameQualityTier.MAC_PATTERN,
            score=_TIER_SCORE[NameQualityTier.MAC_PATTERN],
            chosen_name=chosen,
            source=(
                f"{integration} default"
                if integration in _LOW_NAME_INTEGRATIONS
                else "MAC-pattern fallback"
            ),
            reason=(
                "Name looks like a MAC address or device-id blob — "
                "no human signal to locate it from."
            ),
        )

    # Generic words but not really informative (e.g. "sensor 1").
    # Better than MAC, worse than ESPHome.
    if _reads_like_words(chosen):
        return NameQuality(
            tier=NameQualityTier.FRIENDLY_SET,
            score=_TIER_SCORE[NameQualityTier.FRIENDLY_SET],
            chosen_name=chosen,
            source="entity registry",
            reason="Reads as human-written words.",
        )

    # Anything else: generic domain.<random> pattern.
    if chosen:
        return NameQuality(
            tier=NameQualityTier.GENERIC_DOMAIN,
            score=_TIER_SCORE[NameQualityTier.GENERIC_DOMAIN],
            chosen_name=chosen,
            source="entity_id fallback",
            reason=(
                "No friendly name set; using the entity_id's object_id "
                "portion — usually generic."
            ),
        )

    # Truly empty (shouldn't happen given the object_id fallback).
    return NameQuality(
        tier=NameQualityTier.UNKNOWN,
        score=0.0,
        chosen_name=entity_id,
        source="no_name",
        reason="No name source available — falling back to entity_id.",
    )


def _object_id(entity_id: str) -> str:
    """Extract object_id portion: ``light.kitchen_lamp`` → ``Kitchen lamp``.

    Replaces underscores with spaces and title-cases the first word
    so the visual result reads better than the raw object_id.
    """
    if "." in entity_id:
        return entity_id.split(".", 1)[1].replace("_", " ").strip()
    return entity_id


def _looks_mac_ish(name: str) -> bool:
    """True when the name is dominated by hex / MAC patterns."""
    if not name:
        return False
    # Explicit MAC-segment pattern — always disqualifying.
    if _MAC_SEGMENT_RE.search(name):
        return True
    # Long contiguous hex blob (≥6 chars). On its own a "deadbeef"-
    # style identifier; combined with a generic word like
    # "_temperature" it still gives the user no actionable hint.
    return bool(_HEX_BLOB_RE.search(name))


def _reads_like_words(name: str) -> bool:
    """True when the name contains ≥2 real-looking words.

    "Kitchen Lamp" → True
    "ATC_a4c138" → False (one short word + hex)
    "Bedroom Air Quality" → True
    "sensor 1" → False (one word + digit)
    """
    if not name:
        return False
    words = _WORD_RE.findall(name)
    real_words = [w for w in words if _VOWEL_RE.search(w) and len(w) >= 3]
    return len(real_words) >= 2


__all__ = [
    "NameQuality",
    "NameQualityTier",
    "score_name_quality",
]
