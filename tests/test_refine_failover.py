"""Tests for Refine agent failover (v0.9 phase 8).

Refine's failover is broader than Explain's — it retries on every kind
of post-call failure (parse error, validation error, hallucination,
INSUFFICIENT_BUDGET) because all of those are model-specific and a
different agent may produce a clean response where the previous one
choked.
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
    refine_insight,
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
        "detector": "cooccurrence",
        "area_id": "porch",
        "title": "When binary_sensor.front_door -> on, light.porch turns on",
        "confidence": 0.85,
        "fingerprint": {
            "leader_entity_id": "binary_sensor.front_door",
            "follower_entity_id": "light.porch",
        },
        "payload": {
            "alias": "Porch follow-on",
            "trigger": [
                {
                    "platform": "state",
                    "entity_id": "binary_sensor.front_door",
                    "to": "on",
                }
            ],
            "action": [
                {
                    "service": "light.turn_on",
                    "target": {"entity_id": "light.porch"},
                }
            ],
            "mode": "single",
        },
        "payload_format": "automation",
        "created_at": datetime(2026, 5, 9, tzinfo=UTC),
    }
    base.update(overrides)
    return Insight(**base)


def _ok_response(door_pseudo: str, porch_pseudo: str) -> str:
    return (
        "RATIONALE: Added a 5s debounce.\n"
        "YAML:\n"
        "alias: Porch follow-on\n"
        "trigger:\n"
        f"  - platform: state\n    entity_id: {door_pseudo}\n    to: 'on'\n"
        "    for: '00:00:05'\n"
        "action:\n"
        "  - service: light.turn_on\n"
        f"    target:\n      entity_id: {porch_pseudo}\n"
        "mode: single\n"
    )


def _conv_ok(speech: str) -> SimpleNamespace:
    return SimpleNamespace(
        response=SimpleNamespace(speech={"plain": {"speech": speech}})
    )


def _fake_registry(entity_ids_with_platform: dict[str, str]) -> object:
    entries = {
        eid: SimpleNamespace(entity_id=eid, platform=platform)
        for eid, platform in entity_ids_with_platform.items()
    }
    return SimpleNamespace(entities=entries)


# --- Behavior ---


@pytest.mark.asyncio
async def test_explicit_agent_pin_does_not_fail_over(store: InsightStore) -> None:
    """User-pinned refine: single attempt, even when agent fails."""
    insight = _make_insight()
    redactor = Redactor(store, mode=RedactionMode.AGGRESSIVE)
    hass = MagicMock()

    calls: list[str | None] = []

    async def fake(*_args, agent_id, **_kwargs) -> SimpleNamespace:
        calls.append(agent_id)
        raise RuntimeError("primary down")

    with patch(
        "homeassistant.components.conversation.async_converse",
        new=AsyncMock(side_effect=fake),
        create=True,
    ):
        result = await refine_insight(
            hass,
            agent_id="conversation.user_pin",
            insight=insight,
            redactor=redactor,
        )

    assert calls == ["conversation.user_pin"]
    assert result.success is False
    assert result.chosen_agent_id == "conversation.user_pin"


@pytest.mark.asyncio
async def test_falls_over_on_network_failure(store: InsightStore) -> None:
    """Auto-pick mode: first agent throws, second succeeds with valid YAML."""
    insight = _make_insight()
    redactor = Redactor(store, mode=RedactionMode.AGGRESSIVE)
    hass = MagicMock()

    door_pseudo = await store.get_or_create_pseudonym("binary_sensor.front_door")
    porch_pseudo = await store.get_or_create_pseudonym("light.porch")
    good_yaml = _ok_response(door_pseudo, porch_pseudo)

    calls: list[str | None] = []

    async def fake(*_args, agent_id, **_kwargs) -> SimpleNamespace:
        calls.append(agent_id)
        if agent_id == "conversation.anthropic":
            raise RuntimeError("primary down")
        return _conv_ok(good_yaml)

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
            new=AsyncMock(side_effect=fake),
            create=True,
        ),
    ):
        result = await refine_insight(
            hass, agent_id=None, insight=insight, redactor=redactor
        )

    assert calls == ["conversation.anthropic", "conversation.ollama"]
    assert result.success is True, result.error
    assert result.chosen_agent_id == "conversation.ollama"


@pytest.mark.asyncio
async def test_falls_over_on_parse_failure(store: InsightStore) -> None:
    """First agent emits unparseable garbage, second emits clean YAML.

    This is the case Refine failover most needs to handle — many models
    occasionally emit truncated or malformed YAML even within token
    budget. A second model's attempt is the cheapest fix.
    """
    insight = _make_insight()
    redactor = Redactor(store, mode=RedactionMode.AGGRESSIVE)
    hass = MagicMock()

    door_pseudo = await store.get_or_create_pseudonym("binary_sensor.front_door")
    porch_pseudo = await store.get_or_create_pseudonym("light.porch")
    good_yaml = _ok_response(door_pseudo, porch_pseudo)
    garbage = "RATIONALE: I'll just say no\nYAML:\n: : :\n  not yaml at all"

    calls: list[str | None] = []

    async def fake(*_args, agent_id, **_kwargs) -> SimpleNamespace:
        calls.append(agent_id)
        if agent_id == "conversation.first":
            return _conv_ok(garbage)
        return _conv_ok(good_yaml)

    registry = _fake_registry(
        {
            "conversation.first": "first",
            "conversation.second": "second",
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
            return_value=SimpleNamespace(entity_id="conversation.first"),
            create=True,
        ),
        patch(
            "homeassistant.components.conversation.async_converse",
            new=AsyncMock(side_effect=fake),
            create=True,
        ),
    ):
        result = await refine_insight(
            hass, agent_id=None, insight=insight, redactor=redactor
        )

    # Tried first, fell through to second on parse / validation failure
    assert calls == ["conversation.first", "conversation.second"]
    assert result.success is True, result.error
    assert result.chosen_agent_id == "conversation.second"


@pytest.mark.asyncio
async def test_returns_last_failure_when_all_fail(store: InsightStore) -> None:
    """Every candidate fails => last failure surfaces with chosen_agent_id."""
    insight = _make_insight()
    redactor = Redactor(store, mode=RedactionMode.AGGRESSIVE)
    hass = MagicMock()

    async def fake(*_args, agent_id, **_kwargs) -> SimpleNamespace:
        raise RuntimeError(f"{agent_id} unreachable")

    registry = _fake_registry(
        {
            "conversation.first": "first",
            "conversation.second": "second",
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
            return_value=None,
            create=True,
        ),
        patch(
            "homeassistant.components.conversation.async_converse",
            new=AsyncMock(side_effect=fake),
            create=True,
        ),
    ):
        result = await refine_insight(
            hass, agent_id=None, insight=insight, redactor=redactor
        )

    assert result.success is False
    assert result.chosen_agent_id in {"conversation.first", "conversation.second"}
    assert "unreachable" in (result.error or "")
