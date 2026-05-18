"""Pure helpers used by the REFINE / chat / audit-suggest handler family.

Six free functions extracted from ``ws_api/__init__.py`` in v1.13.7
(step 5 of the v1.13 refactor). All are dependency-free of other
handlers; they only touch HA primitives (state, config_entries) or
do pure-Python string/JSON/AST manipulation.

Helpers:

  - ``_resolve_audit_depth(hass, override=None)`` — pick the LLM
    prompt verbosity ("concise" or "indepth"). Override > first
    entry's OptionsFlow > "concise" default.
  - ``_humanize_llm_error(raw)`` — translate cryptic provider errors
    (Gemini MAX_TOKENS, OpenAI context_length_exceeded, Anthropic
    prompt-too-long, rate-limit) into actionable user guidance.
  - ``_attempt_to_dict(attempt)`` — serialize an LLM ``AttemptAudit``
    (frozen dataclass) into a JSON-safe dict. Tolerates non-dataclass
    inputs.
  - ``_sanitize_yaml_safe(value)`` — round-trip a value through JSON
    so PyYAML's safe_dump can represent it. Handles HA's
    ``Template`` / ``Selector`` / ``mappingproxy`` / custom-enum
    objects that PyYAML otherwise refuses.
  - ``_find_automation_by_id(hass, automation_id)`` — look up an
    automation's raw_config dict by its id or alias. Walks runtime
    state AND automations.yaml + packages/.
  - ``_build_chat_feedback(user_prompt, related_insights)`` — compose
    the LLM feedback string for the v1.13.2 chat_create_automation
    handler. Surfaces related insights as grounding context.

The ``_CHAT_AUTOMATION_SKELETON`` constant lives here too, since it's
only used by ``_build_chat_feedback``'s caller (the chat handler).

Re-exported back into ``ws_api/__init__.py`` for backwards-compat
during the multi-step REFINE family extraction. Once v1.13.8 moves
``ws_refine_automation`` + ``ws_chat_create_automation`` into their
own files, callers will import from ``._refine_helpers`` directly.

The prompt-building cluster (``_wrap_user_feedback`` +
``_authorized_from_user_text`` + ``_principles_for`` +
``_REFINE_PRINCIPLES_*``) is NOT extracted in this step — they form
a tightly-coupled prompt-template subsystem better moved together
in v1.13.8 alongside the handlers that consume them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


# Skeleton "virtual insight" payload the LLM refines for the v1.13.2
# chat_create_automation handler. Empty trigger + condition + action
# mean the LLM is free to populate everything; alias/mode placeholders
# give it a structural reference. Schema matches what apply_automation
# expects.
_CHAT_AUTOMATION_SKELETON: dict[str, Any] = {
    "alias": "New automation",
    "description": "",
    "mode": "single",
    "trigger": [],
    "condition": [],
    "action": [],
}


def _resolve_audit_depth(
    hass: HomeAssistant, override: str | None = None
) -> str:
    """Resolve depth: per-call override > first entry's OptionsFlow >
    'concise' default. Returns 'concise' or 'indepth'."""
    if override in ("concise", "indepth"):
        return override
    try:
        from ..config_flow import get_audit_analysis_depth

        for entry in hass.config_entries.async_entries(DOMAIN):
            return get_audit_analysis_depth(entry)
    except Exception:
        pass
    return "concise"


def _humanize_llm_error(raw: str) -> str:
    """Translate cryptic provider errors into actionable user guidance.

    Common cases we see in the audit pipeline:
      - Gemini hits its output budget mid-YAML → FinishReason.MAX_TOKENS.
        The default Google AI agent config caps `max_output_tokens` at
        ~8192; a full 200-line automation rewrite + rationale can blow
        through it.
      - OpenAI returns 'context_length_exceeded' on huge YAMLs.
      - Anthropic returns 'prompt is too long' / hits stop_reason of
        'max_tokens'.

    For each known failure mode we append a one-line tip pointing the
    user at the lever they can actually pull.
    """
    text = raw or ""
    lowered = text.lower()
    if "max_tokens" in lowered or "max-tokens" in lowered or "max tokens" in lowered:
        return (
            f"{text}\n\n"
            "→ The LLM ran out of output token budget mid-response. "
            "Try one of:\n"
            "  • Switch the panel's analysis-depth toggle to 'Concise' "
            "(top of the panel)\n"
            "  • Type a shorter / more specific follow-up so the model "
            "doesn't try to rewrite the whole YAML\n"
            "  • Raise `max_output_tokens` in your conversation agent's "
            "configuration (Settings → Devices & Services → your "
            "Google AI / OpenAI / Anthropic Conversation entry)"
        )
    if "context_length" in lowered or "prompt is too long" in lowered:
        return (
            f"{text}\n\n"
            "→ The prompt exceeded the model's context window. "
            "Switch to a model with a larger context (Claude Sonnet 4 "
            "or Gemini Pro), or shorten the automation YAML before "
            "auditing."
        )
    if "rate" in lowered and "limit" in lowered:
        return (
            f"{text}\n\n"
            "→ Rate-limited by the LLM provider. Wait a minute and try again."
        )
    return text


def _attempt_to_dict(attempt: Any) -> dict[str, Any]:
    """Serialize an AttemptAudit (frozen dataclass with no to_dict())
    into a JSON-safe dict. Both ws_refine_automation and
    ws_audit_suggest previously called .to_dict() which doesn't
    exist on the AttemptAudit class — masked until audit_suggest
    actually fired and tripped it.
    """
    from dataclasses import asdict, is_dataclass

    if is_dataclass(attempt) and not isinstance(attempt, type):
        return asdict(attempt)
    return {
        "chosen_agent_id": getattr(attempt, "chosen_agent_id", None),
        "bytes_sent": getattr(attempt, "bytes_sent", 0),
        "bytes_received": getattr(attempt, "bytes_received", 0),
        "success": getattr(attempt, "success", False),
    }


def _sanitize_yaml_safe(value: Any) -> Any:
    """Round-trip a value through JSON so PyYAML's safe_dump can
    represent it.

    HA's automation registry surfaces raw_config dicts that often
    include non-JSON Python types: `Template` objects, `Selector`,
    `mappingproxy`, OrderedDict subclasses, custom enums. PyYAML's
    `safe_dump` raises `RepresenterError("cannot represent an
    object", repr_of_value)` on those.

    Casting to JSON first with `default=str` collapses every unknown
    type to its string repr — losing fidelity for Templates (which
    become their `{{ … }}` source string) but keeping the prompt
    serializable, which is what the LLM pipeline needs.
    """
    import json as _json

    try:
        return _json.loads(_json.dumps(value, default=str))
    except Exception:
        return value


def _find_automation_by_id(
    hass: HomeAssistant, automation_id: str
) -> dict | None:
    """Look up an automation's raw_config dict by its id or alias.

    Walks both runtime state (hass.data["automation"]) AND automations.yaml.
    Returns the first match. None when no automation matches.
    """
    component = hass.data.get("automation")
    entities_iter = None
    if hasattr(component, "entities"):
        entities_iter = component.entities
    elif isinstance(component, dict):
        entities_iter = component.values()
    if entities_iter is not None:
        for entry in entities_iter:
            raw = (
                getattr(entry, "raw_config", None)
                or getattr(entry, "_raw_config", None)
            )
            if isinstance(raw, dict) and (
                str(raw.get("id")) == automation_id
                or raw.get("alias") == automation_id
            ):
                return raw
    # File-based fallback: walk automations.yaml AND any glob-loaded
    # config files (packages/, configuration.yaml inline `automation:`).
    # Package-defined automations were previously invisible to the
    # lookup; this catches them too.
    try:
        import glob as _glob
        import os as _os

        import yaml as _yaml

        candidate_paths: list[str] = []
        candidate_paths.append(
            _os.path.join(hass.config.config_dir, "automations.yaml")
        )
        candidate_paths.append(
            _os.path.join(hass.config.config_dir, "configuration.yaml")
        )
        # Common packages directory pattern. We don't try to read
        # arbitrary user-customised layouts — those are rare and the
        # warning banner explains the limitation.
        for p in _glob.glob(
            _os.path.join(hass.config.config_dir, "packages", "*.yaml")
        ):
            candidate_paths.append(p)
        for p in _glob.glob(
            _os.path.join(hass.config.config_dir, "packages", "**", "*.yaml"),
            recursive=True,
        ):
            candidate_paths.append(p)

        seen_paths: set[str] = set()
        for path in candidate_paths:
            if path in seen_paths or not _os.path.exists(path):
                continue
            seen_paths.add(path)
            try:
                with open(path, encoding="utf-8") as f:
                    loaded = _yaml.safe_load(f)
            except Exception:
                continue
            # Top-level automations.yaml ships a list directly.
            # configuration.yaml / packages have `automation:` as a key.
            candidates: list = []
            if isinstance(loaded, list):
                candidates = loaded
            elif isinstance(loaded, dict):
                auto_block = loaded.get("automation")
                if isinstance(auto_block, list):
                    candidates = auto_block
                elif isinstance(auto_block, dict):
                    candidates = [auto_block]
                else:
                    # Treat the top-level dict itself as a candidate
                    candidates = [loaded]
            for entry in candidates:
                if not isinstance(entry, dict):
                    continue
                if (
                    str(entry.get("id")) == automation_id
                    or entry.get("alias") == automation_id
                ):
                    return entry
    except Exception:
        pass
    return None


def _build_chat_feedback(
    user_prompt: str,
    related_insights: list[Any],
) -> str:
    """Compose the LLM feedback string from the user's free-form
    prompt plus any related insight context the caller passed.

    Related insights are surfaced as "I previously detected …"
    paragraphs so the LLM can ground YAML on the user's actual
    behaviour, not just the prose request. Each insight contributes
    its title + payload summary; full payloads aren't included
    because the redactor would have to walk them and a 5-insight
    bundle would blow the LLM token budget.
    """
    parts: list[str] = []
    parts.append(
        "The user has asked you to write a new Home Assistant automation. "
        "Their request is below. Produce a complete YAML automation "
        "that matches what they described — fill in all of trigger, "
        "condition, action, alias, mode. Use real entity_ids only if "
        "the user mentioned them by name."
    )
    parts.append(f"\nUser request:\n{user_prompt.strip()}")
    if related_insights:
        ctx_lines: list[str] = []
        for ins in related_insights[:5]:  # cap at 5 to bound tokens
            title = getattr(ins, "title", None) or ""
            confidence = getattr(ins, "confidence", 0.0)
            detector = getattr(ins, "detector", "")
            line = f"  - {title}"
            if confidence:
                line += f" (confidence {confidence:.2f}"
                if detector:
                    line += f" via {detector}"
                line += ")"
            ctx_lines.append(line)
        if ctx_lines:
            parts.append(
                "\nRelevant patterns I previously detected in this "
                "user's home (you may use these to ground the automation, "
                "but only if they match what the user asked):\n"
                + "\n".join(ctx_lines)
            )
    return "\n".join(parts)


__all__ = [
    "_CHAT_AUTOMATION_SKELETON",
    "_attempt_to_dict",
    "_build_chat_feedback",
    "_find_automation_by_id",
    "_humanize_llm_error",
    "_resolve_audit_depth",
    "_sanitize_yaml_safe",
]
