"""Tests for recorder backfill — mocked recorder, real buffer."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ha_insights.observers.history_backfill import (
    DEFAULT_DOMAINS,
    backfill,
)
from custom_components.ha_insights.observers.state_event_buffer import StateEventBuffer


def _state(entity_id: str, state: str, when: datetime) -> SimpleNamespace:
    """Mimic HA's State object enough for the backfill code."""
    return SimpleNamespace(
        entity_id=entity_id,
        state=state,
        last_changed=when,
    )


def _hass_with_states(states_by_entity: dict[str, list]) -> MagicMock:
    """Build a MagicMock hass whose recorder returns the given states."""
    hass = MagicMock()
    # entity_registry path: er.async_get(hass).async_get(entity_id) -> entry|None
    return hass


@pytest.mark.asyncio
async def test_no_lookback_is_noop() -> None:
    buf = StateEventBuffer(max_age=timedelta(days=30))
    hass = MagicMock()
    summary = await backfill(hass, buf, lookback_days=0)
    assert summary["events_added"] == 0
    assert len(buf) == 0


@pytest.mark.asyncio
async def test_backfill_ingests_allowed_domain() -> None:
    """light.* is in the default allowlist; events should land in the buffer."""
    buf = StateEventBuffer(max_age=timedelta(days=30))
    hass = MagicMock()
    end = datetime.now(tz=UTC)
    states = {
        "light.kitchen": [
            _state("light.kitchen", "off", end - timedelta(days=2)),
            _state("light.kitchen", "on", end - timedelta(days=2, minutes=-1)),
            _state("light.kitchen", "off", end - timedelta(days=1)),
        ],
    }
    with patch(
        "custom_components.ha_insights.observers.history_backfill._fetch_history",
        new=AsyncMock(return_value=states),
    ), patch(
        "homeassistant.helpers.entity_registry.async_get",
        return_value=MagicMock(async_get=lambda _: None),
        create=True,
    ):
        summary = await backfill(hass, buf, lookback_days=14)
    assert summary["events_added"] == 3
    assert summary["entities_seen"] == 1
    assert len(buf) == 3


@pytest.mark.asyncio
async def test_backfill_skips_disallowed_domain() -> None:
    """weather.* isn't in the allowlist; should be entirely skipped."""
    buf = StateEventBuffer(max_age=timedelta(days=30))
    hass = MagicMock()
    end = datetime.now(tz=UTC)
    states = {
        "weather.home": [
            _state("weather.home", "sunny", end - timedelta(days=1)),
            _state("weather.home", "rainy", end - timedelta(hours=12)),
        ],
        "light.kitchen": [
            _state("light.kitchen", "on", end - timedelta(days=1)),
        ],
    }
    with patch(
        "custom_components.ha_insights.observers.history_backfill._fetch_history",
        new=AsyncMock(return_value=states),
    ), patch(
        "homeassistant.helpers.entity_registry.async_get",
        return_value=MagicMock(async_get=lambda _: None),
        create=True,
    ):
        summary = await backfill(hass, buf, lookback_days=14)
    # Weather entities skipped, light ingested
    assert summary["events_added"] == 1
    assert summary["events_skipped"] == 2  # both weather states
    assert summary["entities_seen"] == 1


@pytest.mark.asyncio
async def test_backfill_skips_unavailable_states() -> None:
    """unavailable/unknown carry no behavioral signal — skip them."""
    buf = StateEventBuffer(max_age=timedelta(days=30))
    hass = MagicMock()
    end = datetime.now(tz=UTC)
    states = {
        "light.kitchen": [
            _state("light.kitchen", "unavailable", end - timedelta(days=2)),
            _state("light.kitchen", "on", end - timedelta(days=1)),
            _state("light.kitchen", "unknown", end - timedelta(hours=1)),
        ],
    }
    with patch(
        "custom_components.ha_insights.observers.history_backfill._fetch_history",
        new=AsyncMock(return_value=states),
    ), patch(
        "homeassistant.helpers.entity_registry.async_get",
        return_value=MagicMock(async_get=lambda _: None),
        create=True,
    ):
        summary = await backfill(hass, buf, lookback_days=14)
    assert summary["events_added"] == 1  # only "on" state
    assert summary["events_skipped"] == 2


@pytest.mark.asyncio
async def test_backfill_records_old_state_as_prior() -> None:
    """Sequential states should chain — second event's old_state = first's new_state."""
    buf = StateEventBuffer(max_age=timedelta(days=30))
    hass = MagicMock()
    end = datetime.now(tz=UTC)
    states = {
        "binary_sensor.door": [
            _state("binary_sensor.door", "off", end - timedelta(days=2)),
            _state("binary_sensor.door", "on", end - timedelta(days=2, minutes=-1)),
        ],
    }
    with patch(
        "custom_components.ha_insights.observers.history_backfill._fetch_history",
        new=AsyncMock(return_value=states),
    ), patch(
        "homeassistant.helpers.entity_registry.async_get",
        return_value=MagicMock(async_get=lambda _: None),
        create=True,
    ):
        await backfill(hass, buf, lookback_days=14)
    events = list(buf.query())
    assert len(events) == 2
    assert events[0].old_state is None  # first state has no prior
    assert events[1].old_state == "off"  # chains from prior


@pytest.mark.asyncio
async def test_backfill_returns_duration() -> None:
    buf = StateEventBuffer(max_age=timedelta(days=30))
    hass = MagicMock()
    with patch(
        "custom_components.ha_insights.observers.history_backfill._fetch_history",
        new=AsyncMock(return_value={}),
    ), patch(
        "homeassistant.helpers.entity_registry.async_get",
        return_value=MagicMock(async_get=lambda _: None),
        create=True,
    ):
        summary = await backfill(hass, buf, lookback_days=7)
    assert "duration_seconds" in summary
    assert summary["duration_seconds"] >= 0


@pytest.mark.asyncio
async def test_custom_domain_allowlist() -> None:
    """Caller can override the default allowlist."""
    buf = StateEventBuffer(max_age=timedelta(days=30))
    hass = MagicMock()
    end = datetime.now(tz=UTC)
    states = {
        "switch.fan": [_state("switch.fan", "on", end - timedelta(days=1))],
        "light.kitchen": [_state("light.kitchen", "on", end - timedelta(days=1))],
    }
    with patch(
        "custom_components.ha_insights.observers.history_backfill._fetch_history",
        new=AsyncMock(return_value=states),
    ), patch(
        "homeassistant.helpers.entity_registry.async_get",
        return_value=MagicMock(async_get=lambda _: None),
        create=True,
    ):
        # Restrict to light only
        summary = await backfill(
            hass, buf, lookback_days=14, allowed_domains=frozenset({"light"})
        )
    assert summary["events_added"] == 1
    assert summary["entities_seen"] == 1


def test_default_domains_includes_common_routine_signals() -> None:
    """Sanity check the default allowlist."""
    assert "light" in DEFAULT_DOMAINS
    assert "binary_sensor" in DEFAULT_DOMAINS
    assert "switch" in DEFAULT_DOMAINS
    assert "lock" in DEFAULT_DOMAINS
    # Things we deliberately exclude
    assert "weather" not in DEFAULT_DOMAINS
    assert "sun" not in DEFAULT_DOMAINS
    assert "zone" not in DEFAULT_DOMAINS
