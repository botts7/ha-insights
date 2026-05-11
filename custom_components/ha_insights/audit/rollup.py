"""Long-term rollup materializer for the AutomationAudit feature.

Computes per-entity day-of-week / day-of-month / month-of-year
state-transition counts from HA's recorder and stores them in the
`audit_rollups` SQLite table. The audit packet builder reads from
the cache — never queries the recorder inline — keeping the 5-min
scan loop fast even on installs with 6 months of history.

**Performance invariants (CRITICAL):**

- Runs on a daily-ish schedule, never during the scan loop.
- One entity per executor call, with `await asyncio.sleep(0)`
  between to yield the event loop.
- Per-run cap: 50 entities. Big installs spread over multiple days.
- TTL: an entity's rollup is "fresh" for 7 days. Re-running daily
  on already-fresh entities is waste.
- Statistics API first (pre-aggregated, indexed) → fall back to
  `get_significant_states` only when statistics aren't available
  (non-numeric entities, mostly).

**Privacy invariants:**

- Aggregate counts only. No timestamps, no state values, no
  context_ids leave the rollup module.
- Respects `blocked_entities`: never rolls up a blocked entity.

This module also exposes observation builders that read from the
rollup cache and produce Observation dicts (same shape as the
buffer-based observations in audit/packet.py).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from ..store.store import HaInsightsStore

_LOGGER = logging.getLogger(__name__)

# Single-flight lock. Only one rollup batch runs at a time across
# the whole integration — concurrent invocations are no-ops. Avoids
# stacking recorder queries when a user clicks "run rollup" twice
# in a row or the scheduler fires while a previous batch is still
# in flight.
_RUN_LOCK = asyncio.Lock()

# Per-entity recorder query timeout. If one entity blocks the
# executor for longer than this, we abandon it and log; next entity
# in the batch still gets processed. Prevents one slow entity from
# hanging an entire run.
_PER_ENTITY_TIMEOUT_SEC = 20.0

# Total per-batch wall-clock cap. Defensive — if the batch takes
# more than this overall (busy recorder, slow disk), stop early
# and let the next scheduled call pick up where we left off.
_BATCH_BUDGET_SEC = 120.0


# Configuration knobs. Conservative defaults that don't crater
# small HA boxes.
ROLLUP_WINDOW_DAYS = 90
ROLLUP_TTL_DAYS = 7
ROLLUP_BATCH_PER_RUN = 50
# Small-test default — the manual service call uses this so the
# first user-triggered roll-out exercises 5 entities, not 50.
ROLLUP_BATCH_SMALL = 5
# Bucket dimensions. Stable strings — the schema indexes on them.
DIM_DOW = "dow"  # day-of-week, 0=Mon ... 6=Sun
DIM_DOM = "dom"  # day-of-month, 1..31
DIM_MOY = "moy"  # month-of-year, 1..12


# ---------------------------------------------------------------------------
# Rollup materialization
# ---------------------------------------------------------------------------


async def run_rollup_batch(
    hass: "HomeAssistant",
    store: "HaInsightsStore",
    *,
    target_entity_ids: list[str],
    blocked_entities: frozenset[str] = frozenset(),
    batch_size: int = ROLLUP_BATCH_PER_RUN,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Roll up the next batch of stale audit-target entities.

    Single-flight: if a previous batch is still in flight, returns
    immediately with `skipped_inflight=True`. Each entity has its
    own 20s timeout AND the batch has a 120s overall budget — if
    either fires we stop early and the next call picks up where we
    left off.

    Returns a summary dict with `entities_processed`, `errors`,
    `skipped_blocked`, `next_due_count`, `timed_out`, `budget_exceeded`.
    """
    if _RUN_LOCK.locked():
        return {
            "entities_processed": 0,
            "errors": 0,
            "skipped_blocked": 0,
            "next_due_count": -1,
            "skipped_inflight": True,
        }
    async with _RUN_LOCK:
        return await _run_rollup_batch_locked(
            hass,
            store,
            target_entity_ids=target_entity_ids,
            blocked_entities=blocked_entities,
            batch_size=batch_size,
            now=now,
        )


