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


_SYSTEM_PROMPT_TMPL = (
    "You are explaining a detected home automation routine to a Home Assistant user.\n"
    "Home Assistant version: {ha_version}\n"
    "Use only documented HA core features that exist in {ha_version_major}+.\n"
    "Do not reference specific integrations not present in the payload.\n"
    "Keep your explanation under 200 words. Plain prose, no code."
)

_USER_PROMPT_TMPL = (
    "Explain this routine the user has been following:\n\n"
    "Title: {title}\n"
    "Confidence: {confidence:.0%}\n"
    "Action that would be automated:\n"
    "{payload_summary}\n\n"
    "Explain when this happens and why it might be worth automating."
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
    insight: Insight, redacted_payload: dict, ha_version: str
) -> tuple[str, str]:
    """Build (system_prompt, user_prompt) for the LLM."""
    payload_summary = _summarize_payload(redacted_payload)
    system = _SYSTEM_PROMPT_TMPL.format(
        ha_version=ha_version,
        ha_version_major=ha_version.rsplit(".", 1)[0] if "." in ha_version else ha_version,
    )
    user = _USER_PROMPT_TMPL.format(
        title=insight.title,
        confidence=insight.confidence,
        payload_summary=payload_summary,
    )
    return system, user


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

    ha_version = getattr(hass.config, "version", "unknown")
    system_prompt, user_prompt = build_explain_prompt(
        redacted_insight, redacted_payload, str(ha_version)
    )
    full_prompt = system_prompt + "\n\n" + user_prompt
    bytes_sent = len(full_prompt.encode("utf-8"))

    try:
        result = await ha_conversation.async_converse(
            hass,
            text=full_prompt,
            conversation_id=None,
            context=None,
            language=None,
            agent_id=agent_id,
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

    speech = _extract_speech(result)
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
