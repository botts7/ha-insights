"""LLM gateway — opt-in, narrow, stateless.

Each Explain call is one-shot: insight in, prose out. The LLM is a
translator, not a brain — no retrieval, no conversation memory. See
docs/ARCHITECTURE.md sections 'LLM context injection' and 'Privacy model'.

Modules:
  redactor    — pseudonymize entity_ids + strip always-redacted attributes
  context     — build tiered system-prompt context based on privacy mode
  agent_client — call HA Conversation agents and capture the response
  privacy_log — write to outbound_calls audit table
"""
from __future__ import annotations

from .agent_client import ExplanationResult, build_explain_prompt, explain_insight
from .privacy_log import record_call
from .redactor import (
    ALWAYS_REDACT_ATTRIBUTES,
    RedactionMap,
    RedactionMode,
    Redactor,
)

__all__ = [
    "ALWAYS_REDACT_ATTRIBUTES",
    "ExplanationResult",
    "RedactionMap",
    "RedactionMode",
    "Redactor",
    "build_explain_prompt",
    "explain_insight",
    "record_call",
]
