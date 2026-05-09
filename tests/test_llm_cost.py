"""Tests for the LLM cost estimator (v0.9 phase 1C)."""
from __future__ import annotations

import pytest

from custom_components.ha_insights.llm.cost import estimate_cost


def test_local_agent_is_free() -> None:
    """Local agents (Ollama, default conversation) report $0 always."""
    result = estimate_cost(
        agent_id="conversation.ollama_llama3",
        bytes_sent=20_000,
        bytes_received=5_000,
    )
    assert result["cost_usd"] == 0.0
    assert result["source"] == "local_free"
    # Tokens still counted so users can see local-side throughput
    assert result["tokens_in"] > 0
    assert result["tokens_out"] > 0


def test_local_when_explicit_locality_passed() -> None:
    """Caller-provided locality wins over agent_id heuristic."""
    result = estimate_cost(
        agent_id="conversation.something_anthropic",
        bytes_sent=4000,
        bytes_received=400,
        locality="local",
    )
    assert result["cost_usd"] == 0.0
    assert result["source"] == "local_free"


def test_known_anthropic_model_uses_exact_pricing() -> None:
    """A claude-sonnet-4 marker resolves to its specific price (3/15)."""
    # 4000 bytes ≈ 1000 tokens in, 400 bytes ≈ 100 tokens out
    result = estimate_cost(
        agent_id="conversation.claude-sonnet-4",
        bytes_sent=4000,
        bytes_received=400,
    )
    assert result["source"] == "exact"
    assert result["tokens_in"] == 1000
    assert result["tokens_out"] == 100
    expected = 1000 * 3.0 / 1_000_000 + 100 * 15.0 / 1_000_000
    assert result["cost_usd"] == pytest.approx(expected, abs=1e-4)


def test_opus_priced_higher_than_haiku() -> None:
    """Sanity check on the pricing tiers — opus > sonnet > haiku."""
    payload = {"bytes_sent": 4000, "bytes_received": 4000}
    opus = estimate_cost(agent_id="conversation.claude-opus-4", **payload)
    sonnet = estimate_cost(agent_id="conversation.claude-sonnet-4", **payload)
    haiku = estimate_cost(agent_id="conversation.claude-haiku-4", **payload)
    assert opus["cost_usd"] > sonnet["cost_usd"] > haiku["cost_usd"]


def test_vendor_only_match_uses_default_label() -> None:
    """A bare 'anthropic' substring lands on the generic Sonnet-tier price."""
    result = estimate_cost(
        agent_id="conversation.anthropic_proxy",
        bytes_sent=4000,
        bytes_received=400,
    )
    assert result["source"] == "default"


def test_unknown_cloud_agent_falls_back() -> None:
    """An unrecognized cloud agent reports a fallback estimate, not zero."""
    result = estimate_cost(
        agent_id="conversation.some_random_paid_provider",
        bytes_sent=4000,
        bytes_received=400,
    )
    assert result["source"] == "fallback"
    assert result["cost_usd"] > 0


def test_zero_bytes_yields_zero_tokens() -> None:
    result = estimate_cost(
        agent_id="conversation.claude-sonnet-4",
        bytes_sent=0,
        bytes_received=0,
    )
    assert result["tokens_in"] == 0
    assert result["tokens_out"] == 0
    assert result["cost_usd"] == 0.0


def test_none_agent_id_falls_back_safely() -> None:
    """A null agent_id shouldn't crash — treat as unknown cloud."""
    result = estimate_cost(
        agent_id=None,
        bytes_sent=1000,
        bytes_received=100,
    )
    assert "cost_usd" in result
    assert result["source"] == "fallback"
