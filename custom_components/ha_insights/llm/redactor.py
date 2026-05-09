"""Redactor — pseudonymize entity_ids + strip sensitive attributes.

Privacy modes (configured via the wizard, stored on the config entry):

  OFF        — LLM disabled entirely. Redactor not called.
  AGGRESSIVE — entity_ids replaced with stable pseudonyms; numeric bucketing on
  BALANCED   — entity_ids pseudonymized but pseudonyms stay stable across calls
  PERMISSIVE — real entity_ids pass through (opt-in, banner warning)

Always-redacted attributes are stripped regardless of mode — that's the
hard floor below which we never go.

Returns a RedactionMap so the LLM response can be dereferenced back to
real entity_ids before being shown to the user.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..store import InsightStore


class RedactionMode(StrEnum):
    OFF = "off"
    AGGRESSIVE = "aggressive"
    BALANCED = "balanced"
    PERMISSIVE = "permissive"


# Hard floor — these names are stripped from any payload the LLM sees,
# regardless of mode. User-editable additions live in detector_config.
ALWAYS_REDACT_ATTRIBUTES: frozenset[str] = frozenset({
    # GPS / geo
    "gps_lat", "gps_lon", "gps_accuracy", "latitude", "longitude", "altitude",
    # Network identifiers
    "mac", "ip", "ip_address", "bssid", "ssid",
    # Credentials
    "password", "token", "access_token", "auth", "api_key", "secret",
    # Hardware identifiers
    "serial_number", "device_id",
})

_ENTITY_ID_RE = re.compile(r"\b([a-z_]+)\.([a-z0-9_]+)\b")


@dataclass(frozen=True)
class RedactionMap:
    """Tracks pseudonymization so LLM output can be dereferenced.

    `entity_to_pseudonym` covers what we sent; `pseudonym_to_entity` is the
    inverse for parsing the LLM's response. `entities_blocked` records
    entity_ids that were stripped entirely due to per-entity opt-out
    (different from being attributes-stripped).
    """

    entity_to_pseudonym: dict[str, str] = field(default_factory=dict)
    pseudonym_to_entity: dict[str, str] = field(default_factory=dict)
    attributes_stripped: list[str] = field(default_factory=list)
    entities_blocked: list[str] = field(default_factory=list)

    def dereference(self, text: str) -> str:
        """Replace any pseudonyms in `text` with their real entity_ids."""
        if not self.pseudonym_to_entity:
            return text
        result = text
        # Sort by length descending so longer pseudonyms match first (avoids
        # partial overlap when one pseudonym is a prefix of another).
        for pseudonym in sorted(self.pseudonym_to_entity, key=len, reverse=True):
            result = result.replace(pseudonym, self.pseudonym_to_entity[pseudonym])
        return result


class Redactor:
    """Apply privacy redaction to insight payloads bound for an LLM."""

    def __init__(
        self,
        store: InsightStore,
        *,
        mode: RedactionMode = RedactionMode.AGGRESSIVE,
        extra_attribute_blocklist: frozenset[str] | None = None,
        blocked_entities: frozenset[str] | None = None,
    ) -> None:
        self._store = store
        self._mode = mode
        self._blocklist = ALWAYS_REDACT_ATTRIBUTES | (extra_attribute_blocklist or frozenset())
        # Privacy floor — these entity_ids are stripped from any LLM-bound
        # payload regardless of mode. The redactor refuses to forward them
        # in any form (real, pseudonymized, or as substring inside a value).
        self._blocked_entities = blocked_entities or frozenset()

    @property
    def blocked_entities(self) -> frozenset[str]:
        return self._blocked_entities

    @property
    def mode(self) -> RedactionMode:
        return self._mode

    async def redact_insight_payload(
        self, insight_payload: dict[str, Any]
    ) -> tuple[dict[str, Any], RedactionMap]:
        """Redact an insight's payload dict, returning the redacted copy + map.

        The original is never mutated. The map allows dereferencing LLM
        responses that mention pseudonyms back to real entity_ids.
        """
        redaction_map = RedactionMap()
        if self._mode is RedactionMode.OFF:
            # Caller shouldn't reach the redactor in OFF mode, but be safe.
            return self.strip_attributes_recursive(insight_payload, redaction_map), redaction_map

        if self._mode is RedactionMode.PERMISSIVE:
            return self.strip_attributes_recursive(insight_payload, redaction_map), redaction_map

        # AGGRESSIVE / BALANCED — pseudonymize entity_ids, strip attributes
        cleaned = self.strip_attributes_recursive(insight_payload, redaction_map)
        return await self._pseudonymize_recursive(cleaned, redaction_map), redaction_map

    async def redact_text(self, text: str) -> tuple[str, RedactionMap]:
        """Redact a free-text string (e.g. an insight title)."""
        redaction_map = RedactionMap()
        if self._mode in (RedactionMode.OFF, RedactionMode.PERMISSIVE):
            return text, redaction_map
        return await self._pseudonymize_text(text, redaction_map), redaction_map

    def strip_attributes_recursive(
        self, value: Any, redaction_map: RedactionMap
    ) -> Any:
        """Walk a nested structure, dropping any blocklisted attribute keys.

        Mutates a fresh copy; the input is never touched. Also enforces the
        per-entity opt-out: any value that mentions a blocked entity_id is
        replaced with a `[blocked]` placeholder, and dict items whose
        `entity_id` field references a blocked entity are dropped wholesale.
        """
        if isinstance(value, dict):
            cleaned: dict[str, Any] = {}
            for key, sub in value.items():
                if isinstance(key, str) and key.lower() in self._blocklist:
                    redaction_map.attributes_stripped.append(key)
                    continue
                cleaned[key] = self.strip_attributes_recursive(sub, redaction_map)
            # If the cleaned dict references a blocked entity_id directly
            # (e.g. {"entity_id": "lock.front_door"}), drop the value to a
            # marker so the LLM never sees it.
            eid = cleaned.get("entity_id")
            if isinstance(eid, str) and eid in self._blocked_entities:
                if eid not in redaction_map.entities_blocked:
                    redaction_map.entities_blocked.append(eid)
                return {"entity_id": "[blocked]"}
            if isinstance(eid, list):
                filtered = [e for e in eid if e not in self._blocked_entities]
                dropped = [e for e in eid if e in self._blocked_entities]
                for e in dropped:
                    if e not in redaction_map.entities_blocked:
                        redaction_map.entities_blocked.append(e)
                if dropped:
                    cleaned["entity_id"] = filtered or ["[blocked]"]
            return cleaned
        if isinstance(value, list):
            return [self.strip_attributes_recursive(item, redaction_map) for item in value]
        if isinstance(value, str) and value in self._blocked_entities:
            if value not in redaction_map.entities_blocked:
                redaction_map.entities_blocked.append(value)
            return "[blocked]"
        return value

    async def _pseudonymize_recursive(
        self, value: Any, redaction_map: RedactionMap
    ) -> Any:
        """Walk and replace any entity_id-shaped strings with pseudonyms."""
        if isinstance(value, str):
            return await self._pseudonymize_text(value, redaction_map)
        if isinstance(value, dict):
            return {
                key: await self._pseudonymize_recursive(sub, redaction_map)
                for key, sub in value.items()
            }
        if isinstance(value, list):
            return [
                await self._pseudonymize_recursive(item, redaction_map)
                for item in value
            ]
        return value

    async def _pseudonymize_text(
        self, text: str, redaction_map: RedactionMap
    ) -> str:
        """Replace any entity_id-shaped substrings with their pseudonym.

        Blocked entities are replaced with `[blocked]` instead of a
        pseudonym — they shouldn't even be referenceable.
        """
        matches = list(_ENTITY_ID_RE.finditer(text))
        if not matches:
            return text
        result_parts: list[str] = []
        last_end = 0
        for match in matches:
            entity_id = match.group(0)
            start, end = match.span()
            if entity_id in self._blocked_entities:
                if entity_id not in redaction_map.entities_blocked:
                    redaction_map.entities_blocked.append(entity_id)
                replacement = "[blocked]"
            else:
                replacement = await self._get_or_record_pseudonym(
                    entity_id, redaction_map
                )
            result_parts.append(text[last_end:start])
            result_parts.append(replacement)
            last_end = end
        result_parts.append(text[last_end:])
        return "".join(result_parts)

    async def _get_or_record_pseudonym(
        self, entity_id: str, redaction_map: RedactionMap
    ) -> str:
        """Lookup-or-create a pseudonym and record it in the map."""
        if entity_id in redaction_map.entity_to_pseudonym:
            return redaction_map.entity_to_pseudonym[entity_id]
        pseudonym = await self._store.get_or_create_pseudonym(entity_id)
        redaction_map.entity_to_pseudonym[entity_id] = pseudonym
        redaction_map.pseudonym_to_entity[pseudonym] = entity_id
        return pseudonym
