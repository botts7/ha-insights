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

# v0.9 phase 6: alternative prompt for ANOMALY-kind insights. The user
# wants likely causes, not "should I automate this?". Numbered list keeps
# the response scannable in a small toast / panel section.
_USER_PROMPT_HYPOTHESIZE_TMPL = (
    "I'm looking at an unusual pattern from my Home Assistant instance "
    "and want help diagnosing it:\n\n"
    "{title}\n\n"
    "Details:\n{payload_summary}\n\n"
    "Suggest 2-3 plausible causes for this anomaly. Common ones (dead "
    "battery, network drop, stuck contact, manual override loop, runaway "
    "automation) are fine — be specific about which is most likely given "
    "the pattern above. Plain prose, numbered list, under 120 words."
)


@dataclass(frozen=True)
class AttemptAudit:
    """One row per LLM round-trip, for accurate audit logging.

    Failover may walk multiple candidates; each network round-trip MUST
    appear in the privacy log so users can see exactly what left their
    network. Earlier failed attempts get their own row; only the final
    attempt's payload bubbles up on the result for the WS reply.
    """

    chosen_agent_id: str | None
    bytes_sent: int
    bytes_received: int
    success: bool


@dataclass(frozen=True)
class ExplanationResult:
    """Outcome of an Explain call.

    `chosen_agent_id` is the agent that actually responded — relevant when
    failover walked the candidate list before landing on a working agent.
    Callers should audit-log against `attempts` (one row per attempt) so
    failed earlier attempts don't disappear from the privacy log.
    """

    explanation: str | None
    redaction_map: RedactionMap
    bytes_sent: int
    bytes_received: int
    success: bool
    error: str | None = None
    chosen_agent_id: str | None = None
    # v1.0 review #2: per-attempt audit rows. WS handlers iterate this
    # and call record_call for each so failed earlier attempts in a
    # failover chain don't escape the privacy log.
    attempts: tuple[AttemptAudit, ...] = ()


def build_hypothesize_prompt(insight: Insight, redacted_payload: dict) -> str:
    """Build a "what could cause this anomaly?" prompt.

    Uses the same payload-summary helper as explain so the LLM gets the
    same tabular view of triggers/conditions/actions, but with a
    diagnose-focused instruction.
    """
    payload_summary = _summarize_payload(redacted_payload)
    return _USER_PROMPT_HYPOTHESIZE_TMPL.format(
        title=insight.title,
        payload_summary=payload_summary,
    )


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
                # Spell it out so the LLM doesn't confuse the service name
                # (light.turn_off) for another entity_id.
                if eid:
                    lines.append(
                        f"  Call service: {service} (this turns the entity "
                        f"on or off depending on the service name)"
                    )
                    lines.append(f"  Target entity: {eid}")
                else:
                    lines.append(f"  Call service: {service}")
    return "\n".join(lines) if lines else "  (no readable summary)"


def _get_assist_default_agent_id(hass: HomeAssistant) -> str | None:
    """Best-effort lookup of HA's currently-configured default conversation agent.

    HA exposes the default through several APIs that have shifted shape across
    versions. We try the modern surface first, fall back to older forms, and
    return None if nothing matches. Pure read — never raises.
    """
    try:
        from homeassistant.components import conversation as ha_conv
    except Exception:
        return None
    # 2024.x+: conversation.async_get_default_agent(hass) returns the agent
    # object (or sometimes the entity_id directly on newer betas).
    candidate_attr = getattr(ha_conv, "async_get_default_agent", None)
    if callable(candidate_attr):
        try:
            agent = candidate_attr(hass)
        except Exception:
            agent = None
        if isinstance(agent, str):
            return agent
        entity_id = getattr(agent, "entity_id", None) if agent is not None else None
        if isinstance(entity_id, str):
            return entity_id
    # Older API path: conversation.get_agent_manager(hass).default_agent
    get_mgr = getattr(ha_conv, "get_agent_manager", None) or getattr(
        ha_conv, "_get_agent_manager", None
    )
    if callable(get_mgr):
        try:
            manager = get_mgr(hass)
        except Exception:
            manager = None
        default = getattr(manager, "default_agent", None) if manager else None
        if isinstance(default, str):
            return default
        entity_id = getattr(default, "entity_id", None) if default is not None else None
        if isinstance(entity_id, str):
            return entity_id
    return None


