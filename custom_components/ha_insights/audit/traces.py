"""HA Automation Trace fetcher — async wrapper around the built-in
automation/trace WebSocket API.

HA stores the last N execution traces per automation (default 5,
configurable per-automation). Each trace records the exact firing
time, condition pass/fail per step, action outcomes, errors, and
variables. We turn these into aggregate observations the audit
packet can use as **ground truth** instead of inferring from raw
state changes.

Async-cheap: each `_get_trace` is a single WS round-trip returning
small JSON. We fetch every trace for every audited automation
inline during the scan (typically 5-50 traces total) — no back-
pressure needed at that scale.

Privacy note: traces include the user's automation variables and
template results. We extract only AGGREGATE counts/timestamps here.
The raw trace blobs never leave this module, never go to the LLM.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class TraceAggregates:
    """Per-automation summary extracted from HA's stored traces.

    All fields are optional — when no traces exist (new automation,
    `stored_traces: 0` configured), this is an empty dataclass and
    the packet just skips trace-derived observations.
    """

    automation_id: str
    trace_count: int = 0
    last_run_at: datetime | None = None
    # Number of runs where every condition passed and all actions ran
    successful_runs: int = 0
    # Number of runs where at least one condition evaluated to False
    # (the automation triggered but bailed out at a condition step)
    condition_blocked_runs: int = 0
    # Number of runs where an action raised an error
    action_errored_runs: int = 0
    # Average wall-clock time the run took, from trigger to last action
    avg_duration_ms: float | None = None
    # Per-condition pass rates: {step_key: (passes, total)} so the
    # audit packet can say "condition step #2 blocked 142 of 184 fires"
    condition_pass_rates: dict[str, tuple[int, int]] = field(
        default_factory=dict
    )


async def fetch_trace_aggregates(
    hass: "HomeAssistant",
    automation_id: str,
) -> TraceAggregates:
    """Return a TraceAggregates summarizing every stored trace for one
    automation. Empty aggregates on any error — traces are optional
    enrichment, not a hard dependency.

    The automation_id must be the HA-internal automation entity id
    (e.g. "automation.morning_routine") OR the YAML id. We try the
    entity_id form first since that's what HA's trace WS API expects.
    """
    # HA's trace WS API keys by item_id (the automation's id, NOT
    # the entity_id). If we were given the YAML "id" field, that's
    # already the right form. If we were given an alias, we need to
    # resolve. The simplest path: try both shapes.
    candidates = [automation_id]
    if not automation_id.startswith("automation."):
        candidates.append(f"automation.{automation_id}")

    listing: list[dict[str, Any]] | None = None
    chosen_key: str | None = None
    for candidate in candidates:
        listing = await _list_traces(hass, candidate)
        if listing is not None:
            chosen_key = candidate
            break
    if listing is None or chosen_key is None:
        return TraceAggregates(automation_id=automation_id)
    if not listing:
        return TraceAggregates(automation_id=automation_id)

    # Pull each trace's detail in parallel (small, async-cheap).
    detail_tasks = [
        _get_trace(hass, chosen_key, t.get("run_id"))
        for t in listing
        if t.get("run_id")
    ]
    details = await asyncio.gather(*detail_tasks, return_exceptions=True)

    aggregates = _aggregate_traces(automation_id, listing, details)
    return aggregates


async def _list_traces(
    hass: "HomeAssistant",
    item_id: str,
) -> list[dict[str, Any]] | None:
    """`trace/list` WS command via HA's internal helper. Returns None
    if the API isn't available or the id has no traces."""
    try:
        # The trace component exposes async_list_traces / async_get_trace
        # helpers through `hass.data["trace"]`. Falling back to the WS
        # command is fragile, so prefer direct API.
        from homeassistant.components.trace import (
            async_list_contexts,  # noqa: F401  — present to confirm import works
        )
        from homeassistant.components.trace.models import (
            async_store_trace,  # noqa: F401
        )
    except Exception:  # noqa: BLE001
        # Trace integration may not be loaded; just bail out.
        return None

    try:
        # Public-API path: list_automation_traces() is the documented
        # accessor on the trace integration. It returns a list of
        # ItemTrace dicts.
        from homeassistant.components.automation import (
            DOMAIN as AUTOMATION_DOMAIN,
        )
        from homeassistant.components.trace import (
            async_get_traces_for_domain,
        )

        traces = await async_get_traces_for_domain(
            hass, AUTOMATION_DOMAIN
        )
        # Filter by our item_id. The structure varies by HA version —
        # try both shapes.
        bare_id = item_id.removeprefix("automation.")
        item_traces = traces.get(item_id) or traces.get(bare_id)
        if item_traces is None:
            return []
        # Normalize to list of {run_id, timestamp} for the detail-fetch
        # phase. Different HA versions store this differently.
        out: list[dict[str, Any]] = []
        iterable = (
            item_traces.values()
            if isinstance(item_traces, dict)
            else item_traces
        )
        for t in iterable:
            if hasattr(t, "as_short_dict"):
                out.append(t.as_short_dict())
            elif isinstance(t, dict):
                out.append(t)
        return out
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug(
            "audit/traces: list failed for %s: %s — skipping trace observations",
            item_id,
            err,
        )
        return None


