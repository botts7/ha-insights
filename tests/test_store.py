"""Tests for InsightStore (SQLite + pseudonym map)."""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
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
        "created_at": datetime(2026, 5, 8, 12, 0, tzinfo=UTC),
    }
    base.update(overrides)
    return Insight(**base)


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[InsightStore]:
    db = InsightStore(tmp_path / "test.db")
    await db.open()
    yield db
    await db.close()


# --- Migrations ---


async def test_open_creates_fresh_schema(tmp_path: Path) -> None:
    db = InsightStore(tmp_path / "fresh.db")
    await db.open()
    insights = await db.list_insights()
    assert insights == []
    await db.close()


async def test_open_is_idempotent(tmp_path: Path) -> None:
    """Opening an already-migrated DB doesn't re-apply or error."""
    path = tmp_path / "test.db"
    db1 = InsightStore(path)
    await db1.open()
    await db1.close()
    db2 = InsightStore(path)
    await db2.open()  # must not raise
    assert await db2.list_insights() == []
    await db2.close()


# --- Insight CRUD ---


async def test_add_and_get_roundtrip(store: InsightStore) -> None:
    ins = _make_insight()
    await store.add_insight(ins)
    fetched = await store.get_insight(ins.id)
    assert fetched is not None
    assert fetched.id == ins.id
    assert fetched.kind is ins.kind
    assert fetched.confidence == ins.confidence
    assert fetched.fingerprint == ins.fingerprint
    assert fetched.payload == ins.payload
    assert fetched.payload_format == ins.payload_format
    assert fetched.created_at == ins.created_at
    assert fetched.conflicts_with == ()


async def test_add_insight_with_conflicts(store: InsightStore) -> None:
    ins = _make_insight(conflicts_with=("automation_a", "automation_b"))
    await store.add_insight(ins)
    fetched = await store.get_insight(ins.id)
    assert fetched is not None
    assert fetched.conflicts_with == ("automation_a", "automation_b")


async def test_get_insight_unknown_returns_none(store: InsightStore) -> None:
    assert await store.get_insight("nonexistent") is None


async def test_add_insight_is_upsert_by_id(store: InsightStore) -> None:
    ins1 = _make_insight(title="Original")
    await store.add_insight(ins1)
    ins2 = _make_insight(title="Updated")
    await store.add_insight(ins2)
    fetched = await store.get_insight(ins1.id)
    assert fetched is not None
    assert fetched.title == "Updated"


async def test_list_insights_empty(store: InsightStore) -> None:
    assert await store.list_insights() == []


async def test_list_insights_excludes_dismissed_by_default(store: InsightStore) -> None:
    a = _make_insight(insight_id="a", fingerprint={"k": 1})
    b = _make_insight(insight_id="b", fingerprint={"k": 2})
    await store.add_insight(a)
    await store.add_insight(b)
    await store.dismiss_insight("a")

    listing = await store.list_insights()
    assert {i.id for i in listing} == {"b"}

    full = await store.list_insights(include_dismissed=True)
    assert {i.id for i in full} == {"a", "b"}


async def test_dismiss_unknown_returns_false(store: InsightStore) -> None:
    assert await store.dismiss_insight("nonexistent") is False


async def test_snooze_persists(store: InsightStore) -> None:
    ins = _make_insight()
    await store.add_insight(ins)
    until = datetime(2026, 5, 15, tzinfo=UTC)
    assert await store.snooze_insight(ins.id, until=until) is True

    fetched = await store.get_insight(ins.id)
    assert fetched is not None
    assert fetched.snoozed_until == until


# --- Pseudonym map ---


async def test_pseudonym_get_or_create_stable(store: InsightStore) -> None:
    p1 = await store.get_or_create_pseudonym("light.kitchen", area_id="kitchen")
    p2 = await store.get_or_create_pseudonym("light.kitchen")
    assert p1 == p2


async def test_pseudonym_distinct_for_different_entities(store: InsightStore) -> None:
    p1 = await store.get_or_create_pseudonym("light.kitchen")
    p2 = await store.get_or_create_pseudonym("light.bedroom")
    assert p1 != p2


async def test_pseudonym_starts_with_domain(store: InsightStore) -> None:
    p = await store.get_or_create_pseudonym("sensor.temperature")
    assert p.startswith("sensor.")


async def test_pseudonym_rename_preserves_string(store: InsightStore) -> None:
    """Renaming entity_id keeps the same pseudonym string."""
    p_before = await store.get_or_create_pseudonym("light.kitchen")
    assert await store.rename_entity_pseudonym("light.kitchen", "light.galley") is True

    p_after = await store.get_or_create_pseudonym("light.galley")
    assert p_after == p_before


async def test_pseudonym_rename_frees_old_id(store: InsightStore) -> None:
    """After rename, the old entity_id has no pseudonym; querying creates a new one."""
    p_before = await store.get_or_create_pseudonym("light.kitchen")
    await store.rename_entity_pseudonym("light.kitchen", "light.galley")
    p_old_again = await store.get_or_create_pseudonym("light.kitchen")
    assert p_old_again != p_before


async def test_pseudonym_rename_no_op_for_unknown(store: InsightStore) -> None:
    assert await store.rename_entity_pseudonym("light.never", "light.also_never") is False


async def test_pseudonym_rename_same_id_no_op(store: InsightStore) -> None:
    await store.get_or_create_pseudonym("light.kitchen")
    assert await store.rename_entity_pseudonym("light.kitchen", "light.kitchen") is False


# --- Connection lifecycle ---


async def test_use_before_open_raises(tmp_path: Path) -> None:
    db = InsightStore(tmp_path / "unopened.db")
    with pytest.raises(RuntimeError, match="not open"):
        await db.list_insights()
