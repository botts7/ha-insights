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

# Per-chunk recorder query timeout. v1.2: rollup now queries one
# week at a time, so we time-bound each chunk independently. If a
# chunk stalls, we abort it and the entity's cursor doesn't advance —
# the next batch picks the same chunk up again.
_PER_CHUNK_TIMEOUT_SEC = 15.0

# Per-entity wall-clock cap across all of its chunks in a single
# batch. Even when the per-chunk timeout protects each call, we
# don't want one entity to monopolize the batch on first-time
# backfill — cap and let the next batch resume.
_PER_ENTITY_TIMEOUT_SEC = 60.0

# Total per-batch wall-clock cap. Defensive — if the batch takes
# more than this overall (busy recorder, slow disk), stop early
# and let the next scheduled call pick up where we left off.
_BATCH_BUDGET_SEC = 120.0

# How many 7-day chunks of recorder history we'll backfill for one
# entity in a single batch. 8 chunks = 56 days/batch/entity. With
# the per-entity 60s wall-clock cap, this works out to ~7.5 s per
# chunk worst case (typical: 1-2 s). Daily scheduler can fully
# backfill a 90-day window in 2 batches, 180-day in 4.
_MAX_CHUNKS_PER_ENTITY = 8

# Chunk width. One week is short enough that even chatty entities
# return a manageable payload (~10k events worst case), long enough
# that we don't pay too many round-trip costs.
_CHUNK_DAYS = 7

# Defensive row cap per chunk. If a single 7-day query returns more
# rows than this, the entity is too chatty to safely roll up — we
# skip the chunk, log, and let the cursor stand (entity will be
# retried next batch). Prevents memory blowups on edge installs.
_CHUNK_ROW_CAP = 5000


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


# Live progress for the in-flight rollup batch. Read by the
# `home_insights/rollup_progress` WS endpoint so the card can show
# a progress bar without polling the DB. Module-global is fine —
# the run lock guarantees at most one batch at a time. Defined here
# (not adjacent to _RUN_LOCK) because the initial `window_days` value
# references ROLLUP_WINDOW_DAYS above.
_PROGRESS: dict[str, Any] = {
    "running": False,
    "total": 0,
    "processed": 0,
    "errors": 0,
    "timed_out": 0,
    "current_entity_id": None,
    "started_ts": None,
    "finished_ts": None,
    "window_days": ROLLUP_WINDOW_DAYS,
    "last_summary": None,
}


def reset_progress() -> None:
    """Wipe live progress state. Called from `async_unload_entry` so a
    reloaded integration doesn't inherit a previous load's stale
    `last_summary` / `finished_ts` in the WS endpoint output."""
    _PROGRESS.update(
        running=False,
        total=0,
        processed=0,
        errors=0,
        timed_out=0,
        current_entity_id=None,
        started_ts=None,
        finished_ts=None,
        window_days=ROLLUP_WINDOW_DAYS,
        last_summary=None,
    )


def get_rollup_progress() -> dict[str, Any]:
    """Snapshot of the current/last rollup batch. Cheap dict copy."""
    snap = dict(_PROGRESS)
    if snap["running"] and snap["started_ts"] is not None:
        elapsed = datetime.now(tz=UTC).timestamp() - snap["started_ts"]
        snap["elapsed_sec"] = round(elapsed, 1)
        if snap["processed"] > 0 and snap["total"] > 0:
            per_entity = elapsed / snap["processed"]
            remaining = max(0, snap["total"] - snap["processed"])
            snap["eta_sec"] = round(per_entity * remaining, 1)
    return snap


# ---------------------------------------------------------------------------
# Rollup materialization
# ---------------------------------------------------------------------------


def _resolve_window_days(hass: HomeAssistant, entry: Any = None) -> int:
    """Resolve the rollup window for the audit pipeline.

    Prefers an explicit `entry` (the per-entry detector path passes
    its own ConfigEntry). Without one, takes the MAX across all
    HA Insights config entries — that way the rollup batch runs
    once and serves the largest window any entry wants. Smaller-
    window entries just read a subset of the same buckets.

    Falls back to the module default (90) when no entries exist
    yet or the options lookup blows up.
    """
    try:
        from ..config_flow import get_audit_rollup_window_days
        from ..const import DOMAIN

        if entry is not None:
            return get_audit_rollup_window_days(entry)
        entries = list(hass.config_entries.async_entries(DOMAIN))
        if not entries:
            return ROLLUP_WINDOW_DAYS
        return max(get_audit_rollup_window_days(e) for e in entries)
    except Exception:
        pass
    return ROLLUP_WINDOW_DAYS


