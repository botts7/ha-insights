"""Dual-emit AutomationAudit findings to HA's standard Repairs registry.

Strategy: when an audit insight crosses an actionability bar, ALSO
surface it as an `issue_registry` entry. Users who never open our
sidebar panel see audit findings in Settings → Repairs alongside
HA's other issue notifications.

Why this matters
----------------
- **Discoverability**: Repairs is the canonical "stuff that's wrong"
  surface in HA. Users check it; they don't always remember a custom
  panel exists.
- **Core-merge bridge**: the deterministic detectors-as-Repairs slice
  is the cleanest piece to eventually upstream into core HA. By
  emitting via the official registry today, we're rehearsing the
  shape a core PR would take.
- **Two-way fix flow**: the `is_fixable` flag tells HA to render a
  "Fix" button. Our `IssueHandler` opens the audit row in the panel
  with the right deep-link.

What surfaces (and what doesn't)
--------------------------------
We DON'T emit a Repairs entry for every audit insight — Repairs is a
high-signal surface, and spamming it would train users to ignore it.
Filters:

  - confidence >= 0.7 (actionable, not heuristic-only)
  - observation kind is in the allow-list (only kinds with clear
    user-facing remediation)
  - excludes pure context-only rollup observations

Lifecycle
---------
Every scan calls `sync_audit_issues(hass, current_insights)` which:
  1. Diffs the current audit insight set against existing
     `ha_insights:audit:...` issue ids.
  2. Creates issues for new audit insights that meet the bar.
  3. Deletes issues whose insight is gone (replaced / dismissed /
     no longer applies).

Idempotent — re-running with the same insights is a no-op.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ..const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from ..insight import Insight

_LOGGER = logging.getLogger(__name__)


# Confidence threshold below which we don't bother HA Repairs.
# Heuristic rollup findings (context_only) stay in our panel only.
_MIN_REPAIRS_CONFIDENCE = 0.7

# Observation kinds eligible for Repairs surface. Each has a clear,
# user-facing remediation that a non-power-user can act on.
_REPAIRS_ELIGIBLE_KINDS: frozenset[str] = frozenset(
    {
        "entity_silent",        # entity is unavailable / missing
        "entity_stale_state",   # state cached on disconnect (v1.2.1+)
        "trace_dormant",        # automation hasn't fired in 30d+
        "trace_action_errors",  # actions throwing exceptions
        "redundant_target",     # mechanical fix available
    }
)

# Issue-id prefix so our entries are easy to spot and sweep.
_ISSUE_PREFIX = "audit:"


def _issue_id_for(insight_id: str) -> str:
    return f"{_ISSUE_PREFIX}{insight_id}"


def _eligible_observation_kinds(insight: Insight) -> list[str]:
    """Return the observation kinds in this insight that qualify for
    Repairs emission. Empty list = skip."""
    if insight.detector != "automation_audit":
        return []
    payload = insight.payload or {}
    # Deterministic-fix audits stash observations under _audit.observations
    auditmeta = payload.get("_audit")
    if isinstance(auditmeta, dict) and isinstance(
        auditmeta.get("observations"), list
    ):
        observations = auditmeta["observations"]
    else:
        observations = payload.get("observations") or []
    kinds: list[str] = []
    for obs in observations:
        if not isinstance(obs, dict):
            continue
        kind = obs.get("kind")
        if not isinstance(kind, str) or kind not in _REPAIRS_ELIGIBLE_KINDS:
            continue
        if (obs.get("metrics") or {}).get("context_only"):
            continue
        kinds.append(kind)
    return kinds


def _summary_for(insight: Insight) -> tuple[str, str]:
    """Produce (alias, finding_summary) for the translation placeholders."""
    payload = insight.payload or {}
    auditmeta = payload.get("_audit") if isinstance(payload, dict) else None
    if isinstance(auditmeta, dict):
        alias = auditmeta.get("automation_alias") or auditmeta.get(
            "automation_id"
        ) or "unknown"
        observations = auditmeta.get("observations") or payload.get(
            "observations"
        )
    else:
        alias = payload.get("automation_alias") or payload.get(
            "automation_id"
        ) or "unknown"
        observations = payload.get("observations")
    summary = ""
    if isinstance(observations, list):
        # Concatenate the eligible findings into one paragraph; cap
        # length so the Repairs detail panel stays readable.
        bullets: list[str] = []
        for obs in observations:
            if not isinstance(obs, dict):
                continue
            kind = obs.get("kind")
            if not isinstance(kind, str) or kind not in _REPAIRS_ELIGIBLE_KINDS:
                continue
            if (obs.get("metrics") or {}).get("context_only"):
                continue
            text = (obs.get("text") or "").strip()
            if text:
                bullets.append(text)
        summary = " · ".join(bullets[:3])
        if len(bullets) > 3:
            summary += f" (+{len(bullets) - 3} more)"
    if not summary:
        summary = insight.title
    if len(summary) > 380:
        summary = summary[:377] + "…"
    return str(alias), summary


def sync_audit_issues(
    hass: HomeAssistant,
    insights: list[Insight],
) -> dict[str, int]:
    """Reconcile the issue registry with the current audit insight set.

    Returns counters: {created, updated, deleted}.
    """
    try:
        from homeassistant.helpers import issue_registry as ir
    except Exception:
        _LOGGER.debug("issue_registry import failed — skipping Repairs sync")
        return {"created": 0, "updated": 0, "deleted": 0}

    desired: dict[str, Insight] = {}
    for ins in insights:
        if ins.confidence < _MIN_REPAIRS_CONFIDENCE:
            continue
        eligible = _eligible_observation_kinds(ins)
        if not eligible:
            continue
        desired[_issue_id_for(ins.id)] = ins

    registry = ir.async_get(hass)
    existing_ids: set[str] = {
        issue.issue_id
        for issue in registry.issues.values()
        if issue.domain == DOMAIN
        and issue.issue_id.startswith(_ISSUE_PREFIX)
    }
    desired_ids = set(desired.keys())
    to_create = desired_ids - existing_ids
    to_delete = existing_ids - desired_ids
    # We don't track "to_update" separately — async_create_issue is
    # idempotent and we always pass the latest placeholders, so any
    # already-existing entry gets refreshed on every sync.

    created = 0
    for issue_id in to_create:
        ins = desired[issue_id]
        try:
            _emit_one(hass, ir, issue_id, ins)
            created += 1
        except Exception as err:
            _LOGGER.debug("Repairs emit failed for %s: %s", issue_id, err)

    updated = 0
    for issue_id in desired_ids - to_create:
        ins = desired[issue_id]
        try:
            _emit_one(hass, ir, issue_id, ins)
            updated += 1
        except Exception as err:
            _LOGGER.debug("Repairs refresh failed for %s: %s", issue_id, err)

    deleted = 0
    for issue_id in to_delete:
        try:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
            deleted += 1
        except Exception as err:
            _LOGGER.debug("Repairs delete failed for %s: %s", issue_id, err)

    if created or deleted:
        _LOGGER.info(
            "Repairs sync: %d created, %d updated, %d deleted "
            "(total audit issues: %d)",
            created,
            updated,
            deleted,
            len(desired),
        )
    return {"created": created, "updated": updated, "deleted": deleted}


def _emit_one(
    hass: HomeAssistant,
    ir_module: Any,
    issue_id: str,
    insight: Insight,
) -> None:
    """Create-or-refresh ONE Repairs entry for an audit insight."""
    alias, summary = _summary_for(insight)
    # Severity = warning. We're flagging things the user probably
    # wants to know but nothing is broken in the running system; a
    # CRITICAL severity is reserved for "your HA won't start" cases.
    severity = ir_module.IssueSeverity.WARNING
    ir_module.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,  # Phase 2 of this work will add a Fix flow
        severity=severity,
        translation_key="audit_finding",
        translation_placeholders={
            "automation": alias,
            "summary": summary,
        },
        learn_more_url="/ha-insights",
    )


def clear_issue_for_insight(hass: HomeAssistant, insight_id: str) -> bool:
    """Idempotent: drop the Repairs entry for one insight id. Called
    from ws_dismiss / ws_apply so dismissing in our panel also
    clears the Repairs surface. Returns True if a row was deleted."""
    try:
        from homeassistant.helpers import issue_registry as ir
    except Exception:
        return False
    issue_id = _issue_id_for(insight_id)
    registry = ir.async_get(hass)
    if registry.async_get_issue(DOMAIN, issue_id) is None:
        return False
    try:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return True
    except Exception as err:
        _LOGGER.debug("Repairs clear failed for %s: %s", issue_id, err)
        return False


def clear_all_audit_issues(hass: HomeAssistant) -> int:
    """Sweep ALL ha_insights audit Repairs entries. Called on
    integration unload / purge so we don't leave orphan issues.
    Returns count deleted."""
    try:
        from homeassistant.helpers import issue_registry as ir
    except Exception:
        return 0
    registry = ir.async_get(hass)
    issue_ids = [
        issue.issue_id
        for issue in registry.issues.values()
        if issue.domain == DOMAIN
        and issue.issue_id.startswith(_ISSUE_PREFIX)
    ]
    n = 0
    for iid in issue_ids:
        try:
            ir.async_delete_issue(hass, DOMAIN, iid)
            n += 1
        except Exception as err:
            _LOGGER.debug("Repairs sweep failed for %s: %s", iid, err)
    return n
