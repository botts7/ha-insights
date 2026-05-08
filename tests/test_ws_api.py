"""Tests for the HA Insights WebSocket API."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_insights.config_flow import CONF_LLM_MODE, LlmMode
from custom_components.ha_insights.const import DOMAIN
from custom_components.ha_insights.insight import Insight, InsightKind
from custom_components.ha_insights.ws_api import (
    INTEGRATION_VERSION,
    SUPPORTED_METHODS,
    WS_PROTOCOL_VERSION,
)


def _make_insight(insight_id: str = "abc123", **overrides) -> Insight:
    base = {
        "id": insight_id,
        "kind": InsightKind.AUTOMATION_PROPOSAL,
        "detector": "schedule",
        "area_id": "area_1",
        "title": "Test routine",
        "confidence": 0.85,
        "fingerprint": {"entity": "light.kitchen"},
        "payload": {"trigger": [{"platform": "time", "at": "06:47:00"}]},
        "payload_format": "automation",
        "created_at": datetime(2026, 5, 8, 12, 0, tzinfo=UTC),
    }
    base.update(overrides)
    return Insight(**base)


@pytest.fixture
async def setup_integration(hass: HomeAssistant) -> MockConfigEntry:
    """Set up a config entry and return it."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_LLM_MODE: LlmMode.OFF.value},
        unique_id=DOMAIN,
        title="HA Insights",
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


# --- hello ---


async def test_hello_handshake(hass: HomeAssistant, hass_ws_client, setup_integration) -> None:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "home_insights/hello"})
    msg = await client.receive_json()
    assert msg["success"] is True
    result = msg["result"]
    assert result["integration_version"] == INTEGRATION_VERSION
    assert result["ws_protocol_version"] == WS_PROTOCOL_VERSION
    assert set(result["supported_methods"]) == set(SUPPORTED_METHODS)


async def test_hello_accepts_card_version(
    hass: HomeAssistant, hass_ws_client, setup_integration
) -> None:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "home_insights/hello", "card_version": "0.1.0-dev"}
    )
    msg = await client.receive_json()
    assert msg["success"] is True


# --- list ---


async def test_list_empty_returns_empty(
    hass: HomeAssistant, hass_ws_client, setup_integration
) -> None:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "home_insights/list"})
    msg = await client.receive_json()
    assert msg["success"] is True
    assert msg["result"]["insights"] == []


async def test_list_returns_added_insight(
    hass: HomeAssistant, hass_ws_client, setup_integration
) -> None:
    store = hass.data[DOMAIN][setup_integration.entry_id]["store"]
    await store.add_insight(_make_insight())

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "home_insights/list"})
    msg = await client.receive_json()
    assert msg["success"] is True
    insights = msg["result"]["insights"]
    assert len(insights) == 1
    assert insights[0]["id"] == "abc123"
    assert insights[0]["title"] == "Test routine"
    assert insights[0]["confidence"] == 0.85


async def test_list_excludes_dismissed_by_default(
    hass: HomeAssistant, hass_ws_client, setup_integration
) -> None:
    store = hass.data[DOMAIN][setup_integration.entry_id]["store"]
    await store.add_insight(_make_insight(insight_id="a", fingerprint={"k": 1}))
    await store.add_insight(_make_insight(insight_id="b", fingerprint={"k": 2}))
    await store.dismiss_insight("a")

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "home_insights/list"})
    msg = await client.receive_json()
    assert {i["id"] for i in msg["result"]["insights"]} == {"b"}


async def test_list_with_include_dismissed(
    hass: HomeAssistant, hass_ws_client, setup_integration
) -> None:
    store = hass.data[DOMAIN][setup_integration.entry_id]["store"]
    await store.add_insight(_make_insight(insight_id="a", fingerprint={"k": 1}))
    await store.dismiss_insight("a")

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "home_insights/list", "include_dismissed": True}
    )
    msg = await client.receive_json()
    assert {i["id"] for i in msg["result"]["insights"]} == {"a"}


# --- dismiss / snooze ---


async def test_dismiss_existing_insight(
    hass: HomeAssistant, hass_ws_client, setup_integration
) -> None:
    store = hass.data[DOMAIN][setup_integration.entry_id]["store"]
    await store.add_insight(_make_insight())

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "home_insights/dismiss", "insight_id": "abc123"}
    )
    msg = await client.receive_json()
    assert msg["success"] is True


async def test_dismiss_unknown_returns_error(
    hass: HomeAssistant, hass_ws_client, setup_integration
) -> None:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "home_insights/dismiss", "insight_id": "nonexistent"}
    )
    msg = await client.receive_json()
    assert msg["success"] is False
    assert msg["error"]["code"] == "not_found"


async def test_snooze_existing_insight(
    hass: HomeAssistant, hass_ws_client, setup_integration
) -> None:
    store = hass.data[DOMAIN][setup_integration.entry_id]["store"]
    await store.add_insight(_make_insight())
    until = (datetime.now(tz=UTC) + timedelta(days=7)).isoformat()

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "home_insights/snooze", "insight_id": "abc123", "until": until}
    )
    msg = await client.receive_json()
    assert msg["success"] is True


async def test_snooze_invalid_timestamp(
    hass: HomeAssistant, hass_ws_client, setup_integration
) -> None:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "home_insights/snooze", "insight_id": "abc123", "until": "not-a-date"}
    )
    msg = await client.receive_json()
    assert msg["success"] is False
    assert msg["error"]["code"] == "invalid_time"


# --- subscribe ---


async def test_subscribe_emits_event_on_add(
    hass: HomeAssistant, hass_ws_client, setup_integration
) -> None:
    """Subscribed clients should receive events when insights are added."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "home_insights/subscribe"})
    msg = await client.receive_json()
    assert msg["success"] is True

    store = hass.data[DOMAIN][setup_integration.entry_id]["store"]
    await store.add_insight(_make_insight(insight_id="evt1", fingerprint={"k": 1}))

    event = await client.receive_json()
    assert event["type"] == "event"
    assert event["event"]["action"] == "added"
    assert event["event"]["insight"]["id"] == "evt1"


async def test_subscribe_emits_event_on_dismiss(
    hass: HomeAssistant, hass_ws_client, setup_integration
) -> None:
    store = hass.data[DOMAIN][setup_integration.entry_id]["store"]
    await store.add_insight(_make_insight(insight_id="evt2", fingerprint={"k": 2}))

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "home_insights/subscribe"})
    await client.receive_json()  # ack

    await store.dismiss_insight("evt2")
    event = await client.receive_json()
    assert event["type"] == "event"
    assert event["event"]["action"] == "dismissed"
    assert event["event"]["insight"]["id"] == "evt2"