async def run_rollup_batch(
    hass: HomeAssistant,
    store: HaInsightsStore,
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
    hass: HomeAssistant,
    store: HaInsightsStore,
    *,
    target_entity_ids: list[str],
    blocked_entities: frozenset[str] = frozenset(),
    batch_size: int = ROLLUP_BATCH_PER_RUN,
    now: datetime | None = None,
) -> dict[str, Any]:
    if now is None:
        now = datetime.now(tz=UTC)
    end_of_today_ts = _start_of_day_utc(now).timestamp()
    candidates_all = [e for e in target_entity_ids if e not in blocked_entities]
    blocked_count = len(target_entity_ids) - len(candidates_all)
    # v1.2: incremental picker. Returns only entities whose cursor
    # hasn't yet caught up to today. Caught-up entities are no-ops.
    candidates = await store.list_entities_needing_rollup(
        candidates_all, end_of_today_ts
    )
    batch = candidates[:batch_size]

    # Resolve the rollup window from OptionsFlow once per batch.
    # The detector pre-fetch path uses the same resolver so audit
    # findings + the materialized cache stay in sync.
    window_days = _resolve_window_days(hass)

    # v1.12.14: probe the recorder's oldest data once per batch. This
    # caps the per-entity initial cursor so we don't walk through
    # pre-retention empty chunks (the SQL-audit-observed warmup bug).
    # ~14 cheap probes total, well below the per-batch budget; reuse
    # across all entities below.
    recorder_oldest_ts = await _probe_recorder_oldest_ts(hass)

    started = datetime.now(tz=UTC)
    processed = 0
    errors = 0
    timed_out: list[str] = []
    budget_exceeded = False

    # Initialize live progress for the card. Cleared on return.
    _PROGRESS.update(
        running=True,
        total=len(batch),
        processed=0,
        errors=0,
        timed_out=0,
        current_entity_id=None,
        started_ts=started.timestamp(),
        finished_ts=None,
        window_days=window_days,
        last_summary=None,
    )

    try:
        for eid in batch:
            # Per-batch wall clock guard — defensive against
            # pathological recorder backends. Stop early; next call
            # resumes.
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
            _PROGRESS["current_entity_id"] = eid
            try:
                # Incremental: each call processes at most
                # _MAX_CHUNKS_PER_ENTITY chunks of 7 days, then
                # advances the cursor. Subsequent batches resume.
                result = await asyncio.wait_for(
                    _compute_rollups_for_entity_incremental(
                        hass,
                        store,
                        eid,
                        window_days=window_days,
                        now=now,
                        recorder_oldest_ts=recorder_oldest_ts,
                    ),
                    timeout=_PER_ENTITY_TIMEOUT_SEC,
                )
                if result.get("advanced"):
                    processed += 1
                    _PROGRESS["processed"] = processed
            except TimeoutError:
                timed_out.append(eid)
                _PROGRESS["timed_out"] = len(timed_out)
                _LOGGER.warning(
                    "rollup: %s timed out after %ds — cursor not advanced; will retry",
                    eid,
                    int(_PER_ENTITY_TIMEOUT_SEC),
                )
            except Exception as err:
                errors += 1
                _PROGRESS["errors"] = errors
                _LOGGER.debug("rollup failed for %s: %s", eid, err)
            # Yield the event loop after every entity. The HA
            # recorder query is the heaviest piece here; if it bursts
            # CPU, the next entity waits naturally.
            await asyncio.sleep(0)

        summary = {
            "entities_processed": processed,
            "errors": errors,
            "skipped_blocked": blocked_count,
            "next_due_count": max(
                0, len(candidates) - processed - errors - len(timed_out)
            ),
            "timed_out_entities": timed_out,
            "budget_exceeded": budget_exceeded,
            "batch_duration_sec": round(
                (datetime.now(tz=UTC) - started).total_seconds(), 1
            ),
        }
    finally:
        _PROGRESS.update(
            running=False,
            current_entity_id=None,
            finished_ts=datetime.now(tz=UTC).timestamp(),
            last_summary=locals().get("summary"),
        )
    return summary


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


