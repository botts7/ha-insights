"""Tests for the daily-digest notification module."""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from custom_components.ha_insights.insight import Insight, InsightKind
from custom_components.ha_insights.notifications.digest import (
    build_digest_message,
    fire_digest,
)
from custom_components.ha_insights.store import InsightStore

_NOW = datetime(2026, 5, 10, 9, 0, tzinfo=UTC)


def _make_insight(
    insight_id: str,
    *,
    detector: str = "schedule",
    confidence: float = 0.8,
    title: str = "Sample insight",
    created_at: datetime = _NOW,
) -> Insight:
    return Insight(
        id=insight_id,
        kind=InsightKind.AUTOMATION_PROPOSAL,
        detector=detector,
        area_id=None,
        title=title,
        confidence=confidence,
        fingerprint={"id": insight_id},
        payload={"trigger": "time"},
        payload_format="blueprint",
        created_at=created_at,
    )


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[InsightStore]:
    db = InsightStore(tmp_path / "digest.db")
    await db.open()
    yield db
    await db.close()


# --- Pure formatter ---


def test_build_message_returns_none_when_empty() -> None:
    """No new + no open => no notification (silence is golden)."""
    assert build_digest_message(new_insights=[], open_insights=[]) is None


def test_build_message_lists_new_with_breakdown() -> None:
    new = [
        _make_insight("a", detector="schedule", title="Lights nightly", confidence=0.9),
        _make_insight("b", detector="schedule", title="Coffee 7am", confidence=0.7),
        _make_insight("c", detector="long_tail", title="Fan left on", confidence=0.6),
    ]
    msg = build_digest_message(new_insights=new, open_insights=new)
    assert msg is not None
    assert "3 new insight(s) today" in msg
    assert "2 schedule" in msg
    assert "1 long_tail" in msg
    # Sorted by confidence desc — top title appears first
    a_pos = msg.find("Lights nightly")
    b_pos = msg.find("Coffee 7am")
    assert 0 <= a_pos < b_pos


def test_build_message_truncates_titles_with_more_indicator() -> None:
    new = [
        _make_insight(f"i{i}", title=f"Insight {i}", confidence=0.9 - i * 0.01)
        for i in range(5)
    ]
    msg = build_digest_message(new_insights=new, open_insights=new)
    assert msg is not None
    assert "+ 2 more" in msg


def test_build_message_separates_still_open() -> None:
    """Open-but-not-new insights count toward a "still open" line."""
    cutoff = _NOW - timedelta(days=2)
    older = [_make_insight("old", title="Old one", created_at=cutoff)]
    new = [_make_insight("new", title="Fresh one", created_at=_NOW)]
    msg = build_digest_message(new_insights=new, open_insights=new + older)
    assert msg is not None
    assert "1 insight(s) still open from earlier" in msg


def test_build_message_no_new_but_open_says_so() -> None:
    """When yesterday produced nothing but old items linger, mention it."""
    older = [_make_insight("old", title="Lingering", created_at=_NOW - timedelta(days=3))]
    msg = build_digest_message(new_insights=[], open_insights=older)
    assert msg is not None
    assert "No new insights today" in msg
    assert "1 insight(s) still open" in msg


# --- fire_digest end-to-end ---


class _FakeServices:
    """Stand-in for hass.services that records persistent_notification calls."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def async_call(
        self,
        domain: str,
        service: str,
        data: dict[str, Any],
        *,
        blocking: bool = False,
    ) -> None:
        self.calls.append(
            {"domain": domain, "service": service, "data": data, "blocking": blocking}
        )


class _FakeHass:
    def __init__(self) -> None:
        self.services = _FakeServices()


async def test_fire_digest_skips_when_no_insights(store: InsightStore) -> None:
    hass = _FakeHass()
    result = await fire_digest(hass, store, now=_NOW)  # type: ignore[arg-type]
    assert result is None
    assert hass.services.calls == []


async def test_fire_digest_emits_notification_with_stable_id(store: InsightStore) -> None:
    await store.add_insight(_make_insight("i1", title="Detected schedule"))
    hass = _FakeHass()

    result = await fire_digest(hass, store, now=_NOW)  # type: ignore[arg-type]

    assert result == {"new": 1, "open": 1}
    assert len(hass.services.calls) == 1
    call = hass.services.calls[0]
    assert call["domain"] == "persistent_notification"
    assert call["service"] == "create"
    assert call["data"]["title"] == "HA Insights — daily digest"
    # Date-stamped notification_id => one per day, not stacking
    assert call["data"]["notification_id"] == "ha_insights_digest_20260510"
    assert "Detected schedule" in call["data"]["message"]


async def test_fire_digest_buckets_old_vs_new(store: InsightStore) -> None:
    """Insights older than 24h count as 'open' but not 'new'."""
    await store.add_insight(_make_insight("new", created_at=_NOW))
    await store.add_insight(
        _make_insight("old", created_at=_NOW - timedelta(days=3))
    )
    hass = _FakeHass()

    result = await fire_digest(hass, store, now=_NOW)  # type: ignore[arg-type]

    assert result == {"new": 1, "open": 2}
    msg = hass.services.calls[0]["data"]["message"]
    assert "1 new insight(s) today" in msg
    assert "1 insight(s) still open from earlier" in msg


async def test_fire_digest_swallows_service_failures(
    store: InsightStore,
) -> None:
    """If persistent_notification.create raises, digest returns None and doesn't crash."""
    await store.add_insight(_make_insight("i1"))
    hass = _FakeHass()
    hass.services.async_call = AsyncMock(  # type: ignore[method-assign]
        side_effect=RuntimeError("HA went sideways")
    )

    result = await fire_digest(hass, store, now=_NOW)  # type: ignore[arg-type]

    assert result is None
