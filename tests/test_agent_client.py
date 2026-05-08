"""Tests for the LLM agent client.

Heavy mocking — we don't actually call any LLM. The point is:
  1. The redactor runs BEFORE the prompt is built
  2. The HA conversation API is called with the redacted prompt
  3. The redaction map deref is applied to the response
  4. Bytes-sent / bytes-received are captured for the audit log
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
    build_explain_prompt,
    explain_insight,
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
        "area_id": "kitchen",
        "title": "On weekdays light.kitchen turns on at 06:47",
        "confidence": 0.85,
        "fingerprint": {"entity": "light.kitchen"},
        "payload": {
            "alias": "Test",
            "trigger": [{"platform": "time", "at": "06:47:00"}],
            "condition": [{"condition": "time", "weekday": ["mon", "tue", "wed"]}],
            "action": [{"service": "light.turn_on", "target": {"entity_id": "light.kitchen"}}],
            "mode": "single",
        },
        "payload_format": "automation",
        "created_at": datetime(2026, 5, 8, tzinfo=UTC),
    }
    base.update(overrides)
    return Insight(**base)


def _mock_conversation_result(speech: str) -> SimpleNamespace:
    """Shape the mock to match HA's ConversationResult `response.speech.plain.speech`."""
    return SimpleNamespace(
        response=SimpleNamespace(speech={"plain": {"speech": speech}})
    )


# --- Prompt building ---


def test_build_prompt_includes_ha_version() -> None:
    insight = _make_insight()
    redacted_payload = insight.payload
    system, _ = build_explain_prompt(insight, redacted_payload, "2025.4.2")
    assert "2025.4.2" in system
    assert "2025.4+" in system  # major-version reference


def test_build_prompt_summarizes_action() -> None:
    insight = _make_insight()
    _, user = build_explain_prompt(insight, insight.payload, "2025.4.2")
    assert "06:47:00" in user
    assert "light.turn_on" in user
    assert "light.kitchen" in user


def test_build_prompt_includes_confidence() -> None:
    insight = _make_insight(confidence=0.85)
    _, user = build_explain_prompt(insight, insight.payload, "2025.4.2")
    assert "85%" in user


# --- explain_insight ---


@pytest.mark.asyncio
async def test_explain_routes_redacted_payload(store: InsightStore) -> None:
    """The agent must receive the redacted text, not the real entity_ids."""
    insight = _make_insight()
    redactor = Redactor(store, mode=RedactionMode.AGGRESSIVE)
    hass = MagicMock()
    hass.config.version = "2025.4.2"

    sent_text: str | None = None

    async def fake_converse(*_args, text: str, **_kwargs) -> SimpleNamespace:
        nonlocal sent_text
        sent_text = text
        return _mock_conversation_result("light.entity_xxx turns on every weekday morning.")

    with patch(
        "homeassistant.components.conversation.async_converse",
        new=AsyncMock(side_effect=fake_converse),
    ):
        result = await explain_insight(
            hass, agent_id="ollama", insight=insight, redactor=redactor
        )

    assert sent_text is not None
    # The real entity_id MUST NOT appear in what was sent
    assert "light.kitchen" not in sent_text
    # A pseudonym should be present
    assert "light.entity_" in sent_text
    assert result.success is True


@pytest.mark.asyncio
async def test_explain_dereferences_response(store: InsightStore) -> None:
    """The LLM response is deref'd back to real entity_ids before display."""
    insight = _make_insight()
    redactor = Redactor(store, mode=RedactionMode.AGGRESSIVE)
    hass = MagicMock()
    hass.config.version = "2025.4.2"

    # Pre-create the pseudonym so we know what to put in the fake response
    pseudonym = await store.get_or_create_pseudonym("light.kitchen")
    fake_speech = f"Every weekday morning, {pseudonym} comes on at 06:47."

    with patch(
        "homeassistant.components.conversation.async_converse",
        new=AsyncMock(return_value=_mock_conversation_result(fake_speech)),
    ):
        result = await explain_insight(
            hass, agent_id="ollama", insight=insight, redactor=redactor
        )

    assert result.success is True
    assert result.explanation is not None
    assert "light.kitchen" in result.explanation  # deref'd back
    assert pseudonym not in result.explanation  # pseudonym replaced


@pytest.mark.asyncio
async def test_explain_records_byte_counts(store: InsightStore) -> None:
    insight = _make_insight()
    redactor = Redactor(store, mode=RedactionMode.AGGRESSIVE)
    hass = MagicMock()
    hass.config.version = "2025.4.2"

    speech = "It runs at 06:47 on weekdays."

    with patch(
        "homeassistant.components.conversation.async_converse",
        new=AsyncMock(return_value=_mock_conversation_result(speech)),
    ):
        result = await explain_insight(
            hass, agent_id="ollama", insight=insight, redactor=redactor
        )

    assert result.bytes_sent > 0
    assert result.bytes_received == len(speech.encode("utf-8"))


@pytest.mark.asyncio
async def test_explain_handles_conversation_failure(store: InsightStore) -> None:
    insight = _make_insight()
    redactor = Redactor(store, mode=RedactionMode.AGGRESSIVE)
    hass = MagicMock()
    hass.config.version = "2025.4.2"

    with patch(
        "homeassistant.components.conversation.async_converse",
        new=AsyncMock(side_effect=RuntimeError("agent down")),
    ):
        result = await explain_insight(
            hass, agent_id="ollama", insight=insight, redactor=redactor
        )

    assert result.success is False
    assert result.explanation is None
    assert "agent down" in (result.error or "")


@pytest.mark.asyncio
async def test_explain_handles_empty_speech(store: InsightStore) -> None:
    insight = _make_insight()
    redactor = Redactor(store, mode=RedactionMode.AGGRESSIVE)
    hass = MagicMock()
    hass.config.version = "2025.4.2"

    empty = SimpleNamespace(response=SimpleNamespace(speech={}))
    with patch(
        "homeassistant.components.conversation.async_converse",
        new=AsyncMock(return_value=empty),
    ):
        result = await explain_insight(
            hass, agent_id="ollama", insight=insight, redactor=redactor
        )

    assert result.success is False
    assert "no speech" in (result.error or "").lower()
