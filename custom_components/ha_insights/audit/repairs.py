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

# v1.13.1 — stricter floor for proposal-style insights (schedule /
# cooccurrence / stale automations / etc.). The audit pipeline gets
# the 0.7 floor above because audit findings are deterministic; a
# 0.7 trigger-drift detection has actionable certainty. Proposals
# are inferential — a 0.7 schedule could still be a coincidence
# from a short observation window. Bumping to 0.85 keeps Repairs a
# high-signal surface even if the user is opted in.
_MIN_PROPOSAL_REPAIRS_CONFIDENCE = 0.85

# Insight kinds eligible for the proposal-stream Repairs emission.
# AUTOMATION_PROPOSAL covers schedule / cooccurrence / streak /
# long_tail / state_shift / etc. AUTOMATION_IMPROVEMENT covers
# stale_automation + future linter-style detectors.
_PROPOSAL_ELIGIBLE_KINDS: frozenset[str] = frozenset(
    {"automation_proposal", "automation_improvement"},
)

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

# Issue-id prefixes so our entries are easy to spot and sweep.
# Two streams: audit (deterministic findings on existing automations)
# and proposal (inferential pattern discoveries).
_ISSUE_PREFIX = "audit:"
_PROPOSAL_PREFIX = "proposal:"


def _issue_id_for(insight_id: str) -> str:
    return f"{_ISSUE_PREFIX}{insight_id}"


