"""Regression test: failover attempts each get their own privacy-log row.

v1.0 review found that record_call ran exactly once per WS call, against
the LAST attempt's bytes. Failed earlier attempts in a failover chain
silently disappeared from outbound_calls. This test asserts every
attempt — success AND failure — produces a row.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ha_insights.insight import Insight, InsightKind
from custom_components.ha_insights.llm import (
    RedactionMode,
    Redactor,
    explain_insight,
)
from custom_components.ha_insights.store import InsightStore


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[InsightStore]:
    db = InsightStore(tmp_path / "audit.db")
    await db.open()
    yield db
    await db.close()


def _insight() -> Insight:
    return Insight(
        id="abc",
        kind=InsightKind.AUTOMATION_PROPOSAL,
        detector="schedule",
        area_id=None,
        title="Test",
        confidence=0.9,
        fingerprint={"e": "x"},
        payload={
            "alias": "t",
            "trigger": [{"platform": "time", "at": "06:00:00"}],
            "action": [
                {"service": "light.turn_on", "target": {"entity_id": "light.x"}}
            ],
            "mode": "single",
        },
        payload_format="automation",
        created_at=datetime(2026, 5, 10, tzinfo=UTC),
    )


def _ok(speech: str) -> SimpleNamespace:
    return SimpleNamespace(
        response=SimpleNamespace(speech={"plain": {"speech": speech}})
    )


def _fake_registry(entries: dict[str, str]) -> object:
    return SimpleNamespace(
        entities={
            eid: SimpleNamespace(entity_id=eid, platform=p)
            for eid, p in entries.items()
        }
    )


@pytest.mark.asyncio
async def test_attempts_recorded_per_round_trip(store: InsightStore) -> None:
    """Two-agent failover: success on second => result.attempts has 2 rows."""
    redactor = Redactor(store, mode=RedactionMode.AGGRESSIVE)
    hass = MagicMock()

    async def fake(*_args, agent_id, **_kwargs) -> SimpleNamespace:
        if agent_id == "conversation.first":
            raise RuntimeError("primary down")
        return _ok("clean response from second")

    registry = _fake_registry({
        "conversation.first": "first",
        "conversation.second": "second",
    })
    with (
        patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=registry,
            create=True,
        ),
        patch(
            "homeassistant.components.conversation.async_get_default_agent",
            return_value=SimpleNamespace(entity_id="conversation.first"),
            create=True,
        ),
        patch(
            "homeassistant.components.conversation.async_converse",
            new=AsyncMock(side_effect=fake),
            create=True,
        ),
    ):
        result = await explain_insight(
            hass, agent_id=None, insight=_insight(), redactor=redactor
        )

    # Two attempts: failed first, successful second
    assert len(result.attempts) == 2
    assert result.attempts[0].chosen_agent_id == "conversation.first"
    assert result.attempts[0].success is False
    assert result.attempts[1].chosen_agent_id == "conversation.second"
    assert result.attempts[1].success is True


@pytest.mark.asyncio
async def test_single_attempt_explicit_pin_records_one(
    store: InsightStore,
) -> None:
    """Explicit agent_id => single attempt => single audit row."""
    redactor = Redactor(store, mode=RedactionMode.AGGRESSIVE)
    hass = MagicMock()

    with patch(
        "homeassistant.components.conversation.async_converse",
        new=AsyncMock(return_value=_ok("ok")),
        create=True,
    ):
        result = await explain_insight(
            hass,
            agent_id="conversation.user_pin",
            insight=_insight(),
            redactor=redactor,
        )

    assert len(result.attempts) == 1
    assert result.attempts[0].chosen_agent_id == "conversation.user_pin"
    assert result.attempts[0].success is True


@pytest.mark.asyncio
async def test_all_failed_records_each_attempt(store: InsightStore) -> None:
    """All candidates fail => one audit row per attempt."""
    redactor = Redactor(store, mode=RedactionMode.AGGRESSIVE)
    hass = MagicMock()

    async def always_fail(*_args, agent_id, **_kwargs) -> SimpleNamespace:
        raise RuntimeError(f"{agent_id} unreachable")

    registry = _fake_registry({
        "conversation.a": "a",
        "conversation.b": "b",
    })
    with (
        patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=registry,
            create=True,
        ),
        patch(
            "homeassistant.components.conversation.async_get_default_agent",
            return_value=None,
            create=True,
        ),
        patch(
            "homeassistant.components.conversation.async_converse",
            new=AsyncMock(side_effect=always_fail),
            create=True,
        ),
    ):
        result = await explain_insight(
            hass, agent_id=None, insight=_insight(), redactor=redactor
        )

    assert result.success is False
    assert len(result.attempts) == 2
    assert all(a.success is False for a in result.attempts)
    # Bytes_sent should be non-zero on every attempt — the prompt did
    # leave the network even if the call errored.
    assert all(a.bytes_sent > 0 for a in result.attempts)
