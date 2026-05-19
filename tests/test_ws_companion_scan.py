"""Tests for the v1.15.0 companion-scan WS handler family.

Covers the subscribe / sample / unsubscribe message types defined in
``find-my-ha/docs/WS_PROTOCOL.md``. Sample threading into the BLE
EMA pipeline is asserted by monkeypatching ``apply_rssi_ema`` —
we don't run the full live-find smoothing here; the EMA primitive
has its own unit test in ``test_lib_ble_capability.py`` already
(and the helper is a pure function).
"""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_insights.config_flow import (
    CONF_LLM_MODE,
    CONF_NOTIFY_ON_INSIGHT,
    LlmMode,
)
from custom_components.ha_insights.const import DOMAIN
from custom_components.ha_insights.ws_api import companion_scan


@pytest.fixture
async def setup_integration(hass: HomeAssistant) -> MockConfigEntry:
    """Set up the integration so ws handlers + audit store are wired."""
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


@pytest.fixture(autouse=True)
def _clear_subscription_registry() -> None:
    """Each test starts with an empty companion-scan registry.

    The registry is a module-level dict (per WS_PROTOCOL.md the
    server keeps one entry per live PWA subscription). Prevents
    cross-test bleed.
    """
    companion_scan._SUBSCRIPTIONS.clear()
    yield
    companion_scan._SUBSCRIPTIONS.clear()


# --- subscribe ---


async def test_subscribe_returns_subscription_id_and_rate_cap(
    hass: HomeAssistant, hass_ws_client, setup_integration
) -> None:
    """Subscribe → reply carries a new uuid and the spec rate cap."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "home_insights/companion_scan_subscribe",
            "entity_id": "binary_sensor.lost_phone",
            "ble_mac": "AA:BB:CC:11:22:33",
        }
    )
    resp = await client.receive_json()
    assert resp["success"] is True
    result = resp["result"]
    assert isinstance(result["subscription_id"], str)
    assert len(result["subscription_id"]) >= 16
    assert result["max_sample_rate_hz"] == companion_scan.MAX_SAMPLE_RATE_HZ


async def test_subscribe_replaces_existing_for_same_user_entity(
    hass: HomeAssistant, hass_ws_client, setup_integration
) -> None:
    """Per spec: second subscribe for same (user, entity) replaces the first."""
    client = await hass_ws_client(hass)
    # First subscribe.
    await client.send_json_auto_id(
        {
            "type": "home_insights/companion_scan_subscribe",
            "entity_id": "binary_sensor.lost_phone",
        }
    )
    resp1 = await client.receive_json()
    sub1 = resp1["result"]["subscription_id"]

    # Second subscribe for same entity → replaces.
    await client.send_json_auto_id(
        {
            "type": "home_insights/companion_scan_subscribe",
            "entity_id": "binary_sensor.lost_phone",
        }
    )
    resp2 = await client.receive_json()
    sub2 = resp2["result"]["subscription_id"]

    assert sub1 != sub2
    assert sub1 not in companion_scan._SUBSCRIPTIONS
    assert sub2 in companion_scan._SUBSCRIPTIONS


# --- sample ---


async def test_sample_with_valid_subscription_threaded_through_ema(
    hass: HomeAssistant, hass_ws_client, setup_integration
) -> None:
    """Valid sample → EMA helper called, RSSI accepted, ack returned."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "home_insights/companion_scan_subscribe",
            "entity_id": "binary_sensor.lost_phone",
        }
    )
    sub_resp = await client.receive_json()
    sub_id = sub_resp["result"]["subscription_id"]

    with patch.object(
        companion_scan, "apply_rssi_ema", return_value=-65.0
    ) as mock_ema:
        await client.send_json_auto_id(
            {
                "type": "home_insights/companion_scan_sample",
                "subscription_id": sub_id,
                "rssi": -67,
                "ts_ms": int(time.time() * 1000),
            }
        )
        # Two messages will come back: an event on the subscribe-msg-id
        # channel (the live update), and the result ack on the sample-
        # msg-id channel. We only assert the ack here; the event ordering
        # is delivery-order-defined and we don't want a flaky test.
        # Collect until we see the success result.
        seen_success = False
        for _ in range(3):
            resp = await client.receive_json()
            if resp.get("type") == "result" and resp.get("success") is True:
                seen_success = True
                break
        assert seen_success
    mock_ema.assert_called_once()
    # Subscription state advanced.
    rec = companion_scan._SUBSCRIPTIONS[sub_id]
    assert rec["samples_accepted"] == 1
    assert rec["ema_value"] == -65.0


