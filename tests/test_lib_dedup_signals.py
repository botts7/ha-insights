"""Tests for lib/dedup_signals."""
from __future__ import annotations

from custom_components.ha_insights.lib.dedup_signals import (
    DeviceRecord,
    EntityRecord,
    find_dedup_candidates,
)


def _erec(entity_id: str, device_id: str | None) -> EntityRecord:
    return EntityRecord(entity_id=entity_id, device_id=device_id)


def _drec(
    device_id: str,
    *,
    manufacturer: str | None = None,
    model: str | None = None,
    via_device_id: str | None = None,
    connections: list[tuple[str, str]] | None = None,
    identifiers: list[tuple[str, str]] | None = None,
) -> DeviceRecord:
    return DeviceRecord(
        device_id=device_id,
        manufacturer=manufacturer,
        model=model,
        via_device_id=via_device_id,
        connections=connections or [],
        identifiers=identifiers or [],
    )


# ---------- MAC match ---------------------------------------------------


def test_shared_mac_strongest_signal() -> None:
    entities = {
        "light.tuya_plug": _erec("light.tuya_plug", "dev_tuya"),
        "sensor.ble_plug_power": _erec("sensor.ble_plug_power", "dev_ble"),
    }
    devices = {
        "dev_tuya": _drec("dev_tuya", connections=[("mac", "AA:BB:CC:DD:EE:FF")]),
        "dev_ble": _drec("dev_ble", connections=[("mac", "aa:bb:cc:dd:ee:ff")]),
    }
    results = find_dedup_candidates(
        "light.tuya_plug", entity_records=entities, device_records=devices
    )
    assert len(results) == 1
    assert results[0].entity_id == "sensor.ble_plug_power"
    assert "MAC" in results[0].reason
    assert results[0].confidence == 0.95


def test_mac_case_insensitive() -> None:
    """MACs may be reported in different cases by different integrations."""
    entities = {
        "a": _erec("a", "d1"),
        "b": _erec("b", "d2"),
    }
    devices = {
        "d1": _drec("d1", connections=[("mac", "AA:11:BB:22:CC:33")]),
        "d2": _drec("d2", connections=[("mac", "aa:11:bb:22:cc:33")]),
    }
    assert len(find_dedup_candidates(
        "a", entity_records=entities, device_records=devices
    )) == 1


# ---------- Bluetooth address -------------------------------------------


def test_shared_bluetooth_address() -> None:
    entities = {
        "sensor.govee_temp": _erec("sensor.govee_temp", "dev_cloud"),
        "sensor.govee_ble_temp": _erec("sensor.govee_ble_temp", "dev_ble"),
    }
    devices = {
        "dev_cloud": _drec(
            "dev_cloud", connections=[("bluetooth", "A4:C1:38:11:22:33")]
        ),
        "dev_ble": _drec(
            "dev_ble", connections=[("bluetooth", "A4:C1:38:11:22:33")]
        ),
    }
    results = find_dedup_candidates(
        "sensor.govee_temp",
        entity_records=entities,
        device_records=devices,
    )
    assert results[0].reason.lower().startswith("shared bluetooth")
    assert results[0].confidence == 0.95


# ---------- Zigbee IEEE -------------------------------------------------


def test_shared_zigbee_ieee() -> None:
    entities = {
        "a": _erec("a", "d1"),
        "b": _erec("b", "d2"),
    }
    devices = {
        "d1": _drec("d1", connections=[("zigbee", "00:158d:0001:2c3d4e")]),
        "d2": _drec("d2", connections=[("zigbee", "00:158d:0001:2c3d4e")]),
    }
    results = find_dedup_candidates(
        "a", entity_records=entities, device_records=devices
    )
    assert results[0].reason.lower().startswith("shared zigbee")


# ---------- Identifier overlap (Matter bridging) ------------------------


def test_shared_identifier_overlap() -> None:
    entities = {
        "light.hue_bulb": _erec("light.hue_bulb", "dev_hue"),
        "light.matter_bulb": _erec("light.matter_bulb", "dev_matter"),
    }
    devices = {
        "dev_hue": _drec(
            "dev_hue",
            identifiers=[("hue", "00:17:88:01:02:03:04:05")],
        ),
        "dev_matter": _drec(
            "dev_matter",
            identifiers=[
                ("matter", "abc123"),
                ("hue", "00:17:88:01:02:03:04:05"),
            ],
        ),
    }
    results = find_dedup_candidates(
        "light.hue_bulb",
        entity_records=entities,
        device_records=devices,
    )
    assert len(results) == 1
    assert "hue identifier" in results[0].reason
    assert results[0].confidence == 0.90


# ---------- IP / host attribute -----------------------------------------


