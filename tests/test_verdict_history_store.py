"""Tests for verdict_history persistence in InsightStore.

v1.14.4a: the store-layer half of AdaptiveFeedbackDetector.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from custom_components.ha_insights.insight import Insight, InsightKind
from custom_components.ha_insights.store import InsightStore


def _make_insight(insight_id: str = "abc123", **overrides: Any) -> Insight:
    base: dict[str, Any] = {
        "id": insight_id,
        "kind": InsightKind.AUTOMATION_PROPOSAL,
        "detector": "schedule",
        "area_id": "area_1",
        "title": "Test routine",
        "confidence": 0.85,
        "fingerprint": {"entity": "light.kitchen"},
        "payload": {"trigger": "time"},
        "payload_format": "blueprint",
        "created_at": datetime(2026, 5, 19, 12, 0, tzinfo=UTC),
    }
    base.update(overrides)
    return Insight(**base)


def _fp(automations: list[str] | None = None) -> dict[str, Any]:
    """Compact EnvironmentalFingerprint-like dict for serialization tests."""
    return {
        "automation_ids": automations or [],
        "sensors_per_area": {},
        "active_integrations": [],
    }


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[InsightStore]:
    db = InsightStore(tmp_path / "test.db")
    await db.open()
    yield db
    await db.close()


# ---------- Migration ------------------------------------------------


async def test_migration_creates_verdict_history_table(tmp_path: Path) -> None:
    """A fresh open() applies migration 6 → table exists, indexes exist."""
    db = InsightStore(tmp_path / "fresh.db")
    await db.open()
    # Probe via INFO query. sqlite_master lists every table + index.
    async with db._c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='verdict_history'"
    ) as cur:
        row = await cur.fetchone()
    assert row is not None
    async with db._c.execute(
        "SELECT name FROM sqlite_master WHERE type='index' "
        "AND name='ix_verdict_history_insight'"
    ) as cur:
        idx_row = await cur.fetchone()
    assert idx_row is not None
    await db.close()


async def test_migration_schema_version_is_6(tmp_path: Path) -> None:
    db = InsightStore(tmp_path / "ver.db")
    await db.open()
    # schema_version has one row per applied migration; the store
    # reads MAX(version) elsewhere.
    async with db._c.execute(
        "SELECT MAX(version) AS v FROM schema_version"
    ) as cur:
        row = await cur.fetchone()
    assert row["v"] == 6
    await db.close()


# ---------- record_verdict + get_verdict_history --------------------


async def test_record_and_read_single_verdict(store: InsightStore) -> None:
    await store.add_insight(_make_insight("ins1"))
    when = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
    fp = _fp(automations=["automation.a", "automation.b"])
    await store.record_verdict(
        "ins1",
        kind="dismissed",
        fingerprint=fp,
        when=when,
    )
    history = await store.get_verdict_history("ins1")
    assert len(history) == 1
    assert history[0]["insight_id"] == "ins1"
    assert history[0]["kind"] == "dismissed"
    assert history[0]["timestamp"] == when.timestamp()
    assert history[0]["fingerprint"] == fp
    assert history[0]["user_id_hash"] is None


async def test_verdicts_ordered_by_timestamp_ascending(
    store: InsightStore,
) -> None:
    await store.add_insight(_make_insight("ins1"))
    # Write out of chronological order — query should still sort.
    later = datetime(2026, 5, 10, tzinfo=UTC)
    earlier = datetime(2026, 5, 1, tzinfo=UTC)
    middle = datetime(2026, 5, 5, tzinfo=UTC)
    await store.record_verdict(
        "ins1", kind="dismissed", fingerprint=_fp(), when=later
    )
    await store.record_verdict(
        "ins1", kind="applied", fingerprint=_fp(), when=earlier
    )
    await store.record_verdict(
        "ins1", kind="retired", fingerprint=_fp(), when=middle
    )
    history = await store.get_verdict_history("ins1")
    assert [v["timestamp"] for v in history] == [
        earlier.timestamp(),
        middle.timestamp(),
        later.timestamp(),
    ]
    assert [v["kind"] for v in history] == ["applied", "retired", "dismissed"]


async def test_user_id_hash_round_trip(store: InsightStore) -> None:
    await store.add_insight(_make_insight("ins1"))
    await store.record_verdict(
        "ins1",
        kind="dismissed",
        fingerprint=_fp(),
        when=datetime(2026, 5, 1, tzinfo=UTC),
        user_id_hash="user_hash_abc",
    )
    history = await store.get_verdict_history("ins1")
    assert history[0]["user_id_hash"] == "user_hash_abc"


async def test_unknown_insight_returns_empty_history(
    store: InsightStore,
) -> None:
    assert await store.get_verdict_history("does_not_exist") == []


async def test_fingerprint_with_nested_dict_round_trips(
    store: InsightStore,
) -> None:
    """sensors_per_area is a nested dict — JSON serialization must
    preserve it cleanly."""
    await store.add_insight(_make_insight("ins1"))
    complex_fp = {
        "automation_ids": ["a", "b"],
        "sensors_per_area": {
            "kitchen": {"motion": 2, "temperature": 1},
            "bedroom": {"motion": 1},
        },
        "active_integrations": ["mqtt", "zha"],
    }
    await store.record_verdict(
        "ins1",
        kind="dismissed",
        fingerprint=complex_fp,
        when=datetime(2026, 5, 1, tzinfo=UTC),
    )
    history = await store.get_verdict_history("ins1")
    assert history[0]["fingerprint"] == complex_fp


# ---------- get_all_verdict_histories -------------------------------


async def test_bulk_read_groups_by_insight(store: InsightStore) -> None:
    await store.add_insight(_make_insight("ins1"))
    await store.add_insight(_make_insight("ins2"))
    base = datetime(2026, 5, 1, tzinfo=UTC)
    await store.record_verdict(
        "ins1", kind="dismissed", fingerprint=_fp(), when=base
    )
    await store.record_verdict(
        "ins1",
        kind="applied",
        fingerprint=_fp(),
        when=base + timedelta(days=1),
    )
    await store.record_verdict(
        "ins2",
        kind="retired",
        fingerprint=_fp(),
        when=base + timedelta(days=2),
    )
    histories = await store.get_all_verdict_histories()
    assert set(histories) == {"ins1", "ins2"}
    assert len(histories["ins1"]) == 2
    assert len(histories["ins2"]) == 1
    # Each insight's list is ascending by timestamp
    assert histories["ins1"][0]["kind"] == "dismissed"
    assert histories["ins1"][1]["kind"] == "applied"


async def test_bulk_read_empty_when_no_verdicts(store: InsightStore) -> None:
    """Inserting an insight doesn't auto-create a history entry."""
    await store.add_insight(_make_insight("ins1"))
    histories = await store.get_all_verdict_histories()
    assert histories == {}