async def _get_trace(
    hass: "HomeAssistant",
    item_id: str,
    run_id: str,
) -> dict[str, Any] | None:
    """Fetch one detailed trace. Returns None on any error."""
    try:
        from homeassistant.components.automation import (
            DOMAIN as AUTOMATION_DOMAIN,
        )
        from homeassistant.components.trace import async_get_trace

        trace = await async_get_trace(
            hass, AUTOMATION_DOMAIN, item_id, run_id
        )
        if hasattr(trace, "as_dict"):
            return trace.as_dict()
        return trace if isinstance(trace, dict) else None
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("audit/traces: get failed for %s/%s: %s", item_id, run_id, err)
        return None


def _aggregate_traces(
    automation_id: str,
    listing: list[dict[str, Any]],
    details: list[Any],
) -> TraceAggregates:
    """Reduce raw traces to the aggregate fields. Pure / sync."""
    trace_count = len(listing)
    last_run_at: datetime | None = None
    successful = 0
    condition_blocked = 0
    action_errored = 0
    durations_ms: list[float] = []
    cond_passes: dict[str, list[bool]] = {}

    for entry, detail in zip(listing, details, strict=False):
        ts_raw = entry.get("timestamp", {}).get("start") if isinstance(
            entry.get("timestamp"), dict
        ) else entry.get("start_time")
        ts = _parse_dt(ts_raw)
        if ts is not None and (last_run_at is None or ts > last_run_at):
            last_run_at = ts

        if isinstance(detail, Exception) or not isinstance(detail, dict):
            continue

        # Duration from trigger to final action
        start = _parse_dt(
            detail.get("timestamp", {}).get("start")
            if isinstance(detail.get("timestamp"), dict)
            else detail.get("start_time")
        )
        finish = _parse_dt(
            detail.get("timestamp", {}).get("finish")
            if isinstance(detail.get("timestamp"), dict)
            else detail.get("finish_time")
        )
        if start is not None and finish is not None:
            durations_ms.append((finish - start).total_seconds() * 1000.0)

        # Walk the trace's `trace` dict — keys are step paths
        # ("condition/0", "action/2", ...), values are list of
        # execution records with `result.result` / `error`.
        run_steps = detail.get("trace") or {}
        run_had_condition_block = False
        run_had_action_error = False
        for step_key, runs in run_steps.items():
            if not isinstance(runs, list) or not runs:
                continue
            step_records = [r for r in runs if isinstance(r, dict)]
            if not step_records:
                continue
            head = step_records[0]
            result = head.get("result", {})
            error = head.get("error")
            if step_key.startswith("condition/"):
                passed = bool(result.get("result")) if isinstance(result, dict) else False
                cond_passes.setdefault(step_key, []).append(passed)
                if not passed:
                    run_had_condition_block = True
            elif step_key.startswith("action/"):
                if error is not None:
                    run_had_action_error = True
        if run_had_action_error:
            action_errored += 1
        elif run_had_condition_block:
            condition_blocked += 1
        else:
            successful += 1

    avg_duration = (
        sum(durations_ms) / len(durations_ms) if durations_ms else None
    )
    condition_pass_rates: dict[str, tuple[int, int]] = {
        key: (sum(passes), len(passes))
        for key, passes in cond_passes.items()
    }

    return TraceAggregates(
        automation_id=automation_id,
        trace_count=trace_count,
        last_run_at=last_run_at,
        successful_runs=successful,
        condition_blocked_runs=condition_blocked,
        action_errored_runs=action_errored,
        avg_duration_ms=avg_duration,
        condition_pass_rates=condition_pass_rates,
    )


