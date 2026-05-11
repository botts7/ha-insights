"""Database schema and migration manifest.

Migrations are keyed by target version and applied in order. Bump
CURRENT_VERSION and add a new entry to MIGRATIONS for any schema change.
Never edit a previously-shipped migration.
"""
from __future__ import annotations

CURRENT_VERSION = 2

MIGRATIONS: dict[int, str] = {
    1: """
    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY
    );
    INSERT OR IGNORE INTO schema_version (version) VALUES (1);

    CREATE TABLE IF NOT EXISTS insights (
        id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        detector TEXT NOT NULL,
        area_id TEXT,
        title TEXT NOT NULL,
        confidence REAL NOT NULL,
        fingerprint_json TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        payload_format TEXT NOT NULL DEFAULT 'blueprint',
        explanation TEXT,
        conflicts_with_json TEXT,
        created_at REAL NOT NULL,
        snoozed_until REAL,
        dismissed_at REAL,
        applied_at REAL,
        applied_artifact_id TEXT
    );
    CREATE INDEX IF NOT EXISTS ix_insights_kind ON insights(kind);
    CREATE INDEX IF NOT EXISTS ix_insights_detector ON insights(detector);
    CREATE INDEX IF NOT EXISTS ix_insights_status
        ON insights(dismissed_at, applied_at, snoozed_until);

    CREATE TABLE IF NOT EXISTS pseudonym_map (
        entity_id TEXT PRIMARY KEY,
        pseudonym TEXT NOT NULL UNIQUE,
        area_id TEXT,
        created_at REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS ix_pseudonym_pseudonym ON pseudonym_map(pseudonym);

    CREATE TABLE IF NOT EXISTS outbound_calls (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp REAL NOT NULL,
        insight_id TEXT,
        agent TEXT NOT NULL,
        agent_locality TEXT NOT NULL,
        redaction_mode TEXT NOT NULL,
        bytes_sent INTEGER NOT NULL,
        bytes_received INTEGER,
        success INTEGER,
        redacted_payload_json TEXT
    );

    CREATE TABLE IF NOT EXISTS applied_history (
        insight_id TEXT PRIMARY KEY,
        artifact_kind TEXT NOT NULL,
        artifact_id TEXT NOT NULL,
        snapshot_json TEXT NOT NULL,
        snapshot_hash TEXT NOT NULL,
        applied_at REAL NOT NULL,
        undo_window_expires_at REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS state_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp REAL NOT NULL,
        entity_id TEXT NOT NULL,
        domain TEXT NOT NULL,
        area_id TEXT,
        old_state TEXT,
        new_state TEXT
    );
    CREATE INDEX IF NOT EXISTS ix_state_events_ts ON state_events(timestamp);
    CREATE INDEX IF NOT EXISTS ix_state_events_eid ON state_events(entity_id);
    """,
    # v1.1 — AuditRollups. Stores pre-computed long-term aggregates
    # (day-of-week / day-of-month / month-of-year transition counts)
    # per entity. The rollup job runs off the scan loop on a daily
    # schedule; the audit packet reads from this table cheaply. See
    # custom_components/ha_insights/audit/rollup.py.
    #
    # Key: (entity_id, dimension, bucket). dimension ∈ {dow, dom, moy};
    # bucket: 0-6 for dow, 1-31 for dom, 1-12 for moy. `transitions`
    # is the count of state changes in that bucket over `window_days`.
    # `computed_at` is the unix ts of the rollup run.
    2: """
    CREATE TABLE IF NOT EXISTS audit_rollups (
        entity_id TEXT NOT NULL,
        dimension TEXT NOT NULL,
        bucket INTEGER NOT NULL,
        transitions INTEGER NOT NULL,
        window_days INTEGER NOT NULL,
        computed_at REAL NOT NULL,
        PRIMARY KEY (entity_id, dimension, bucket)
    );
    CREATE INDEX IF NOT EXISTS ix_rollups_entity
        ON audit_rollups(entity_id);
    CREATE INDEX IF NOT EXISTS ix_rollups_stale
        ON audit_rollups(computed_at);

    INSERT OR REPLACE INTO schema_version (version) VALUES (2);
    """,
}
