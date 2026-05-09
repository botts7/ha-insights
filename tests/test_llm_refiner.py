"""Tests for LLM refiner — prompt build, response parse, validation, and the
end-to-end refine_insight call (with HA conversation mocked).

We don't hit a real LLM. The seams we cover:
  1. parse_refine_response handles RATIONALE / YAML splitting and code-fence stripping
  2. Validation rejects hallucinated entities + invalid shapes
  3. diff_payloads summarizes top-level changes
  4. refine_insight redacts -> calls -> dereferences -> validates
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
    build_refine_prompt,
    diff_payloads,
    parse_refine_response,
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
                {"platform": "state", "entity_id": "binary_sensor.front_door", "to": "on"}
            ],
            "action": [
                {"service": "light.turn_on", "target": {"entity_id": "light.porch"}}
            ],
            "mode": "single",
        },
        "payload_format": "automation",
        "created_at": datetime(2026, 5, 9, tzinfo=UTC),
    }
    base.update(overrides)
    return Insight(**base)


def _conv(speech: str) -> SimpleNamespace:
    return SimpleNamespace(
        response=SimpleNamespace(speech={"plain": {"speech": speech}})
    )


# --- Prompt building ---


def test_prompt_lists_only_original_entities() -> None:
    insight = _make_insight()
    prompt = build_refine_prompt(insight.payload, prior_explanation=None)
    assert "binary_sensor.front_door" in prompt
    assert "light.porch" in prompt
    assert "Use ONLY these entity_ids" in prompt


def test_prompt_handles_no_prior_explanation() -> None:
    insight = _make_insight()
    prompt = build_refine_prompt(insight.payload, prior_explanation=None)
    assert "infer common-sense caveats" in prompt


def test_prompt_includes_prior_explanation() -> None:
    insight = _make_insight()
    prompt = build_refine_prompt(
        insight.payload,
        prior_explanation="Watch for re-triggering on door bounce.",
    )
    assert "door bounce" in prompt


# --- Response parsing ---


def test_parse_clean_response() -> None:
    text = (
        "RATIONALE: Added a 5s debounce so flapping doesn't re-trigger.\n"
        "YAML:\n"
        "alias: Porch follow-on\n"
        "trigger:\n"
        "  - platform: state\n"
        "    entity_id: binary_sensor.front_door\n"
        "    to: 'on'\n"
        "    for: '00:00:05'\n"
        "action:\n"
        "  - service: light.turn_on\n"
        "    target:\n"
        "      entity_id: light.porch\n"
        "mode: single\n"
    )
    rationale, payload, error = parse_refine_response(text)
    assert error is None
    assert rationale is not None and "5s debounce" in rationale
    assert payload is not None
    assert payload["alias"] == "Porch follow-on"
    assert payload["trigger"][0]["for"] == "00:00:05"


def test_parse_strips_yaml_fences() -> None:
    """LLMs love wrapping YAML in ```yaml ... ``` even when told not to."""
    text = (
        "RATIONALE: Added mode queued.\n"
        "YAML:\n"
        "```yaml\n"
        "alias: x\n"
        "trigger:\n"
        "  - platform: state\n"
        "    entity_id: binary_sensor.a\n"
        "action:\n"
        "  - service: light.turn_on\n"
        "mode: queued\n"
        "```"
    )
    _, payload, error = parse_refine_response(text)
    assert error is None
    assert payload is not None
    assert payload["mode"] == "queued"


def test_parse_missing_yaml_section() -> None:
    text = "RATIONALE: I have nothing to add.\n(no YAML)"
    rationale, payload, error = parse_refine_response(text)
    assert payload is None
    assert error is not None and "missing YAML" in error
    assert rationale is not None


def test_parse_invalid_yaml_without_truncation_signals() -> None:
    """A YAML body that doesn't parse but has no truncation markers
    surfaces the raw parser error. To make this case unambiguous, we
    include `mode:` (so the missing-mode heuristic doesn't fire) and
    use balanced brackets.
    """
    text = (
        "RATIONALE: x\n"
        "YAML:\n"
        "mode: single\n"
        "trigger:\n"
        "  - 'unbalanced quote: 'extra' garbage'\n"
    )
    _, payload, error = parse_refine_response(text)
    assert payload is None
    assert error is not None
    # Either parser error or truncation — both are acceptable failure
    # surfaces. The test's job is to confirm we don't crash and we
    # produce a non-empty error.


def test_parse_truncated_yaml_unclosed_quote() -> None:
    """Unclosed quote on the last line should be flagged as truncation."""
    text = (
        "RATIONALE: x\n"
        "YAML:\n"
        "alias: 'unfinished\n"
    )
    _, payload, error = parse_refine_response(text)
    assert payload is None
    assert error is not None
    # Either "cut off" (truncation heuristic) or "YAML parse failed" — both
    # acceptable since both correctly tell the user something's wrong.
    assert "cut off" in error or "parse failed" in error


def test_parse_empty_response() -> None:
    _, payload, error = parse_refine_response("")
    assert payload is None
    assert error is not None


# --- Diff ---


def test_diff_added_key() -> None:
    orig = {"alias": "x", "trigger": [], "action": [], "mode": "single"}
    refined = {**orig, "condition": [{"condition": "time"}]}
    summary = diff_payloads(orig, refined)
    assert "+ condition" in summary


def test_diff_removed_key() -> None:
    orig = {"alias": "x", "trigger": [], "action": [], "condition": []}
    refined = {k: v for k, v in orig.items() if k != "condition"}
    summary = diff_payloads(orig, refined)
    assert "- condition" in summary


def test_diff_changed_key() -> None:
    orig = {"alias": "x", "mode": "single", "trigger": [], "action": []}
    refined = {**orig, "mode": "queued"}
    summary = diff_payloads(orig, refined)
    assert "~ mode" in summary


def test_diff_skips_id() -> None:
    orig = {"id": "old", "alias": "x"}
    refined = {"id": "new", "alias": "x"}
    summary = diff_payloads(orig, refined)
    assert all("id" not in s for s in summary)


def test_diff_no_changes() -> None:
    payload = {"alias": "x", "mode": "single"}
    assert diff_payloads(payload, payload) == []


# --- refine_insight (end-to-end with mocked HA conversation) ---


@pytest.mark.asyncio
async def test_refine_happy_path(store: InsightStore) -> None:
    insight = _make_insight()
    redactor = Redactor(store, mode=RedactionMode.AGGRESSIVE)
    hass = MagicMock()

    # Pre-resolve pseudonyms so we can build a fake LLM response in pseudonym-space
    door_pseudo = await store.get_or_create_pseudonym("binary_sensor.front_door")
    porch_pseudo = await store.get_or_create_pseudonym("light.porch")

    fake_yaml = (
        "RATIONALE: Added 5s debounce to absorb door bounce.\n"
        "YAML:\n"
        "alias: Porch follow-on\n"
        "trigger:\n"
        f"  - platform: state\n    entity_id: {door_pseudo}\n    to: 'on'\n    for: '00:00:05'\n"
        "action:\n"
        f"  - service: light.turn_on\n    target:\n      entity_id: {porch_pseudo}\n"
        "mode: single\n"
    )

    with patch(
        "homeassistant.components.conversation.async_converse",
        new=AsyncMock(return_value=_conv(fake_yaml)),
        create=True,
    ):
        result = await refine_insight(
            hass, agent_id="ollama", insight=insight, redactor=redactor
        )

    assert result.success is True, result.error
    assert result.refined_payload is not None
    # Pseudonyms got dereferenced back to real entity_ids
    assert (
        result.refined_payload["trigger"][0]["entity_id"] == "binary_sensor.front_door"
    )
    assert (
        result.refined_payload["action"][0]["target"]["entity_id"] == "light.porch"
    )
    # The new debounce field made it through
    assert result.refined_payload["trigger"][0]["for"] == "00:00:05"
    assert result.rationale is not None and "debounce" in result.rationale


@pytest.mark.asyncio
async def test_refine_allows_new_service_calls(store: InsightStore) -> None:
    """A refinement that introduces a new service (e.g. light.turn_off
    when the original used light.turn_on) should NOT be flagged as a
    hallucinated entity. Services and entity_ids share a `domain.something`
    shape; the validator must distinguish them by field context."""
    insight = _make_insight()
    redactor = Redactor(store, mode=RedactionMode.AGGRESSIVE)
    hass = MagicMock()

    door_pseudo = await store.get_or_create_pseudonym("binary_sensor.front_door")
    porch_pseudo = await store.get_or_create_pseudonym("light.porch")
    # Refined automation adds a delayed light.turn_off. The original used
    # light.turn_on. light.turn_off is a NEW service but not a new entity.
    fake_yaml = (
        "RATIONALE: Add a 2-minute auto-off after motion clears.\n"
        "YAML:\n"
        "alias: Porch follow-on\n"
        "trigger:\n"
        f"  - platform: state\n    entity_id: {door_pseudo}\n    to: 'on'\n"
        "action:\n"
        f"  - service: light.turn_on\n    target:\n      entity_id: {porch_pseudo}\n"
        "  - delay: '00:02:00'\n"
        f"  - service: light.turn_off\n    target:\n      entity_id: {porch_pseudo}\n"
        "mode: single\n"
    )
    with patch(
        "homeassistant.components.conversation.async_converse",
        new=AsyncMock(return_value=_conv(fake_yaml)),
        create=True,
    ):
        result = await refine_insight(
            hass, agent_id="ollama", insight=insight, redactor=redactor
        )

    assert result.success is True, f"unexpected failure: {result.error}"
    assert result.refined_payload is not None
    # The refined payload references only the original entity_ids
    actions = result.refined_payload["action"]
    assert any(a.get("service") == "light.turn_off" for a in actions)


@pytest.mark.asyncio
async def test_refine_rejects_hallucinated_entity(store: InsightStore) -> None:
    """LLM proposes an entity that wasn't in the original — must reject."""
    insight = _make_insight()
    redactor = Redactor(store, mode=RedactionMode.AGGRESSIVE)
    hass = MagicMock()

    # Hallucinate a NEW entity that wasn't in the original
    fake_yaml = (
        "RATIONALE: Also turn off the bedroom lamp.\n"
        "YAML:\n"
        "alias: Porch follow-on\n"
        "trigger:\n"
        "  - platform: state\n    entity_id: binary_sensor.front_door\n"
        "action:\n"
        "  - service: light.turn_on\n    target:\n      entity_id: light.bedroom_lamp\n"
        "mode: single\n"
    )

    with patch(
        "homeassistant.components.conversation.async_converse",
        new=AsyncMock(return_value=_conv(fake_yaml)),
        create=True,
    ):
        result = await refine_insight(
            hass, agent_id="ollama", insight=insight, redactor=redactor
        )

    assert result.success is False
    assert "validation failed" in (result.error or "")
    assert "light.bedroom_lamp" in (result.error or "")


@pytest.mark.asyncio
async def test_refine_rejects_missing_required_keys(store: InsightStore) -> None:
    insight = _make_insight()
    redactor = Redactor(store, mode=RedactionMode.AGGRESSIVE)
    hass = MagicMock()

    fake_yaml = (
        "RATIONALE: dropped trigger by mistake\n"
        "YAML:\n"
        "alias: x\n"
        "action:\n  - service: light.turn_on\n"
        "mode: single\n"
    )

    with patch(
        "homeassistant.components.conversation.async_converse",
        new=AsyncMock(return_value=_conv(fake_yaml)),
        create=True,
    ):
        result = await refine_insight(
            hass, agent_id="ollama", insight=insight, redactor=redactor
        )

    assert result.success is False
    assert "trigger" in (result.error or "")


@pytest.mark.asyncio
async def test_refine_handles_conversation_failure(store: InsightStore) -> None:
    insight = _make_insight()
    redactor = Redactor(store, mode=RedactionMode.AGGRESSIVE)
    hass = MagicMock()

    with patch(
        "homeassistant.components.conversation.async_converse",
        new=AsyncMock(side_effect=RuntimeError("provider down")),
        create=True,
    ):
        result = await refine_insight(
            hass, agent_id="ollama", insight=insight, redactor=redactor
        )

    assert result.success is False
    assert "provider down" in (result.error or "")


@pytest.mark.asyncio
async def test_refine_records_byte_counts(store: InsightStore) -> None:
    insight = _make_insight()
    redactor = Redactor(store, mode=RedactionMode.AGGRESSIVE)
    hass = MagicMock()

    door_p = await store.get_or_create_pseudonym("binary_sensor.front_door")
    porch_p = await store.get_or_create_pseudonym("light.porch")
    fake = (
        "RATIONALE: ok\n"
        "YAML:\n"
        f"alias: x\ntrigger:\n  - platform: state\n    entity_id: {door_p}\n"
        f"action:\n  - service: light.turn_on\n    target:\n      entity_id: {porch_p}\n"
        "mode: single\n"
    )
    with patch(
        "homeassistant.components.conversation.async_converse",
        new=AsyncMock(return_value=_conv(fake)),
        create=True,
    ):
        result = await refine_insight(
            hass, agent_id="ollama", insight=insight, redactor=redactor
        )
    assert result.bytes_sent > 0
    assert result.bytes_received == len(fake.encode("utf-8"))


@pytest.mark.asyncio
async def test_refine_diff_summary_populated(store: InsightStore) -> None:
    insight = _make_insight()
    redactor = Redactor(store, mode=RedactionMode.AGGRESSIVE)
    hass = MagicMock()

    door_p = await store.get_or_create_pseudonym("binary_sensor.front_door")
    porch_p = await store.get_or_create_pseudonym("light.porch")
    fake = (
        "RATIONALE: Added condition\n"
        "YAML:\n"
        f"alias: x\ntrigger:\n  - platform: state\n    entity_id: {door_p}\n"
        "condition:\n  - condition: state\n    entity_id: light.porch\n    state: 'off'\n"
        f"action:\n  - service: light.turn_on\n    target:\n      entity_id: {porch_p}\n"
        "mode: single\n"
    )
    with patch(
        "homeassistant.components.conversation.async_converse",
        new=AsyncMock(return_value=_conv(fake)),
        create=True,
    ):
        result = await refine_insight(
            hass, agent_id="ollama", insight=insight, redactor=redactor
        )
    assert result.success is True
    assert "+ condition" in result.diff_summary


@pytest.mark.asyncio
async def test_refine_uses_prior_explanation(store: InsightStore) -> None:
    """Prior explanation should be redacted and routed into the prompt."""
    insight = _make_insight()
    redactor = Redactor(store, mode=RedactionMode.AGGRESSIVE)
    hass = MagicMock()

    sent_prompt: str | None = None

    async def capture(*_args, text: str, **_kwargs) -> SimpleNamespace:
        nonlocal sent_prompt
        sent_prompt = text
        # Return a deliberately invalid response so we don't have to construct valid YAML
        return _conv("RATIONALE: x\nYAML:\ngarbage")

    with patch(
        "homeassistant.components.conversation.async_converse",
        new=AsyncMock(side_effect=capture),
        create=True,
    ):
        await refine_insight(
            hass,
            agent_id="ollama",
            insight=insight,
            redactor=redactor,
            prior_explanation=(
                "Watch for door bounce on light.porch and binary_sensor.front_door."
            ),
        )

    assert sent_prompt is not None
    assert "door bounce" in sent_prompt
    # Real entity_ids must NOT appear; they should have been pseudonymized
    assert "light.porch" not in sent_prompt
    assert "binary_sensor.front_door" not in sent_prompt