def _list_agent_candidates(
    hass: HomeAssistant,
    *,
    requested: str | None,
    preferred: str | None = None,
) -> list[str | None]:
    """Build the prioritized list of agents to try.

    Order:
      1. If `requested` is explicit (per-call WS pin), single-shot — respect
         the user's intent for this specific call, no failover.
      2. `preferred` (from OptionsFlow) — the user's persistent agent of
         choice. Tried first, but failover still walks the rest if it fails.
      3. Assist's configured default agent (skipping the rule-based built-in).
      4. All other non-builtin conversation.* entities, in registry order.
      5. None (HA's fallback) if nothing else is installed.

    Returns at minimum [None] so the caller never has an empty list.
    """
    if requested is not None:
        return [requested]

    seen: set[str] = set()
    candidates: list[str | None] = []

    if (
        isinstance(preferred, str)
        and preferred
        and preferred != "conversation.home_assistant"
    ):
        candidates.append(preferred)
        seen.add(preferred)

    assist_default = _get_assist_default_agent_id(hass)
    if (
        isinstance(assist_default, str)
        and assist_default != "conversation.home_assistant"
        and assist_default not in seen
    ):
        candidates.append(assist_default)
        seen.add(assist_default)

    try:
        from homeassistant.helpers import entity_registry as er

        registry = er.async_get(hass)
        for entry in registry.entities.values():
            if not entry.entity_id.startswith("conversation."):
                continue
            if entry.platform in {"homeassistant", "conversation"}:
                continue
            if entry.entity_id in seen:
                continue
            candidates.append(entry.entity_id)
            seen.add(entry.entity_id)
    except Exception:  # pragma: no cover — defensive
        pass

    if not candidates:
        # Nothing better installed — let HA route to whatever it deems default
        # (typically the rule-based built-in, which gracefully says "I don't
        # know"). Single attempt; no failover to try.
        candidates.append(None)
    return candidates


async def explain_insight(
    hass: HomeAssistant,
    *,
    agent_id: str | None,
    insight: Insight,
    redactor: Redactor,
    prompt_kind: str = "explain",
    preferred_agent_id: str | None = None,
) -> ExplanationResult:
    """Call the configured Conversation agent and return an LLM response.

    `prompt_kind` selects the user prompt:
      - "explain": "why is this routine worth automating?" (default)
      - "hypothesize": "what plausible causes could explain this anomaly?"

    Resolution order (auto-pick path, agent_id=None):
      1. `preferred_agent_id` from OptionsFlow — tried first, failover-eligible
      2. Assist's configured default agent
      3. Other installed LLM agents in registry order
    If `agent_id` is explicit (per-call WS pin), it short-circuits to a
    single attempt — no failover, respects the caller's intent.

    On any failure, returns the last attempt's result with `success=False`.
    Caller is responsible for recording the audit log entry against
    `result.chosen_agent_id`.
    """
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

    if prompt_kind == "hypothesize":
        user_prompt = build_hypothesize_prompt(redacted_insight, redacted_payload)
    else:
        user_prompt = build_explain_prompt(redacted_insight, redacted_payload)
    bytes_sent = len(user_prompt.encode("utf-8"))

    candidates = _list_agent_candidates(
        hass, requested=agent_id, preferred=preferred_agent_id
    )
    audits: list[AttemptAudit] = []
    last_result: ExplanationResult | None = None
    for candidate in candidates:
        last_result = await _explain_one_attempt(
            hass,
            chosen_agent_id=candidate,
            user_prompt=user_prompt,
            bytes_sent=bytes_sent,
            redaction_map=redaction_map,
        )
        audits.append(
            AttemptAudit(
                chosen_agent_id=last_result.chosen_agent_id,
                bytes_sent=last_result.bytes_sent,
                bytes_received=last_result.bytes_received,
                success=last_result.success,
            )
        )
        if last_result.success:
            return _with_attempts(last_result, audits)
    # All attempts failed — return the last (most recent) failure verbatim.
    # _list_agent_candidates always returns at least [None] so last_result
    # is guaranteed populated.
    assert last_result is not None
    return _with_attempts(last_result, audits)


def _with_attempts(
    result: ExplanationResult, audits: list[AttemptAudit]
) -> ExplanationResult:
    """Re-pack the frozen dataclass with the accumulated audit list."""
    from dataclasses import replace

    return replace(result, attempts=tuple(audits))


async def _explain_one_attempt(
    hass: HomeAssistant,
    *,
    chosen_agent_id: str | None,
    user_prompt: str,
    bytes_sent: int,
    redaction_map: RedactionMap,
) -> ExplanationResult:
    """Single-shot Conversation API call with redacted prompt + deref response."""
    from homeassistant.components import conversation as ha_conversation

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
            chosen_agent_id=chosen_agent_id,
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
            chosen_agent_id=chosen_agent_id,
        )

    if speech is None:
        return ExplanationResult(
            explanation=None,
            redaction_map=redaction_map,
            bytes_sent=bytes_sent,
            bytes_received=0,
            success=False,
            error="agent returned no speech",
            chosen_agent_id=chosen_agent_id,
        )

    dereffed = redaction_map.dereference(speech)
    return ExplanationResult(
        explanation=dereffed,
        redaction_map=redaction_map,
        bytes_sent=bytes_sent,
        bytes_received=len(speech.encode("utf-8")),
        success=True,
        chosen_agent_id=chosen_agent_id,
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


def _extract_conversation_id(result: object) -> str | None:
    """Pull `conversation_id` off a ConversationResult, if present.

    HA's conversation API echoes back (and assigns) a conversation_id on
    each call. Threading this id back into a follow-up call lets the
    agent maintain context — turning one-shot Refine into a multi-turn
    iterative dialogue. Tolerant of slight shape drift.
    """
    cid = getattr(result, "conversation_id", None)
    if isinstance(cid, str) and cid:
        return cid
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
