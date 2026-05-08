"""Tests for the WS apply pipeline (apply command + AutomationWriter + applied_history)."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_insights.config_flow import CONF_LLM_MODE, LlmMode
from custom_components.ha_insights.const import DOMAIN
from custom_components.ha_insights.insight import Insight, InsightKind


def _make_insight(insight_id: str = "abc123", **overrides: Any) -> Insight:
    base: dict[str, Any] = {
        "id": insight_id,
        "kind": InsightKind.AUTOMATION_PROPOSAL,
        "detector": "schedule",
        "area_id": "kitchen",
        "title": "Weekday morning routine",
        "confidence": 0.9,
        "fingerprint": {"entity": "light.kitchen"},
        "payload": {
            "alias": "HA Insights: weekday kitchen on",
            "trigger": [{"platform": "time", "at": "06:47:00"}],
            "condition": [{"condition": "time", "weekday": ["mon", "tue"]}],
            "action": [
                {"service": "light.turn_on", "target": {"entity_id": "light.kitchen"}}
            ],
            "mode": "single",
        },
        "payload_format": "automation",
        "created_at": datetime(2026, 5, 8, 12, 0, tzinfo=UTC),
    }
    base.update(overrides)
    return Insight(**base)


@pytest.fixture
async def setup_integration(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_LLM_MODE: LlmMode.OFF.value},
        unique_id=DOMAIN,
        title="HA Insights",
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    # Set up automation component for the storage helper + reload service.
    from homeassistant.setup import async_setup_component

    await async_setup_component(hass, "automation", {})
    await hass.async_block_till_done()
    # The real automation.reload service re-reads configuration.yaml; the
    # pytest-homeassistant testing_config doesn't ship one, so swap in a
    # no-op for tests. In production reload happens normally.
    from homeassistant.core import ServiceCall

    async def _noop_reload(_call: ServiceCall) -> None:
        return None

    hass.services.async_remove("automation", "reload")
    hass.services.async_register("automation", "reload", _noop_reload)
    return entry


async def test_apply_unknown_insight_returns_not_found(
    hass: HomeAssistant, hass_ws_client, setup_integration
) -> None:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "home_insights/apply", "insight_id": "nope"}
    )
    msg = await client.receive_json()
    assert msg["success"] is False
    assert msg["error"]["code"] == "not_found"


async def test_apply_unsupported_format_rejected(
    hass: HomeAssistant, hass_ws_client, setup_integration
) -> None:
    store = hass.data[DOMAIN][setup_integration.entry_id]["store"]
    bad = _make_insight(insight_id="card1", payload_format="card")
    await store.add_insight(bad)

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "home_insights/apply", "insight_id": "card1"}
    )
    msg = await client.receive_json()
    assert msg["success"] is False
    assert msg["error"]["code"] == "unsupported_format"


async def test_apply_invalid_payload_rejected(
    hass: HomeAssistant, hass_ws_client, setup_integration
) -> None:
    store = hass.data[DOMAIN][setup_integration.entry_id]["store"]
    # Payload missing required 'action' field
    bad_payload = {"alias": "broken", "trigger": [{"platform": "time", "at": "06:47"}]}
    bad = _make_insight(insight_id="bad1", payload=bad_payload)
    await store.add_insight(bad)

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "home_insights/apply", "insight_id": "bad1"}
    )
    msg = await client.receive_json()
    assert msg["success"] is False
    assert msg["error"]["code"] == "invalid_payload"


async def test_apply_records_history(
    hass: HomeAssistant, hass_ws_client, setup_integration
) -> None:
    """Successful apply: returns automation_id, records applied_history, marks insight applied."""
    store = hass.data[DOMAIN][setup_integration.entry_id]["store"]
    insight = _make_insight()
    await store.add_insight(insight)

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "home_insights/apply", "insight_id": insight.id}
    )
    msg = await client.receive_json()
    assert msg["success"] is True
    auto_id = msg["result"]["automation_id"]
    assert auto_id.startswith("ha_insights_")

    history = await store.get_applied_history(insight.id)
    assert history is not None
    assert history["artifact_kind"] == "automation"
    assert history["artifact_id"] == auto_id
    assert history["snapshot"]["alias"] == "HA Insights: weekday kitchen on"
    assert isinstance(history["snapshot_hash"], str)
    assert len(history["snapshot_hash"]) == 32

    refreshed = await store.get_insight(insight.id)
    assert refreshed is not None
    # applied_at field is stored separately; check via the list filter
    applied_only = await store.list_insights(include_applied=True)
    assert any(i.id == insight.id for i in applied_only)