async def _run_rollup_batch_locked(
    hass: "HomeAssistant",
    store: "HaInsightsStore",
    *,
    target_entity_ids: list[str],
    blocked_entities: frozenset[str] = frozenset(),
    batch_size: int = ROLLUP_BATCH_PER_RUN,
    now: datetime | None = None,
) -> dict[str, Any]:
    if now is None:
        now = datetime.now(tz=UTC)
    stale_cutoff = (now - timedelta(days=ROLLUP_TTL_DAYS)).timestamp()
    candidates_all = [e for e in target_entity_ids if e not in blocked_entities]
    blocked_count = len(target_entity_ids) - len(candidates_all)
    candidates = await store.list_stale_rollup_entities(
        candidates_all, stale_cutoff
    )
    batch = candidates[:batch_size]

    started = datetime.now(tz=UTC)
    processed = 0
    errors = 0
    timed_out: list[str] = []
    budget_exceeded = False

    for eid in batch:
        # Per-batch wall clock guard — defensive against pathological
        # recorder backends. Stop early; next call resumes.
        elapsed = (datetime.now(tz=UTC) - started).total_seconds()
        if elapsed > _BATCH_BUDGET_SEC:
            budget_exceeded = True
            _LOGGER.info(
                "rollup: batch budget exceeded after %ds, %d processed; "
                "remainder picked up on next run.",
                int(elapsed),
                processed,
            )
            break
        try:
            rows = await asyncio.wait_for(
                _compute_rollups_for_entity(hass, eid, now=now),
                timeout=_PER_ENTITY_TIMEOUT_SEC,
            )
            await store.upsert_rollups(
                eid,
                rows,
                window_days=ROLLUP_WINDOW_DAYS,
                computed_at_ts=now.timestamp(),
            )
            processed += 1
        except TimeoutError:
            timed_out.append(eid)
            _LOGGER.warning(
                "rollup: %s timed out after %ds — skipping",
                eid,
                int(_PER_ENTITY_TIMEOUT_SEC),
            )
        except Exception as err:  # noqa: BLE001
            errors += 1
            _LOGGER.debug("rollup failed for %s: %s", eid, err)
        # Yield the event loop after every entity. The HA recorder
        # query is the heaviest piece here; if it bursts CPU, the
        # next entity waits naturally.
        await asyncio.sleep(0)

    return {
        "entities_processed": processed,
        "errors": errors,
        "skipped_blocked": blocked_count,
        "next_due_count": max(0, len(candidates) - processed - errors - len(timed_out)),
        "timed_out_entities": timed_out,
        "budget_exceeded": budget_exceeded,
        "batch_duration_sec": round(
            (datetime.now(tz=UTC) - started).total_seconds(), 1
        ),
    }


def collect_audit_target_entities(
    existing_automations: list[dict[str, Any]],
) -> list[str]:
    """Walk every automation, collect the entity_ids the audit cares
    about. Used by the manual-trigger service + future scheduler.
    Stable result so the set of entities that get rolled up is
    deterministic for a given automations.yaml."""
    from ..apply.conflict_scanner import _as_list, _extract_target_entities

    seen: set[str] = set()
    for auto in existing_automations:
        seen.update(_extract_target_entities(auto.get("action")))
        for trig in _as_list(auto.get("trigger")):
            if not isinstance(trig, dict):
                continue
            tid = trig.get("entity_id")
            if isinstance(tid, str):
                seen.add(tid)
            elif isinstance(tid, list):
                seen.update(e for e in tid if isinstance(e, str))
    return sorted(seen)


