"""Tests for StateEventBuffer."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from custom_components.ha_insights.observers.state_event_buffer import (
    StateEvent,
    StateEventBuffer,
)


def _ev(
    *,
    entity_id: str = "light.kitchen",
    domain: str = "light",
    area_id: str | None = "kitchen",
    timestamp: datetime | None = None,
    old_state: str | None = "off",
    new_state: str | None = "on",
) -> StateEvent:
    return StateEvent(
        timestamp=timestamp or datetime(2026, 5, 8, 12, 0, tzinfo=UTC),
        entity_id=entity_id,
        domain=domain,
        area_id=area_id,
        old_state=old_state,
        new_state=new_state,
    )


def test_add_accepts_event_with_no_filter() -> None:
    buf = StateEventBuffer()
    assert buf.add(_ev()) is True
    assert len(buf) == 1


def test_add_filters_by_area() -> None:
    buf = StateEventBuffer(area_filter=frozenset({"living"}))
    assert buf.add(_ev(area_id="kitchen")) is False
    assert buf.add(_ev(area_id="living")) is True
    assert len(buf) == 1


def test_add_with_no_filter_accepts_none_area() -> None:
    buf = StateEventBuffer()
    assert buf.add(_ev(area_id=None)) is True


def test_filter_with_none_area_rejected() -> None:
    """Area filter set; events without an area_id are rejected."""
    buf = StateEventBuffer(area_filter=frozenset({"kitchen"}))
    assert buf.add(_ev(area_id=None)) is False


def test_query_by_entity_id() -> None:
    buf = StateEventBuffer()
    buf.add(_ev(entity_id="light.kitchen"))
    buf.add(_ev(entity_id="light.bedroom"))
    results = list(buf.query(entity_id="light.kitchen"))
    assert len(results) == 1
    assert results[0].entity_id == "light.kitchen"


def test_query_by_since_inclusive() -> None:
    buf = StateEventBuffer()
    t1 = datetime(2026, 5, 8, 10, 0, tzinfo=UTC)
    t2 = datetime(2026, 5, 8, 12, 0, tzinfo=UTC)
    buf.add(_ev(timestamp=t1))
    buf.add(_ev(timestamp=t2))
    results = list(buf.query(since=t2))
    assert len(results) == 1
    assert results[0].timestamp == t2


def test_query_by_until_exclusive() -> None:
    buf = StateEventBuffer()
    t1 = datetime(2026, 5, 8, 10, 0, tzinfo=UTC)
    t2 = datetime(2026, 5, 8, 12, 0, tzinfo=UTC)
    buf.add(_ev(timestamp=t1))
    buf.add(_ev(timestamp=t2))
    results = list(buf.query(until=t2))
    assert len(results) == 1
    assert results[0].timestamp == t1


def test_query_combined_filters() -> None:
    buf = StateEventBuffer()
    t1 = datetime(2026, 5, 8, 10, 0, tzinfo=UTC)
    buf.add(_ev(entity_id="light.kitchen", timestamp=t1))
    buf.add(_ev(entity_id="light.bedroom", timestamp=t1))
    results = list(buf.query(entity_id="light.kitchen", since=t1, until=t1 + timedelta(hours=1)))
    assert len(results) == 1
    assert results[0].entity_id == "light.kitchen"


def test_prune_drops_old_events() -> None:
    buf = StateEventBuffer(max_age=timedelta(hours=1))
    now = datetime(2026, 5, 8, 12, 0, tzinfo=UTC)
    buf.add(_ev(timestamp=now - timedelta(hours=2)))  # too old
    buf.add(_ev(timestamp=now - timedelta(minutes=30)))  # within
    removed = buf.prune(now=now)
    assert removed == 1
    assert len(buf) == 1


def test_prune_returns_zero_when_nothing_old() -> None:
    buf = StateEventBuffer(max_age=timedelta(days=1))
    now = datetime(2026, 5, 8, 12, 0, tzinfo=UTC)
    buf.add(_ev(timestamp=now))
    assert buf.prune(now=now) == 0


def test_default_max_age_is_seven_days() -> None:
    buf = StateEventBuffer()
    assert buf.max_age == timedelta(days=7)


def test_rename_entity_updates_events() -> None:
    buf = StateEventBuffer()
    buf.add(_ev(entity_id="light.kitchen"))
    buf.add(_ev(entity_id="light.bedroom"))
    buf.add(_ev(entity_id="light.kitchen"))

    count = buf.rename_entity("light.kitchen", "light.galley")
    assert count == 2

    new_results = list(buf.query(entity_id="light.galley"))
    assert len(new_results) == 2

    old_results = list(buf.query(entity_id="light.kitchen"))
    assert len(old_results) == 0


def test_rename_entity_no_op_when_old_absent() -> None:
    buf = StateEventBuffer()
    buf.add(_ev(entity_id="light.bedroom"))
    count = buf.rename_entity("light.kitchen", "light.galley")
    assert count == 0
    assert len(buf) == 1


def test_rename_entity_same_name_no_op() -> None:
    buf = StateEventBuffer()
    buf.add(_ev(entity_id="light.kitchen"))
    count = buf.rename_entity("light.kitchen", "light.kitchen")
    assert count == 0


def test_rename_entity_preserves_other_fields() -> None:
    """Rename should keep timestamp, area, states intact."""
    buf = StateEventBuffer()
    t = datetime(2026, 5, 8, 12, 0, tzinfo=UTC)
    buf.add(_ev(
        entity_id="light.kitchen",
        timestamp=t,
        area_id="kitchen",
        old_state="off",
        new_state="on",
    ))
    buf.rename_entity("light.kitchen", "light.galley")
    [renamed] = list(buf.query(entity_id="light.galley"))
    assert renamed.timestamp == t
    assert renamed.area_id == "kitchen"
    assert renamed.old_state == "off"
    assert renamed.new_state == "on"
    assert renamed.domain == "light"


def test_len_zero_initially() -> None:
    buf = StateEventBuffer()
    assert len(buf) == 0


def test_clear_empties_buffer() -> None:
    buf = StateEventBuffer()
    buf.add(_ev(entity_id="light.a"))
    buf.add(_ev(entity_id="light.b"))
    removed = buf.clear()
    assert removed == 2
    assert len(buf) == 0


def test_clear_returns_zero_on_empty_buffer() -> None:
    assert StateEventBuffer().clear() == 0