def _start_of_day_utc(t: datetime) -> datetime:
    """Midnight in HA local time, returned as UTC. We bucket on
    LOCAL day boundaries so 'every Monday morning at 7' falls into
    Monday consistently regardless of UTC offset."""
    local = dt_util.as_local(t)
    midnight_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight_local.astimezone(UTC)


# v1.12.14: probe the recorder's oldest data depth once per batch.
# Mirrors the strategy in `ws_api.ws_recorder_status` but lives here
# so the batch loop can pass the result through to per-entity rollup
# without re-probing per entity. Used to clamp the initial cursor —
# eliminates the "100+ entities sitting at the same cursor with 0
# rollups written" warmup bug observed in real-install SQL audit
# 2026-05-18.
_RECORDER_PROBE_DAYS: tuple[int, ...] = (
    1, 3, 7, 14, 30, 60, 90, 120, 150, 180, 210, 270, 365,
)


async def _probe_recorder_oldest_ts(
    hass: HomeAssistant,
) -> float | None:
    """Return the UNIX timestamp (seconds) of the recorder's deepest
    retained data, or None if the probe fails.

    Walks `_RECORDER_PROBE_DAYS` from shallow to deep until a probe
    returns empty — the depth before that is the retention ceiling.
    Each probe is a 1-hour slice with no entity filter, so the
    recorder reads one tiny page per depth.

    Routes through the recorder's own executor so we serialise
    against in-flight writes instead of fighting the default pool.
    """
    try:
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.history import (
            get_significant_states,
        )
    except ImportError:
        return None

    try:
        rec = get_instance(hass)
    except Exception:
        return None

    def _probe_sync() -> float | None:
        now_dt = datetime.now(tz=UTC)
        deepest_with_data_days: int | None = None
        for days in _RECORDER_PROBE_DAYS:
            start = now_dt - timedelta(days=days)
            end = start + timedelta(hours=1)
            try:
                result = get_significant_states(
                    hass,
                    start,
                    end,
                    None,
                    significant_changes_only=True,
                    minimal_response=True,
                    no_attributes=True,
                )
            except Exception as err:
                _LOGGER.debug(
                    "rollup recorder probe at %dd failed: %s",
                    days,
                    err,
                )
                break
            if result:
                deepest_with_data_days = days
                continue
            break
        if deepest_with_data_days is None:
            return None
        # Convert to UNIX timestamp (start of the deepest probe slice).
        # Floored to start-of-day UTC for consistency with cursor logic.
        oldest_dt = _start_of_day_utc(
            datetime.now(tz=UTC) - timedelta(days=deepest_with_data_days)
        )
        return oldest_dt.timestamp()

    try:
        return await rec.async_add_executor_job(_probe_sync)
    except Exception as err:
        _LOGGER.debug("rollup recorder probe failed: %s", err)
        return None


async def _query_states_chunk(
    hass: HomeAssistant,
    entity_id: str,
    chunk_start: datetime,
    chunk_end: datetime,
) -> list[Any] | None:
    """Run get_significant_states for one chunk on the recorder's
    own executor. Idiomatic per HA core review guidelines — the
    recorder serializes its own connection pool, so reads scheduled
    here cooperate cleanly with concurrent recorder writes instead
    of fighting them on the default executor.

    Returns None on any failure (caller skips the chunk). Bounded
    to _CHUNK_ROW_CAP rows; over-cap chunks are rejected so memory
    stays predictable.
    """
    try:
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.history import (
            get_significant_states,
        )
    except ImportError:  # recorder not available — graceful no-op
        return None

    def _query() -> list[Any] | str | None:
        """Three-valued return so the caller can tell apart:
          - list: chunk succeeded, here are the states
          - "rowcap": chunk exceeded the OOM-safety row cap; skip
            forward by 1 day (the chunk would always be too big)
          - None: query itself failed (recorder timeout, schema
            issue, etc.); cursor must NOT be advanced — retry on
            next batch
        the previous bool-collapsed contract
        (`None` for both row-cap AND failure) caused failures to be
        treated as row-cap, advancing the cursor by 1 day per fail
        — losing up to 6 days of recoverable history if the
        recorder hiccupped during a chunked backfill.
        """
        try:
            result = get_significant_states(
                hass,
                chunk_start,
                chunk_end,
                [entity_id],
                significant_changes_only=True,
                minimal_response=True,
                no_attributes=True,
            )
        except Exception as err:
            _LOGGER.debug(
                "rollup: states query failed for %s [%s..%s]: %s",
                entity_id,
                chunk_start.isoformat(),
                chunk_end.isoformat(),
                err,
            )
            return None  # genuine failure — caller retries chunk
        rows = result.get(entity_id) if isinstance(result, dict) else []
        rows = rows or []
        if len(rows) > _CHUNK_ROW_CAP:
            # Row-cap — chunk too big to safely materialize. Caller
            # advances cursor 1 day to skip the worst day.
            return "rowcap"
        return rows

    # `recorder.get_instance(hass).async_add_executor_job` routes
    # the query through the recorder's dedicated thread, so it
    # serializes against in-flight writes the same way HA's
    # built-in history/statistics endpoints do.
    return await get_instance(hass).async_add_executor_job(_query)