def _parse_dt(value: Any) -> datetime | None:
    """Best-effort ISO-8601 parser. HA traces sometimes ship strings,
    sometimes datetime objects; tolerate both."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Observation builders — packet.py imports these to layer trace-derived
# observations on top of the buffer-derived ones. Sync / pure.
# ---------------------------------------------------------------------------


# Constants kept here (not in packet.py) because trace primitives can
# evolve independently as HA's trace API changes.
TRACE_DORMANT_DAYS = 30
TRACE_CONDITION_BLOCK_RATIO = 0.5  # >50% blocked → flag
TRACE_MIN_RUNS_FOR_RATIO = 8


def observations_from_traces(
    aggregates: TraceAggregates,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return Observation-dicts derived from one TraceAggregates.

    Returns dicts (not Observation dataclass instances) because this
    module shouldn't import packet.py to avoid a circular import.
    packet.py converts these to Observations.
    """
    if now is None:
        from datetime import UTC

        now = datetime.now(tz=UTC)
    out: list[dict[str, Any]] = []

    # Dormant: last run > N days ago (or no runs at all but the
    # automation exists)
    if aggregates.trace_count == 0:
        out.append(
            {
                "kind": "trace_never_fired",
                "text": (
                    "This automation has no execution traces in HA's "
                    "history. Either it never fired, or HA discarded its "
                    "traces (stored_traces: 0). If it never fired — the "
                    "trigger may be broken or the entity dead."
                ),
                "confidence": 0.6,
                "metrics": {"trace_count": 0},
            }
        )
    elif aggregates.last_run_at is not None:
        age = now - aggregates.last_run_at
        if age > timedelta(days=TRACE_DORMANT_DAYS):
            out.append(
                {
                    "kind": "trace_dormant",
                    "text": (
                        f"This automation last fired {age.days}d ago. "
                        "It may be broken, gated by a stale condition, "
                        "or no longer needed."
                    ),
                    "confidence": 0.85,
                    "metrics": {"days_since_last_run": age.days},
                }
            )

    # Condition pass rate — flag steps that block more than half the runs
    for step_key, (passes, total) in aggregates.condition_pass_rates.items():
        if total < TRACE_MIN_RUNS_FOR_RATIO:
            continue
        pass_ratio = passes / total
        if pass_ratio > (1.0 - TRACE_CONDITION_BLOCK_RATIO):
            continue  # condition passes most of the time → fine
        blocks = total - passes
        out.append(
            {
                "kind": "trace_condition_blocks",
                "text": (
                    f"Condition `{step_key}` evaluated False on "
                    f"{blocks} of {total} fires ({(1-pass_ratio)*100:.0f}% "
                    "blocked). The condition may be too strict — review "
                    "whether you intended it to be that selective."
                ),
                "confidence": 0.85,
                "metrics": {
                    "step": step_key,
                    "block_ratio": round(1.0 - pass_ratio, 3),
                    "total_runs": total,
                    "blocked_runs": blocks,
                },
            }
        )

    # Action errors
    if aggregates.action_errored_runs > 0 and aggregates.trace_count > 0:
        error_ratio = aggregates.action_errored_runs / aggregates.trace_count
        out.append(
            {
                "kind": "trace_action_errors",
                "text": (
                    f"{aggregates.action_errored_runs} of "
                    f"{aggregates.trace_count} recent runs hit an action "
                    f"error ({error_ratio*100:.0f}%). Check the trace tab "
                    "in HA's automation UI for the failing step."
                ),
                "confidence": 0.9,
                "metrics": {
                    "errored_runs": aggregates.action_errored_runs,
                    "total_runs": aggregates.trace_count,
                    "error_ratio": round(error_ratio, 3),
                },
            }
        )

    return out
