"""LLM refiner — propose modifications to an automation insight.

Takes an `AUTOMATION_PROPOSAL` insight (and optionally the LLM's prior
explanation), asks the LLM to refine the YAML to address considerations
it raised, then validates the response is structurally sound and only
references entities that were in the original proposal.

Failure surfaces are explicit. We never silently retry — invalid output
returns a specific error so the user can decide whether to refine again.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import yaml

from ..apply.validator import validate_automation
from .agent_client import (
    AttemptAudit,
    _extract_conversation_id,
    _extract_response_type,
    _extract_speech,
    _list_agent_candidates,
)
from .redactor import RedactionMap, Redactor

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from ..insight import Insight


_REFINE_PROMPT_TMPL = (
    "Refine this Home Assistant automation. Add a debounce, condition, or "
    "mode change as appropriate. Be terse — keep the YAML minimal.\n\n"
    "Budget discipline (CRITICAL):\n"
    "- Keep the entire response under 250 tokens.\n"
    "- If you cannot produce a complete valid YAML refinement within that\n"
    "  budget, output exactly this single line and NOTHING ELSE:\n"
    "    INSUFFICIENT_BUDGET\n"
    "- Do NOT start emitting YAML you cannot finish. A truncated YAML is\n"
    "  worse than admitting the budget is too tight.\n\n"
    "Otherwise, output exactly two sections (no markdown fences, no extra\n"
    "commentary):\n"
    "RATIONALE: <one short sentence>\n"
    "YAML:\n"
    "alias: ...\n"
    "trigger: [...]\n"
    "action: [...]\n"
    "mode: ...\n\n"
    "Constraints (strict):\n"
    "- Use ONLY these entity_ids: {entity_list}\n"
    "- Output must be complete valid YAML (close all quotes/brackets)\n\n"
    "Current automation:\n"
    "{current_yaml}\n\n"
    "Considerations: {considerations}\n"
)


# Sentinel the LLM emits when it can't fit a complete refinement in budget.
# We instruct it explicitly above; reliable enough on Gemini Pro / Flash,
# Claude, GPT-4, Llama 3.x. Cheaper rule-based agents won't emit it but
# they also can't refine, so the existing rule-based fallback path catches
# them earlier.
INSUFFICIENT_BUDGET_MARKER = "INSUFFICIENT_BUDGET"


@dataclass(frozen=True)
class RefinementResult:
    """Outcome of a Refine call.

    `success=False` populates `error` with a user-readable explanation.
    `raw_response` is included on failure for debugging — never on success.
    `chosen_agent_id` reports which agent actually responded, relevant when
    failover walked the candidate list before landing on a working agent.
    """

    refined_payload: dict[str, Any] | None
    rationale: str | None
    diff_summary: list[str]
    redaction_map: RedactionMap
    bytes_sent: int
    bytes_received: int
    success: bool
    error: str | None = None
    raw_response: str | None = None
    chosen_agent_id: str | None = None
    # v1.0 RC #2: agent's conversation_id from HA's Conversation API.
    # Threading this back on follow-up Refine calls turns the one-shot
    # exchange into a multi-turn dialogue (the agent remembers what it
    # proposed last time and what feedback led to changes).
    conversation_id: str | None = None
    # v1.0 review #2: per-attempt audit rows. WS handler iterates this
    # and calls record_call per row so failed earlier attempts in a
    # failover chain don't escape the privacy log.
    attempts: tuple[AttemptAudit, ...] = ()

    @classmethod
    def failure(
        cls,
        *,
        error: str,
        redaction_map: RedactionMap,
        bytes_sent: int,
        bytes_received: int = 0,
        rationale: str | None = None,
        raw_response: str | None = None,
        chosen_agent_id: str | None = None,
    ) -> RefinementResult:
        """Build a failure result with sensible defaults for unused fields.

        Collapses what was previously 8 nearly-identical constructor
        calls into named-arg sites that show only what's actually
        different per failure path. v1.0 review #14.
        """
        return cls(
            refined_payload=None,
            rationale=rationale,
            diff_summary=[],
            redaction_map=redaction_map,
            bytes_sent=bytes_sent,
            bytes_received=bytes_received,
            success=False,
            error=error,
            raw_response=raw_response,
            chosen_agent_id=chosen_agent_id,
        )


def _yaml_dump(payload: dict[str, Any]) -> str:
    return yaml.safe_dump(payload, default_flow_style=False, sort_keys=False).strip()


_ENTITY_ID_FIELDS: frozenset[str] = frozenset(
    {"entity_id", "entity_ids"}
)


def _collect_entity_ids(
    value: Any,
    accumulator: set[str],
    *,
    in_entity_field: bool = False,
) -> None:
    """Walk a payload and gather entity_id values in entity-id-bearing fields.

    Only string values reached via known entity_id keys (`entity_id`,
    `entity_ids`) are collected. This avoids false-positives like
    `light.turn_off` (a service name in `service:`) being treated as a
    hallucinated entity_id during refinement validation.

    For free-text fields like `alias`, `description`, or `message`, we
    don't scan — refinements may legitimately mention services or new
    descriptive text without the entity-id constraint applying.
    """
    if isinstance(value, str):
        if not in_entity_field:
            return
        for match in re.finditer(r"\b([a-z_]+)\.([a-z0-9_]+)\b", value):
            accumulator.add(match.group(0))
    elif isinstance(value, dict):
        for key, sub in value.items():
            sub_in_entity_field = (
                in_entity_field
                or (isinstance(key, str) and key in _ENTITY_ID_FIELDS)
            )
            _collect_entity_ids(
                sub, accumulator, in_entity_field=sub_in_entity_field
            )
    elif isinstance(value, list):
        for item in value:
            _collect_entity_ids(
                item, accumulator, in_entity_field=in_entity_field
            )


def build_refine_prompt(
    redacted_payload: dict[str, Any],
    *,
    prior_explanation: str | None,
    feedback: str | None = None,
) -> str:
    entities: set[str] = set()
    _collect_entity_ids(redacted_payload, entities)
    parts: list[str] = []
    if feedback:
        # User feedback is the highest-priority instruction; place it first.
        parts.append(f"USER FEEDBACK: {feedback.strip()}")
    if prior_explanation:
        parts.append(prior_explanation.strip())
    if not parts:
        parts.append("(infer common-sense caveats)")
    considerations = "\n".join(parts)
    return _REFINE_PROMPT_TMPL.format(
        entity_list=", ".join(sorted(entities)) or "(none)",
        current_yaml=_yaml_dump(redacted_payload),
        considerations=considerations,
    )


def parse_refine_response(text: str) -> tuple[str | None, dict[str, Any] | None, str | None]:
    """Return (rationale, payload, error). Exactly one of (payload, error) is set."""
    if not text:
        return None, None, "empty response"

    # Honor the LLM's explicit budget surrender before trying to parse.
    early_lines = [line.strip() for line in text.strip().splitlines()[:5]]
    if INSUFFICIENT_BUDGET_MARKER in early_lines:
        return None, None, (
            "LLM said it can't produce a complete refinement within its "
            "current token budget. Increase max_output_tokens in your LLM "
            "Conversation integration's config (try 4096+), or switch to a "
            "non-thinking model that uses tokens more efficiently."
        )

    # Detect provider safety / policy refusals before treating "no YAML"
    # as a parser failure. These are model-side decisions to refuse the
    # task, not user errors. Common phrasings across Gemini, Claude, GPT.
    if _looks_like_refusal(text):
        return None, None, (
            "LLM declined to refine this automation (safety / policy "
            "refusal from the model). Try a different agent, rephrase "
            "your considerations, or switch the conversation integration "
            "to a model with looser policies."
        )

    # Match the RATIONALE line specifically (one logical line, not greedy
    # over a YAML block). If the LLM emits an empty `RATIONALE:` line
    # followed by YAML:, an unbounded `(.+?)` with DOTALL would capture
    # the whole YAML body as the rationale because the lookahead
    # `(?=\n\s*YAML:|\Z)` doesn't match when YAML: is the very next non-
    # whitespace token. Use a single-line capture instead.
    rationale_match = re.search(r"RATIONALE:[ \t]*([^\n\r]*)", text)
    rationale_raw = rationale_match.group(1).strip() if rationale_match else None
    rationale = rationale_raw if rationale_raw else None
    yaml_match = re.search(r"YAML:\s*(.+)", text, re.DOTALL)

    if yaml_match is None:
        return rationale, None, "missing YAML section"

    yaml_body = yaml_match.group(1).strip()
    # Strip ```yaml ... ``` fences if the LLM added them despite our prompt
    yaml_body = re.sub(r"^```(?:yaml|yml)?\s*\n?", "", yaml_body)
    yaml_body = re.sub(r"\n?```\s*$", "", yaml_body)

    try:
        parsed = yaml.safe_load(yaml_body)
    except yaml.YAMLError as exc:
        # Detect truncation patterns so users get an actionable error.
        if _looks_truncated(yaml_body):
            return rationale, None, (
                "LLM response was cut off mid-YAML — likely hit "
                "max_output_tokens. Increase the limit in your LLM "
                "Conversation integration's config (Settings → Devices & "
                "Services → your LLM → Configure → Maximum tokens)."
            )
        return rationale, None, f"YAML parse failed: {exc}"

    if not isinstance(parsed, dict):
        return rationale, None, "YAML did not parse to a mapping"

    return rationale, parsed, None


_REFUSAL_PHRASES: tuple[str, ...] = (
    "i cannot help",
    "i can't help",
    "i can not help",
    "i'm not able to",
    "i am not able to",
    "i'm unable",
    "i am unable",
    "i won't",
    "i will not",
    "i must decline",
    "i refuse",
    "as an ai",
    "i don't have the ability",
    "i do not have the ability",
    "cannot generate",
    "can't generate",
    "cannot modify",
    "can't modify",
    "cannot assist",
    "can't assist",
    "against my",
    "i'm sorry, but i can",
    "i am sorry, but i can",
)


def _looks_like_refusal(text: str) -> bool:
    """Provider-side safety refusal — no YAML, no rationale, just a no.

    We check the first ~300 chars (refusals come up front; YAML always
    later if at all). Case-insensitive substring match against a list of
    common refusal openers across major LLM providers.
    """
    if not text:
        return False
    head = text[:300].lower()
    # If there's a YAML section, the model isn't refusing; it generated
    # something. Skip the refusal check.
    if "yaml:" in head:
        return False
    return any(phrase in head for phrase in _REFUSAL_PHRASES)


def _looks_truncated(yaml_body: str) -> bool:
    """Heuristics for token-limit truncation.

    Catches cases the YAML parser would either reject outright (unclosed
    quote/bracket) AND cases where the body parses but ends mid-key.
    """
    if not yaml_body:
        return True
    text = yaml_body.rstrip()
    last_line = text.splitlines()[-1] if text else ""
    # Unterminated single/double quote on the last non-empty line
    if last_line.count("'") % 2 == 1 or last_line.count('"') % 2 == 1:
        return True
    # Unbalanced brackets across the whole body
    if yaml_body.count("[") != yaml_body.count("]"):
        return True
    if yaml_body.count("{") != yaml_body.count("}"):
        return True
    stripped = last_line.rstrip()
    # Trailing colon — key opened, no value
    if stripped.endswith(":") and not stripped.endswith("::"):
        return True
    # Dangling list dash
    if stripped.endswith(("- ", "-")) and len(stripped) <= 4:
        return True
    # Last line is a bare indented identifier (no colon, no dash, no value).
    # E.g. "    target" — the LLM was about to type ":" + a target dict
    # but ran out of tokens. yaml.safe_load may either raise or coerce
    # depending on context.
    if re.fullmatch(r"\s*[a-zA-Z_][a-zA-Z0-9_]*\s*", last_line):
        return True
    # Our prompt explicitly asks for `mode: ...` as the final block. If it's
    # missing entirely, the response was cut off before the LLM got there.
    if "mode:" not in yaml_body and "mode :" not in yaml_body:
        return True
    return False


def _looks_structurally_incomplete(payload: dict[str, Any]) -> bool:
    """A parsed-but-broken payload that's likely a token-limit cut-off.

    `validate_automation` rejects on shape errors, but we want to give the
    user a more actionable error than "trigger[0] must be a dict" if the
    real issue is "the YAML stopped halfway through emitting the trigger."
    """
    required = {"alias", "trigger", "action", "mode"}
    missing = required - set(payload.keys())
    # Missing 'action' is the dead-giveaway truncation pattern: LLMs emit
    # alias -> trigger -> action -> mode in order, so 'action' missing
    # almost always means the response stopped between trigger and action.
    if "action" in missing and "trigger" in payload:
        return True
    # Trigger present but not a list-of-dicts (e.g. partial string value)
    triggers = payload.get("trigger")
    if triggers is not None and not isinstance(triggers, list):
        return True
    if isinstance(triggers, list):
        for trigger in triggers:
            if not isinstance(trigger, dict):
                return True
    return False


def diff_payloads(original: dict[str, Any], refined: dict[str, Any]) -> list[str]:
    """Top-level key-by-key summary. Sufficient for the modal preview.

    `+ key` for new, `- key` for removed, `~ key` for changed value.
    Skips `id` since the writer regenerates it.
    """
    summary: list[str] = []
    skip = {"id"}
    keys = (set(original) | set(refined)) - skip
    for key in sorted(keys):
        in_orig, in_refined = key in original, key in refined
        if in_orig and not in_refined:
            summary.append(f"- {key}")
        elif in_refined and not in_orig:
            summary.append(f"+ {key}")
        elif original.get(key) != refined.get(key):
            summary.append(f"~ {key}")
    return summary


def _validate_refined(
    refined: dict[str, Any],
    allowed_entities: set[str],
) -> str | None:
    """Return error string on failure, None on success."""
    shape_errors = validate_automation(refined)
    if shape_errors:
        return "; ".join(shape_errors)

    refined_entities: set[str] = set()
    _collect_entity_ids(refined, refined_entities)
    hallucinated = refined_entities - allowed_entities
    if hallucinated:
        return (
            "refined automation references entities not in the original: "
            f"{sorted(hallucinated)}"
        )
    return None


async def refine_insight(
    hass: HomeAssistant,
    *,
    agent_id: str | None,
    insight: Insight,
    redactor: Redactor,
    prior_explanation: str | None = None,
    feedback: str | None = None,
    preferred_agent_id: str | None = None,
    conversation_id: str | None = None,
) -> RefinementResult:
    """Ask the configured Conversation agent for a refined version of the automation.

    Pseudonymizes the payload, calls the LLM, parses the response, dereferences
    pseudonyms back to real entity_ids, and validates the result is shape-valid
    and references no hallucinated entities. On any validation failure, returns
    `success=False` with the actual reason and the raw response for debugging.

    Auto-pick path (agent_id=None) walks the same candidate list as Explain
    (Assist's default first, then other LLM agents). Retries on every kind
    of failure — network, parse error, validation error, hallucination —
    because all of them are model-specific and a different agent may
    succeed where the previous one failed. User-pinned agent_id => single
    attempt, no failover.
    """
    redacted_payload, redaction_map = await redactor.redact_insight_payload(
        insight.payload
    )
    redacted_explanation: str | None = None
    if prior_explanation:
        redacted_explanation, _ = await redactor.redact_text(prior_explanation)
    redacted_feedback: str | None = None
    if feedback:
        redacted_feedback, _ = await redactor.redact_text(feedback)

    prompt = build_refine_prompt(
        redacted_payload,
        prior_explanation=redacted_explanation,
        feedback=redacted_feedback,
    )
    bytes_sent = len(prompt.encode("utf-8"))

    candidates = _list_agent_candidates(
        hass, requested=agent_id, preferred=preferred_agent_id
    )
    audits: list[AttemptAudit] = []
    last_result: RefinementResult | None = None
    for idx, candidate in enumerate(candidates):
        # Conversation_id is tied to a specific agent; if failover walks
        # to a different agent on attempt 2+, the prior id is meaningless
        # there. Only thread it on the first attempt.
        thread_id = conversation_id if idx == 0 else None
        last_result = await _refine_one_attempt(
            hass,
            chosen_agent_id=candidate,
            prompt=prompt,
            bytes_sent=bytes_sent,
            redaction_map=redaction_map,
            insight=insight,
            conversation_id=thread_id,
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
            return _refine_with_attempts(last_result, audits)
    # All attempts failed — return the most recent failure verbatim.
    # _list_agent_candidates always returns at least [None].
    assert last_result is not None
    return _refine_with_attempts(last_result, audits)


def _refine_with_attempts(
    result: RefinementResult, audits: list[AttemptAudit]
) -> RefinementResult:
    """Re-pack the frozen dataclass with the accumulated audit list."""
    from dataclasses import replace

    return replace(result, attempts=tuple(audits))


async def _refine_one_attempt(
    hass: HomeAssistant,
    *,
    chosen_agent_id: str | None,
    prompt: str,
    bytes_sent: int,
    redaction_map: RedactionMap,
    insight: Insight,
    conversation_id: str | None = None,
) -> RefinementResult:
    """Single-shot Refine: converse, parse, deref, validate, return."""
    from homeassistant.components import conversation as ha_conversation

    try:
        result = await ha_conversation.async_converse(
            hass,
            text=prompt,
            conversation_id=conversation_id,
            context=None,
            language=None,
            agent_id=chosen_agent_id,
        )
    except Exception as err:
        return RefinementResult.failure(
            error=str(err),
            redaction_map=redaction_map,
            bytes_sent=bytes_sent,
            chosen_agent_id=chosen_agent_id,
        )

    response_type = _extract_response_type(result)
    speech = _extract_speech(result)
    bytes_received = len(speech.encode("utf-8")) if speech else 0
    new_conversation_id = _extract_conversation_id(result) or conversation_id
    # v1.0 review #8: deref speech before showing it in errors / raw_response.
    # Pseudonyms in the prompt round-trip through the LLM; the user wants
    # to see their real entity_ids in error output, not "light.entity_xxx".
    deref_speech = (
        redaction_map.dereference(speech) if speech else speech
    )

    if response_type and "error" in response_type.lower():
        is_llm_agent = (
            chosen_agent_id is not None
            and chosen_agent_id != "conversation.home_assistant"
        )
        if is_llm_agent:
            err_msg = (
                f"LLM agent ({chosen_agent_id}) returned an error: "
                f"{deref_speech or '(no message)'}"
            )
        else:
            err_msg = (
                "Active Conversation agent isn't an LLM (rule-based fallback). "
                "Refine requires an LLM Conversation integration."
            )
        return RefinementResult.failure(
            error=err_msg,
            redaction_map=redaction_map,
            bytes_sent=bytes_sent,
            bytes_received=bytes_received,
            raw_response=deref_speech,
            chosen_agent_id=chosen_agent_id,
        )

    if speech is None:
        return RefinementResult.failure(
            error="agent returned no speech",
            redaction_map=redaction_map,
            bytes_sent=bytes_sent,
            chosen_agent_id=chosen_agent_id,
        )

    rationale, parsed, parse_error = parse_refine_response(speech)
    # Dereference the rationale ONCE here — it surfaces in:
    #   - the diff modal's "Why these changes" panel
    #   - the refined YAML's `description` backfill (further down)
    #   - error-path returns
    # Without this step the LLM's pseudonym references (e.g.
    # "light.entity_1y3s70 — redundant with light.entity_5ywga1") leak
    # to the user as gibberish IDs instead of their real entities.
    rationale = (
        redaction_map.dereference(rationale) if rationale else rationale
    )
    if parse_error or parsed is None:
        return RefinementResult.failure(
            error=f"could not parse refinement: {parse_error}",
            redaction_map=redaction_map,
            bytes_sent=bytes_sent,
            bytes_received=bytes_received,
            rationale=rationale,
            raw_response=deref_speech,
            chosen_agent_id=chosen_agent_id,
        )

    # Dereference pseudonyms: the LLM's output references the redacted names,
    # so rebuild it through the redaction map back into real entity_ids.
    dereferenced_yaml = redaction_map.dereference(_yaml_dump(parsed))
    try:
        refined = yaml.safe_load(dereferenced_yaml)
    except yaml.YAMLError as exc:
        return RefinementResult.failure(
            error=f"dereferenced YAML re-parse failed: {exc}",
            redaction_map=redaction_map,
            bytes_sent=bytes_sent,
            bytes_received=bytes_received,
            rationale=rationale,
            raw_response=deref_speech,
            chosen_agent_id=chosen_agent_id,
        )
    if not isinstance(refined, dict):
        return RefinementResult.failure(
            error="dereferenced YAML did not parse to a mapping",
            redaction_map=redaction_map,
            bytes_sent=bytes_sent,
            bytes_received=bytes_received,
            rationale=rationale,
            raw_response=deref_speech,
            chosen_agent_id=chosen_agent_id,
        )

    # LLMs frequently drop the `description` field when they emit refined
    # YAML — they re-emit alias/trigger/action/mode but forget the
    # narrative description. Backfill it: the rationale is usually more
    # useful than the detector-generated description (it explains what
    # CHANGED), so prefer it; otherwise carry the original through.
    if not refined.get("description"):
        if rationale:
            refined["description"] = rationale.strip()
        elif insight.payload.get("description"):
            refined["description"] = insight.payload["description"]

    allowed_entities: set[str] = set()
    _collect_entity_ids(insight.payload, allowed_entities)
    validation_error = _validate_refined(refined, allowed_entities)
    if validation_error:
        # Distinguish "the YAML stopped halfway" from real validation issues.
        # Same root cause as truncation but the parser was lenient enough to
        # produce a partial dict — the validator catches it as missing keys
        # or wrong-type triggers. Surface the actionable message instead.
        if _looks_structurally_incomplete(refined):
            return RefinementResult.failure(
                error=(
                    "LLM response was cut off mid-YAML — likely hit "
                    "max_output_tokens. Increase the limit in your LLM "
                    "Conversation integration's config (try 4096), or "
                    "switch to a non-thinking model that uses tokens "
                    "more efficiently."
                ),
                redaction_map=redaction_map,
                bytes_sent=bytes_sent,
                bytes_received=bytes_received,
                rationale=rationale,
                raw_response=deref_speech,
                chosen_agent_id=chosen_agent_id,
            )
        return RefinementResult.failure(
            error=f"validation failed: {validation_error}",
            redaction_map=redaction_map,
            bytes_sent=bytes_sent,
            bytes_received=bytes_received,
            rationale=rationale,
            raw_response=deref_speech,
            chosen_agent_id=chosen_agent_id,
        )

    diff_summary = diff_payloads(insight.payload, refined)

    return RefinementResult(
        refined_payload=refined,
        rationale=rationale,
        diff_summary=diff_summary,
        redaction_map=redaction_map,
        bytes_sent=bytes_sent,
        bytes_received=bytes_received,
        success=True,
        chosen_agent_id=chosen_agent_id,
        conversation_id=new_conversation_id,
    )
