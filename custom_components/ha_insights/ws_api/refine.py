"""WS handlers for the REFINE / refine-existing-automation family.

Four user-facing handlers + the prompt-template cluster they share:

  - ``ws_refine`` — user-initiated LLM refinement of an existing
    AUTOMATION_PROPOSAL insight.
  - ``ws_refine_cost_estimate`` — pre-flight cost check; same
    redaction + prompt pipeline as ``ws_refine`` but stops before
    the LLM call.
  - ``ws_refine_automation`` — refine an EXISTING automation by
    automation_id / alias (not by insight). Wraps the raw_config in
    a virtual Insight and runs the refine pipeline.
  - ``ws_apply_automation_refinement`` — write the refined automation
    back to HA.

## Prompt-template cluster

Lives in this module because every handler consumes it:

  - ``_REFINE_PRINCIPLES_CONCISE`` / ``_REFINE_PRINCIPLES_INDEPTH``
    — depth-tiered "RULES" block.
  - ``_principles_for(depth)`` — picker.
  - ``_OBS_KIND_HINTS`` — per-observation-kind verb-led hints.
  - ``_authorized_from_user_text(user_text)`` — derive an
    "AUTHORIZED EDITS" stanza so the LLM stays inside intent.
  - ``_wrap_user_feedback(user_feedback, conversation_turn, depth)``
    — compose per-turn LLM feedback (turn 0 = USER+AUTHORIZED+RULES;
    turn N>0 = USER only; conversation_id threads the rest).

Extracted in v1.13.8 (step 6). Pure-Python helpers without the
prompt-template subsystem (``_humanize_llm_error``,
``_sanitize_yaml_safe``, etc.) live in ``_refine_helpers.py`` from
v1.13.7.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from ..config_flow import get_blocked_entities
from ..const import DOMAIN
from ..insight import Insight, InsightKind
from ..llm import RedactionMode, Redactor, refine_insight
from ._helpers import (
    _audit_attempts,
    _get_store,
    _resolve_blocked_entities,
    _resolve_preferred_agent_id,
)
from ._refine_helpers import (
    _attempt_to_dict,
    _find_automation_by_id,
    _humanize_llm_error,
    _resolve_audit_depth,
    _sanitize_yaml_safe,
)

if TYPE_CHECKING:
    pass

_LOGGER = logging.getLogger(__name__)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/refine",
        vol.Required("insight_id"): str,
        vol.Optional("agent_id"): vol.Any(str, None),
        vol.Optional("feedback"): vol.Any(str, None),
        # v1.0 RC #2: thread conversation_id from prior Refine on same
        # insight so the agent retains context across turns.
        vol.Optional("conversation_id"): vol.Any(str, None),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_refine(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """User-initiated LLM refinement of an automation insight.

    Pseudonymizes the payload, calls the configured Conversation agent,
    parses + dereferences + validates the response. Does NOT mutate the
    insight — the refined payload is returned for the card to preview, then
    applied via `home_insights/apply` with `payload_override` if accepted.
    """

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
    if insight.payload_format != "automation":
        connection.send_error(
            msg["id"],
            "unsupported_format",
            f"refine only supports payload_format='automation' (got "
            f"{insight.payload_format!r})",
        )
        return

    from ..config_flow import get_blocked_entities

    blocked = _resolve_blocked_entities(hass, get_blocked_entities)
    preferred = _resolve_preferred_agent_id(hass)
    redactor = Redactor(
        store, mode=RedactionMode.AGGRESSIVE, blocked_entities=blocked
    )
    result = await refine_insight(
        hass,
        agent_id=msg.get("agent_id"),
        insight=insight,
        redactor=redactor,
        prior_explanation=insight.explanation,
        feedback=msg.get("feedback"),
        preferred_agent_id=preferred,
        conversation_id=msg.get("conversation_id"),
    )

    # Audit every attempt — failover may have made multiple round-trips
    # before landing on a working agent. Each round-trip is bytes that
    # left the network and MUST appear in the privacy log.
    await _audit_attempts(
        store, result.attempts, insight_id=insight.id, redactor=redactor
    )

    if not result.success:
        # Include a truncated raw_response so the user (and the card) can see
        # what the LLM actually returned when validation rejects the output.
        # Many LLMs produce shape-incomplete YAML even within token budget;
        # being able to inspect the raw text is essential for self-service
        # debugging.
        detail = result.error or "Refinement failed"
        if result.raw_response:
            snippet = result.raw_response.strip()
            if len(snippet) > 600:
                snippet = snippet[:600] + "…"
            detail = f"{detail}\n\nLLM said:\n{snippet}"
        connection.send_error(msg["id"], "refine_failed", detail)
        return

    connection.send_result(
        msg["id"],
        {
            "refined_payload": result.refined_payload,
            "rationale": result.rationale,
            "diff_summary": result.diff_summary,
            "bytes_sent": result.bytes_sent,
            "bytes_received": result.bytes_received,
            # Card threads this back on the next Refine for context.
            "conversation_id": result.conversation_id,
        },
    )


def _resolve_refine_cost_threshold(hass: HomeAssistant) -> float:
    """Pick the lowest threshold across active config entries.

    Lowest wins so a "be cautious" entry isn't bypassed by a more
    permissive one in a multi-entry future.
    """
    from ..config_flow import (
        DEFAULT_REFINE_COST_THRESHOLD_USD,
        get_refine_cost_threshold,
    )

    thresholds = [
        get_refine_cost_threshold(entry)
        for entry in hass.config_entries.async_entries(DOMAIN)
    ]
    return min(thresholds) if thresholds else DEFAULT_REFINE_COST_THRESHOLD_USD


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/refine_cost_estimate",
        vol.Required("insight_id"): str,
        vol.Optional("feedback"): vol.Any(str, None),
        vol.Optional("agent_id"): vol.Any(str, None),
    }
)
@websocket_api.async_response
async def ws_refine_cost_estimate(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Server-side pre-flight: estimate token + USD cost of a Refine call.

    Runs the same redaction + prompt-build pipeline as ws_refine but stops
    before the LLM. Returns {tokens_in, tokens_out, cost_usd, agent_id,
    threshold_usd, requires_confirm} so the card can decide whether to
    show a "are you sure?" dialog before burning tokens.

    Output bytes are estimated from a typical refined-automation length
    (~800 bytes / ~200 tokens). The figure is rough by definition — we
    don't know the agent's actual response until we make the call — but
    it's the cheapest way to prevent expensive misclicks on Opus-tier
    models without round-tripping a real call.
    """
    from ..llm import RedactionMode, Redactor, build_refine_prompt
    from ..llm.agent_client import _list_agent_candidates
    from ..llm.cost import estimate_cost

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
    if insight.payload_format != "automation":
        connection.send_error(
            msg["id"],
            "unsupported_format",
            "cost estimate only supports payload_format='automation'",
        )
        return

    # Pre-build the prompt the same way refine_insight would, so the byte
    # count is realistic.
    blocked = _resolve_blocked_entities(hass, get_blocked_entities)
    redactor = Redactor(
        store, mode=RedactionMode.AGGRESSIVE, blocked_entities=blocked
    )
    redacted_payload, _ = await redactor.redact_insight_payload(insight.payload)

    redacted_explanation: str | None = None
    if insight.explanation:
        redacted_explanation, _ = await redactor.redact_text(insight.explanation)
    redacted_feedback: str | None = None
    feedback = msg.get("feedback")
    if feedback:
        redacted_feedback, _ = await redactor.redact_text(feedback)

    prompt = build_refine_prompt(
        redacted_payload,
        prior_explanation=redacted_explanation,
        feedback=redacted_feedback,
    )
    bytes_sent = len(prompt.encode("utf-8"))
    # Heuristic: a refined automation YAML response is ~800 bytes (~200 tokens).
    # If the model emits a long RATIONALE block first the figure is light;
    # if it abbreviates aggressively the figure is high. Mid-band estimate.
    bytes_received_est = 800

    requested = msg.get("agent_id")
    preferred = _resolve_preferred_agent_id(hass)
    candidates = _list_agent_candidates(
        hass, requested=requested, preferred=preferred
    )
    # The agent the cost will most likely fall on: the first non-None candidate.
    target_agent = next((c for c in candidates if c is not None), None)

    cost = estimate_cost(
        agent_id=target_agent,
        bytes_sent=bytes_sent,
        bytes_received=bytes_received_est,
    )

    threshold = _resolve_refine_cost_threshold(hass)
    requires_confirm = (
        target_agent is not None
        and float(cost["cost_usd"]) > threshold
        and cost["source"] != "local_free"
    )

    connection.send_result(
        msg["id"],
        {
            "agent_id": target_agent,
            "tokens_in": cost["tokens_in"],
            "tokens_out": cost["tokens_out"],
            "cost_usd": cost["cost_usd"],
            "cost_source": cost["source"],
            "threshold_usd": threshold,
            "requires_confirm": requires_confirm,
        },
    )