async def _compute_rollups_for_entity(
    hass: "HomeAssistant",
    entity_id: str,
    *,
    now: datetime,
) -> list[tuple[str, int, int]]:
    """Walk the recorder for one entity, return (dim, bucket, count)
    tuples ready for `Store.upsert_rollups`.

    Strategy: prefer the recorder Statistics API (cheap, pre-rolled
    by HA) when the entity has statistics. Fall back to
    `get_significant_states` for non-numeric / non-stat entities.
    """
    since = now - timedelta(days=ROLLUP_WINDOW_DAYS)

    # Try the states path. Statistics-API path is more performant
    # but only works for numeric sensors that HA's recorder has
    # explicitly opted into (sensors with state_class). For the
    # audit use case we mostly care about binary sensors / switches
    # / lights, which use significant states. Keep this path simple
    # for now; the statistics-first optimisation lands in a
    # follow-up when we have benchmark numbers on real installs.
    bucket_counts: dict[str, dict[int, int]] = {
        DIM_DOW: {},
        DIM_DOM: {},
        DIM_MOY: {},
    }

    def _query_states() -> list[Any]:
        # Run on the executor so the recorder DB query doesn't
        # block the event loop. `get_significant_states` is the
        # standard HA helper.
        try:
            from homeassistant.components.recorder.history import (
                get_significant_states,
            )
        except Exception:  # noqa: BLE001
            return []
        try:
            result = get_significant_states(
                hass,
                since,
                now,
                [entity_id],
                significant_changes_only=True,
                minimal_response=True,
                no_attributes=True,
            )
            return result.get(entity_id) if isinstance(result, dict) else []
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug(
                "rollup: get_significant_states failed for %s: %s",
                entity_id,
                err,
            )
            return []

    states = await hass.async_add_executor_job(_query_states)
    if not states:
        return []

    for st in states:
        ts = _state_timestamp(st)
        if ts is None:
            continue
        local_ts = dt_util.as_local(ts)
        # weekday(): 0=Mon..6=Sun — matches our DIM_DOW convention
        dow = local_ts.weekday()
        dom = local_ts.day
        moy = local_ts.month
        bucket_counts[DIM_DOW][dow] = bucket_counts[DIM_DOW].get(dow, 0) + 1
        bucket_counts[DIM_DOM][dom] = bucket_counts[DIM_DOM].get(dom, 0) + 1
        bucket_counts[DIM_MOY][moy] = bucket_counts[DIM_MOY].get(moy, 0) + 1

    # Flatten to upsert tuple list
    out: list[tuple[str, int, int]] = []
    for dim, buckets in bucket_counts.items():
        for bucket, count in buckets.items():
            out.append((dim, bucket, count))
    return out


def _state_timestamp(st: Any) -> datetime | None:
    """Tolerate the multiple shapes HA returns from get_significant_states.

    Modern: State objects with last_changed/last_updated datetimes.
    minimal_response: dicts with `last_changed` string.
    """
    if st is None:
        return None
    if hasattr(st, "last_changed") and st.last_changed is not None:
        return st.last_changed
    if isinstance(st, dict):
        for key in ("last_changed", "last_updated"):
            v = st.get(key)
            if isinstance(v, str):
                try:
                    return datetime.fromisoformat(v.replace("Z", "+00:00"))
                except ValueError:
                    pass
            elif isinstance(v, datetime):
                return v
    return None


# ---------------------------------------------------------------------------
# Observation builders — packet.py imports these and ships the resulting
# Observation dicts the same way it does for traces.
# ---------------------------------------------------------------------------


# Significant-skew thresholds. A pattern is "real" when:
#   - the window has enough data (≥ 20 transitions total)
#   - one bucket holds ≥ 60% of activity (heavily skewed)
#   - OR there are buckets with zero activity that should have some
#     (used for "never fires on weekends")
_MIN_TOTAL_FOR_ROLLUP_OBS = 20
_SKEW_RATIO = 0.60
_DOW_NAMES = (
    "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun",
)
_MONTH_NAMES = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)


def observations_from_rollups(
    entity_id: str,
    rollups: dict[str, dict[int, int]],
) -> list[dict[str, Any]]:
    """Return Observation-dicts derived from one entity's rollup buckets.

    Returns dicts (not Observation instances) — packet.py wraps them.
    Empty when the rollup is too sparse to draw conclusions.
    """
    out: list[dict[str, Any]] = []
    # Day-of-week patterns
    out.extend(_dow_observations(entity_id, rollups.get(DIM_DOW) or {}))
    # Day-of-month patterns
    out.extend(_dom_observations(entity_id, rollups.get(DIM_DOM) or {}))
    # Month-of-year patterns
    out.extend(_moy_observations(entity_id, rollups.get(DIM_MOY) or {}))
    return out


