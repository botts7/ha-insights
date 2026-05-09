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


# --- v0.9 phase 1C: cost estimate aggregation ---


async def test_summary_includes_cost_estimate(store: InsightStore) -> None:
    """A cloud call rolls up into est_cost_usd_total > 0."""
    await record_call(
        store,
        insight_id="i1",
        agent="conversation.claude-sonnet-4",
        agent_locality="cloud",
        redaction_mode="aggressive",
        bytes_sent=4000,
        bytes_received=400,
        success=True,
    )
    summary = await store.get_outbound_call_summary(
        since=datetime.now(tz=UTC) - timedelta(days=1)
    )
    assert summary["est_cost_usd_total"] > 0


async def test_summary_local_only_costs_zero(store: InsightStore) -> None:
    """Three local calls should still report $0.00 — no surprise charges."""
    for i in range(3):
        await record_call(
            store,
            insight_id=f"i{i}",
            agent="conversation.ollama_llama3",
            agent_locality="local",
            redaction_mode="aggressive",
            bytes_sent=10_000,
            bytes_received=2_000,
            success=True,
        )
    summary = await store.get_outbound_call_summary(
        since=datetime.now(tz=UTC) - timedelta(days=1)
    )
    assert summary["est_cost_usd_total"] == 0.0


async def test_summary_mixed_agents_only_charges_cloud(store: InsightStore) -> None:
    """Local call + cloud call: total only reflects the cloud one."""
    await record_call(
        store,
        insight_id="i_local",
        agent="conversation.ollama",
        agent_locality="local",
        redaction_mode="aggressive",
        bytes_sent=10_000,
        bytes_received=2_000,
        success=True,
    )
    await record_call(
        store,
        insight_id="i_cloud",
        agent="conversation.claude-haiku-4",
        agent_locality="cloud",
        redaction_mode="aggressive",
        bytes_sent=4000,
        bytes_received=400,
        success=True,
    )
    summary = await store.get_outbound_call_summary(
        since=datetime.now(tz=UTC) - timedelta(days=1)
    )
    # Haiku-4: 1000 in * $1/M + 100 out * $5/M = $0.0015
    assert summary["est_cost_usd_total"] == pytest.approx(0.0015, abs=1e-4)


async def test_audit_rows_carry_per_call_cost(store: InsightStore) -> None:
    """get_outbound_calls returns per-row tokens + cost so the panel can show them."""
    await record_call(
        store,
        insight_id="i1",
        agent="conversation.claude-sonnet-4",
        agent_locality="cloud",
        redaction_mode="aggressive",
        bytes_sent=4000,
        bytes_received=400,
        success=True,
    )
    rows = await store.get_outbound_calls(limit=10)
    assert len(rows) == 1
    row = rows[0]
    assert "est_tokens_in" in row
    assert "est_tokens_out" in row
    assert "est_cost_usd" in row
    assert "cost_source" in row
    assert row["est_tokens_in"] == 1000
    assert row["est_cost_usd"] > 0


async def test_sensor_exposes_cost_estimate(store: InsightStore) -> None:
    """est_cost_usd_today is populated on the privacy_log sensor."""
    await record_call(
        store,
        insight_id="i1",
        agent="conversation.gpt-4o-mini",
        agent_locality="cloud",
        redaction_mode="aggressive",
        bytes_sent=4000,
        bytes_received=400,
        success=True,
    )
    sensor = PrivacyLogSensor(store=store, entry_id="entry1")
    await sensor.async_update()
    cost = sensor.extra_state_attributes["est_cost_usd_today"]
    assert isinstance(cost, float)
    assert cost > 0
