"""Outbound-call audit log.

Every LLM call writes one row to the `outbound_calls` table so the user can
inspect what left their network. The `sensor.ha_insights_privacy_log` entity
(see `sensor.py`) surfaces a 24h summary, and the panel's audit log section
exposes the per-call rows via `home_insights/audit_log`.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..store import InsightStore


# Conversation-agent platforms that run locally (data stays on the network).
# Used to classify each call as "local" or "cloud" in the audit log so users
# (and `sensor.ha_insights_privacy_log`) can see at a glance how much of
# their LLM activity is leaving the network.
_LOCAL_AGENT_PLATFORMS: frozenset[str] = frozenset({
    "ollama",        # popular local LLM runner
    "piper",         # local TTS — usually wired as STT-only but lists as conversation
    "wyoming",       # protocol; usually local-side
    "homeassistant", # built-in rule-based agent (no network)
    "conversation",  # default conversation entity
})


def derive_agent_locality(agent_id: str | None) -> str:
    """Best-effort classify an agent_id as local / cloud / unknown.

    Looks at the entity's domain prefix and any well-known platform name
    embedded in the entity_id. We default to "cloud" for anything that
    looks like a Conversation entity from a known cloud provider, and
    "local" for entities from local providers. Falls back to "unknown"
    for unrecognized agents.
    """
    if not agent_id:
        return "unknown"
    lowered = agent_id.lower()
    # Default-agent / built-in rule-based path
    if lowered == "conversation.home_assistant":
        return "local"
    # Look for known local platform substrings in the entity slug
    for marker in _LOCAL_AGENT_PLATFORMS:
        if marker in lowered:
            return "local"
    # Known cloud platform substrings
    cloud_markers = (
        "anthropic",
        "openai",
        "google",
        "gemini",
        "claude",
        "cloud",      # nabu casa cloud
    )
    for marker in cloud_markers:
        if marker in lowered:
            return "cloud"
    return "unknown"


async def record_call(
    store: InsightStore,
    *,
    insight_id: str | None,
    agent: str,
    agent_locality: str,
    redaction_mode: str,
    bytes_sent: int,
    bytes_received: int | None,
    success: bool,
    redacted_payload: dict | None = None,
) -> None:
    """Append an entry to outbound_calls."""
    from datetime import UTC, datetime

    payload_json = (
        json.dumps(redacted_payload, sort_keys=True) if redacted_payload else None
    )
    await store._c.execute(  # intentional cross-module write to the same store
        """
        INSERT INTO outbound_calls (
            timestamp, insight_id, agent, agent_locality, redaction_mode,
            bytes_sent, bytes_received, success, redacted_payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now(tz=UTC).timestamp(),
            insight_id,
            agent,
            agent_locality,
            redaction_mode,
            bytes_sent,
            bytes_received,
            1 if success else 0,
            payload_json,
        ),
    )
    await store._c.commit()