_REFINE_PRINCIPLES_CONCISE = (
    "RULES:\n"
    "1. Default to no change. Empty diff_summary is a valid answer.\n"
    "2. Before editing, name one edge case the change could break. "
    "If unsure, KEEP the field.\n"
    "3. Don't change platform/from/to/for/attribute/condition/"
    "service/target shape unless a finding pinpoints it as buggy.\n"
    "4. Don't add weekday/time/sun conditions when a state trigger "
    "on the same entity already gates firing.\n"
    "5. You may ONLY make edits listed under AUTHORIZED EDITS below. "
    "If a finding lists an entity, you can act on THAT entity — "
    "don't generalise to others.\n"
    "6. Preserve mode:/max:/initial_state:/for:/templates/custom "
    "services + `action:` vs `service:` key style verbatim.\n"
    "7. Rationale: per change, name it + one edge case ruled out."
)

_REFINE_PRINCIPLES_INDEPTH = """RULES (think through each before responding):

1. MINIMAL CHANGE IS DEFAULT. If no finding points to a CLEAR, SAFE
   fix, return original YAML with rationale explaining what you
   considered. Empty diff_summary with a no-change rationale is a
   valid, welcome outcome. Confidence in the user's existing setup
   beats your prior on what's idiomatic.

2. REGRESSION CHECK BEFORE EVERY EDIT. For each proposed change,
   answer in your rationale: "what edge case is the existing YAML
   handling that this edit could break?" Examples to consider:
    - `for:` durations preventing flicker on noisy sensors
    - `mode: single` / `max:` / `max_exceeded:` preventing queue
      buildup or race conditions
    - `initial_state` controlling behaviour at reboot
    - condition blocks guarding state combinations you can't see
    - template `entity_id:` lists computed at trigger time
    - explicit `service_data` / `target` shapes required by specific
      platforms (Hue scenes, MQTT JSON modes, etc.)
    - notification side-effects (persistent_notification.create,
      notify.* calls) the user relies on
   If you can't explain why a field is safe to remove, KEEP IT.

3. PRESERVE UNKNOWNS. Custom services, weird-looking templates,
   oddly-named entities, comments inside `description:` — preserve
   verbatim. Reformat is NOT improvement.

4. TRIGGER + STRUCTURE ARE LOAD-BEARING. Don't change `platform:`,
   `from:`, `to:`, `for:`, `attribute:`, `event_type:`, `event_data:`,
   `condition.condition`, `action[].service`, or `action[].target`
   shape unless a finding explicitly identifies a specific bug there.

5. DON'T DUPLICATE THE TRIGGER. A STATE trigger on entity X only
   fires when X changes. Adding a `weekday:` / `time:` / `sun:`
   condition that filters days X is naturally silent on is redundant
   noise. Conditions are for state INDEPENDENT of the trigger
   (someone home, sun position when not sun-triggered, etc.).

6. NEVER SILENTLY SWAP ENTITIES. If a finding says an entity is
   unavailable/missing, FLAG it in your rationale. Never guess a
   replacement entity_id and write it into YAML.

7. WALK YOUR REASONING IN `rationale`. For every change: name it,
   justify it against the findings, AND explicitly name one edge
   case you considered and ruled out. Reasoning quality > number
   of changes."""

