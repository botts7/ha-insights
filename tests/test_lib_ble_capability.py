"""Tests for lib/ble_capability."""
from __future__ import annotations

from custom_components.ha_insights.lib.ble_capability import (
    BLECapability,
    ble_capability_for,
)


def test_bluetooth_connection_makes_entity_trackable() -> None:
    cap = ble_capability_for(
        "sensor.foo",
        device_connections=[("bluetooth", "AA:BB:CC:DD:EE:FF")],
    )
    assert cap.is_trackable
    assert cap.bluetooth_address == "AA:BB:CC:DD:EE:FF"
    assert cap.seen_by_proxies == []


def test_bluetooth_address_normalized_to_uppercase_colon() -> None:
    """Different integrations report addresses in different formats —
    canonicalize to AA:BB:CC:DD:EE:FF."""
    cap = ble_capability_for(
        "sensor.foo",
        device_connections=[("bluetooth", "aa:bb:cc:dd:ee:ff")],
    )
    assert cap.bluetooth_address == "AA:BB:CC:DD:EE:FF"

    cap2 = ble_capability_for(
        "sensor.foo",
        device_connections=[("bluetooth", "AA-BB-CC-DD-EE-FF")],
    )
    assert cap2.bluetooth_address == "AA:BB:CC:DD:EE:FF"


def test_state_attributes_fallback() -> None:
    """When device registry has no bluetooth connection, fall back to
    state attributes."""
    cap = ble_capability_for(
        "sensor.foo",
        device_connections=[],
        state_attributes={"bluetooth_address": "11:22:33:44:55:66"},
    )
    assert cap.is_trackable
    assert cap.bluetooth_address == "11:22:33:44:55:66"


def test_state_attributes_mac_key_works() -> None:
    cap = ble_capability_for(
        "sensor.foo",
        device_connections=[],
        state_attributes={"mac": "ab:cd:ef:01:23:45"},
    )
    assert cap.bluetooth_address == "AB:CD:EF:01:23:45"


def test_connection_takes_precedence_over_state_attrs() -> None:
    """Connections are authoritative — state attrs only filled when
    connection lookup failed."""
    cap = ble_capability_for(
        "sensor.foo",
        device_connections=[("bluetooth", "AA:11:BB:22:CC:33")],
        state_attributes={"bluetooth_address": "DD:DD:DD:DD:DD:DD"},
    )
    assert cap.bluetooth_address == "AA:11:BB:22:CC:33"


def test_no_ble_address_returns_not_trackable() -> None:
    cap = ble_capability_for(
        "light.living_room",
        device_connections=[("mac", "AA:BB:CC:DD:EE:FF")],  # WiFi MAC, not BLE
        state_attributes={"ip_address": "192.168.1.50"},
    )
    assert not cap.is_trackable
    assert cap.bluetooth_address is None
    assert "no BLE address" in cap.reason


def test_zigbee_ieee_not_treated_as_ble() -> None:
    """Zigbee IEEE addresses are 8 bytes; BLE is 6 bytes. Reject."""
    cap = ble_capability_for(
        "sensor.zha_foo",
        device_connections=[
            ("zigbee", "00:15:8d:00:01:2c:3d:4e"),
        ],
    )
    assert not cap.is_trackable


def test_seen_by_proxies_in_reason_when_present() -> None:
    cap = ble_capability_for(
        "sensor.foo",
        device_connections=[("bluetooth", "AA:BB:CC:DD:EE:FF")],
        seen_by_proxies=["esp_kitchen", "esp_hallway"],
    )
    assert cap.is_trackable
    assert len(cap.seen_by_proxies) == 2
    assert "esp_kitchen" in cap.reason
    assert "2 proxies" in cap.reason


def test_trackable_without_proxies_warns_about_phone() -> None:
    cap = ble_capability_for(
        "sensor.foo",
        device_connections=[("bluetooth", "AA:BB:CC:DD:EE:FF")],
        seen_by_proxies=[],
    )
    assert cap.is_trackable
    assert "companion app" in cap.reason.lower()


def test_one_proxy_pluralization() -> None:
    cap = ble_capability_for(
        "sensor.foo",
        device_connections=[("bluetooth", "AA:BB:CC:DD:EE:FF")],
        seen_by_proxies=["solo_proxy"],
    )
    assert "1 proxy" in cap.reason
    assert "1 proxies" not in cap.reason


def test_garbage_input_does_not_crash() -> None:
    """None-safe defaults — caller might pass empty / missing data."""
    cap = ble_capability_for("sensor.foo")
    assert isinstance(cap, BLECapability)
    assert not cap.is_trackable


def test_short_hex_not_treated_as_address() -> None:
    """3-byte hex (like a partial address) shouldn't pass."""
    cap = ble_capability_for(
        "sensor.foo",
        device_connections=[("bluetooth", "AA:BB:CC")],
    )
    assert not cap.is_trackable
