"""Tests for InsightStore (SQLite + pseudonym map)."""
from __future__ import annotations

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


# --- Snooze filter ---


async def test_list_excludes_snoozed_by_default(store: InsightStore) -> None:
    a = _make_insight(insight_id="a", fingerprint={"k": 1})
    b = _make_insight(insight_id="b", fingerprint={"k": 2})
    await store.add_insight(a)
    await store.add_insight(b)
    future = datetime.now(tz=UTC) + timedelta(days=7)
    await store.snooze_insight("a", until=future)

    listing = await store.list_insights()
    assert {i.id for i in listing} == {"b"}


async def test_list_includes_expired_snoozed(store: InsightStore) -> None:
    """Snoozed insights past their snoozed_until are visible again."""
    a = _make_insight(insight_id="a", fingerprint={"k": 1})
    await store.add_insight(a)
    past = datetime.now(tz=UTC) - timedelta(days=1)
    await store.snooze_insight("a", until=past)

    listing = await store.list_insights()
    assert {i.id for i in listing} == {"a"}


async def test_list_with_include_snoozed(store: InsightStore) -> None:
    a = _make_insight(insight_id="a", fingerprint={"k": 1})
    await store.add_insight(a)
    future = datetime.now(tz=UTC) + timedelta(days=7)
    await store.snooze_insight("a", until=future)

    listing = await store.list_insights(include_snoozed=True)
    assert {i.id for i in listing} == {"a"}


# --- Purge ---


async def test_purge_observations_clears_insights(store: InsightStore) -> None:
    await store.add_insight(_make_insight(insight_id="a", fingerprint={"k": 1}))
    await store.add_insight(_make_insight(insight_id="b", fingerprint={"k": 2}))

    counts = await store.purge_observations()
    assert counts["insights_deleted"] == 2

    assert await store.list_insights() == []


async def test_purge_observations_preserves_pseudonyms(store: InsightStore) -> None:
    """Pseudonyms must survive purge so cross-restart references stay stable."""
    p1 = await store.get_or_create_pseudonym("light.kitchen")
    await store.add_insight(_make_insight())
    await store.purge_observations()
    p2 = await store.get_or_create_pseudonym("light.kitchen")
    assert p1 == p2


# --- Retire + stale-sweep interaction (issue #116) ---
#
# replace_active_insights_for_detectors must NEVER delete a retired row.
# Pre-fix it checked applied/dismissed/snoozed but not retired_at, so a
# retired insight the detector skipped for one scan got swept; when the
# detector re-emitted it later it was a FRESH insert → "added" event →
# new notification, and the retire verdict was gone ("they come back").


async def test_sweep_preserves_retired_rows(store: InsightStore) -> None:
    retired = _make_insight(
        insight_id="retired1", detector="location_proposal", fingerprint={"k": "r"}
    )
    stale = _make_insight(
        insight_id="stale1", detector="location_proposal", fingerprint={"k": "s"}
    )
    await store.add_insight(retired)
    await store.add_insight(stale)
    assert await store.retire_insight("retired1") is True

    # Detector ran but emitted nothing this scan → both rows are stale
    # candidates; only the NON-retired one may be swept.
    swept = await store.replace_active_insights_for_detectors(
        completed_detectors=frozenset({"location_proposal"}),
        emitted_ids=frozenset(),
    )
    assert swept == 1

    gone = await store.get_insight("stale1")
    assert gone is None

    kept = await store.get_insight("retired1")
    assert kept is not None
    assert kept.retired_at is not None
    # Default listing still hides it; include_retired surfaces it.
    assert "retired1" not in {i.id for i in await store.list_insights()}
    assert "retired1" in {
        i.id for i in await store.list_insights(include_retired=True)
    }


async def test_retired_insight_reemit_stays_retired_and_fires_refreshed(
    store: InsightStore,
) -> None:
    """Full #116 'retire comes back' scenario: retire an insight, run a
    sweep that doesn't re-emit it, then re-add the same insight id (the
    detector saw the pattern again). The row must survive the sweep,
    stay retired, and fire 'refreshed' (notification-suppressed) —
    never a fresh 'added'."""
    events: list[tuple[str, str | None]] = []
    store.add_listener(lambda etype, ins: events.append((etype, ins.id if ins else None)))

    ins = _make_insight(
        insight_id="loc1", detector="location_proposal", fingerprint={"entity_id": "sensor.x"}
    )
    await store.add_insight(ins)
    assert await store.retire_insight("loc1") is True

    # Scan where the detector did NOT re-emit it (e.g. r dipped below
    # threshold for a day) — sweep must keep the retired row.
    swept = await store.replace_active_insights_for_detectors(
        completed_detectors=frozenset({"location_proposal"}),
        emitted_ids=frozenset(),
    )
    assert swept == 0
    assert await store.get_insight("loc1") is not None

    # Next scan re-detects the same fingerprint → same id → upsert.
    await store.add_insight(ins)
    kept = await store.get_insight("loc1")
    assert kept is not None
    assert kept.retired_at is not None, "retire verdict must survive re-emission"

    # Event sequence: added (first insert), retired (user action),
    # refreshed (re-emit). No second "added" — that's what previously
    # re-triggered notifications after the sweep deleted the retired row.
    assert events == [("added", "loc1"), ("retired", "loc1"), ("refreshed", "loc1")]
    assert "loc1" not in {i.id for i in await store.list_insights()}


async def test_sweep_still_removes_stale_active_rows(store: InsightStore) -> None:
    """Sanity: the sweep still does its job for non-retired rows, and
    rows from detectors that didn't run are untouched."""
    a = _make_insight(insight_id="a", detector="location_proposal", fingerprint={"k": 1})
    b = _make_insight(insight_id="b", detector="other_detector", fingerprint={"k": 2})
    await store.add_insight(a)
    await store.add_insight(b)

    swept = await store.replace_active_insights_for_detectors(
        completed_detectors=frozenset({"location_proposal"}),
        emitted_ids=frozenset(),
    )
    assert swept == 1
    assert await store.get_insight("a") is None
    assert await store.get_insight("b") is not None  # other detector didn't run


async def test_clear_retired_allows_fresh_notification(store: InsightStore) -> None:
    """Un-retiring is the explicit user action that legitimately lets
    the insight notify again as a fresh 'added'."""
    events: list[str] = []
    store.add_listener(lambda etype, ins: events.append(etype))

    ins = _make_insight(insight_id="u1", detector="location_proposal")
    await store.add_insight(ins)
    await store.retire_insight("u1")
    assert await store.clear_retired("u1") is True

    # Row survived (retire cleared, not deleted) → re-emit is 'refreshed'.
    await store.add_insight(ins)
    assert events == ["added", "retired", "unretired", "refreshed"]
    assert (await store.get_insight("u1")).retired_at is None