def _state_to_bucket_deltas(
    states: list[Any],
) -> dict[str, dict[int, int]]:
    """Aggregate a chunk's state list into per-dimension bucket
    deltas. Pure function — no HA calls, easy to test."""
    deltas: dict[str, dict[int, int]] = {
        DIM_DOW: {},
        DIM_DOM: {},
        DIM_MOY: {},
    }
    for st in states:
        ts = _state_timestamp(st)
        if ts is None:
            continue
        local_ts = dt_util.as_local(ts)
        dow = local_ts.weekday()  # 0=Mon..6=Sun
        dom = local_ts.day
        moy = local_ts.month
        deltas[DIM_DOW][dow] = deltas[DIM_DOW].get(dow, 0) + 1
        deltas[DIM_DOM][dom] = deltas[DIM_DOM].get(dom, 0) + 1
        deltas[DIM_MOY][moy] = deltas[DIM_MOY].get(moy, 0) + 1
    return deltas


async def _compute_rollups_for_entity_incremental(
    hass: HomeAssistant,
    store: HaInsightsStore,
    entity_id: str,
    *,
    window_days: int = ROLLUP_WINDOW_DAYS,
    now: datetime,
    recorder_oldest_ts: float | None = None,
) -> dict[str, Any]:
    """Advance one entity's rollup by at most _MAX_CHUNKS_PER_ENTITY
    weeks of recorder history. Merges chunks additively into
    audit_rollups + advances audit_rollup_progress.

    Returns a status dict so the batch loop knows whether work was
    done (for the progress bar). Never raises on per-chunk failures —
    skips and leaves the cursor where it stood.

    Strategy:
      1. Read the entity's cursor + window. If absent or window
         changed, start at `max(now - window_days, recorder_oldest_ts)`.
      2. Compute end = midnight at start of today (don't double-
         count partial days; today is still being written).
      3. Walk forward in 7-day chunks, additively merging each
         chunk's bucket counts.
      4. After each chunk succeeds, advance the cursor by 7 days.
         A failed chunk leaves the cursor untouched so the next
         batch picks the same week up.
      5. Stop when window is full, or _MAX_CHUNKS_PER_ENTITY hit.

    `recorder_oldest_ts` is the UNIX timestamp (seconds) of the
    oldest recorder data observed at batch start, probed once via
    `_probe_recorder_oldest_ts`. When set, the initial cursor is
    clamped to `max(now - window_days, recorder_oldest_ts)` so the
    rollup doesn't waste batches walking through pre-retention
    empty chunks. v1.12.14 fix for the SQL-audit-observed "100+
    entities sitting at the same cursor with 0 rollups written"
    bug — the cursor was advancing through 56 days of pre-retention
    history per batch before reaching any real data.
    """
    end_ts = _start_of_day_utc(now).timestamp()

    progress = await store.get_rollup_progress(entity_id)
    if progress is None or progress[1] != window_days:
        # First time, or window changed → fresh start. v1.12.14:
        # clamp the initial cursor to the deeper of (now - window)
        # and the recorder's oldest data. Before the clamp, on installs
        # where recorder retention < configured window (e.g., default
        # 10-day keep with 180-day audit window), the cursor walked
        # through 170 days of empty chunks before producing any data —
        # creating the impression that the integration was broken.
        cursor_ts = _start_of_day_utc(
            now - timedelta(days=window_days)
        ).timestamp()
        if recorder_oldest_ts is not None and recorder_oldest_ts > cursor_ts:
            cursor_ts = recorder_oldest_ts
        # Wipe any v1.1-era buckets for this entity so the
        # incremental merge starts from a clean slate. Otherwise old
        # full-window totals + new chunk deltas = inflated counts.
        # No-op for entities that have no prior rollup.
        await store.clear_rollups_for_entity(entity_id)
    else:
        cursor_ts, _ = progress

    if cursor_ts >= end_ts:
        # Up to date.
        return {"advanced": False, "reason": "current", "chunks": 0}

    chunks_processed = 0
    rows_seen = 0
    entity_started = datetime.now(tz=UTC)
    while chunks_processed < _MAX_CHUNKS_PER_ENTITY and cursor_ts < end_ts:
        # Per-entity wall-clock guard inside the per-batch budget.
        per_entity_elapsed = (
            datetime.now(tz=UTC) - entity_started
        ).total_seconds()
        if per_entity_elapsed > _PER_ENTITY_TIMEOUT_SEC:
            _LOGGER.debug(
                "rollup: %s hit per-entity cap after %d chunks",
                entity_id,
                chunks_processed,
            )
            break

        chunk_start = datetime.fromtimestamp(cursor_ts, tz=UTC)
        chunk_end = min(
            chunk_start + timedelta(days=_CHUNK_DAYS),
            datetime.fromtimestamp(end_ts, tz=UTC),
        )

        try:
            states = await asyncio.wait_for(
                _query_states_chunk(hass, entity_id, chunk_start, chunk_end),
                timeout=_PER_CHUNK_TIMEOUT_SEC,
            )
        except TimeoutError:
            _LOGGER.warning(
                "rollup: %s chunk %s..%s timed out; cursor not advanced",
                entity_id,
                chunk_start.date(),
                chunk_end.date(),
            )
            break  # leave cursor; next batch retries

        if states is None:
            # genuine query failure (recorder
            # crash, schema mismatch, etc.). NOT row-cap. Leave the
            # cursor where it is so we retry the same chunk on the
            # next batch — anything else would lose up to 6 days of
            # recoverable history per failure.
            _LOGGER.warning(
                "rollup: %s chunk %s..%s query failed; cursor not "
                "advanced — will retry next batch",
                entity_id,
                chunk_start.date(),
                chunk_end.date(),
            )
            break
        if states == "rowcap":
            # Row-cap exceeded — chunk is too large to safely
            # materialize. Retrying gets the same result, so advance
            # the cursor by exactly one day to skip past the worst
            # day. Conservative: don't skip the whole chunk.
            cursor_ts = (chunk_start + timedelta(days=1)).timestamp()
            await store.set_rollup_progress(
                entity_id,
                cursor_ts,
                window_days,
                now.timestamp(),
            )
            chunks_processed += 1
            await asyncio.sleep(0)
            continue

        rows_seen += len(states)
        if states:
            deltas = _state_to_bucket_deltas(states)
            rows = [
                (dim, bucket, delta)
                for dim, buckets in deltas.items()
                for bucket, delta in buckets.items()
            ]
            await store.merge_rollups(
                entity_id,
                rows,
                window_days=window_days,
                computed_at_ts=now.timestamp(),
            )

        cursor_ts = chunk_end.timestamp()
        await store.set_rollup_progress(
            entity_id,
            cursor_ts,
            window_days,
            now.timestamp(),
        )
        chunks_processed += 1
        await asyncio.sleep(0)

    return {
        "advanced": chunks_processed > 0,
        "chunks": chunks_processed,
        "rows_seen": rows_seen,
        "cursor_ts": cursor_ts,
    }


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