def _proposal_issue_id_for(insight_id: str) -> str:
    return f"{_PROPOSAL_PREFIX}{insight_id}"


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
    from ws_dismiss / ws_apply so dismissing in our panel also clears
    the Repairs surface. Tries BOTH prefixes (audit + proposal) since
    the caller doesn't know which stream emitted the issue. Returns
    True if any row was deleted."""
    try:
        from homeassistant.helpers import issue_registry as ir
    except Exception:
        return False
    registry = ir.async_get(hass)
    deleted_any = False
    for issue_id in (
        _issue_id_for(insight_id),
        _proposal_issue_id_for(insight_id),
    ):
        if registry.async_get_issue(DOMAIN, issue_id) is None:
            continue
        try:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
            deleted_any = True
        except Exception as err:
            _LOGGER.debug("Repairs clear failed for %s: %s", issue_id, err)
    return deleted_any


def clear_all_audit_issues(hass: HomeAssistant) -> int:
    """Sweep ALL ha_insights Repairs entries (audit + proposal).
    Called on integration unload / purge so we don't leave orphan
    issues. Returns count deleted."""
    try:
        from homeassistant.helpers import issue_registry as ir
    except Exception:
        return 0
    registry = ir.async_get(hass)
    issue_ids = [
        issue.issue_id
        for issue in registry.issues.values()
        if issue.domain == DOMAIN
        and (
            issue.issue_id.startswith(_ISSUE_PREFIX)
            or issue.issue_id.startswith(_PROPOSAL_PREFIX)
        )
    ]
    n = 0
    for iid in issue_ids:
        try:
            ir.async_delete_issue(hass, DOMAIN, iid)
            n += 1
        except Exception as err:
            _LOGGER.debug("Repairs sweep failed for %s: %s", iid, err)
    return n


# v1.13.1 — proposal-stream Repairs emission ----------------------


def _proposal_summary_for(insight: Insight) -> str:
    """One-line summary for a proposal-style insight. Uses the
    insight's `title` directly (already concise + human-readable
    by every detector that emits AUTOMATION_PROPOSAL /
    AUTOMATION_IMPROVEMENT). Caps to 380 chars for Repairs detail
    panel readability."""
    summary = insight.title or ""
    if len(summary) > 380:
        summary = summary[:377] + "…"
    return summary


def _eligible_proposal(insight: Insight) -> bool:
    """Gate proposal-stream insights into Repairs.

    Filters (all must hold):
      - confidence >= _MIN_PROPOSAL_REPAIRS_CONFIDENCE (0.85)
      - kind in _PROPOSAL_ELIGIBLE_KINDS
      - detector != "automation_audit" (audit handled by the
        sync_audit_issues path)
      - has a non-empty title
    """
    if insight.confidence < _MIN_PROPOSAL_REPAIRS_CONFIDENCE:
        return False
    if str(insight.kind) not in _PROPOSAL_ELIGIBLE_KINDS:
        return False
    if insight.detector == "automation_audit":
        # audit findings have their own (less-strict) bridge.
        return False
    if not insight.title:
        return False
    return True


def sync_proposal_issues(
    hass: HomeAssistant,
    insights: list[Insight],
) -> dict[str, int]:
    """Reconcile the issue registry with the high-confidence proposal
    insight set. Mirror of `sync_audit_issues` but uses the proposal
    prefix + stricter confidence floor.

    Caller is expected to gate this behind the OptionsFlow toggle
    `CONF_EMIT_PROPOSALS_TO_REPAIRS`. Off by default — a busy install
    can produce dozens of high-confidence proposals and we don't want
    to flood HA's Repairs surface on every user by default.

    Returns counters: {created, updated, deleted}.
    """
    try:
        from homeassistant.helpers import issue_registry as ir
    except Exception:
        _LOGGER.debug(
            "issue_registry import failed — skipping proposal Repairs sync",
        )
        return {"created": 0, "updated": 0, "deleted": 0}

    desired: dict[str, Insight] = {}
    for ins in insights:
        if not _eligible_proposal(ins):
            continue
        desired[_proposal_issue_id_for(ins.id)] = ins

    registry = ir.async_get(hass)
    existing_ids: set[str] = {
        issue.issue_id
        for issue in registry.issues.values()
        if issue.domain == DOMAIN
        and issue.issue_id.startswith(_PROPOSAL_PREFIX)
    }
    desired_ids = set(desired.keys())
    to_create = desired_ids - existing_ids
    to_delete = existing_ids - desired_ids

    created = 0
    for issue_id in to_create:
        ins = desired[issue_id]
        try:
            _emit_one_proposal(hass, ir, issue_id, ins)
            created += 1
        except Exception as err:
            _LOGGER.debug(
                "Proposal Repairs emit failed for %s: %s", issue_id, err,
            )

    updated = 0
    for issue_id in desired_ids - to_create:
        ins = desired[issue_id]
        try:
            _emit_one_proposal(hass, ir, issue_id, ins)
            updated += 1
        except Exception as err:
            _LOGGER.debug(
                "Proposal Repairs refresh failed for %s: %s", issue_id, err,
            )

    deleted = 0
    for issue_id in to_delete:
        try:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
            deleted += 1
        except Exception as err:
            _LOGGER.debug(
                "Proposal Repairs delete failed for %s: %s", issue_id, err,
            )

    if created or deleted:
        _LOGGER.info(
            "Proposal Repairs sync: %d created, %d updated, %d deleted "
            "(total proposal issues: %d)",
            created,
            updated,
            deleted,
            len(desired),
        )
    return {"created": created, "updated": updated, "deleted": deleted}


def _emit_one_proposal(
    hass: HomeAssistant,
    ir_module: Any,
    issue_id: str,
    insight: Insight,
) -> None:
    """Create-or-refresh ONE Repairs entry for a proposal insight.

    Uses the existing `audit_finding` translation key — the placeholder
    shape (`automation`, `summary`) is generic enough to render any
    proposal text. The Fix button isn't surfaced (is_fixable=False)
    because proposals are reviewed in our panel; clicking the issue
    deep-links there via learn_more_url.
    """
    summary = _proposal_summary_for(insight)
    # `automation` placeholder is the detector name for proposal-stream;
    # the audit version uses the automation_alias. Card panel handles
    # both; Repairs detail panel renders the placeholder verbatim.
    automation_label = insight.detector or "ha_insights"
    severity = ir_module.IssueSeverity.WARNING
    ir_module.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=severity,
        translation_key="audit_finding",
        translation_placeholders={
            "automation": automation_label,
            "summary": summary,
        },
        learn_more_url="/ha-insights",
    )
