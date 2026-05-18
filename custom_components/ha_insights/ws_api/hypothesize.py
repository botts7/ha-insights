"""WebSocket handler: ws_hypothesize.

Extracted from ``ws_api/__init__.py`` in v1.13.9 (step 7). The
handler asks the conversation agent for a plain-English causal
hypothesis behind an anomaly insight. Returns rationale + audit
trail; never writes state.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.components import websocket_api

from ._helpers import (
    _audit_attempts,
    _get_store,
    _resolve_blocked_entities,
    _resolve_preferred_agent_id,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/hypothesize",
        vol.Required("insight_id"): str,
        vol.Optional("agent_id"): vol.Any(str, None),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_hypothesize(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """LLM hypothesis generator for ANOMALY-kind insights.

    Same redactor + agent + dereference + audit shape as ws_explain, but
    asks the LLM for plausible causes ("battery dead?", "stuck contact?",
    "runaway automation?") instead of "should I automate this?". Returns
    the response text directly — not persisted on the insight, since
    hypotheses are throwaway suggestions the user can re-roll on demand.
    """
    from ..config_flow import get_blocked_entities
    from ..insight import InsightKind
    from ..llm import RedactionMode, Redactor, explain_insight

    store = _get_store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_set_up", "Store not initialized")
        return

    insight = await store.get_insight(msg["insight_id"])
    if insight is None:
        connection.send_error(
            msg["id"], "not_found", f"No insight {msg['insight_id']!r}"
        )
        return

    if insight.kind is not InsightKind.ANOMALY:
        connection.send_error(
            msg["id"],
            "invalid_kind",
            "Hypothesize only works on ANOMALY-kind insights",
        )
        return

    agent_id = msg.get("agent_id")
    blocked = _resolve_blocked_entities(hass, get_blocked_entities)
    preferred = _resolve_preferred_agent_id(hass)
    redactor = Redactor(
        store, mode=RedactionMode.AGGRESSIVE, blocked_entities=blocked
    )
    result = await explain_insight(
        hass,
        agent_id=agent_id,
        insight=insight,
        redactor=redactor,
        prompt_kind="hypothesize",
        preferred_agent_id=preferred,
    )

    await _audit_attempts(
        store, result.attempts, insight_id=insight.id, redactor=redactor
    )

    if not result.success:
        connection.send_error(
            msg["id"],
            "hypothesize_failed",
            result.error or "Conversation agent returned no speech",
        )
        return

    connection.send_result(
        msg["id"],
        {
            "hypothesis": result.explanation,
            "bytes_sent": result.bytes_sent,
            "bytes_received": result.bytes_received,
        },
    )


