"""WebSocket handler: ws_audit_suggest + its two prompt helpers.

Extracted from ``ws_api/__init__.py`` in v1.13.9 (step 7 of the
v1.13 refactor). The handler reads an automation's raw YAML +
recent observations, prompts the conversation agent to suggest
improvements, and returns a side-by-side diff plus rationale.

Helpers ``_build_audit_feedback`` and
``_authorized_edits_from_observations`` are only used by this
handler; they move alongside it.
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
    _attempt_to_dict,
    _find_automation_by_id,
    _humanize_llm_error,
    _resolve_audit_depth,
    _sanitize_yaml_safe,
)
from .refine import _OBS_KIND_HINTS, _principles_for

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


def _build_audit_feedback(
    observations: list[dict[str, Any]],
    *,
    depth: str = "concise",
) -> str:
    """Audit feedback builder. `depth` chooses concise (~150 tok)
    vs indepth (~600 tok) principles."""
    findings: list[str] = []
    has_context_only = False
    has_actionable = False
    for obs in observations:
        kind = obs.get("kind") or ""
        text = (obs.get("text") or "").strip()
        is_context = bool((obs.get("metrics") or {}).get("context_only"))
        if is_context:
            has_context_only = True
        else:
            has_actionable = True
        findings.append(f"- {text}")
        hint = _OBS_KIND_HINTS.get(kind)
        if hint:
            findings.append(f"  {hint}")

    header = "FINDINGS:"
    if has_context_only and not has_actionable:
        header = (
            "ALL findings are CONTEXT-ONLY. Likely correct answer: "
            "no change.\nFINDINGS:"
        )

    # Derive the per-call authorization list. Rule 5 says "you may
    # ONLY make edits listed below" — this is "below".
    authorized = _authorized_edits_from_observations(observations)

    return "\n".join(
        [header, *findings, "", authorized, "", _principles_for(depth)]
    )


def _authorized_edits_from_observations(
    observations: list[dict[str, Any]],
) -> str:
    """Build an `AUTHORIZED EDITS:` block from the observation list.

    Each observation kind unlocks a specific edit class on a specific
    entity / step. Anything not listed is implicitly forbidden by
    Rule 5. This is the contextual-rule architecture the user
    requested — instead of a universal "never remove entities" rule,
    we tell the LLM exactly which removals / changes the findings
    actually justify.
    """
    lines: list[str] = []
    remove_targets: list[str] = []
    raise_for_targets: list[str] = []
    shift_triggers: list[tuple[str, str]] = []
    drop_redundant: list[tuple[str, list[str]]] = []
    disable_dormant = False
    investigate_action_errors = False
    loosen_conditions: list[str] = []

    for obs in observations:
        kind = obs.get("kind") or ""
        metrics = obs.get("metrics") or {}
        if (metrics or {}).get("context_only"):
            continue
        if kind == "entity_silent":
            eid = metrics.get("entity_id")
            if isinstance(eid, str):
                remove_targets.append(eid)
        elif kind == "long_on_duration":
            eid = metrics.get("entity_id")
            if isinstance(eid, str):
                raise_for_targets.append(eid)
        elif kind == "trigger_time_drift":
            tt = metrics.get("trigger_time")
            delta = metrics.get("delta_min")
            if isinstance(tt, str) and isinstance(delta, (int, float)):
                sign = "+" if delta > 0 else ""
                shift_triggers.append((tt, f"{sign}{delta:.0f} min"))
        elif kind == "redundant_target":
            container = metrics.get("container")
            members = metrics.get("redundant_members") or []
            if isinstance(container, str) and members:
                drop_redundant.append((container, list(members)))
        elif kind == "trace_dormant":
            disable_dormant = True
        elif kind == "trace_action_errors":
            investigate_action_errors = True
        elif kind == "trace_condition_blocks":
            step = metrics.get("step")
            if isinstance(step, str):
                loosen_conditions.append(step)

    if remove_targets:
        lines.append(
            "- REMOVE these entities from action targets (they are "
            f"unavailable / missing): {', '.join(sorted(set(remove_targets)))}"
        )
    if drop_redundant:
        for container, members in drop_redundant:
            lines.append(
                f"- REMOVE redundant members of {container} from action "
                f"targets: {', '.join(members)}"
            )
    if raise_for_targets:
        lines.append(
            "- RAISE the `for:` clause on actions targeting: "
            f"{', '.join(sorted(set(raise_for_targets)))}"
        )
    if shift_triggers:
        parts = [f"{t} by {d}" for t, d in shift_triggers]
        lines.append(
            "- SHIFT time trigger(s) toward observed reality: "
            + "; ".join(parts)
        )
    if disable_dormant:
        lines.append(
            "- FLAG the automation as dormant (no fires in 30d+). A "
            "safe edit is to set `initial_state: false` OR recommend "
            "disable in your rationale; don't rewrite logic."
        )
    if investigate_action_errors:
        lines.append(
            "- FLAG action-error steps in your rationale; DO NOT "
            "rewrite the failing action (no failing trace available)."
        )
    if loosen_conditions:
        lines.append(
            "- CONSIDER loosening these condition steps (most fires "
            f"blocked): {', '.join(loosen_conditions)}"
        )

    if not lines:
        return (
            "AUTHORIZED EDITS:\n"
            "- (none from findings — only safe meta-edits like fixing "
            "alias typos, normalising YAML formatting, or adding a "
            "clarifying `description:` are permitted. Do NOT touch "
            "triggers, conditions, or action targets.)"
        )
    return "AUTHORIZED EDITS:\n" + "\n".join(lines)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/audit_suggest",
        vol.Required("insight_id"): str,
        vol.Optional("analysis_depth"): vol.In(["concise", "indepth"]),
        # Two-stage refinement: when present, use this dict as the
        # starting YAML instead of the original automation. Pattern:
        # user clicks 📋 Preview on a deterministic audit, then asks
        # the LLM to further-refine the algorithm's output. The card
        # passes the algorithm's refined config here. Server prompt
        # frames it as "here is the YAML AFTER our deterministic
        # fixes; further-refine based on the observations + the
        # user's extra feedback."
        vol.Optional("seed_config"): dict,
        vol.Optional("extra_feedback"): str,
    }
)
@websocket_api.async_response
async def ws_audit_suggest(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Run an audit insight through the LLM refine pipeline to get
    concrete YAML edits. Only meaningful for audit insights whose
    payload_format is "report" — automation-format insights already
    have a deterministic refined YAML and ship with Apply directly.

    Pipeline:
      1. Load the audit insight from the store
      2. Check the content-hash cache (skip LLM on hit)
      3. Build a virtual Insight using the underlying automation YAML
      4. Synthesize "feedback" text from the observations
      5. Run through refine_insight (existing redactor + agent
         failover + audit log)
      6. Cache the result + return refined YAML / rationale / diff

    Privacy: same Redactor and same audit log as ws_refine_automation.
    No bespoke LLM path here — we reuse the proven pipeline.
    """
    from datetime import UTC
    from datetime import datetime as _dt

    from ..audit.cache import (
        CachedSuggestion,
        compute_cache_key,
    )
    from ..audit.cache import (
        get as cache_get,
    )
    from ..audit.cache import (
        put as cache_put,
    )
    from ..config_flow import get_blocked_entities
    from ..insight import Insight, InsightKind
    from ..llm import RedactionMode, Redactor, refine_insight

    insight_id = msg["insight_id"]
    store = _get_store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_set_up", "Store not initialized")
        return
    audit_insight = await store.get_insight(insight_id)
    if audit_insight is None:
        connection.send_error(
            msg["id"], "not_found", f"No audit insight with id {insight_id}"
        )
        return
    if audit_insight.detector != "automation_audit":
        connection.send_error(
            msg["id"],
            "wrong_kind",
            "audit_suggest only works on automation_audit insights",
        )
        return

    payload = audit_insight.payload or {}
    # Deterministic-fix audits (payload_format="automation") put the
    # refined YAML at the top level and stash audit metadata under
    # `_audit`. Report-format audits put automation_id + observations
    # at the top level. Handle BOTH shapes so the LLM-refine-further
    # flow off a 📋 Preview works.
    audit_meta = (
        payload.get("_audit") if isinstance(payload.get("_audit"), dict) else {}
    )
    automation_id = (
        payload.get("automation_id")
        or audit_meta.get("automation_id")
    )
    observations = (
        payload.get("observations")
        or audit_meta.get("observations")
        or []
    )
    if not automation_id:
        connection.send_error(
            msg["id"], "incomplete", "Audit insight is missing automation_id"
        )
        return

    # Load the current automation YAML from HA — the audit insight's
    # payload may be stale by the time the user clicks.
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

    # Two-stage refinement: if the caller passed a seed_config (the
    # algorithm's already-refined YAML from a 📋 Preview), use THAT
    # as the starting point. The LLM further-refines it instead of
    # re-doing what the deterministic stage already handled. Saves
    # tokens, prevents the LLM from undoing safe edits.
    seed_config_raw = msg.get("seed_config")
    use_seed = isinstance(seed_config_raw, dict) and seed_config_raw
    if use_seed:
        starting_payload = _sanitize_yaml_safe(seed_config_raw)
        # Strip out any audit metadata the card may have left in
        # before sending — we don't want it inside the YAML sent to
        # the LLM.
        if isinstance(starting_payload, dict):
            starting_payload.pop("_audit", None)
    else:
        starting_payload = raw

    # Cache lookup. Cache key uses the EFFECTIVE starting payload so
    # a two-stage call with a different seed gets its own cache slot.
    observation_kinds = [o.get("kind", "") for o in observations]
    cache_extras = list(observation_kinds)
    extra_feedback = msg.get("extra_feedback") or ""
    if extra_feedback:
        cache_extras.append(f"extra_fb:{extra_feedback[:200]}")
    if use_seed:
        cache_extras.append("stage:two")
    # integration_version invalidates cached refinements when the
    # prompt logic / detector behavior changes in a new release.
    # Lazy import: _get_integration_version lives in ws_api/__init__.py
    # and importing it at module load would be circular.
    from . import _get_integration_version
    _iv = await _get_integration_version(hass)
    cache_key = compute_cache_key(starting_payload, cache_extras, _iv)
    cached = cache_get(cache_key)
    if isinstance(cached, CachedSuggestion):
        try:
            import yaml as _yaml

            cached_original = _yaml.safe_dump(
                starting_payload, sort_keys=False, default_flow_style=False
            )
            cached_refined = _yaml.safe_dump(
                cached.refined_yaml,
                sort_keys=False,
                default_flow_style=False,
            )
        except Exception:
            cached_original = str(starting_payload)
            cached_refined = str(cached.refined_yaml)
        connection.send_result(
            msg["id"],
            {
                "automation_id": automation_id,
                "alias": starting_payload.get("alias")
                if isinstance(starting_payload, dict)
                else None,
                "refined_config": cached.refined_yaml,
                "original_yaml": cached_original,
                "refined_yaml": cached_refined,
                "rationale": cached.rationale,
                "diff_summary": cached.diff_summary,
                "cached": True,
                "stage_two": use_seed,
                "bytes_sent": 0,
                "bytes_received": 0,
            },
        )
        return

    # Build the virtual insight + feedback text from observations.
    virtual_fingerprint = {
        "automation_id": automation_id,
        "kind": "automation_audit_suggest",
    }
    virtual_insight = Insight(
        id=Insight.compute_id(
            InsightKind.AUTOMATION_PROPOSAL, virtual_fingerprint
        ),
        kind=InsightKind.AUTOMATION_PROPOSAL,
        detector="user_audit",
        area_id=None,
        title=(
            "Refine existing automation based on audit findings: "
            f"{(starting_payload or {}).get('alias') if isinstance(starting_payload, dict) else automation_id}"  # noqa: E501
        ),
        confidence=1.0,
        fingerprint=virtual_fingerprint,
        payload=starting_payload,
        payload_format="automation",
        created_at=_dt.now(tz=UTC),
    )

    # Build via the use-case-aware helper. Per-observation-kind
    # hints + shared regression principles + dynamic "all
    # context-only" early-exit framing all live in one place.
    #
    # Stage-two calls force depth=concise to leave more output token
    # headroom for the model. Stage-two prompts re-include the YAML
    # (the algorithm's output), and Gemini's default max_output_tokens
    # is small enough that re-emitting a full YAML + verbose rationale
    # hits MAX_TOKENS. Concise principles are sufficient — the user
    # is iterating; they've already seen the rules once.
    depth = _resolve_audit_depth(hass, msg.get("analysis_depth"))
    effective_depth = "concise" if use_seed else depth
    feedback = _build_audit_feedback(observations, depth=effective_depth)
    if use_seed:
        # Frame the second-stage call: the LLM is iterating on the
        # algorithm's output, not starting from scratch.
        feedback = (
            "STAGE TWO. The YAML has already been fixed by our "
            "deterministic stage — build on it, don't undo it. "
            "Output the refined YAML and a 1-2 sentence rationale.\n\n"
            + feedback
        )
    if extra_feedback.strip():
        feedback += (
            "\n\nUSER ADDITIONAL REQUEST:\n"
            + extra_feedback.strip()
        )

    blocked = _resolve_blocked_entities(hass, get_blocked_entities)
    redactor = Redactor(
        store, mode=RedactionMode.AGGRESSIVE, blocked_entities=blocked
    )
    preferred = _resolve_preferred_agent_id(hass)

    try:
        result = await refine_insight(
            hass,
            agent_id=msg.get("agent_id"),
            insight=virtual_insight,
            redactor=redactor,
            feedback=feedback,
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

    # Cache + audit log.
    cache_put(
        cache_key,
        refined_yaml=result.refined_payload,
        rationale=result.rationale,
        diff_summary=result.diff_summary,
    )
    await _audit_attempts(
        store, result.attempts, insight_id=virtual_insight.id, redactor=redactor
    )

    # Render both sides as proper YAML so the side-by-side diff
    # is readable. JSON looks like garbage in a YAML context;
    # the user expects what they'd see in HA's automation editor.
    # For stage-two calls the "original" is the algorithm's output
    # (starting_payload), not the raw automation — that's what the
    # user is comparing the LLM's further-refinement against.
    diff_baseline = starting_payload if use_seed else raw
    try:
        import yaml as _yaml

        original_yaml_str = _yaml.safe_dump(
            diff_baseline, sort_keys=False, default_flow_style=False
        )
        refined_yaml_str = _yaml.safe_dump(
            result.refined_payload,
            sort_keys=False,
            default_flow_style=False,
        )
    except Exception:
        original_yaml_str = str(diff_baseline)
        refined_yaml_str = str(result.refined_payload)

    connection.send_result(
        msg["id"],
        {
            "automation_id": automation_id,
            "alias": raw.get("alias"),
            "refined_config": result.refined_payload,
            "original_yaml": original_yaml_str,
            "refined_yaml": refined_yaml_str,
            "rationale": result.rationale,
            "diff_summary": result.diff_summary,
            "cached": False,
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


