"""WebSocket handler: ws_chat_create_automation.

Extracted from ``ws_api/__init__.py`` in v1.13.9 (step 7). The
"blank-canvas" chat handler: the user types a prompt, we feed it
(plus any related insights as grounding) to the conversation
agent, and return a YAML automation ready to apply.
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
from ._refine_helpers import (
    _CHAT_AUTOMATION_SKELETON,
    _build_chat_feedback,
    _humanize_llm_error,
    _resolve_audit_depth,
)
from .refine import _wrap_user_feedback

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/chat_create_automation",
        vol.Required("prompt"): vol.All(str, vol.Length(min=1, max=2000)),
        vol.Optional("agent_id"): vol.Any(str, None),
        vol.Optional("conversation_id"): vol.Any(str, None),
        vol.Optional("related_insight_ids", default=list): [str],
        vol.Optional("analysis_depth"): vol.In(["concise", "indepth"]),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_chat_create_automation(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Generate an automation YAML from a free-form user prompt.

    Closes the AI Agent HA competitive gap (May 2026 analysis). User
    types "turn on porch light at sunset" → we return YAML the card
    previews before applying via the existing `home_insights/apply`
    flow.

    Differentiator vs AI Agent HA: callers can pass
    `related_insight_ids` to surface high-confidence existing
    insights as LLM context. The card can pre-populate this from
    its current list view — e.g. "make me an automation for the
    pattern in insight schedule_porch_light_18:30" passes that
    insight's id so the LLM has both prose + concrete observed
    behaviour.

    Re-uses the existing `refine_insight` pipeline (same redactor,
    same Conversation-agent failover, same audit trail). Failures
    propagate through `_humanize_llm_error` so the card surfaces
    user-readable errors not stack traces.

    Privacy: full audit row per attempt via `_audit_attempts`,
    matching ws_refine + ws_refine_automation.
    """
    from datetime import UTC, datetime

    from ..config_flow import get_blocked_entities
    from ..insight import Insight, InsightKind
    from ..llm import RedactionMode, Redactor, refine_insight

    user_prompt: str = msg["prompt"]

    store = _get_store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_set_up", "Store not initialized")
        return

    # Resolve related insights for context. Bad / missing ids are
    # tolerated — silently dropped rather than failing the chat call.
    related_insights: list[Any] = []
    for ins_id in msg.get("related_insight_ids") or []:
        try:
            ins = await store.get_insight(ins_id)
        except Exception:
            ins = None
        if ins is not None:
            related_insights.append(ins)

    # Build a virtual insight wrapping the empty automation skeleton.
    # Same shape `ws_refine_automation` uses for refining existing
    # automations — the only difference is the skeleton payload vs
    # a populated raw_config.
    virtual_fingerprint = {
        "kind": "chat_create_automation",
        # Prompt hash isn't needed — every chat call gets a fresh
        # virtual id via the timestamp inside compute_id below.
        "timestamp_micros": int(datetime.now(tz=UTC).timestamp() * 1_000_000),
    }
    virtual_insight = Insight(
        id=Insight.compute_id(
            InsightKind.AUTOMATION_PROPOSAL, virtual_fingerprint,
        ),
        kind=InsightKind.AUTOMATION_PROPOSAL,
        detector="chat",
        area_id=None,
        title=(
            "Chat-created automation: " + (user_prompt[:80].strip() or "untitled")
        ),
        confidence=1.0,
        fingerprint=virtual_fingerprint,
        payload=dict(_CHAT_AUTOMATION_SKELETON),
        payload_format="automation",
        created_at=datetime.now(tz=UTC),
    )

    blocked = _resolve_blocked_entities(hass, get_blocked_entities)
    redactor = Redactor(
        store, mode=RedactionMode.AGGRESSIVE, blocked_entities=blocked,
    )
    preferred = _resolve_preferred_agent_id(hass)

    depth = _resolve_audit_depth(hass, msg.get("analysis_depth"))
    feedback = _wrap_user_feedback(
        _build_chat_feedback(user_prompt, related_insights),
        conversation_turn=1 if msg.get("conversation_id") else 0,
        depth=depth,
    )

    try:
        result = await refine_insight(
            hass,
            agent_id=msg.get("agent_id"),
            insight=virtual_insight,
            redactor=redactor,
            feedback=feedback,
            preferred_agent_id=preferred,
            conversation_id=msg.get("conversation_id"),
        )
    except Exception as err:
        connection.send_error(
            msg["id"], "chat_failed", _humanize_llm_error(str(err)),
        )
        return

    # Audit every attempt so failover round-trips appear in the
    # privacy log — matches ws_refine + ws_refine_automation.
    await _audit_attempts(
        store, result.attempts, insight_id=virtual_insight.id,
        redactor=redactor,
    )

    if not result.success or result.refined_payload is None:
        detail = result.error or "Chat-create returned no automation"
        if result.raw_response:
            snippet = result.raw_response.strip()
            if len(snippet) > 600:
                snippet = snippet[:600] + "…"
            detail = f"{detail}\n\nLLM said:\n{snippet}"
        connection.send_error(
            msg["id"], "chat_failed", _humanize_llm_error(detail),
        )
        return

    connection.send_result(
        msg["id"],
        {
            "refined_payload": result.refined_payload,
            "rationale": result.rationale,
            "diff_summary": result.diff_summary,
            "bytes_sent": result.bytes_sent,
            "bytes_received": result.bytes_received,
            "conversation_id": result.conversation_id,
            "related_insights_used": [
                {
                    "id": getattr(ins, "id", None),
                    "title": getattr(ins, "title", None),
                    "confidence": getattr(ins, "confidence", None),
                }
                for ins in related_insights
            ],
        },
    )