# Per-dimension minimum window-day thresholds. Below these the
# observation would be a false positive — "weekday-only" can't be
# inferred from 7 days of data; "1st-3rd of each month" needs
# multiple months. Each guard runs FIRST, before any data math.
_MIN_WINDOW_FOR_DOW = 28   # ≥4 weeks
_MIN_WINDOW_FOR_DOM = 60   # ≥2 months
_MIN_WINDOW_FOR_MOY = 365  # ≥1 year (already enforced in _moy_observations)
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
    *,
    window_days: int = ROLLUP_WINDOW_DAYS,
) -> list[dict[str, Any]]:
    """Return Observation-dicts derived from one entity's rollup buckets.

    Returns dicts (not Observation instances) — packet.py wraps them.
    Empty when the rollup is too sparse to draw conclusions.
    """
    out: list[dict[str, Any]] = []
    # Day-of-week patterns
    out.extend(_dow_observations(entity_id, rollups.get(DIM_DOW) or {}, window_days))
    # Day-of-month patterns
    out.extend(_dom_observations(entity_id, rollups.get(DIM_DOM) or {}, window_days))
    # Month-of-year patterns
    out.extend(_moy_observations(entity_id, rollups.get(DIM_MOY) or {}, window_days))
    return out


def _dow_observations(
    entity_id: str, buckets: dict[int, int], window_days: int = ROLLUP_WINDOW_DAYS
) -> list[dict[str, Any]]:
    # Need at least 4 weeks for "weekday-only" claims to be meaningful.
    # With 1-week data, "never weekends" is a trivial coincidence.
    if window_days < _MIN_WINDOW_FOR_DOW:
        return []
    total = sum(buckets.values())
    if total < _MIN_TOTAL_FOR_ROLLUP_OBS:
        return []
    out: list[dict[str, Any]] = []
    # Zero-bucket detection — "never fires Sat/Sun"
    #
    # Note framing: these are INFORMATIONAL observations, not
    # prescriptive ones. A trigger-based automation already gates
    # firing on the trigger entity, so adding a day-of-week
    # condition on the trigger entity itself is redundant. The LLM
    # prompt downstream has a guardrail against this. We surface
    # the pattern as context the LLM can use to understand the
    # user's home rhythm, NOT as an instruction to add conditions.
    zero_days = [i for i in range(7) if buckets.get(i, 0) == 0]
    if 5 in zero_days and 6 in zero_days and total >= 30:
        out.append(
            {
                "kind": "rollup_weekday_only",
                "text": (
                    f"Note: {entity_id} only transitions on weekdays "
                    f"in the last {window_days} days — never Saturdays or Sundays "
                    f"({total} weekday events). Informational context "
                    "for understanding the home's rhythm; not "
                    "necessarily a reason to add a weekday condition "
                    "if the trigger already gates firing."
                ),
                "confidence": 0.85,
                "metrics": {
                    "entity_id": entity_id,
                    "weekday_transitions": total,
                    "weekend_transitions": 0,
                    "dimension": DIM_DOW,
                    "context_only": True,
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
                        f"Note: {entity_id} never transitions on "
                        f"{day_names} over {window_days} days ({total} events on "
                        "other days). Informational only — adding a "
                        "day-of-week condition is usually unnecessary "
                        "when the trigger entity already gates firing."
                    ),
                    "confidence": 0.6,
                    "metrics": {
                        "entity_id": entity_id,
                        "zero_days": [_DOW_NAMES[d] for d in zero_days],
                        "total": total,
                        "dimension": DIM_DOW,
                        "context_only": True,
                    },
                }
            )
    return out


