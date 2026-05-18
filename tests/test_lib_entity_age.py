"""Tests for v1.12.11 lib/entity_age.py — pure helpers for the
newly-added entity badge."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from custom_components.ha_insights.lib.entity_age import (
    NEWLY_ADDED_THRESHOLD_DAYS,
    days_since_added,
    is_newly_added,
)


def test_days_since_added_basic() -> None:
    now = datetime(2026, 5, 17, 12, 0, tzinfo=UTC)
    created = now - timedelta(days=5)
    assert days_since_added(created, now=now) == 5


def test_days_since_added_floors_partial_day() -> None:
    """A 6-hour-old entity returns 0 — 'added today'."""
    now = datetime(2026, 5, 17, 12, 0, tzinfo=UTC)
    created = now - timedelta(hours=6)
    assert days_since_added(created, now=now) == 0


def test_days_since_added_none_input() -> None:
    """Older HA versions don't expose created_at — return None gracefully."""
    assert days_since_added(None) is None


def test_days_since_added_non_datetime() -> None:
    """Defensive against a stringified or otherwise wrong type."""
    assert days_since_added("2026-05-17T00:00:00Z") is None  # type: ignore[arg-type]


def test_days_since_added_naive_datetime() -> None:
    """A tz-naive created_at can't be safely subtracted from a tz-aware
    `now`. Return None rather than guessing the timezone."""
    now = datetime(2026, 5, 17, 12, 0, tzinfo=UTC)
    naive_created = datetime(2026, 5, 15, 12, 0)  # no tzinfo
    assert days_since_added(naive_created, now=now) is None


def test_days_since_added_future_timestamp() -> None:
    """Clock skew can make created_at > now. Treat as 'unknown' rather
    than surface a negative-days badge."""
    now = datetime(2026, 5, 17, 12, 0, tzinfo=UTC)
    created = now + timedelta(days=2)
    assert days_since_added(created, now=now) is None


def test_is_newly_added_within_threshold() -> None:
    now = datetime(2026, 5, 17, 12, 0, tzinfo=UTC)
    created = now - timedelta(days=NEWLY_ADDED_THRESHOLD_DAYS - 1)
    assert is_newly_added(created, now=now)


def test_is_newly_added_at_threshold_boundary() -> None:
    """The threshold is inclusive — exactly N days still counts."""
    now = datetime(2026, 5, 17, 12, 0, tzinfo=UTC)
    created = now - timedelta(days=NEWLY_ADDED_THRESHOLD_DAYS)
    assert is_newly_added(created, now=now)


def test_is_newly_added_past_threshold() -> None:
    now = datetime(2026, 5, 17, 12, 0, tzinfo=UTC)
    created = now - timedelta(days=NEWLY_ADDED_THRESHOLD_DAYS + 1)
    assert not is_newly_added(created, now=now)


def test_is_newly_added_none() -> None:
    """No created_at → no badge."""
    assert not is_newly_added(None)


def test_is_newly_added_custom_threshold() -> None:
    """Threshold is overridable so callers can tighten the badge window
    (e.g. only show for <7 days)."""
    now = datetime(2026, 5, 17, 12, 0, tzinfo=UTC)
    created = now - timedelta(days=10)
    assert is_newly_added(created, now=now, threshold_days=14)
    assert not is_newly_added(created, now=now, threshold_days=7)