def _principles_for(depth: str) -> str:
    """Return the principles block matching the configured depth."""
    return (
        _REFINE_PRINCIPLES_INDEPTH
        if depth == "indepth"
        else _REFINE_PRINCIPLES_CONCISE
    )


_OBS_KIND_HINTS: dict[str, str] = {
    "long_on_duration": (
        "→ raise/add `for:`. Don't touch triggers/conditions."
    ),
    "trigger_time_drift": (
        "→ shift `at:` by observed delta (5-min boundary). Nothing else."
    ),
    "entity_silent": (
        "→ FLAG in rationale. Never guess a replacement."
    ),
    "redundant_target": (
        "→ drop the listed member entries. Mechanical, tight scope."
    ),
    "trace_dormant": (
        "→ FLAG; suggest user disable. Don't rewrite logic."
    ),
    "trace_condition_blocks": (
        "→ loosen condition only if blocked runs were unintentional. "
        "Else KEEP."
    ),
    "trace_action_errors": (
        "→ FLAG the erroring step. Don't rewrite — no failing trace."
    ),
    "rollup_weekday_only": "→ CONTEXT ONLY. Don't add weekday condition.",
    "rollup_dow_dark_days": "→ CONTEXT ONLY. Don't add weekday condition.",
    "rollup_month_start_spike": "→ CONTEXT ONLY. No date condition.",
    "rollup_seasonal_silence": (
        "→ CONTEXT. Add `month:` cond ONLY if trigger is time/sun-based."
    ),
    "has_recent_insights": "→ CONTEXT. Related findings exist; don't act.",
}


