"""LLM agent client — call HA Conversation agents to explain insights.

Narrow surface. No prompt engineering tricks, no retrieval, no memory. Each
call is one-shot: insight in, prose out. The redactor applies BEFORE we
hand the prompt to HA's conversation integration; the redaction map is
used AFTER to dereference any pseudonyms in the response.

The HA Conversation API gives us agent picking via `agent_id`. We don't
re-implement provider selection — that's exactly what HA's existing
Conversation infrastructure handles.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .redactor import RedactionMap, Redactor

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from ..insight import Insight


_USER_PROMPT_TMPL = (
    "I'd like you to explain a Home Assistant routine I've been following.\n\n"
    "{title}\n\n"
    "This automation would:\n"
    "{payload_summary}\n\n"
    "In one or two short paragraphs, explain why this routine might be worth "
    "automating and any caveats. Plain prose, no code, under 150 words."
)


@dataclass(frozen=True)
class ExplanationResult:
    """Outcome of an Explain call."""

    explanation: str | None
    redaction_map: RedactionMap
    bytes_sent: int
    bytes_received: int
    success: bool
    error: str | None = None


def build_explain_prompt(
    insight: Insight, redacted_payload: dict, _ha_version: str = ""
) -> str:
    """Build a single self-contained user prompt for HA's Conversation API.

    HA's `conversation.async_converse` takes one `text` argument — there's no
    separate system-prompt slot. Each Conversation integration (Ollama,
    Anthropic, etc.) configures its own system prompt at the integration
    level. We just send a natural user-style question that any reasonable
    LLM can answer; rule-based agents will fail gracefully.

    The `_ha_version` parameter is kept for backwards-compatible test
    signatures but no longer used.
    """
    payload_summary = _summarize_payload(redacted_payload)
    return _USER_PROMPT_TMPL.format(
        title=insight.title,
        payload_summary=payload_summary,
    )


def _summarize_payload(payload: dict) -> str:
    """Render an automation dict as a few human-readable lines for the prompt."""
    lines: list[str] = []
    if alias := payload.get("alias"):
        lines.append(f"  Alias: {alias}")
    if triggers := payload.get("trigger"):
        for trigger in triggers if isinstance(triggers, list) else [triggers]:
            if isinstance(trigger, dict):
                platform = trigger.get("platform", "?")
                at = trigger.get("at")
                if platform == "time" and at:
                    lines.append(f"  Trigger: time {at}")
                else:
                    lines.append(f"  Trigger: {platform}")
    if conditions := payload.get("condition"):
        for cond in conditions if isinstance(conditions, list) else [conditions]:
            if isinstance(cond, dict) and cond.get("condition") == "time":
                weekdays = cond.get("weekday", [])
                lines.append(f"  Days: {', '.join(weekdays)}")
    if actions := payload.get("action"):
        for action in actions if isinstance(actions, list) else [actions]:
            if isinstance(action, dict):
                service = action.get("service", "?")
                target = action.get("target", {})
                eid = target.get("entity_id") if isinstance(target, dict) else None
                if eid:
                    lines.append(f"  Action: {service} on {eid}")
                else:
                    lines.append(f"  Action: {service}")
    return "\n".join(lines) if lines else "  (no readable summary)"


def _pick_llm_agent_id(hass: HomeAssistant, requested: str | None) -> str | None:
    """Pick an LLM-backed Conversation agent.

    If the caller passed an agent_id explicitly, honor it. Otherwise scan the
    entity_registry for a `conversation.*` entity not from the built-in
    `homeassistant` platform — that's an installed LLM Conversation
    integration (Google AI, OpenAI, Anthropic, Ollama, etc.). Falls back to
    None (HA's default agent) only if nothing else is installed.

    HA's `conversation.async_converse(agent_id=None)` routes to the
    conversation-domain default which on most installs is the rule-based
    `conversation.home_assistant`, even when the user's pipelines are
    configured to use an LLM agent. Auto-picking saves the user a config
    step and matches the spirit of their pipeline choice.
    """
    if requested is not None:
        return requested

    try:
        from homeassistant.helpers import entity_registry as er

        registry = er.async_get(hass)
        for entry in registry.entities.values():
            if not entry.entity_id.startswith("conversation."):
                continue
            # The built-in rule-based agent registers under platform="homeassistant"
            # whereas LLM integrations register under their own platform name.
            if entry.platform in {"homeassistant", "conversation"}:
                continue
            return entry.entity_id
    except Exception:  # pragma: no cover - defensive; fall back to default
        return None
    return None


async def explain_insight(
    hass: HomeAssistant,
    *,
    agent_id: str | None,
    insight: Insight,
    redactor: Redactor,
) -> ExplanationResult:
    """Call the configured Conversation agent and return an explanation.

    On any failure, returns a result with `success=False`. Caller is
    responsible for recording the audit log entry and updating the insight.
    """
    from homeassistant.components import conversation as ha_conversation

    chosen_agent_id = _pick_llm_agent_id(hass, agent_id)

    redacted_payload, redaction_map = await redactor.redact_insight_payload(
        insight.payload
    )
    redacted_title = (await redactor.redact_text(insight.title))[0]
    redacted_insight = type(insight)(
        id=insight.id,
        kind=insight.kind,
        detector=insight.detector,
        area_id=insight.area_id,
        title=redacted_title,
        confidence=insight.confidence,
        fingerprint={},
        payload=redacted_payload,
        payload_format=insight.payload_format,
        created_at=insight.created_at,
    )

    user_prompt = build_explain_prompt(redacted_insight, redacted_payload)
    bytes_sent = len(user_prompt.encode("utf-8"))

    try:
        result = await ha_conversation.async_converse(
            hass,
            text=user_prompt,
            conversation_id=None,
            context=None,
            language=None,
            agent_id=chosen_agent_id,
        )
    except Exception as err:  # surface any conversation failure to the user
        return ExplanationResult(
            explanation=None,
            redaction_map=redaction_map,
            bytes_sent=bytes_sent,
            bytes_received=0,
            success=False,
            error=str(err),
        )

    response_type = _extract_response_type(result)
    speech = _extract_speech(result)

    # Handle agent error responses — but distinguish:
    #   1. We routed to an LLM agent and IT failed (rate limit, API down, key
    #      invalid). Surface the agent's actual speech to the user.
    #   2. We fell back to HA's default rule-based agent and it returned
    #      "I don't understand". Surface install instructions for an LLM.
    if response_type and "error" in response_type.lower():
        is_llm_agent = (
            chosen_agent_id is not None
            and chosen_agent_id != "conversation.home_assistant"
        )
        if is_llm_agent:
            error_msg = (
                f"LLM agent ({chosen_agent_id}) returned an error: "
                f"{speech or '(no message)'}"
            )
        else:
            error_msg = (
                "Active Conversation agent isn't an LLM (rule-based fallback). "
                "Install an LLM Conversation integration like Anthropic, OpenAI, "
                "Google Generative AI, or Ollama, then select it as your agent."
            )
        return ExplanationResult(
            explanation=None,
            redaction_map=redaction_map,
            bytes_sent=bytes_sent,
            bytes_received=len(speech.encode("utf-8")) if speech else 0,
            success=False,
            error=error_msg,
        )

    if speech is None:
        return ExplanationResult(
            explanation=None,
            redaction_map=redaction_map,
            bytes_sent=bytes_sent,
            bytes_received=0,
            success=False,
            error="agent returned no speech",
        )

    dereffed = redaction_map.dereference(speech)
    return ExplanationResult(
        explanation=dereffed,
        redaction_map=redaction_map,
        bytes_sent=bytes_sent,
        bytes_received=len(speech.encode("utf-8")),
        success=True,
    )


def _extract_speech(result: object) -> str | None:
    """Drill into a ConversationResult-shaped object to get the plain speech.

    HA's conversation result shape is `result.response.speech.plain.speech`
    in current versions. We tolerate slight shape variation to survive
    minor HA upgrades.
    """
    response = getattr(result, "response", None)
    if response is None:
        return None
    speech_obj = getattr(response, "speech", None)
    if isinstance(speech_obj, dict):
        plain = speech_obj.get("plain")
        if isinstance(plain, dict):
            return plain.get("speech")
        if isinstance(plain, str):
            return plain
    speech_str = getattr(speech_obj, "plain", None)
    if isinstance(speech_str, str):
        return speech_str
    return None


def _extract_response_type(result: object) -> str | None:
    """Get the response_type as a lowercase string ('action_done', 'error', etc.)."""
    response = getattr(result, "response", None)
    if response is None:
        return None
    rt = getattr(response, "response_type", None)
    if rt is None:
        return None
    # Could be an enum (.value) or already a string
    return str(getattr(rt, "value", rt)).lower()
