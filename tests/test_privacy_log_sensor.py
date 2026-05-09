"""Tests for the privacy_log sensor + the store's outbound-call summary."""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from custom_components.ha_insights.llm import record_call
from custom_components.ha_insights.sensor import PrivacyLogSensor
from custom_components.ha_insights.store import InsightStore


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[InsightStore]:
    db = InsightStore(tmp_path / "test.db")
    await db.open()
    yield db
    await db.close()


# --- Store summary ---


async def test_summary_empty_store(store: InsightStore) -> None:
    summary = await store.get_outbound_call_summary(
        since=datetime(2026, 5, 8, tzinfo=UTC)
    )
    assert summary["call_count"] == 0
    assert summary["bytes_sent_total"] == 0
    assert summary["bytes_received_total"] == 0
    assert summary["last_call_timestamp"] is None
    assert summary["last_agent"] is None


async def test_summary_counts_calls(store: InsightStore) -> None:
    for i in range(3):
        await record_call(
            store,
            insight_id=f"i{i}",
            agent="ollama",
            agent_locality="local",
            redaction_mode="aggressive",
            bytes_sent=100 + i,
            bytes_received=50,
            success=True,
        )
    summary = await store.get_outbound_call_summary(
        since=datetime.now(tz=UTC) - timedelta(days=1)
    )
    assert summary["call_count"] == 3
    assert summary["bytes_sent_total"] == 100 + 101 + 102
    assert summary["bytes_received_total"] == 150
    assert summary["last_agent"] == "ollama"


async def test_summary_filters_by_window(store: InsightStore) -> None:
    """Only calls within the window are counted."""
    await record_call(
        store,
        insight_id="i1",
        agent="ollama",
        agent_locality="local",
        redaction_mode="aggressive",
        bytes_sent=100,
        bytes_received=50,
        success=True,
    )
    # Window in the future — nothing should match
    summary = await store.get_outbound_call_summary(
        since=datetime.now(tz=UTC) + timedelta(hours=1)
    )
    assert summary["call_count"] == 0


async def test_summary_picks_latest_agent(store: InsightStore) -> None:
    await record_call(
        store,
        insight_id="i1",
        agent="ollama",
        agent_locality="local",
        redaction_mode="aggressive",
        bytes_sent=100,
        bytes_received=50,
        success=True,
    )
    await record_call(
        store,
        insight_id="i2",
        agent="anthropic",
        agent_locality="cloud",
        redaction_mode="aggressive",
        bytes_sent=200,
        bytes_received=80,
        success=True,
    )
    summary = await store.get_outbound_call_summary(
        since=datetime.now(tz=UTC) - timedelta(days=1)
    )
    assert summary["last_agent"] == "anthropic"


# --- Sensor entity ---


async def test_sensor_initial_state_zero(store: InsightStore) -> None:
    sensor = PrivacyLogSensor(store=store, entry_id="entry1")
    assert sensor.unique_id == "ha_insights_entry1_privacy_log"
    await sensor.async_update()
    assert sensor.native_value == 0
    assert sensor.extra_state_attributes["last_call_timestamp"] is None
    assert sensor.extra_state_attributes["bytes_sent_today"] == 0
    assert sensor.extra_state_attributes["bytes_received_today"] == 0
    assert sensor.extra_state_attributes["last_agent"] is None


async def test_sensor_reflects_recorded_call(store: InsightStore) -> None:
    await record_call(
        store,
        insight_id="i1",
        agent="ollama",
        agent_locality="local",
        redaction_mode="aggressive",
        bytes_sent=512,
        bytes_received=256,
        success=True,
    )
    sensor = PrivacyLogSensor(store=store, entry_id="entry1")
    await sensor.async_update()
    assert sensor.native_value == 1
    assert sensor.extra_state_attributes["bytes_sent_today"] == 512
    assert sensor.extra_state_attributes["bytes_received_today"] == 256
    assert sensor.extra_state_attributes["last_agent"] == "ollama"
    assert sensor.extra_state_attributes["last_call_timestamp"] is not None


async def test_sensor_handles_multiple_calls(store: InsightStore) -> None:
    for i in range(5):
        await record_call(
            store,
            insight_id=f"i{i}",
            agent="anthropic",
            agent_locality="cloud",
            redaction_mode="aggressive",
            bytes_sent=200,
            bytes_received=100,
            success=True,
        )
    sensor = PrivacyLogSensor(store=store, entry_id="entry1")
    await sensor.async_update()
    assert sensor.native_value == 5
    assert sensor.extra_state_attributes["bytes_sent_today"] == 1000
    assert sensor.extra_state_attributes["bytes_received_today"] == 500