def _authorized_from_user_text(user_text: str) -> str:
    """Build an AUTHORIZED EDITS block for user-typed refines.

    Without specific findings, the user's request IS the authorisation.
    We don't try to parse it — just echo it as the canonical
    authority for what's allowed, in the prompt the LLM sees. The
    Refine principles already say "execute the request faithfully."
    """
    text = (user_text or "").strip()
    if not text:
        return (
            "AUTHORIZED EDITS:\n"
            "- (no specific request — apply only obvious bug fixes; "
            "default to no change if nothing is clearly broken.)"
        )
    return (
        "AUTHORIZED EDITS:\n"
        f"- Execute the user request: {text}\n"
        "- Only side-edits required to make that request work are "
        "permitted. Do NOT add unrequested restructuring."
    )


def _wrap_user_feedback(
    user_feedback: str,
    *,
    conversation_turn: int = 0,
    depth: str = "concise",
) -> str:
    """User-feedback wrap.

    Turn 0: USER request + AUTHORIZED EDITS (derived from request)
            + RULES (depth-aware).
    Turn N>0: USER request only — conversation_id thread carries
    the rules.
    """
    user_text = (user_feedback or "").strip()
    if conversation_turn > 0:
        return f"USER: {user_text or '(no follow-up text)'}"
    authorized = _authorized_from_user_text(user_text)
    user_section = (
        f"USER: {user_text}" if user_text
        else "USER: (no specific request — flag obvious bugs only; "
             "return no-change if nothing is clearly wrong.)"
    )
    return (
        user_section
        + "\n\n"
        + authorized
        + "\n\n"
        + _principles_for(depth)
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/refine_automation",
        vol.Required("automation_id"): str,
        vol.Required("feedback"): str,
        vol.Optional("agent_id"): vol.Any(str, None),
        vol.Optional("conversation_id"): vol.Any(str, None),
        vol.Optional("analysis_depth"): vol.In(["concise", "indepth"]),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_refine_automation(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Run an existing automation through the LLM refine pipeline."""

    from ..config_flow import get_blocked_entities
    from ..llm import RedactionMode, Redactor, refine_insight

    automation_id = msg["automation_id"]
    raw = await hass.async_add_executor_job(
        _find_automation_by_id, hass, automation_id
    )
    if raw is None:
        connection.send_error(
            msg["id"],
            "not_found",
            f"No automation with id/alias {automation_id!r}",
        )
        return
    # Sanitize the raw_config dict so PyYAML.safe_dump can serialize
    # it downstream (HA injects Template / Selector / etc. objects
    # PyYAML can't represent → RepresenterError otherwise).
    raw = _sanitize_yaml_safe(raw)

    virtual_fingerprint = {
        "automation_id": automation_id,
        "kind": "existing_automation_refinement",
    }
    virtual_insight = Insight(
        id=Insight.compute_id(
            InsightKind.AUTOMATION_PROPOSAL, virtual_fingerprint
        ),
        kind=InsightKind.AUTOMATION_PROPOSAL,
        detector="user_refine",
        area_id=None,
        title=(
            "Refine existing automation: "
            f"{raw.get('alias') or automation_id}"
        ),
        confidence=1.0,
        fingerprint=virtual_fingerprint,
        payload=raw,
        payload_format="automation",
        created_at=datetime.now(tz=UTC),
    )

    store = _get_store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_set_up", "Store not initialized")
        return

    blocked = _resolve_blocked_entities(hass, get_blocked_entities)
    redactor = Redactor(
        store, mode=RedactionMode.AGGRESSIVE, blocked_entities=blocked
    )
    preferred = _resolve_preferred_agent_id(hass)

    # Wrap the user's request with the regression-aware principles.
    # First turn gets the full preamble; follow-ups within the same
    # conversation_id get a lighter touch since the LLM remembers
    # the principles from turn 1.
    depth = _resolve_audit_depth(hass, msg.get("analysis_depth"))
    wrapped_feedback = _wrap_user_feedback(
        msg["feedback"],
        conversation_turn=1 if msg.get("conversation_id") else 0,
        depth=depth,
    )
    try:
        result = await refine_insight(
            hass,
            agent_id=msg.get("agent_id"),
            insight=virtual_insight,
            redactor=redactor,
            feedback=wrapped_feedback,
            preferred_agent_id=preferred,
        )
    except Exception as err:
        connection.send_error(
            msg["id"], "refine_failed", _humanize_llm_error(str(err))
        )
        return

    if not result.success or result.refined_payload is None:
        connection.send_error(
            msg["id"],
            "refine_failed",
            _humanize_llm_error(
                result.error or "LLM refinement returned no payload"
            ),
        )
        return

    try:
        import yaml as _yaml

        refined_yaml = _yaml.safe_dump(
            result.refined_payload,
            sort_keys=False,
            default_flow_style=False,
        )
        original_yaml = _yaml.safe_dump(
            raw, sort_keys=False, default_flow_style=False
        )
    except Exception:
        refined_yaml = str(result.refined_payload)
        original_yaml = str(raw)

    await _audit_attempts(
        store, result.attempts, insight_id=virtual_insight.id, redactor=redactor
    )

    connection.send_result(
        msg["id"],
        {
            "automation_id": automation_id,
            "alias": raw.get("alias"),
            "original_yaml": original_yaml,
            "refined_yaml": refined_yaml,
            "refined_config": result.refined_payload,
            "rationale": result.rationale,
            "diff_summary": result.diff_summary,
            "bytes_sent": result.bytes_sent,
            "bytes_received": result.bytes_received,
            "chosen_agent_id": result.chosen_agent_id,
            "conversation_id": result.conversation_id,
            "attempts": (
                [_attempt_to_dict(a) for a in result.attempts]
                if result.attempts else []
            ),
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/apply_automation_refinement",
        vol.Required("automation_id"): str,
        vol.Required("refined_config"): dict,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_apply_automation_refinement(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Write the refined automation YAML back to disk + reload."""
    from ..apply.automation_writer import AutomationWriter

    automation_id = msg["automation_id"]
    refined = msg["refined_config"]
    if not isinstance(refined, dict):
        connection.send_error(
            msg["id"],
            "bad_payload",
            "refined_config must be an automation dict",
        )
        return

    writer = AutomationWriter(hass)
    try:
        await writer.write(refined, auto_id=automation_id)
    except Exception as err:
        connection.send_error(msg["id"], "write_failed", str(err))
        return

    connection.send_result(
        msg["id"],
        {
            "automation_id": automation_id,
            "applied": True,
            "url": f"/config/automation/edit/{automation_id}",
        },
    )




__all__ = [
    "_OBS_KIND_HINTS",
    "_REFINE_PRINCIPLES_CONCISE",
    "_REFINE_PRINCIPLES_INDEPTH",
    "_authorized_from_user_text",
    "_principles_for",
    "_wrap_user_feedback",
    "ws_apply_automation_refinement",
    "ws_refine",
    "ws_refine_automation",
    "ws_refine_cost_estimate",
]
