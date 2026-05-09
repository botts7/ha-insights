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
    "Refine this Home Assistant automation to address common considerations "
    "(debounce, conditions, mode, race-conditions). Output strictly two "
    "sections, nothing else:\n"
    "RATIONALE: <one short line>\n"
    "YAML:\n"
    "<the complete refined YAML body, no markdown fences>\n\n"
    "Constraints:\n"
    "- Use ONLY these entity_ids: [{entity_list}]\n"
    "- Keep the same trigger entity\n"
    "- Output must be valid HA automation YAML (alias, trigger, action, mode)\n"
    "- Do not invent entities, services, or values that weren't in the original\n\n"
    "Current automation:\n"
    "{current_yaml}\n\n"
    "Considerations from earlier:\n"
    "{considerations}\n"
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
) -> str:
    entities: set[str] = set()
    _collect_entity_ids(redacted_payload, entities)
    considerations = (
        prior_explanation.strip()
        if prior_explanation
        else "(no prior explanation; infer common-sense caveats)"
    )
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
        return rationale, None, f"YAML parse failed: {exc}"

    if not isinstance(parsed, dict):
        return rationale, None, "YAML did not parse to a mapping"

    return rationale, parsed, None


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

    prompt = build_refine_prompt(
        redacted_payload, prior_explanation=redacted_explanation
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