async def test_sample_with_bad_subscription_rejected(
    hass: HomeAssistant, hass_ws_client, setup_integration
) -> None:
    """Unknown subscription_id → explicit error."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "home_insights/companion_scan_sample",
            "subscription_id": "deadbeef",
            "rssi": -67,
            "ts_ms": int(time.time() * 1000),
        }
    )
    resp = await client.receive_json()
    assert resp["success"] is False
    assert resp["error"]["code"] == "unknown_subscription"


async def test_sample_with_stale_ts_silently_dropped(
    hass: HomeAssistant, hass_ws_client, setup_integration
) -> None:
    """ts_ms > 60s old → drop silently, ack still returns success."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "home_insights/companion_scan_subscribe",
            "entity_id": "binary_sensor.lost_phone",
        }
    )
    sub_resp = await client.receive_json()
    sub_id = sub_resp["result"]["subscription_id"]

    stale_ts_ms = int((time.time() - 120) * 1000)  # 2 min old
    await client.send_json_auto_id(
        {
            "type": "home_insights/companion_scan_sample",
            "subscription_id": sub_id,
            "rssi": -67,
            "ts_ms": stale_ts_ms,
        }
    )
    resp = await client.receive_json()
    assert resp["success"] is True  # ack ok, drop silent
    rec = companion_scan._SUBSCRIPTIONS[sub_id]
    assert rec["samples_accepted"] == 0
    assert rec["samples_dropped_stale"] == 1


async def test_sample_rate_above_cap_drops_recent_extras(
    hass: HomeAssistant, hass_ws_client, setup_integration
) -> None:
    """Burst of samples above 4 Hz → only the first one in the window passes."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "home_insights/companion_scan_subscribe",
            "entity_id": "binary_sensor.lost_phone",
        }
    )
    sub_resp = await client.receive_json()
    sub_id = sub_resp["result"]["subscription_id"]

    now_ms = int(time.time() * 1000)
    # Send 5 samples back-to-back (no sleeps). All within the 250 ms
    # window → first wins, rest counted as drops.
    for i in range(5):
        await client.send_json_auto_id(
            {
                "type": "home_insights/companion_scan_sample",
                "subscription_id": sub_id,
                "rssi": -60 - i,
                "ts_ms": now_ms,
            }
        )
        # Drain any reply (event + ack)
        for _ in range(2):
            try:
                msg = await client.receive_json()
                if msg.get("type") == "result":
                    break
            except Exception:
                break

    rec = companion_scan._SUBSCRIPTIONS[sub_id]
    assert rec["samples_accepted"] == 1
    assert rec["samples_dropped_rate"] == 4


# --- unsubscribe ---


async def test_unsubscribe_tears_down_subscription(
    hass: HomeAssistant, hass_ws_client, setup_integration
) -> None:
    """Unsubscribe → registry entry removed; subsequent samples rejected."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "home_insights/companion_scan_subscribe",
            "entity_id": "binary_sensor.lost_phone",
        }
    )
    sub_resp = await client.receive_json()
    sub_id = sub_resp["result"]["subscription_id"]
    assert sub_id in companion_scan._SUBSCRIPTIONS

    await client.send_json_auto_id(
        {
            "type": "home_insights/companion_scan_unsubscribe",
            "subscription_id": sub_id,
        }
    )
    resp = await client.receive_json()
    assert resp["success"] is True
    assert sub_id not in companion_scan._SUBSCRIPTIONS

    # Sample after unsubscribe → error.
    await client.send_json_auto_id(
        {
            "type": "home_insights/companion_scan_sample",
            "subscription_id": sub_id,
            "rssi": -67,
            "ts_ms": int(time.time() * 1000),
        }
    )
    resp = await client.receive_json()
    assert resp["success"] is False
    assert resp["error"]["code"] == "unknown_subscription"


async def test_unsubscribe_is_idempotent(
    hass: HomeAssistant, hass_ws_client, setup_integration
) -> None:
    """Second unsubscribe for the same sub_id succeeds silently."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "home_insights/companion_scan_subscribe",
            "entity_id": "binary_sensor.lost_phone",
        }
    )
    sub_resp = await client.receive_json()
    sub_id = sub_resp["result"]["subscription_id"]
    for _ in range(2):
        await client.send_json_auto_id(
            {
                "type": "home_insights/companion_scan_unsubscribe",
                "subscription_id": sub_id,
            }
        )
        resp = await client.receive_json()
        assert resp["success"] is True


# --- connection-close cleanup ---


async def test_connection_close_auto_cleans_subscriptions(
    hass: HomeAssistant, hass_ws_client, setup_integration
) -> None:
    """Closing the WS connection drops all of its subscriptions.

    The registry should be empty (or strictly missing this sub) once
    HA invokes the connection.subscriptions cleanup hook.
    """
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "home_insights/companion_scan_subscribe",
            "entity_id": "binary_sensor.lost_phone",
        }
    )
    sub_resp = await client.receive_json()
    sub_id = sub_resp["result"]["subscription_id"]
    assert sub_id in companion_scan._SUBSCRIPTIONS

    await client.close()
    # Give HA's loop a chance to flush the close handler.
    await hass.async_block_till_done()

    assert sub_id not in companion_scan._SUBSCRIPTIONS


# --- admin gate ---


async def test_subscribe_admin_gated(
    hass: HomeAssistant,
    hass_ws_client,
    hass_admin_user,
    setup_integration,
) -> None:
    """Non-admin users get unauthorized on subscribe.

    Mirrors ws_ble_live_find's gate — streaming subscriptions and
    arbitrary RSSI injection are too sensitive for non-admin users.
    """
    hass_admin_user.groups = []
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "home_insights/companion_scan_subscribe",
            "entity_id": "binary_sensor.lost_phone",
        }
    )
    resp = await client.receive_json()
    assert resp["success"] is False
    assert resp["error"]["code"] == "unauthorized"
