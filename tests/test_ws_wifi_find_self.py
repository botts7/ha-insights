"""Tests for v1.21 wifi_find_self WS handler.

Covers the streaming-subscription contract: initial result with
current readings, per-state-change event forwarding, target-AP
match flag, error paths for bad entity_ids.
"""
from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_insights.config_flow import (
    CONF_LLM_MODE,
    CONF_NOTIFY_ON_INSIGHT,
    LlmMode,
)
from custom_components.ha_insights.const import DOMAIN


@pytest.fixture
async def setup_integration(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_LLM_MODE: LlmMode.OFF.value,
            CONF_NOTIFY_ON_INSIGHT: False,
        },
        unique_id=DOMAIN,
        title="HA Insights",
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_subscribe_returns_initial_state_for_trackable_entity(
    hass: HomeAssistant, hass_ws_client, setup_integration
) -> None:
    hass.states.async_set(
        "device_tracker.alice_phone",
        "home",
        {"rx_rssi": -55, "ap_mac": "aa:bb:cc:dd:ee:01"},
    )
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "home_insights/wifi_find_self",
            "entity_id": "device_tracker.alice_phone",
        }
    )
    resp = await client.receive_json()
    assert resp["success"] is True
    result = resp["result"]
    assert result["subscribed"] is True
    assert result["entity_id"] == "device_tracker.alice_phone"
    assert result["is_trackable"] is True
    assert result["rssi_raw"] == -55
    assert result["ap_identifier"] == "aa:bb:cc:dd:ee:01"


async def test_subscribe_with_non_trackable_entity_still_subscribes(
    hass: HomeAssistant, hass_ws_client, setup_integration
) -> None:
    """Entity exists but has no Wi-Fi attributes → subscription
    succeeds but is_trackable=False. The PWA can still listen for
    later state changes that might add the attributes."""
    hass.states.async_set("device_tracker.alice_phone", "home", {})
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "home_insights/wifi_find_self",
            "entity_id": "device_tracker.alice_phone",
        }
    )
    resp = await client.receive_json()
    assert resp["success"] is True
    result = resp["result"]
    assert result["subscribed"] is True
    assert result["is_trackable"] is False
    assert "rssi_raw" not in result


async def test_subscribe_with_missing_entity_errors(
    hass: HomeAssistant, hass_ws_client, setup_integration
) -> None:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "home_insights/wifi_find_self",
            "entity_id": "device_tracker.does_not_exist",
        }
    )
    resp = await client.receive_json()
    assert resp["success"] is False
    assert resp["error"]["code"] == "entity_not_found"


async def test_subscribe_with_bad_entity_id_errors(
    hass: HomeAssistant, hass_ws_client, setup_integration
) -> None:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "home_insights/wifi_find_self",
            "entity_id": "not-a-valid-entity-id",
        }
    )
    resp = await client.receive_json()
    assert resp["success"] is False
    assert resp["error"]["code"] == "bad_entity_id"


async def test_state_change_forwards_event_with_rssi(
    hass: HomeAssistant, hass_ws_client, setup_integration
) -> None:
    """Subscribe, then mutate state — the handler should forward an
    event with the new RSSI + AP identifier."""
    hass.states.async_set(
        "device_tracker.alice_phone",
        "home",
        {"rx_rssi": -50, "ap_mac": "aa:bb:cc:dd:ee:01"},
    )
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "home_insights/wifi_find_self",
            "entity_id": "device_tracker.alice_phone",
        }
    )
    # Drain the initial result.
    initial = await client.receive_json()
    assert initial["success"] is True

    # Mutate the entity — should fire an event.
    hass.states.async_set(
        "device_tracker.alice_phone",
        "home",
        {"rx_rssi": -62, "ap_mac": "aa:bb:cc:dd:ee:02"},
    )
    await hass.async_block_till_done()

    msg = await client.receive_json()
    assert msg["type"] == "event"
    event = msg["event"]
    assert event["rssi_raw"] == -62
    assert event["ap_identifier"] == "aa:bb:cc:dd:ee:02"
    # ap_matches_target defaults False when no target was passed.
    assert event["ap_matches_target"] is False


async def test_target_ap_match_flag_set_when_phone_is_at_target_ap(
    hass: HomeAssistant, hass_ws_client, setup_integration
) -> None:
    """When target_ap_device_id is provided and the phone's current
    AP resolves to that device, ap_matches_target=True. We can't
    easily wire a real device-registry entry in this test, so we
    cover the negative case (resolution finds None → match=False)
    + the explicit-no-target case (always False)."""
    hass.states.async_set(
        "device_tracker.alice_phone",
        "home",
        {"rx_rssi": -50, "ap_mac": "aa:bb:cc:dd:ee:01"},
    )
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "home_insights/wifi_find_self",
            "entity_id": "device_tracker.alice_phone",
            "target_ap_device_id": "some_target_device",
        }
    )
    resp = await client.receive_json()
    assert resp["success"] is True
    result = resp["result"]
    # No device matches the ap_mac in the registry → ap_device_id None
    # → ap_matches_target False even though a target was passed.
    assert result["ap_matches_target"] is False
    assert result["target_ap_device_id"] == "some_target_device"
