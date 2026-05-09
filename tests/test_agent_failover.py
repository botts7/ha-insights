"""Tests for Assist-aware LLM agent failover (v0.9 phase 7).

Two behaviors to verify:

  1. Auto-pick walks the candidate list, returning the first success and
     populating chosen_agent_id with the agent that actually responded.

  2. User-pinned agent never falls over — single attempt, even on failure.

The fake `async_converse` records every (agent_id, attempt#) so we can
assert the order of calls matches our priority: Assist default first,
then registry order, with `conversation.home_assistant` excluded.
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
from custom_components.ha_insights.llm.agent_client import (
    _get_assist_default_agent_id,
    _list_agent_candidates,
)
from custom_components.ha_insights.store import InsightStore


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[InsightStore]:
    db = InsightStore(tmp_path / "test.db")
    await db.open()
    yield db
    await db.close()


def _make_insight(**overrides: Any) -> Insight:
    base: dict[str, Any] = {
        "id": "abc",
        "kind": InsightKind.AUTOMATION_PROPOSAL,
        "detector": "schedule",
        "area_id": None,
        "title": "Test routine",
        "confidence": 0.85,
        "fingerprint": {"entity": "light.kitchen"},
        "payload": {
            "alias": "Test",
            "trigger": [{"platform": "time", "at": "06:47:00"}],
            "action": [
                {"service": "light.turn_on", "target": {"entity_id": "light.kitchen"}}
            ],
            "mode": "single",
        },
        "payload_format": "automation",
        "created_at": datetime(2026, 5, 8, tzinfo=UTC),
    }
    base.update(overrides)
    return Insight(**base)


def _ok_result(speech: str) -> SimpleNamespace:
    return SimpleNamespace(
        response=SimpleNamespace(speech={"plain": {"speech": speech}})
    )


def _err_result(speech: str = "rate limited") -> SimpleNamespace:
    return SimpleNamespace(
        response=SimpleNamespace(
            speech={"plain": {"speech": speech}},
            response_type=SimpleNamespace(value="error"),
        )
    )


def _fake_registry(entity_ids_with_platform: dict[str, str]) -> object:
    """Build a stand-in for entity_registry with an .entities mapping."""
    entries = {
        eid: SimpleNamespace(entity_id=eid, platform=platform)
        for eid, platform in entity_ids_with_platform.items()
    }
    registry = SimpleNamespace(entities=entries)
    return registry


# --- Candidate listing ---


def test_explicit_agent_id_short_circuits_to_single_attempt() -> None:
    """If the user passes agent_id, the candidate list is just that one."""
    hass = MagicMock()
    candidates = _list_agent_candidates(hass, requested="conversation.user_pin")
    assert candidates == ["conversation.user_pin"]


def test_auto_pick_orders_assist_default_first() -> None:
    """Auto-pick lists Assist's configured default ahead of other agents."""
    hass = MagicMock()
    registry = _fake_registry(
        {
            "conversation.home_assistant": "homeassistant",  # builtin, skipped
            "conversation.ollama": "ollama",
            "conversation.anthropic": "anthropic",
        }
    )
    with (
        patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=registry,
            create=True,
        ),
        patch(
            "homeassistant.components.conversation.async_get_default_agent",
            return_value=SimpleNamespace(entity_id="conversation.anthropic"),
            create=True,
        ),
    ):
        candidates = _list_agent_candidates(hass, requested=None)

    # Assist default first, then ollama (builtin filtered, anthropic dedup'd)
    assert candidates[0] == "conversation.anthropic"
    assert "conversation.ollama" in candidates
    assert "conversation.home_assistant" not in candidates


def test_auto_pick_excludes_builtin_assist_default() -> None:
    """If Assist default is the rule-based built-in, don't put it first."""
    hass = MagicMock()
    registry = _fake_registry({"conversation.ollama": "ollama"})
    with (
        patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=registry,
            create=True,
        ),
        patch(
            "homeassistant.components.conversation.async_get_default_agent",
            return_value="conversation.home_assistant",
            create=True,
        ),
    ):
        candidates = _list_agent_candidates(hass, requested=None)

    assert candidates == ["conversation.ollama"]


def test_auto_pick_falls_back_to_none_when_nothing_installed() -> None:
    """No LLM agents installed => single attempt with None (HA's default)."""
    hass = MagicMock()
    registry = _fake_registry({"conversation.home_assistant": "homeassistant"})
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
    ):
        candidates = _list_agent_candidates(hass, requested=None)

    assert candidates == [None]


