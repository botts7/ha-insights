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
        self._path = Path(path)
        self._conn: aiosqlite.Connection | None = None
        self._listeners: list[StoreListener] = []

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
                await self._c.executescript(MIGRATIONS[version])
                await self._c.execute(
                    "INSERT OR IGNORE INTO schema_version (version) VALUES (?)",
                    (version,),
                )
                await self._c.commit()

    # --- Insights ---

    async def add_insight(self, insight: Insight) -> None:
        """Insert or replace an insight by id."""
        snoozed_ts = (
            insight.snoozed_until.timestamp() if insight.snoozed_until else None
        )
        await self._c.execute(
            """
            INSERT OR REPLACE INTO insights (
                id, kind, detector, area_id, title, confidence,
                fingerprint_json, payload_json, payload_format,
                explanation, conflicts_with_json, created_at, snoozed_until
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
        await self._c.commit()
        self._notify("added", insight)

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

    async def purge_observations(self) -> dict[str, int]:
        """Wipe insights + outbound_calls audit log.

        Per docs/ARCHITECTURE.md: pseudonym_map and applied_history are
        preserved so post-purge undo + cross-restart pseudonyms still work.
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