def _dow_observations(
    entity_id: str, buckets: dict[int, int]
) -> list[dict[str, Any]]:
    total = sum(buckets.values())
    if total < _MIN_TOTAL_FOR_ROLLUP_OBS:
        return []
    out: list[dict[str, Any]] = []
    # Zero-bucket detection — "never fires Sat/Sun"
    zero_days = [i for i in range(7) if buckets.get(i, 0) == 0]
    if 5 in zero_days and 6 in zero_days and total >= 30:
        out.append(
            {
                "kind": "rollup_weekday_only",
                "text": (
                    f"{entity_id} has no recorded transitions on "
                    "Saturday or Sunday over the last 90 days "
                    f"({total} total weekday transitions). "
                    "Trigger restricted to weekdays?"
                ),
                "confidence": 0.85,
                "metrics": {
                    "entity_id": entity_id,
                    "weekday_transitions": total,
                    "weekend_transitions": 0,
                    "dimension": DIM_DOW,
                },
            }
        )
    elif zero_days:
        # Less-clean pattern: some specific days are zero. Surface
        # only if total is high enough that zeros are meaningful.
        if total >= 50:
            day_names = ", ".join(_DOW_NAMES[d] for d in zero_days)
            out.append(
                {
                    "kind": "rollup_dow_dark_days",
                    "text": (
                        f"{entity_id} has zero transitions on "
                        f"{day_names} over 90 days ({total} total "
                        "elsewhere). Conditional on day-of-week?"
                    ),
                    "confidence": 0.7,
                    "metrics": {
                        "entity_id": entity_id,
                        "zero_days": [_DOW_NAMES[d] for d in zero_days],
                        "total": total,
                        "dimension": DIM_DOW,
                    },
                }
            )
    return out


def _dom_observations(
    entity_id: str, buckets: dict[int, int]
) -> list[dict[str, Any]]:
    total = sum(buckets.values())
    if total < _MIN_TOTAL_FOR_ROLLUP_OBS:
        return []
    out: list[dict[str, Any]] = []
    # Heavy month-start concentration: 1st-3rd holds >30% of activity
    early_count = sum(buckets.get(d, 0) for d in range(1, 4))
    if early_count >= total * 0.3 and total >= 30:
        early_ratio = early_count / total
        out.append(
            {
                "kind": "rollup_month_start_spike",
                "text": (
                    f"{entity_id} concentrates {early_ratio*100:.0f}% of "
                    "its activity on the 1st-3rd of each month "
                    "(90-day window, {total} transitions). Bill / "
                    "payroll / monthly-reset trigger?"
                ).replace("{total}", str(total)),
                "confidence": 0.7,
                "metrics": {
                    "entity_id": entity_id,
                    "early_days_ratio": round(early_ratio, 3),
                    "total": total,
                    "dimension": DIM_DOM,
                },
            }
        )
    return out


def _moy_observations(
    entity_id: str, buckets: dict[int, int]
) -> list[dict[str, Any]]:
    total = sum(buckets.values())
    if total < _MIN_TOTAL_FOR_ROLLUP_OBS:
        return []
    out: list[dict[str, Any]] = []
    # Identify months with zero activity. Only meaningful when the
    # 90-day window actually spans them — for newer installs the
    # zero is just "no data yet", not "user doesn't use it then".
    active_months = {m for m, c in buckets.items() if c > 0}
    silent_months = [m for m in range(1, 13) if m not in active_months]
    if (
        len(active_months) >= 1
        and 1 <= len(silent_months) <= 6
        and total >= 30
    ):
        # Only surface if the silent months are a contiguous run
        # (e.g. Apr-Oct silence = winter heater). Random scatter is
        # likely just insufficient data.
        silent_sorted = sorted(silent_months)
        is_run = all(
            silent_sorted[i + 1] - silent_sorted[i] == 1
            for i in range(len(silent_sorted) - 1)
        )
        if is_run and len(silent_sorted) >= 3:
            start = _MONTH_NAMES[silent_sorted[0] - 1]
            end = _MONTH_NAMES[silent_sorted[-1] - 1]
            out.append(
                {
                    "kind": "rollup_seasonal_silence",
                    "text": (
                        f"{entity_id} had zero transitions {start}-{end} "
                        f"(90-day window, {total} transitions in other "
                        "months). Likely seasonal — consider a "
                        "month-of-year condition or disabling for "
                        "the dormant period."
                    ),
                    "confidence": 0.75,
                    "metrics": {
                        "entity_id": entity_id,
                        "silent_months": [
                            _MONTH_NAMES[m - 1] for m in silent_sorted
                        ],
                        "total": total,
                        "dimension": DIM_MOY,
                    },
                }
            )
    return out
