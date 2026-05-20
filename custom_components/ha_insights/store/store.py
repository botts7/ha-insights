"""Async SQLite-backed store for HA Insights.

Insights, pseudonym map, outbound-call audit, applied history. v0.1
exposes insight CRUD + pseudonym map + a simple listener bus so the WS
API can stream change events to subscribed cards.
"""
from __future__ import annotations

import json
import secrets
import string
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from ..insight import Insight, InsightKind
from ..llm.cost import estimate_cost
from .schema import MIGRATIONS

# Listener signature: (event_type, insight). event_type is one of:
#   "added", "dismissed", "snoozed". insight is None for purge events.
StoreListener = Callable[[str, Insight | None], None]


class InsightStore:
    """Async SQLite store with idempotent migrations + change-event bus."""

    def __init__(self, path: Path | str) -> None:
        import asyncio

        self._path = Path(path)
        self._conn: aiosqlite.Connection | None = None
        self._listeners: list[StoreListener] = []
        # v1.0 review #10: per-store apply lock. ws_apply / ws_undo /
        # bulk-apply pipelines acquire this around the
        # validate+write+record_applied sequence so two near-simultaneous
        # applies on overlapping entities can't race in automations.yaml.
        self.apply_lock = asyncio.Lock()

    async def open(self) -> None:
        """Open the database; apply pending migrations."""
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._migrate()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def _c(self) -> aiosqlite.Connection:
        if self._conn is None:
            msg = "Store is not open; call open() first"
            raise RuntimeError(msg)
        return self._conn

    # --- Listener bus ---

    def add_listener(self, callback: StoreListener) -> Callable[[], None]:
        """Register a listener; returns an unsubscribe callable."""
        self._listeners.append(callback)

        def remove() -> None:
            if callback in self._listeners:
                self._listeners.remove(callback)

        return remove

    def _notify(self, event_type: str, insight: Insight | None) -> None:
        # Iterate over a copy so a listener that unsubscribes itself is safe.
        for cb in list(self._listeners):
            cb(event_type, insight)

    async def _migrate(self) -> None:
        """Apply migrations in order; idempotent."""
        # Detect current version (0 if schema_version table doesn't exist yet)
        async with self._c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        ) as cur:
            exists = await cur.fetchone()

        current = 0
        if exists:
            async with self._c.execute("SELECT MAX(version) FROM schema_version") as cur:
                row = await cur.fetchone()
                if row and row[0] is not None:
                    current = int(row[0])

        for version in sorted(MIGRATIONS.keys()):
            if version > current:
                # Some migrations use ALTER TABLE ADD COLUMN which
                # SQLite doesn't support `IF NOT EXISTS` on. To stay
                # safe across re-runs and partial-failure scenarios,
                # run each statement individually and tolerate the
                # specific "duplicate column" error — every other
                # SQL error still propagates.
                statements = [
                    s.strip()
                    for s in MIGRATIONS[version].split(";")
                    if s.strip()
                ]
                for stmt in statements:
                    try:
                        await self._c.execute(stmt)
                    except Exception as err:
                        msg = str(err).lower()
                        if (
                            "duplicate column" in msg
                            or "already exists" in msg
                        ):
                            # Column / table already present from a
                            # previous partial run. Continue with the
                            # rest of the migration.
                            continue
                        raise
                await self._c.execute(
                    "INSERT OR IGNORE INTO schema_version (version) VALUES (?)",
                    (version,),
                )
                await self._c.commit()

    # --- Insights ---

    async def add_insight(self, insight: Insight) -> None:
        """Upsert an insight by id, PRESERVING dismiss/apply state.

        v1.4 behaviour change (critical for notification UX):
          - INSERT OR REPLACE used to wipe `dismissed_at`,
            `applied_at`, and `applied_artifact_id` on every scan,
            which meant a re-detected-but-dismissed insight fired a
            FRESH "added" event → user got buzzed for the same thing
            forever. Mobile notifications became unbearable on busy
            installs.
          - Now we INSERT ... ON CONFLICT(id) DO UPDATE that
            explicitly leaves those three columns alone. Dismissed
            insights stay dismissed across scans; applied insights
            keep their artifact link.
          - We also fire a DIFFERENT event when it's an update vs
            a fresh insert: "added" (new) → notification fires,
            "refreshed" (existing row, just-updated metadata) →
            notification is SUPPRESSED by the listener.

        The pre-check (SELECT 1 WHERE id=?) is one round-trip per
        upsert, which is cheap relative to the write itself.
        """
        snoozed_ts = (
            insight.snoozed_until.timestamp() if insight.snoozed_until else None
        )
        # Detect whether this is a fresh insert or an update. We need
        # this BEFORE the upsert so the post-upsert notification can
        # pick the right event type. SQLite's RETURNING clause would
        # avoid the extra read but requires SQLite ≥ 3.35; this is
        # the broadest-compat path.
        async with self._c.execute(
            "SELECT 1 FROM insights WHERE id = ?", (insight.id,)
        ) as cur:
            existed = (await cur.fetchone()) is not None
        await self._c.execute(
            """
            INSERT INTO insights (
                id, kind, detector, area_id, title, confidence,
                fingerprint_json, payload_json, payload_format,
                explanation, conflicts_with_json, created_at, snoozed_until,
                vendor, target_user_id, target_user_id_confidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                kind = excluded.kind,
                detector = excluded.detector,
                area_id = excluded.area_id,
                title = excluded.title,
                confidence = excluded.confidence,
                fingerprint_json = excluded.fingerprint_json,
                payload_json = excluded.payload_json,
                payload_format = excluded.payload_format,
                explanation = excluded.explanation,
                conflicts_with_json = excluded.conflicts_with_json,
                created_at = excluded.created_at,
                snoozed_until = excluded.snoozed_until,
                vendor = excluded.vendor,
                target_user_id = excluded.target_user_id,
                target_user_id_confidence = excluded.target_user_id_confidence
                -- DELIBERATELY NOT TOUCHED: dismissed_at, applied_at,
                -- applied_artifact_id, retired_at. These represent user
                -- actions and must survive re-emission of the same
                -- pattern. v1.5.46 added retired_at to this set —
                -- retiring an insight is a permanent "don't auto-
                -- suggest" decision that must persist across re-detects.
            """,
            (
                insight.id,
                str(insight.kind),
                insight.detector,
                insight.area_id,
                insight.title,
                insight.confidence,
                json.dumps(insight.fingerprint, sort_keys=True),
                json.dumps(insight.payload, sort_keys=True),
                insight.payload_format,
                insight.explanation,
                json.dumps(list(insight.conflicts_with)),
                insight.created_at.timestamp(),
                snoozed_ts,
                insight.vendor,
                insight.target_user_id,
                insight.target_user_id_confidence,
            ),
        )
        await self._c.commit()
        # "refreshed" for re-emission of an already-known insight
        # (preserves dismiss/apply state — see docstring above) so
        # the notification listener can skip pushing a duplicate
        # alert. Card subscribers can still react if they want to
        # update titles / confidence in-place.
        self._notify("refreshed" if existed else "added", insight)

    # Reusable LEFT JOIN clause so applied insights carry their undo window
    # info on every read. _row_to_insight reads `i.*` PLUS the joined cols.
    _SELECT_INSIGHTS = (
        "SELECT i.*, "
        "ah.undo_window_expires_at AS ah_undo_window_expires_at "
        "FROM insights i "
        "LEFT JOIN applied_history ah ON ah.insight_id = i.id"
    )

    async def get_insight(self, insight_id: str) -> Insight | None:
        async with self._c.execute(
            f"{self._SELECT_INSIGHTS} WHERE i.id = ?", (insight_id,)
        ) as cur:
            row = await cur.fetchone()
        return self._row_to_insight(row) if row else None

    async def list_insights(
        self,
        *,
        include_dismissed: bool = False,
        include_applied: bool = False,
        include_snoozed: bool = False,
        include_retired: bool = False,
    ) -> list[Insight]:
        clauses: list[str] = []
        params: list[float] = []
        if not include_dismissed:
            clauses.append("i.dismissed_at IS NULL")
        if not include_applied:
            clauses.append("i.applied_at IS NULL")
        if not include_snoozed:
            clauses.append("(i.snoozed_until IS NULL OR i.snoozed_until <= ?)")
            params.append(datetime.now(tz=UTC).timestamp())
        # v1.5.46: retired = permanent "don't auto-suggest" decision.
        # Filtered out by default same as dismissed; the history view
        # opts in via include_retired=True.
        if not include_retired:
            clauses.append("i.retired_at IS NULL")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        async with self._c.execute(
            f"{self._SELECT_INSIGHTS} {where} ORDER BY i.created_at DESC", params
        ) as cur:
            rows = await cur.fetchall()
        return [self._row_to_insight(r) for r in rows]

    async def dismiss_insight(
        self, insight_id: str, *, when: datetime | None = None
    ) -> bool:
        ts = (when or datetime.now(tz=UTC)).timestamp()
        cur = await self._c.execute(
            "UPDATE insights SET dismissed_at = ? WHERE id = ?",
            (ts, insight_id),
        )
        await self._c.commit()
        if cur.rowcount > 0:
            self._notify("dismissed", await self.get_insight(insight_id))
            return True
        return False

    async def snooze_insight(self, insight_id: str, *, until: datetime) -> bool:
        cur = await self._c.execute(
            "UPDATE insights SET snoozed_until = ? WHERE id = ?",
            (until.timestamp(), insight_id),
        )
        await self._c.commit()
        if cur.rowcount > 0:
            self._notify("snoozed", await self.get_insight(insight_id))
            return True
        return False

    async def retire_insight(
        self, insight_id: str, *, when: datetime | None = None
    ) -> bool:
        """Mark an insight as retired — the user has decided NOT to
        automate this pattern. Filtered from ws_list by default same
        as dismissed; surfaced under include_retired=True for the
        history / management view. Reversible via clear_retired.
        """
        ts = (when or datetime.now(tz=UTC)).timestamp()
        cur = await self._c.execute(
            "UPDATE insights SET retired_at = ? WHERE id = ?",
            (ts, insight_id),
        )
        await self._c.commit()
        if cur.rowcount > 0:
            self._notify("retired", await self.get_insight(insight_id))
            return True
        return False

    async def clear_retired(self, insight_id: str) -> bool:
        """Un-retire an insight. Returns True if a row was un-retired."""
        cur = await self._c.execute(
            "UPDATE insights SET retired_at = NULL WHERE id = ? "
            "AND retired_at IS NOT NULL",
            (insight_id,),
        )
        await self._c.commit()
        if cur.rowcount > 0:
            self._notify("unretired", await self.get_insight(insight_id))
            return True
        return False

    # --- Verdict history (v1.14.3/v1.14.4) ---
    #
    # Append-only timeline of apply/dismiss/retire/snooze/undo verdicts
    # WITH the environmental fingerprint captured at verdict time. Read
    # by AdaptiveFeedbackDetector (v1.14.4) to decide which previously-
    # dismissed insights to re-surface when the environment changes.
    #
    # The classic mutators above (dismiss_insight, retire_insight, etc.)
    # update the *current* state on the `insights` row. The recorder
    # here writes the *event* to a separate append-only table. Both
    # writes happen in `ws_dismiss` / `ws_retire` / `ws_apply` / `ws_undo`
    # so callers don't have to remember.

    async def record_verdict(
        self,
        insight_id: str,
        *,
        kind: str,
        fingerprint: dict[str, object],
        when: datetime | None = None,
        user_id_hash: str | None = None,
    ) -> None:
        """Append one verdict to the timeline.

        `kind` must be one of the ``VerdictKind`` string values
        (``"applied"``, ``"dismissed"``, ``"retired"``, ``"unretired"``,
        ``"snoozed"``, ``"undone"``, ``"clear_applied"``). The store
        doesn't validate against the enum to avoid a lib→store
        circular import; callers should pass ``VerdictKind.X.value``.

        `fingerprint` is the JSON-serializable dict form of an
        ``EnvironmentalFingerprint``. We serialize here so the lib
        stays JSON-free (same architectural rule as the other
        pure-function libs).
        """
        ts = (when or datetime.now(tz=UTC)).timestamp()
        await self._c.execute(
            """
            INSERT INTO verdict_history (
                insight_id, kind, timestamp, fingerprint_json, user_id_hash
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                insight_id,
                kind,
                ts,
                json.dumps(fingerprint, sort_keys=True),
                user_id_hash,
            ),
        )
        await self._c.commit()

    async def get_verdict_history(
        self, insight_id: str
    ) -> list[dict[str, object]]:
        """Return all verdicts for one insight, ascending by timestamp.

        Each row is a plain dict so the store keeps no dependency on
        the `lib/user_verdict_history` types. Callers (the detector,
        the WS API) hydrate into ``Verdict`` / ``VerdictHistory`` as
        needed.

        Row schema:
          {
            "insight_id": str,
            "kind": str,                 # VerdictKind value
            "timestamp": float,          # unix seconds, UTC
            "fingerprint": dict,         # JSON-deserialized
            "user_id_hash": str | None,
          }
        """
        async with self._c.execute(
            """
            SELECT insight_id, kind, timestamp, fingerprint_json, user_id_hash
              FROM verdict_history
             WHERE insight_id = ?
             ORDER BY timestamp ASC
            """,
            (insight_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [
            {
                "insight_id": r["insight_id"],
                "kind": r["kind"],
                "timestamp": r["timestamp"],
                "fingerprint": json.loads(r["fingerprint_json"]),
                "user_id_hash": r["user_id_hash"],
            }
            for r in rows
        ]

    async def get_decisive_verdict_kinds_by_detector(
        self,
    ) -> dict[str, list[str]]:
        """For v1.14.7 apply-rate penalty: join verdict_history × insights
        and return ``{detector_name: [verdict_kind, ...]}`` for the
        APPLY / DISMISS / RETIRE rows only.

        Snoozes / undos / clear_applied are filtered out at the SQL
        level — they don't reflect a user's opinion about the
        suggestion's *value*, and including them would dilute the
        penalty signal. The lib's ``apply_rate_from_kinds`` filters
        the same set client-side for defence-in-depth; the SQL
        filter just keeps the rows small for big histories.

        Output is dict-per-detector, not the full ``Verdict`` shape:
        all we need for the apply_rate penalty is the kind sequence.
        Lighter than ``get_all_verdict_histories`` (no fingerprint
        deserialization).
        """
        async with self._c.execute(
            """
            SELECT i.detector, v.kind
              FROM verdict_history v
              JOIN insights i ON i.id = v.insight_id
             WHERE v.kind IN ('applied', 'dismissed', 'retired')
             ORDER BY i.detector ASC, v.timestamp ASC
            """
        ) as cur:
            rows = await cur.fetchall()
        out: dict[str, list[str]] = {}
        for r in rows:
            out.setdefault(r["detector"], []).append(r["kind"])
        return out

    async def get_decisive_verdict_kinds_by_detector_since(
        self, since_ts: float
    ) -> dict[str, list[str]]:
        """v1.22: time-windowed variant for AdaptiveFeedback's detector-
        level rejection signal.

        The all-time variant powers the v1.14.7 penalty (which is quiet
        confidence demotion). v1.22's detector-level meta-insight asks
        the user to consider DISABLING the detector — louder action,
        higher bar, needs RECENT data. Stale 6-month-old rejections
        shouldn't drive a "disable me" prompt on a detector the user
        has been ignoring lately for unrelated reasons.

        ``since_ts`` is a Unix epoch second; rows with
        ``verdict_history.timestamp >= since_ts`` are included.
        """
        async with self._c.execute(
            """
            SELECT i.detector, v.kind
              FROM verdict_history v
              JOIN insights i ON i.id = v.insight_id
             WHERE v.kind IN ('applied', 'dismissed', 'retired')
               AND v.timestamp >= ?
             ORDER BY i.detector ASC, v.timestamp ASC
            """,
            (since_ts,),
        ) as cur:
            rows = await cur.fetchall()
        out: dict[str, list[str]] = {}
        for r in rows:
            out.setdefault(r["detector"], []).append(r["kind"])
        return out

    async def get_all_verdict_histories(
        self,
    ) -> dict[str, list[dict[str, object]]]:
        """Bulk read for the detector pass: every history keyed by id.

        Each value is the same row-dict list shape as
        ``get_verdict_history``. Empty dict when no verdicts recorded.
        Single query + grouping in Python — at expected scales
        (~hundreds of verdicts for an active install) the cost is
        dominated by JSON parsing, not query planning.
        """
        async with self._c.execute(
            """
            SELECT insight_id, kind, timestamp, fingerprint_json, user_id_hash
              FROM verdict_history
             ORDER BY insight_id ASC, timestamp ASC
            """
        ) as cur:
            rows = await cur.fetchall()
        out: dict[str, list[dict[str, object]]] = {}
        for r in rows:
            out.setdefault(r["insight_id"], []).append(
                {
                    "insight_id": r["insight_id"],
                    "kind": r["kind"],
                    "timestamp": r["timestamp"],
                    "fingerprint": json.loads(r["fingerprint_json"]),
                    "user_id_hash": r["user_id_hash"],
                }
            )
        return out

    # --- Applied history ---

    async def record_applied(
        self,
        insight_id: str,
        *,
        artifact_kind: str,
        artifact_id: str,
        snapshot: dict[str, object],
        snapshot_hash: str,
        undo_window_days: int = 7,
    ) -> None:
        """Record an apply: stores snapshot + hash, marks insight as applied."""
        from datetime import timedelta

        now_dt = datetime.now(tz=UTC)
        now_ts = now_dt.timestamp()
        expires_ts = (now_dt + timedelta(days=undo_window_days)).timestamp()

        await self._c.execute(
            """
            INSERT OR REPLACE INTO applied_history (
                insight_id, artifact_kind, artifact_id,
                snapshot_json, snapshot_hash,
                applied_at, undo_window_expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                insight_id,
                artifact_kind,
                artifact_id,
                json.dumps(snapshot, sort_keys=True),
                snapshot_hash,
                now_ts,
                expires_ts,
            ),
        )
        await self._c.execute(
            "UPDATE insights SET applied_at = ?, applied_artifact_id = ? WHERE id = ?",
            (now_ts, artifact_id, insight_id),
        )
        await self._c.commit()
        self._notify("applied", await self.get_insight(insight_id))

    async def replace_active_insights_for_detectors(
        self,
        completed_detectors: frozenset[str],
        emitted_ids: frozenset[str],
    ) -> int:
        """Sweep stale ACTIVE insights from a set of detectors.

        Called once at the end of run_all_detectors. The contract:
          For every detector that ran end-to-end this scan, any insight
          PREVIOUSLY in the store from that detector that wasn't re-emitted
          is now stale and gets deleted — UNLESS the user has acted on it
          (applied / dismissed) or it's currently snoozed. Insights from
          detectors that didn't run (disabled, canceled, timed-out) are
          untouched, since we have no fresh signal about them.

        This makes the store a "current truth" snapshot rather than an
        unbounded log. Adds zero user-visible state — applied / dismissed
        / snoozed semantics are preserved exactly.

        Returns the count of stale rows removed for telemetry.
        """
        if not completed_detectors:
            return 0
        # Build the placeholder lists on the fly (SQLite doesn't support
        # parameterized IN with arbitrary cardinality). Detector names and
        # insight IDs are integration-controlled (no user input), so this
        # is safe from SQL injection — but we still parameterize the
        # values to be defensive.
        det_marks = ",".join("?" * len(completed_detectors))
        params: list[object] = list(completed_detectors)
        emitted_clause = ""
        if emitted_ids:
            id_marks = ",".join("?" * len(emitted_ids))
            emitted_clause = f"AND id NOT IN ({id_marks})"
            params.extend(emitted_ids)

        async with self._c.execute(
            f"SELECT COUNT(*) FROM insights "
            f"WHERE detector IN ({det_marks}) "
            f"  {emitted_clause} "
            f"  AND applied_at IS NULL "
            f"  AND dismissed_at IS NULL "
            f"  AND (snoozed_until IS NULL "
            f"       OR snoozed_until <= strftime('%s','now')) ",
            params,
        ) as cur:
            row = await cur.fetchone()
        before = int(row[0]) if row else 0
        if before == 0:
            return 0

        await self._c.execute(
            f"DELETE FROM insights "
            f"WHERE detector IN ({det_marks}) "
            f"  {emitted_clause} "
            f"  AND applied_at IS NULL "
            f"  AND dismissed_at IS NULL "
            f"  AND (snoozed_until IS NULL "
            f"       OR snoozed_until <= strftime('%s','now')) ",
            params,
        )
        await self._c.commit()

        # Live subscribers don't get per-row removal events here — the
        # panel triggers a list-refresh right after scan_now completes
        # (its post-scan handler refetches the full list), so the cleanup
        # is reflected within ~100ms of the scan finishing. Adding a
        # bulk "swept" event type is a follow-up if scheduled-scan
        # deletes need to land live in already-open panels.
        return before

    async def purge_observations(self) -> dict[str, int]:
        """Wipe insights + outbound_calls audit log.

        Per docs/ARCHITECTURE.md: pseudonym_map and applied_history are
        preserved so post-purge undo + cross-restart pseudonyms still work.

        Fires a `purged` event after the delete so subscribed panels can
        clear their loaded list immediately, no manual page refresh.
        """
        async with self._c.execute("SELECT COUNT(*) FROM insights") as cur:
            row = await cur.fetchone()
            insights_before = int(row[0]) if row else 0
        async with self._c.execute("SELECT COUNT(*) FROM outbound_calls") as cur:
            row = await cur.fetchone()
            calls_before = int(row[0]) if row else 0

        await self._c.execute("DELETE FROM insights")
        await self._c.execute("DELETE FROM outbound_calls")
        await self._c.commit()
        # Notify subscribers so panels live-update without a page refresh.
        # Insight payload is None — the action alone tells the card to
        # drop its local list (no specific id to remove).
        self._notify("purged", None)
        return {
            "insights_deleted": insights_before,
            "outbound_calls_deleted": calls_before,
        }

    async def get_outbound_calls(
        self, *, limit: int = 50
    ) -> list[dict[str, object]]:
        """Return the most recent outbound_calls rows for the audit log viewer.

        Joins to the insights table on insight_id so the UI can show the
        insight title alongside each call. Insight may have been deleted —
        in that case the title is None.
        """
        async with self._c.execute(
            """
            SELECT
                oc.id,
                oc.timestamp,
                oc.insight_id,
                oc.agent,
                oc.agent_locality,
                oc.redaction_mode,
                oc.bytes_sent,
                oc.bytes_received,
                oc.success,
                i.title AS insight_title
            FROM outbound_calls oc
            LEFT JOIN insights i ON i.id = oc.insight_id
            ORDER BY oc.timestamp DESC
            LIMIT ?
            """,
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
        result: list[dict[str, object]] = []
        for row in rows:
            bytes_sent = int(row["bytes_sent"] or 0)
            bytes_received = int(row["bytes_received"] or 0)
            cost = estimate_cost(
                agent_id=row["agent"],
                bytes_sent=bytes_sent,
                bytes_received=bytes_received,
                locality=row["agent_locality"],
            )
            result.append(
                {
                    "id": int(row["id"]),
                    "timestamp": datetime.fromtimestamp(
                        row["timestamp"], tz=UTC
                    ).isoformat(),
                    "insight_id": row["insight_id"],
                    "insight_title": row["insight_title"],
                    "agent": row["agent"],
                    "agent_locality": row["agent_locality"],
                    "redaction_mode": row["redaction_mode"],
                    "bytes_sent": bytes_sent,
                    "bytes_received": bytes_received,
                    "success": (
                        bool(row["success"]) if row["success"] is not None else None
                    ),
                    # v0.9 phase 1C: rough cost estimate. Computed at read
                    # time from bytes + agent_id, no schema migration needed.
                    "est_tokens_in": cost["tokens_in"],
                    "est_tokens_out": cost["tokens_out"],
                    "est_cost_usd": cost["cost_usd"],
                    "cost_source": cost["source"],
                }
            )
        return result

    async def get_outbound_call_summary(
        self, *, since: datetime
    ) -> dict[str, object | None]:
        """Aggregated stats over outbound_calls since the given time.

        Returns a dict with call_count, bytes_sent_total, bytes_received_total,
        last_call_timestamp (datetime|None), last_agent (str|None).
        Empty / no-call windows return zeros and Nones.
        """
        since_ts = since.timestamp()
        async with self._c.execute(
            """
            SELECT
                COUNT(*) AS call_count,
                COALESCE(SUM(bytes_sent), 0) AS bytes_sent_total,
                COALESCE(SUM(bytes_received), 0) AS bytes_received_total,
                MAX(timestamp) AS last_call_timestamp
            FROM outbound_calls
            WHERE timestamp >= ?
            """,
            (since_ts,),
        ) as cur:
            row = await cur.fetchone()

        last_agent: str | None = None
        last_ts_value = row["last_call_timestamp"] if row else None
        if last_ts_value is not None:
            async with self._c.execute(
                """
                SELECT agent FROM outbound_calls
                WHERE timestamp = ?
                ORDER BY id DESC LIMIT 1
                """,
                (last_ts_value,),
            ) as cur:
                latest = await cur.fetchone()
                if latest is not None:
                    last_agent = latest["agent"]

        # Per-call cost estimate aggregated across the window. We sum row-by-row
        # rather than from totals because pricing differs per agent — a window
        # mixing local + cloud agents would otherwise over-charge.
        est_cost_total = 0.0
        async with self._c.execute(
            """
            SELECT agent, agent_locality, bytes_sent, bytes_received
            FROM outbound_calls
            WHERE timestamp >= ?
            """,
            (since_ts,),
        ) as cur:
            cost_rows = await cur.fetchall()
        for cost_row in cost_rows:
            cost = estimate_cost(
                agent_id=cost_row["agent"],
                bytes_sent=int(cost_row["bytes_sent"] or 0),
                bytes_received=int(cost_row["bytes_received"] or 0),
                locality=cost_row["agent_locality"],
            )
            est_cost_total += float(cost["cost_usd"])

        return {
            "call_count": int(row["call_count"]) if row else 0,
            "bytes_sent_total": int(row["bytes_sent_total"]) if row else 0,
            "bytes_received_total": int(row["bytes_received_total"]) if row else 0,
            "last_call_timestamp": (
                datetime.fromtimestamp(last_ts_value, tz=UTC)
                if last_ts_value is not None
                else None
            ),
            "last_agent": last_agent,
            "est_cost_usd_total": round(est_cost_total, 4),
        }

    async def clear_applied(self, insight_id: str) -> bool:
        """Reverse a record_applied: drop the snapshot, clear the marker.

        Returns True if a row was actually un-applied. Notifies subscribers
        with the "undone" event so cards can refresh.
        """
        # Only proceed if there's actually an applied row to clear
        existing = await self.get_applied_history(insight_id)
        if existing is None:
            return False
        await self._c.execute(
            "DELETE FROM applied_history WHERE insight_id = ?", (insight_id,)
        )
        await self._c.execute(
            "UPDATE insights SET applied_at = NULL, applied_artifact_id = NULL "
            "WHERE id = ?",
            (insight_id,),
        )
        await self._c.commit()
        self._notify("undone", await self.get_insight(insight_id))
        return True

    async def get_applied_history(
        self, insight_id: str
    ) -> dict[str, object] | None:
        async with self._c.execute(
            "SELECT * FROM applied_history WHERE insight_id = ?", (insight_id,)
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return {
            "insight_id": row["insight_id"],
            "artifact_kind": row["artifact_kind"],
            "artifact_id": row["artifact_id"],
            "snapshot": json.loads(row["snapshot_json"]),
            "snapshot_hash": row["snapshot_hash"],
            "applied_at": row["applied_at"],
            "undo_window_expires_at": row["undo_window_expires_at"],
        }

    @staticmethod
    def _row_to_insight(row: aiosqlite.Row) -> Insight:
        snoozed = row["snoozed_until"]
        applied_at = (
            row["applied_at"] if "applied_at" in row.keys() else None
        )
        applied_artifact_id = (
            row["applied_artifact_id"]
            if "applied_artifact_id" in row.keys()
            else None
        )
        # `ah_undo_window_expires_at` only exists on rows from the LEFT JOIN
        # path (get_insight / list_insights). Older read paths that don't
        # join still work — applied surface is just None in that case.
        undo_window_ts = (
            row["ah_undo_window_expires_at"]
            if "ah_undo_window_expires_at" in row.keys()
            else None
        )
        return Insight(
            id=row["id"],
            kind=InsightKind(row["kind"]),
            detector=row["detector"],
            area_id=row["area_id"],
            title=row["title"],
            confidence=row["confidence"],
            fingerprint=json.loads(row["fingerprint_json"]),
            payload=json.loads(row["payload_json"]),
            payload_format=row["payload_format"],
            created_at=datetime.fromtimestamp(row["created_at"], tz=UTC),
            snoozed_until=(
                datetime.fromtimestamp(snoozed, tz=UTC) if snoozed else None
            ),
            explanation=row["explanation"],
            conflicts_with=tuple(json.loads(row["conflicts_with_json"] or "[]")),
            applied_at=(
                datetime.fromtimestamp(applied_at, tz=UTC)
                if applied_at
                else None
            ),
            applied_artifact_id=applied_artifact_id,
            undo_window_expires_at=(
                datetime.fromtimestamp(undo_window_ts, tz=UTC)
                if undo_window_ts
                else None
            ),
            vendor=(
                row["vendor"] if "vendor" in row.keys() else None
            ),
            target_user_id=(
                row["target_user_id"]
                if "target_user_id" in row.keys()
                else None
            ),
            target_user_id_confidence=(
                row["target_user_id_confidence"]
                if "target_user_id_confidence" in row.keys()
                else None
            ),
            dismissed_at=(
                datetime.fromtimestamp(row["dismissed_at"], tz=UTC)
                if "dismissed_at" in row.keys() and row["dismissed_at"]
                else None
            ),
            retired_at=(
                datetime.fromtimestamp(row["retired_at"], tz=UTC)
                if "retired_at" in row.keys() and row["retired_at"]
                else None
            ),
        )

    # --- Pseudonym map ---

    async def get_or_create_pseudonym(
        self, entity_id: str, *, area_id: str | None = None
    ) -> str:
        """Return existing pseudonym for entity_id, or generate + store one."""
        async with self._c.execute(
            "SELECT pseudonym FROM pseudonym_map WHERE entity_id = ?",
            (entity_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is not None:
            return row[0]

        pseudonym = self._generate_pseudonym(entity_id)
        await self._c.execute(
            """
            INSERT INTO pseudonym_map (entity_id, pseudonym, area_id, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (entity_id, pseudonym, area_id, datetime.now(tz=UTC).timestamp()),
        )
        await self._c.commit()
        return pseudonym

    async def rename_entity_pseudonym(self, old_id: str, new_id: str) -> bool:
        """Move pseudonym from old_id to new_id, preserving the pseudonym string."""
        if old_id == new_id:
            return False
        cur = await self._c.execute(
            "UPDATE pseudonym_map SET entity_id = ? WHERE entity_id = ?",
            (new_id, old_id),
        )
        await self._c.commit()
        return cur.rowcount > 0

    async def delete_entity_pseudonym(self, entity_id: str) -> bool:
        """Drop the pseudonym row for `entity_id`. Idempotent.

        Called from the entity_registry "remove" handler so a deleted
        entity's pseudonym doesn't linger forever and isn't accidentally
        inherited by a re-created entity_id with a different unique_id.
        Returns True if a row was deleted.
        """
        cur = await self._c.execute(
            "DELETE FROM pseudonym_map WHERE entity_id = ?", (entity_id,)
        )
        await self._c.commit()
        return cur.rowcount > 0

    @staticmethod
    def _generate_pseudonym(entity_id: str) -> str:
        domain = entity_id.split(".", 1)[0] if "." in entity_id else "entity"
        suffix = "".join(
            secrets.choice(string.ascii_lowercase + string.digits) for _ in range(6)
        )
        return f"{domain}.entity_{suffix}"

    # --- AuditRollups (v1.1 schema v2) ---
    #
    # Three dimensions per entity: dow (day-of-week, 0-6), dom
    # (day-of-month, 1-31), moy (month-of-year, 1-12). A "rollup row"
    # is one (entity_id, dimension, bucket, transitions) tuple. The
    # rollup job (audit/rollup.py) computes all 24+31+12 = 67 buckets
    # per entity from the HA recorder in one pass and upserts them
    # atomically. Audit packet builder reads via get_rollups_for_entity.

    async def upsert_rollups(
        self,
        entity_id: str,
        rows: list[tuple[str, int, int]],
        window_days: int,
        computed_at_ts: float,
    ) -> None:
        """Replace all rollup rows for `entity_id` with `rows`.

        v1.1 semantics: replace-all. Used when the window changes
        or when callers want a clean refresh. v1.2 introduces
        `merge_rollups` for the incremental-add path; this method
        stays as the "wipe and replace" primitive.

        rows: list of (dimension, bucket, transitions) tuples.

        DELETE-then-INSERT in one transaction so a partial failure
        leaves the entity's rollup either fully old or fully new —
        never half-migrated.
        """
        await self._c.execute(
            "DELETE FROM audit_rollups WHERE entity_id = ?", (entity_id,)
        )
        if rows:
            await self._c.executemany(
                """
                INSERT INTO audit_rollups (
                    entity_id, dimension, bucket, transitions,
                    window_days, computed_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (entity_id, dim, bucket, count, window_days, computed_at_ts)
                    for (dim, bucket, count) in rows
                ],
            )
        await self._c.commit()

    async def merge_rollups(
        self,
        entity_id: str,
        rows: list[tuple[str, int, int]],
        window_days: int,
        computed_at_ts: float,
    ) -> None:
        """Additively merge `rows` into existing rollup buckets.

        Used by the v1.2 incremental rollup. Each row's `transitions`
        is ADDED to the existing bucket count (or inserted if missing).
        Old buckets that don't appear in `rows` are left untouched —
        this is the key behavior that lets historical data survive
        recorder purges.

        rows: list of (dimension, bucket, delta_count) tuples — deltas,
        not totals.
        """
        if not rows:
            return
        for dim, bucket, delta in rows:
            await self._c.execute(
                """
                INSERT INTO audit_rollups (
                    entity_id, dimension, bucket, transitions,
                    window_days, computed_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(entity_id, dimension, bucket) DO UPDATE SET
                    transitions = transitions + EXCLUDED.transitions,
                    window_days = EXCLUDED.window_days,
                    computed_at = EXCLUDED.computed_at
                """,
                (entity_id, dim, bucket, delta, window_days, computed_at_ts),
            )
        await self._c.commit()

    async def clear_rollups_for_entity(self, entity_id: str) -> int:
        """Delete every rollup bucket for one entity. Called by the
        incremental engine when starting a fresh backfill (no
        progress row) so v1.1 totals don't double-count against the
        v1.2 incremental merge."""
        cur = await self._c.execute(
            "DELETE FROM audit_rollups WHERE entity_id = ?", (entity_id,)
        )
        await self._c.commit()
        return cur.rowcount

    async def get_rollup_progress(
        self, entity_id: str
    ) -> tuple[float, int] | None:
        """Return (last_complete_day_ts, window_days) for an entity, or
        None if no incremental progress has been recorded yet.

        Used by audit/rollup.py to decide whether the next rollup
        batch should backfill from scratch (None) or resume from the
        last cursor.
        """
        async with self._c.execute(
            "SELECT last_complete_day_ts, window_days "
            "FROM audit_rollup_progress WHERE entity_id = ?",
            (entity_id,),
        ) as cur:
            row = await cur.fetchone()
            if row is None:
                return None
            return (float(row["last_complete_day_ts"]), int(row["window_days"]))

    async def set_rollup_progress(
        self,
        entity_id: str,
        last_complete_day_ts: float,
        window_days: int,
        computed_at_ts: float,
    ) -> None:
        """Advance the rollup cursor for an entity."""
        await self._c.execute(
            """
            INSERT INTO audit_rollup_progress (
                entity_id, last_complete_day_ts, computed_at, window_days
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(entity_id) DO UPDATE SET
                last_complete_day_ts = EXCLUDED.last_complete_day_ts,
                computed_at = EXCLUDED.computed_at,
                window_days = EXCLUDED.window_days
            """,
            (entity_id, last_complete_day_ts, computed_at_ts, window_days),
        )
        await self._c.commit()

    async def list_entities_needing_rollup(
        self,
        all_entity_ids: list[str],
        end_of_today_ts: float,
    ) -> list[str]:
        """Return entity_ids whose incremental rollup is not yet
        caught up to the start of today.

        An entity needs rollup if:
          - it has no progress row (never rolled up), OR
          - its `last_complete_day_ts < end_of_today_ts`

        v1.2: this is the canonical batch picker for the incremental
        path. Replaces the old TTL-based `list_stale_rollup_entities`
        for the run loop, which over-fetched and re-did fresh work
        every TTL period.
        """
        if not all_entity_ids:
            return []
        # Pull cursors in one query (caller may have hundreds of
        # entities; per-row SELECTs would be wasteful).
        cursors: dict[str, float] = {}
        async with self._c.execute(
            "SELECT entity_id, last_complete_day_ts FROM audit_rollup_progress"
        ) as cur:
            async for row in cur:
                cursors[row["entity_id"]] = float(row["last_complete_day_ts"])
        needing: list[str] = []
        for eid in all_entity_ids:
            cursor = cursors.get(eid)
            if cursor is None or cursor < end_of_today_ts:
                needing.append(eid)
        return needing

    async def clear_rollup_progress(self) -> int:
        """Wipe every entity's incremental cursor. Called when the
        user changes `audit_rollup_window_days` so the next batch
        starts fresh against the new window."""
        cur = await self._c.execute("DELETE FROM audit_rollup_progress")
        await self._c.commit()
        return cur.rowcount

    async def get_rollups_for_entity(
        self, entity_id: str
    ) -> dict[str, dict[int, int]]:
        """Return a {dimension: {bucket: transitions}} dict for an
        entity. Empty dict if no rollup exists yet."""
        out: dict[str, dict[int, int]] = {}
        async with self._c.execute(
            "SELECT dimension, bucket, transitions FROM audit_rollups "
            "WHERE entity_id = ?",
            (entity_id,),
        ) as cur:
            async for row in cur:
                dim = row["dimension"]
                out.setdefault(dim, {})[int(row["bucket"])] = int(
                    row["transitions"]
                )
        return out

    async def list_stale_rollup_entities(
        self,
        all_entity_ids: list[str],
        stale_after_ts: float,
    ) -> list[str]:
        """Return entity_ids that EITHER have no rollup OR were last
        computed before `stale_after_ts`. Used by the rollup scheduler
        to pick the next batch.

        We feed in the full set of audit-target entities so an entity
        that was rolled up once but then dropped out of any
        automation's targets doesn't keep being refreshed forever.
        """
        if not all_entity_ids:
            return []
        # SQLite has a parameter limit (default 999) — chunk if huge
        rolled_up_at: dict[str, float] = {}
        async with self._c.execute(
            "SELECT entity_id, MAX(computed_at) AS ts FROM audit_rollups "
            "GROUP BY entity_id"
        ) as cur:
            async for row in cur:
                rolled_up_at[row["entity_id"]] = float(row["ts"])
        stale: list[str] = []
        for eid in all_entity_ids:
            last = rolled_up_at.get(eid)
            if last is None or last < stale_after_ts:
                stale.append(eid)
        return stale

    async def prune_rollups_for_entities(
        self, keep_entity_ids: list[str]
    ) -> int:
        """Drop rollups for entities NOT in `keep_entity_ids`. Useful
        when the user removes an automation — its target entities may
        no longer need long-term aggregates. Returns the count of
        rows deleted."""
        if not keep_entity_ids:
            cur = await self._c.execute("DELETE FROM audit_rollups")
            await self._c.commit()
            return cur.rowcount
        placeholders = ",".join(["?"] * len(keep_entity_ids))
        cur = await self._c.execute(
            f"DELETE FROM audit_rollups WHERE entity_id NOT IN ({placeholders})",
            keep_entity_ids,
        )
        await self._c.commit()
        return cur.rowcount

    async def prune_rollups_with_wrong_window(self, window_days: int) -> int:
        """Drop rollup rows materialized against a different window.

        Called when the user changes `audit_rollup_window_days` in
        OptionsFlow — the existing rows were computed for the old
        window and would silently lie about the new one. Cleanest
        fix is to invalidate them; the next rollup batch refills.
        Returns count deleted.
        """
        cur = await self._c.execute(
            "DELETE FROM audit_rollups WHERE window_days != ?",
            (int(window_days),),
        )
        await self._c.commit()
        return cur.rowcount