# ---------- Append-only semantics ------------------------------------


async def test_multiple_verdicts_for_same_insight_all_recorded(
    store: InsightStore,
) -> None:
    """The timeline is append-only — recording 5 dismisses keeps all 5."""
    await store.add_insight(_make_insight("ins1"))
    base = datetime(2026, 5, 1, tzinfo=UTC)
    for i in range(5):
        await store.record_verdict(
            "ins1",
            kind="dismissed",
            fingerprint=_fp(automations=[f"a{i}"]),
            when=base + timedelta(hours=i),
        )
    history = await store.get_verdict_history("ins1")
    assert len(history) == 5
    # Each verdict captured its own fingerprint
    assert {
        tuple(v["fingerprint"]["automation_ids"]) for v in history
    } == {("a0",), ("a1",), ("a2",), ("a3",), ("a4",)}


# ---------- FK CASCADE ---------------------------------------------


async def test_history_survives_until_insight_deleted(
    store: InsightStore,
) -> None:
    """SQLite's foreign-keys pragma is off by default. The verdict_history
    table declares ``FOREIGN KEY ... ON DELETE CASCADE`` for FUTURE use —
    we don't rely on it yet because the store doesn't enable PRAGMA
    foreign_keys=ON globally. This test documents the current state:
    deleting the parent insight leaves orphan rows around. v1.14.4b can
    add explicit cleanup or enable the pragma if needed."""
    await store.add_insight(_make_insight("ins1"))
    await store.record_verdict(
        "ins1",
        kind="dismissed",
        fingerprint=_fp(),
        when=datetime(2026, 5, 1, tzinfo=UTC),
    )
    # Delete the insight row directly (the store has no public delete).
    await store._c.execute("DELETE FROM insights WHERE id = ?", ("ins1",))
    await store._c.commit()
    # Without PRAGMA foreign_keys=ON, the verdict_history row stays.
    history = await store.get_verdict_history("ins1")
    assert len(history) == 1


# ---------- Idempotent migration ------------------------------------


async def test_reopen_doesnt_reapply_migration(tmp_path: Path) -> None:
    """Re-opening a v6 DB doesn't reset / drop the table."""
    path = tmp_path / "stable.db"
    db1 = InsightStore(path)
    await db1.open()
    await db1.add_insight(_make_insight("ins1"))
    await db1.record_verdict(
        "ins1",
        kind="dismissed",
        fingerprint=_fp(automations=["preserved"]),
        when=datetime(2026, 5, 1, tzinfo=UTC),
    )
    await db1.close()

    # Reopen
    db2 = InsightStore(path)
    await db2.open()
    history = await db2.get_verdict_history("ins1")
    assert len(history) == 1
    assert history[0]["fingerprint"]["automation_ids"] == ["preserved"]
    await db2.close()


# ---------- Serialization stability ---------------------------------


async def test_fingerprint_json_sorted_keys_for_diffability(
    store: InsightStore,
) -> None:
    """The store writes fingerprint_json with sort_keys=True so a
    `sqlite3` dump produces stable text. Two fingerprints with the
    same content but different dict-iteration order serialize
    identically."""
    await store.add_insight(_make_insight("ins1"))
    # Two semantically-equivalent fingerprints with different key order
    fp_a = {"b": 1, "a": 1, "c": {"y": 2, "x": 1}}
    fp_b = {"a": 1, "c": {"x": 1, "y": 2}, "b": 1}
    await store.record_verdict(
        "ins1",
        kind="dismissed",
        fingerprint=fp_a,
        when=datetime(2026, 5, 1, tzinfo=UTC),
    )
    # Read the raw row to compare serialized form
    async with store._c.execute(
        "SELECT fingerprint_json FROM verdict_history WHERE insight_id = ?",
        ("ins1",),
    ) as cur:
        row = await cur.fetchone()
    assert row["fingerprint_json"] == json.dumps(fp_b, sort_keys=True)
