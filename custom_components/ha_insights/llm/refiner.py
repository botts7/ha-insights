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
from .agent_client import _extract_response_type, _extract_speech, _pick_llm_agent_id
from .redactor import RedactionMap, Redactor

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from ..insight import Insight


_REFINE_PROMPT_TMPL = (
    "Refine this Home Assistant automation. Add a debounce, condition, or "
    "mode change as appropriate. Be brief.\n\n"
    "Output exactly two sections (no markdown fences, no extra commentary):\n"
    "RATIONALE: <one short sentence>\n"
    "YAML:\n"
    "alias: ...\n"
    "trigger: [...]\n"
    "action: [...]\n"
    "mode: ...\n\n"
    "Constraints (strict):\n"
    "- Use ONLY these entity_ids: {entity_list}\n"
    "- Output must be complete valid YAML (close all quotes/brackets)\n"
    "- Keep the response under 200 tokens total\n\n"
    "Current automation:\n"
    "{current_yaml}\n\n"
    "Considerations: {considerations}\n"
)


@dataclass(frozen=True)
class RefinementResult:
    """Outcome of a Refine call.

    `success=False` populates `error` with a user-readable explanation.
    `raw_response` is included on failure for debugging — never on success.
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


def _yaml_dump(payload: dict[str, Any]) -> str:
    return yaml.safe_dump(payload, default_flow_style=False, sort_keys=False).strip()


def _collect_entity_ids(value: Any, accumulator: set[str]) -> None:
    """Walk a payload and gather every entity_id-shaped string into `accumulator`."""
    if isinstance(value, str):
        for match in re.finditer(r"\b([a-z_]+)\.([a-z0-9_]+)\b", value):
            accumulator.add(match.group(0))
    elif isinstance(value, dict):
        for sub in value.values():
            _collect_entity_ids(sub, accumulator)
    elif isinstance(value, list):
        for item in value:
            _collect_entity_ids(item, accumulator)


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

    rationale_match = re.search(r"RATIONALE:\s*(.+?)(?=\n\s*YAML:|\Z)", text, re.DOTALL)
    yaml_match = re.search(r"YAML:\s*(.+)", text, re.DOTALL)

    rationale = rationale_match.group(1).strip() if rationale_match else None

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
) -> RefinementResult:
    """Ask the configured Conversation agent for a refined version of the automation.

    Pseudonymizes the payload, calls the LLM, parses the response, dereferences
    pseudonyms back to real entity_ids, and validates the result is shape-valid
    and references no hallucinated entities. On any validation failure, returns
    `success=False` with the actual reason and the raw response for debugging.
    """
    from homeassistant.components import conversation as ha_conversation

    chosen_agent_id = _pick_llm_agent_id(hass, agent_id)

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

    try:
        result = await ha_conversation.async_converse(
            hass,
            text=prompt,
            conversation_id=None,
            context=None,
            language=None,
            agent_id=chosen_agent_id,
        )
    except Exception as err:
        return RefinementResult(
            refined_payload=None,
            rationale=None,
            diff_summary=[],
            redaction_map=redaction_map,
            bytes_sent=bytes_sent,
            bytes_received=0,
            success=False,
            error=str(err),
        )

    response_type = _extract_response_type(result)
    speech = _extract_speech(result)
    bytes_received = len(speech.encode("utf-8")) if speech else 0

    if response_type and "error" in response_type.lower():
        is_llm_agent = (
            chosen_agent_id is not None
            and chosen_agent_id != "conversation.home_assistant"
        )
        if is_llm_agent:
            err_msg = (
                f"LLM agent ({chosen_agent_id}) returned an error: "
                f"{speech or '(no message)'}"
            )
        else:
            err_msg = (
                "Active Conversation agent isn't an LLM (rule-based fallback). "
                "Refine requires an LLM Conversation integration."
            )
        return RefinementResult(
            refined_payload=None,
            rationale=None,
            diff_summary=[],
            redaction_map=redaction_map,
            bytes_sent=bytes_sent,
            bytes_received=bytes_received,
            success=False,
            error=err_msg,
            raw_response=speech,
        )

    if speech is None:
        return RefinementResult(
            refined_payload=None,
            rationale=None,
            diff_summary=[],
            redaction_map=redaction_map,
            bytes_sent=bytes_sent,
            bytes_received=0,
            success=False,
            error="agent returned no speech",
        )

    rationale, parsed, parse_error = parse_refine_response(speech)
    if parse_error or parsed is None:
        return RefinementResult(
            refined_payload=None,
            rationale=rationale,
            diff_summary=[],
            redaction_map=redaction_map,
            bytes_sent=bytes_sent,
            bytes_received=bytes_received,
            success=False,
            error=f"could not parse refinement: {parse_error}",
            raw_response=speech,
        )

    # Dereference pseudonyms: the LLM's output references the redacted names,
    # so rebuild it through the redaction map back into real entity_ids.
    dereferenced_yaml = redaction_map.dereference(_yaml_dump(parsed))
    try:
        refined = yaml.safe_load(dereferenced_yaml)
    except yaml.YAMLError as exc:
        return RefinementResult(
            refined_payload=None,
            rationale=rationale,
            diff_summary=[],
            redaction_map=redaction_map,
            bytes_sent=bytes_sent,
            bytes_received=bytes_received,
            success=False,
            error=f"dereferenced YAML re-parse failed: {exc}",
            raw_response=speech,
        )
    if not isinstance(refined, dict):
        return RefinementResult(
            refined_payload=None,
            rationale=rationale,
            diff_summary=[],
            redaction_map=redaction_map,
            bytes_sent=bytes_sent,
            bytes_received=bytes_received,
            success=False,
            error="dereferenced YAML did not parse to a mapping",
            raw_response=speech,
        )

    allowed_entities: set[str] = set()
    _collect_entity_ids(insight.payload, allowed_entities)
    validation_error = _validate_refined(refined, allowed_entities)
    if validation_error:
        # Distinguish "the YAML stopped halfway" from real validation issues.
        # Same root cause as truncation but the parser was lenient enough to
        # produce a partial dict — the validator catches it as missing keys
        # or wrong-type triggers. Surface the actionable message instead.
        if _looks_structurally_incomplete(refined):
            return RefinementResult(
                refined_payload=None,
                rationale=rationale,
                diff_summary=[],
                redaction_map=redaction_map,
                bytes_sent=bytes_sent,
                bytes_received=bytes_received,
                success=False,
                error=(
                    "LLM response was cut off mid-YAML — likely hit "
                    "max_output_tokens. Increase the limit in your LLM "
                    "Conversation integration's config (try 4096), or "
                    "switch to a non-thinking model that uses tokens "
                    "more efficiently."
                ),
                raw_response=speech,
            )
        return RefinementResult(
            refined_payload=None,
            rationale=rationale,
            diff_summary=[],
            redaction_map=redaction_map,
            bytes_sent=bytes_sent,
            bytes_received=bytes_received,
            success=False,
            error=f"validation failed: {validation_error}",
            raw_response=speech,
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
    )