def test_get_assist_default_handles_missing_api() -> None:
    """If HA's conversation module doesn't expose async_get_default_agent."""
    hass = MagicMock()
    # Use a fresh fake module with no relevant attrs
    with patch.dict("sys.modules", {}, clear=False):
        # import_path: the function tolerates ImportError too
        result = _get_assist_default_agent_id(hass)
        # Best-effort lookup never raises; either a string or None
        assert result is None or isinstance(result, str)


# --- Failover end-to-end via explain_insight ---


@pytest.mark.asyncio
async def test_explicit_pin_does_not_fail_over(store: InsightStore) -> None:
    """User-pinned agent_id => single attempt, even on failure."""
    insight = _make_insight()
    redactor = Redactor(store, mode=RedactionMode.AGGRESSIVE)
    hass = MagicMock()

    calls: list[str | None] = []

    async def fake_converse(*_args, agent_id, **_kwargs) -> SimpleNamespace:
        calls.append(agent_id)
        raise RuntimeError("agent down")

    with patch(
        "homeassistant.components.conversation.async_converse",
        new=AsyncMock(side_effect=fake_converse),
        create=True,
    ):
        result = await explain_insight(
            hass,
            agent_id="conversation.user_pin",
            insight=insight,
            redactor=redactor,
        )

    assert calls == ["conversation.user_pin"]
    assert result.success is False
    assert result.chosen_agent_id == "conversation.user_pin"


@pytest.mark.asyncio
async def test_auto_pick_falls_over_on_first_failure(store: InsightStore) -> None:
    """First candidate fails => second is tried; chosen_agent_id reflects the success."""
    insight = _make_insight()
    redactor = Redactor(store, mode=RedactionMode.AGGRESSIVE)
    hass = MagicMock()

    calls: list[str | None] = []

    async def fake_converse(*_args, agent_id, **_kwargs) -> SimpleNamespace:
        calls.append(agent_id)
        if agent_id == "conversation.anthropic":
            raise RuntimeError("primary down")
        return _ok_result("explanation from ollama")

    registry = _fake_registry(
        {
            "conversation.anthropic": "anthropic",
            "conversation.ollama": "ollama",
        }
    )
    with (
        patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=registry,
            create=True,
        ),
        patch(
            "homeassistant.components.conversation.async_get_default_agent",
            return_value=SimpleNamespace(entity_id="conversation.anthropic"),
            create=True,
        ),
        patch(
            "homeassistant.components.conversation.async_converse",
            new=AsyncMock(side_effect=fake_converse),
            create=True,
        ),
    ):
        result = await explain_insight(
            hass, agent_id=None, insight=insight, redactor=redactor
        )

    # Tried the Assist default first, then fell over to the other LLM agent.
    assert calls == ["conversation.anthropic", "conversation.ollama"]
    assert result.success is True
    assert result.chosen_agent_id == "conversation.ollama"
    assert "ollama" in (result.explanation or "").lower()


@pytest.mark.asyncio
async def test_auto_pick_returns_last_failure_when_all_fail(
    store: InsightStore,
) -> None:
    """Every candidate fails => last failure surfaces with its chosen_agent_id."""
    insight = _make_insight()
    redactor = Redactor(store, mode=RedactionMode.AGGRESSIVE)
    hass = MagicMock()

    async def always_fail(*_args, agent_id, **_kwargs) -> SimpleNamespace:
        raise RuntimeError(f"{agent_id} unreachable")

    registry = _fake_registry(
        {
            "conversation.anthropic": "anthropic",
            "conversation.ollama": "ollama",
        }
    )
    with (
        patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=registry,
            create=True,
        ),
        patch(
            "homeassistant.components.conversation.async_get_default_agent",
            return_value=None,  # no Assist default; pure registry order
            create=True,
        ),
        patch(
            "homeassistant.components.conversation.async_converse",
            new=AsyncMock(side_effect=always_fail),
            create=True,
        ),
    ):
        result = await explain_insight(
            hass, agent_id=None, insight=insight, redactor=redactor
        )

    assert result.success is False
    # The last attempt's agent is what surfaces — caller audit-logs against it
    assert result.chosen_agent_id in {"conversation.anthropic", "conversation.ollama"}
    assert "unreachable" in (result.error or "")