def _dom_observations(
    entity_id: str, buckets: dict[int, int], window_days: int = ROLLUP_WINDOW_DAYS
) -> list[dict[str, Any]]:
    # Need ≥2 months for "1st-3rd of each month" claims to hold up.
    # With < 60 days, the "1st-3rd concentration" is just an artifact
    # of which calendar days happened to land in the window.
    if window_days < _MIN_WINDOW_FOR_DOM:
        return []
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
                    f"({window_days}-day window, {total} transitions). Bill / "
                    "payroll / monthly-reset trigger?"
                ),
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
    entity_id: str, buckets: dict[int, int], window_days: int = ROLLUP_WINDOW_DAYS
) -> list[dict[str, Any]]:
    total = sum(buckets.values())
    if total < _MIN_TOTAL_FOR_ROLLUP_OBS:
        return []
    out: list[dict[str, Any]] = []
    # Identify months with zero activity. Only meaningful when the
    # configured window actually spans them — for newer installs or
    # short windows the zero is just "no data yet", not "user
    # doesn't use it then". Seasonal silence detection is only
    # trustworthy when window_days covers >= one full year.
    if window_days < 365:
        # Skip seasonal silence on short windows — too noisy.
        return out
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
                        f"({window_days}-day window, {total} transitions in other "
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
