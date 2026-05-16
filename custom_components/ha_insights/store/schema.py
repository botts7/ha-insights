"""Database schema and migration manifest.

Migrations are keyed by target version and applied in order. Bump
CURRENT_VERSION and add a new entry to MIGRATIONS for any schema change.
Never edit a previously-shipped migration.
"""
from __future__ import annotations

CURRENT_VERSION = 5

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
    # v1.2 — Incremental rollup progress tracker. One row per entity
    # holding the unix timestamp of the latest fully-rolled-up day.
    # Rollup batches resume from this cursor and ONLY query the gap
    # between it and "today", merging new bucket counts additively
    # into audit_rollups. Old buckets survive recorder purges — once
    # a day is rolled up, its counts are ours forever (until the user
    # changes window_days or purges).
    #
    # The audit_rollups table semantics also change: `upsert_rollups`
    # becomes additive (ON CONFLICT increment) rather than replace.
    # Existing v2 rows are kept; they'll be merged into on the next
    # rollup pass.
    3: """
    CREATE TABLE IF NOT EXISTS audit_rollup_progress (
        entity_id TEXT PRIMARY KEY,
        last_complete_day_ts REAL NOT NULL,
        computed_at REAL NOT NULL,
        window_days INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS ix_rollup_progress_computed
        ON audit_rollup_progress(computed_at);

    INSERT OR REPLACE INTO schema_version (version) VALUES (3);
    """,
    # v1.4 — Multi-user + vendor attribution fields. All three nullable
    # because pre-v1.4 detectors don't set them and the household-level
    # default must stay safe (=NULL). Existing rows survive unchanged.
    #
    # vendor: optional manufacturer tag for the future vendor-plugin
    #   marketplace ("Schlage", "Tesla", "Aqara", …).
    # target_user_id: HA user_id when the detector can attribute the
    #   insight to a specific user (mobile_app device → owner).
    # target_user_id_confidence: 0.0–1.0 attribution confidence
    #   (1.0 registry-grade, 0.85 person.*, 0.7 manual map).
    4: """
    ALTER TABLE insights ADD COLUMN vendor TEXT;
    ALTER TABLE insights ADD COLUMN target_user_id TEXT;
    ALTER TABLE insights ADD COLUMN target_user_id_confidence REAL;

    INSERT OR REPLACE INTO schema_version (version) VALUES (4);
    """,
    # v1.5.46 — Retire lifecycle. Distinct from Dismiss (one-off "not
    # relevant") and Snooze (temporary suppression): Retire marks an
    # insight as a pattern the user has consciously decided NOT to
    # automate going forward, even though the detector keeps seeing
    # it. Future re-detections of the same fingerprint stay
    # suppressed until the user manually un-retires. Filtered out of
    # ws_list by default same as dismissed; surfaced via a separate
    # `include_retired` opt-in flag for the "history" view.
    5: """
    ALTER TABLE insights ADD COLUMN retired_at REAL;

    INSERT OR REPLACE INTO schema_version (version) VALUES (5);
    """,
}