def test_shared_ip_address_attribute() -> None:
    entities = {
        "switch.shelly_cloud": _erec("switch.shelly_cloud", "dev_cloud"),
        "sensor.shelly_local_power": _erec(
            "sensor.shelly_local_power", "dev_local"
        ),
    }
    devices = {
        "dev_cloud": _drec("dev_cloud"),
        "dev_local": _drec("dev_local"),
    }
    state_attrs = {
        "switch.shelly_cloud": {"ip_address": "192.168.1.42"},
        "sensor.shelly_local_power": {"host": "192.168.1.42"},
    }
    results = find_dedup_candidates(
        "switch.shelly_cloud",
        entity_records=entities,
        device_records=devices,
        state_attributes=state_attrs,
    )
    assert len(results) == 1
    assert "IP" in results[0].reason
    assert results[0].confidence == 0.75


# ---------- Manufacturer + model + via_device (weak) --------------------


def test_mfr_model_via_match_weak() -> None:
    entities = {
        "a": _erec("a", "d1"),
        "b": _erec("b", "d2"),
    }
    devices = {
        "d1": _drec(
            "d1",
            manufacturer="Signify",
            model="LCT001",
            via_device_id="bridge_1",
        ),
        "d2": _drec(
            "d2",
            manufacturer="Signify",
            model="LCT001",
            via_device_id="bridge_1",
        ),
    }
    results = find_dedup_candidates(
        "a", entity_records=entities, device_records=devices
    )
    assert len(results) == 1
    assert results[0].confidence == 0.55


def test_mfr_model_without_via_does_not_match() -> None:
    """via_device_id must be set on both — otherwise we'd flag every
    pair of identical bulbs as 'same physical device'."""
    entities = {
        "a": _erec("a", "d1"),
        "b": _erec("b", "d2"),
    }
    devices = {
        "d1": _drec("d1", manufacturer="Signify", model="LCT001"),
        "d2": _drec("d2", manufacturer="Signify", model="LCT001"),
    }
    assert find_dedup_candidates(
        "a", entity_records=entities, device_records=devices
    ) == []


# ---------- Negative cases ----------------------------------------------


def test_same_device_id_not_a_duplicate() -> None:
    """Two entities exposing the same device aren't 'duplicate physical
    devices' — HA already treats them as one device."""
    entities = {
        "switch.plug": _erec("switch.plug", "shared_dev"),
        "sensor.plug_power": _erec("sensor.plug_power", "shared_dev"),
    }
    devices = {
        "shared_dev": _drec(
            "shared_dev",
            connections=[("mac", "AA:BB:CC:DD:EE:FF")],
        ),
    }
    assert find_dedup_candidates(
        "switch.plug", entity_records=entities, device_records=devices
    ) == []


def test_no_device_returns_empty() -> None:
    entities = {"sensor.floating": _erec("sensor.floating", None)}
    devices: dict[str, DeviceRecord] = {}
    assert find_dedup_candidates(
        "sensor.floating", entity_records=entities, device_records=devices
    ) == []


def test_no_matching_signals_returns_empty() -> None:
    entities = {
        "a": _erec("a", "d1"),
        "b": _erec("b", "d2"),
    }
    devices = {
        "d1": _drec("d1", connections=[("mac", "11:11:11:11:11:11")]),
        "d2": _drec("d2", connections=[("mac", "22:22:22:22:22:22")]),
    }
    assert find_dedup_candidates(
        "a", entity_records=entities, device_records=devices
    ) == []


# ---------- Output shape ------------------------------------------------


def test_max_candidates_caps_output() -> None:
    """Many duplicates shouldn't flood the response."""
    entities = {"a": _erec("a", "d_a")}
    devices = {
        "d_a": _drec("d_a", connections=[("mac", "00:00:00:00:00:01")]),
    }
    # Add 10 duplicates sharing the same MAC.
    for i in range(10):
        eid = f"dup_{i}"
        did = f"dev_{i}"
        entities[eid] = _erec(eid, did)
        devices[did] = _drec(
            did, connections=[("mac", "00:00:00:00:00:01")]
        )
    results = find_dedup_candidates(
        "a",
        entity_records=entities,
        device_records=devices,
        max_candidates=3,
    )
    assert len(results) == 3


def test_results_sorted_by_confidence_descending() -> None:
    """Strong signals (MAC) should rank above weak ones (mfr/model/via)."""
    entities = {
        "me": _erec("me", "d_me"),
        "mac_dup": _erec("mac_dup", "d_mac"),
        "mfr_dup": _erec("mfr_dup", "d_mfr"),
    }
    devices = {
        "d_me": _drec(
            "d_me",
            connections=[("mac", "AA:BB:CC:DD:EE:FF")],
            manufacturer="X",
            model="Y",
            via_device_id="parent",
        ),
        "d_mac": _drec(
            "d_mac",
            connections=[("mac", "AA:BB:CC:DD:EE:FF")],
        ),
        "d_mfr": _drec(
            "d_mfr",
            manufacturer="X",
            model="Y",
            via_device_id="parent",
        ),
    }
    results = find_dedup_candidates(
        "me", entity_records=entities, device_records=devices
    )
    assert results[0].entity_id == "mac_dup"
    assert results[1].entity_id == "mfr_dup"
    assert results[0].confidence > results[1].confidence
