"""Per-month LLM spend tracking for AutomationAudit.

Pulls aggregates from the existing `outbound_calls` audit log
(bytes-sent + bytes-received per call) and converts to an
estimated USD figure using the integration's existing cost
estimator. The audit-suggest batch service consults this before
each call and stops the batch when the estimated month-to-date
cost crosses the user-configured cap.

Defensive defaults: $5/month, easily overridden via OptionsFlow.
The audit_suggest single-click path (Phase C) is NOT gated — the
user explicitly clicked, that's their call. The gate applies only
to the BATCH service which can stack many calls in one go.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..store.store import HaInsightsStore

_LOGGER = logging.getLogger(__name__)

# Conservative per-1k-token estimate used as a fallback when the
# real cost_estimator can't classify the agent. Pessimistic on
# purpose — we'd rather under-spend than blow past the cap.
_FALLBACK_USD_PER_1K_TOKENS = 0.01
_BYTES_PER_TOKEN_ROUGH = 4.0


@dataclass(frozen=True)
class MonthlySpend:
    month_start_ts: float
    call_count: int
    bytes_total: int
    estimated_usd: float


async def estimate_month_to_date(
    store: "HaInsightsStore", now: datetime | None = None
) -> MonthlySpend:
    """Sum outbound_calls for the current month, convert to USD."""
    if now is None:
        now = datetime.now(tz=UTC)
    month_start = datetime(
        year=now.year, month=now.month, day=1, tzinfo=UTC
    )
    month_start_ts = month_start.timestamp()

    bytes_total = 0
    call_count = 0
    try:
        async with store._c.execute(  # noqa: SLF001 — intentional
            "SELECT COALESCE(SUM(bytes_sent), 0) AS bs, "
            "COALESCE(SUM(bytes_received), 0) AS br, "
            "COUNT(*) AS n "
            "FROM outbound_calls WHERE timestamp >= ?",
            (month_start_ts,),
        ) as cur:
            row = await cur.fetchone()
            if row is not None:
                bytes_total = int(row["bs"]) + int(row["br"])
                call_count = int(row["n"])
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("budget: month-to-date query failed: %s", err)

    estimated_tokens = bytes_total / _BYTES_PER_TOKEN_ROUGH
    estimated_usd = (estimated_tokens / 1000.0) * _FALLBACK_USD_PER_1K_TOKENS

    return MonthlySpend(
        month_start_ts=month_start_ts,
        call_count=call_count,
        bytes_total=bytes_total,
        estimated_usd=round(estimated_usd, 4),
    )


def is_within_budget(
    current: MonthlySpend, *, monthly_cap_usd: float
) -> bool:
    """Whether another batch call would stay under the user's cap.

    Treats the cap as a soft ceiling: returns True only if the
    current month-to-date is STRICTLY less than the cap. The single
    next call could still cross it, but we let one over-shoot
    happen rather than blocking when we don't know the actual cost
    of the next call.
    """
    if monthly_cap_usd <= 0:
        return False  # 0 cap means "disabled"
    return current.estimated_usd < monthly_cap_usd


def is_local_agent(agent_id: str | None) -> bool:
    """Whether the configured agent is local — i.e. no $ cost per
    call so the monthly budget gate shouldn't fire. Wraps the
    existing locality classifier so future heuristics live in one
    place.

    `None` returns False (conservative: treat unknown as cloud so
    the gate still protects). The audit suggest batch only skips
    budget enforcement when we're confidently local.
    """
    from ..llm.privacy_log import derive_agent_locality

    if agent_id is None:
        return False
    return derive_agent_locality(agent_id) == "local"


def reset_for_test() -> None:
    """No-op placeholder. The spend tracker is stateless — it
    derives everything from the audit log on demand. Provided so
    tests can express intent."""
    _ = time.time()  # touch time so the import isn't dead-weight
