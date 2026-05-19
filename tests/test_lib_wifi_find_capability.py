"""Tests for lib/wifi_find_capability."""
from __future__ import annotations

from custom_components.ha_insights.lib.wifi_find_capability import (
    WifiFindCapability,
    wifi_find_capability_for,
)


def test_unifi_style_attributes_make_entity_trackable() -> None:
    cap = wifi_find_capability_for(
        "device_tracker.unifi_phone",
        state_attributes={
            "rx_rssi": -52,
            "ap_mac": "aa:bb:cc:dd:ee:ff",
        },
    )
    assert cap.is_trackable
    assert cap.signal_attribute == "rx_rssi"
    assert cap.signal_dbm == -52
    assert cap.ap_attribute == "ap_mac"
    assert cap.ap_identifier == "aa:bb:cc:dd:ee:ff"


def test_asuswrt_style_attributes_also_work() -> None:
    cap = wifi_find_capability_for(
        "device_tracker.phone",
        state_attributes={"signal_strength": -68, "host": "router_living_room"},
    )
    assert cap.is_trackable
    assert cap.signal_attribute == "signal_strength"
    assert cap.ap_attribute == "host"
    assert cap.ap_identifier == "router_living_room"


def test_signal_only_no_ap_is_not_trackable() -> None:
    cap = wifi_find_capability_for(
        "device_tracker.phone",
        state_attributes={"rx_rssi": -50},
    )
    assert not cap.is_trackable
    assert cap.signal_dbm == -50
    assert cap.ap_attribute is None
    assert "no AP identifier" in cap.reason


def test_ap_only_no_signal_is_not_trackable() -> None:
    cap = wifi_find_capability_for(
        "device_tracker.phone",
        state_attributes={"ap_mac": "aa:bb:cc:dd:ee:ff"},
    )
    assert not cap.is_trackable
    assert cap.ap_identifier == "aa:bb:cc:dd:ee:ff"
    assert cap.signal_attribute is None
    assert "no signal-strength reading" in cap.reason


def test_no_recognised_attributes_is_not_trackable() -> None:
    cap = wifi_find_capability_for(
        "device_tracker.phone",
        state_attributes={"some_other_attribute": "value"},
    )
    assert not cap.is_trackable
    assert "no recognised Wi-Fi signal" in cap.reason


def test_zigbee_linkquality_does_not_match() -> None:
    """A Zigbee entity that happens to share the `signal` key name
    but reports a 0-255 linkquality value should NOT be considered
    Wi-Fi-trackable (dBm filter rejects positive >0 readings)."""
    cap = wifi_find_capability_for(
        "sensor.zigbee_temp",
        state_attributes={"signal": 200, "ap_mac": "aa:bb:cc:dd:ee:ff"},
    )
    assert not cap.is_trackable
    assert cap.signal_attribute is None


def test_dbm_range_boundary() -> None:
    """0 dBm is the upper allowed boundary; +1 dBm is rejected."""
    cap_zero = wifi_find_capability_for(
        "device_tracker.test",
        state_attributes={"rssi": 0, "bssid": "aa:bb:cc:dd:ee:ff"},
    )
    assert cap_zero.is_trackable
    assert cap_zero.signal_dbm == 0

    cap_pos = wifi_find_capability_for(
        "device_tracker.test",
        state_attributes={"rssi": 1, "bssid": "aa:bb:cc:dd:ee:ff"},
    )
    assert not cap_pos.is_trackable


def test_priority_signal_attribute_ordering() -> None:
    """When multiple matching keys are present, the most-specific
    (UniFi `rx_rssi`) wins over generic `signal`."""
    cap = wifi_find_capability_for(
        "device_tracker.test",
        state_attributes={
            "signal": -75,
            "rx_rssi": -55,
            "ap_mac": "aa:bb:cc:dd:ee:ff",
        },
    )
    assert cap.signal_attribute == "rx_rssi"
    assert cap.signal_dbm == -55


def test_empty_ap_string_is_not_trackable() -> None:
    cap = wifi_find_capability_for(
        "device_tracker.test",
        state_attributes={"rx_rssi": -55, "ap_mac": "   "},
    )
    assert not cap.is_trackable


def test_garbage_input_does_not_crash() -> None:
    cap = wifi_find_capability_for("device_tracker.test")
    assert isinstance(cap, WifiFindCapability)
    assert not cap.is_trackable


def test_reason_describes_what_was_found() -> None:
    cap = wifi_find_capability_for(
        "device_tracker.test",
        state_attributes={"rx_rssi": -55, "ap_mac": "AP_KITCHEN"},
    )
    assert "-55 dBm" in cap.reason
    assert "AP_KITCHEN" in cap.reason
