"""Tests for WifiFindDetector — v1.18.

Targets the pure inference helper (`_infer_locations`) so we don't
need to stand up a real HA registry for every assertion. The scan()
wrapper that loads HA registries is a thin layer over the helper —
exercised end-to-end by the integration smoke test below.
"""
from __future__ import annotations

import pytest

from custom_components.ha_insights.detectors.wifi_find import (
    WifiFindDetector,
    WifiFindEntityFacts,
    _infer_locations,
    _resolve_ap,
)
from custom_components.ha_insights.insight import InsightKind


def _facts(
    entity_id: str,
    *,
    area_id: str | None = None,
    rx_rssi: int | None = None,
    ap_mac: str | None = None,
    **extra_attrs: object,
) -> WifiFindEntityFacts:
    attrs: dict = {**extra_attrs}
    if rx_rssi is not None:
        attrs["rx_rssi"] = rx_rssi
    if ap_mac is not None:
        attrs["ap_mac"] = ap_mac
    return WifiFindEntityFacts(
        entity_id=entity_id, area_id=area_id, attributes=attrs
    )


_KITCHEN_AP_MAC = "aa:bb:cc:dd:ee:01"
_LIVING_AP_MAC = "aa:bb:cc:dd:ee:02"

_MAC_TO_DEV = {
    _KITCHEN_AP_MAC: "ap_kitchen_dev",
    _LIVING_AP_MAC: "ap_living_dev",
}
_DEVICE_AREA: dict[str, str | None] = {
    "ap_kitchen_dev": "kitchen",
    "ap_living_dev": "living_room",
}
_DEVICE_NAME = {
    "ap_kitchen_dev": "UniFi AP Kitchen",
    "ap_living_dev": "UniFi AP Living Room",
}
_AREA_NAME_BY_ID = {
    "kitchen": "Kitchen",
    "living_room": "Living Room",
}


def test_unassigned_entity_with_strong_signal_emits_inference() -> None:
    inferences = _infer_locations(
        [_facts("device_tracker.alice_phone", rx_rssi=-45, ap_mac=_KITCHEN_AP_MAC)],
        mac_to_device_id=_MAC_TO_DEV,
        device_area=_DEVICE_AREA,
        device_name=_DEVICE_NAME,
        area_name_by_id=_AREA_NAME_BY_ID,
    )
    assert len(inferences) == 1
    inf = inferences[0]
    assert inf.entity_id == "device_tracker.alice_phone"
    assert inf.proposed_area_id == "kitchen"
    assert inf.proposed_area_name == "Kitchen"
    assert inf.ap_device_id == "ap_kitchen_dev"
    assert inf.confidence == 0.80


def test_signal_below_minus_75_dbm_is_skipped() -> None:
    """-80 dBm: too weak to reliably infer same-area."""
    inferences = _infer_locations(
        [_facts("device_tracker.bob_phone", rx_rssi=-80, ap_mac=_KITCHEN_AP_MAC)],
        mac_to_device_id=_MAC_TO_DEV,
        device_area=_DEVICE_AREA,
        device_name=_DEVICE_NAME,
        area_name_by_id=_AREA_NAME_BY_ID,
    )
    assert inferences == []


def test_entity_already_in_proposed_area_no_inference() -> None:
    inferences = _infer_locations(
        [_facts(
            "device_tracker.alice_phone",
            area_id="kitchen",
            rx_rssi=-50,
            ap_mac=_KITCHEN_AP_MAC,
        )],
        mac_to_device_id=_MAC_TO_DEV,
        device_area=_DEVICE_AREA,
        device_name=_DEVICE_NAME,
        area_name_by_id=_AREA_NAME_BY_ID,
    )
    assert inferences == []


def test_entity_in_different_area_emits_advisory() -> None:
    """Tagged 'bedroom' but currently sees kitchen AP → advisory."""
    inferences = _infer_locations(
        [_facts(
            "device_tracker.alice_phone",
            area_id="bedroom",
            rx_rssi=-50,
            ap_mac=_KITCHEN_AP_MAC,
        )],
        mac_to_device_id=_MAC_TO_DEV,
        device_area=_DEVICE_AREA,
        device_name=_DEVICE_NAME,
        area_name_by_id=_AREA_NAME_BY_ID,
    )
    assert len(inferences) == 1
    inf = inferences[0]
    assert inf.current_area_id == "bedroom"
    assert inf.proposed_area_id == "kitchen"


def test_single_ap_install_emits_nothing() -> None:
    """Only one AP with an area_id → no inference possible.

    The detector would otherwise just propose the same area for
    every Wi-Fi device, which isn't useful."""
    mac_to_dev = {_KITCHEN_AP_MAC: "ap_kitchen_dev"}
    device_area: dict[str, str | None] = {"ap_kitchen_dev": "kitchen"}
    inferences = _infer_locations(
        [_facts("device_tracker.alice_phone", rx_rssi=-45, ap_mac=_KITCHEN_AP_MAC)],
        mac_to_device_id=mac_to_dev,
        device_area=device_area,
        device_name={"ap_kitchen_dev": "Lone AP"},
        area_name_by_id={"kitchen": "Kitchen"},
    )
    assert inferences == []


def test_ap_with_no_area_id_is_skipped() -> None:
    """AP exists in registry but isn't tagged to an area — can't infer."""
    inferences = _infer_locations(
        [_facts("device_tracker.alice_phone", rx_rssi=-45, ap_mac=_LIVING_AP_MAC)],
        mac_to_device_id=_MAC_TO_DEV,
        device_area={"ap_kitchen_dev": "kitchen", "ap_living_dev": None},
        device_name=_DEVICE_NAME,
        area_name_by_id=_AREA_NAME_BY_ID,
    )
    assert inferences == []


def test_unknown_ap_mac_is_skipped() -> None:
    inferences = _infer_locations(
        [_facts(
            "device_tracker.alice_phone",
            rx_rssi=-45,
            ap_mac="ff:ff:ff:ff:ff:ff",
        )],
        mac_to_device_id=_MAC_TO_DEV,
        device_area=_DEVICE_AREA,
        device_name=_DEVICE_NAME,
        area_name_by_id=_AREA_NAME_BY_ID,
    )
    assert inferences == []


def test_blocked_entity_is_skipped() -> None:
    inferences = _infer_locations(
        [_facts("device_tracker.private_phone", rx_rssi=-50, ap_mac=_KITCHEN_AP_MAC)],
        mac_to_device_id=_MAC_TO_DEV,
        device_area=_DEVICE_AREA,
        device_name=_DEVICE_NAME,
        area_name_by_id=_AREA_NAME_BY_ID,
        blocked_entities=frozenset({"device_tracker.private_phone"}),
    )
    assert inferences == []


def test_non_device_tracker_domain_is_skipped() -> None:
    """A `light` entity with `rx_rssi` is a false positive — skip."""
    inferences = _infer_locations(
        [_facts("light.kitchen", rx_rssi=-45, ap_mac=_KITCHEN_AP_MAC)],
        mac_to_device_id=_MAC_TO_DEV,
        device_area=_DEVICE_AREA,
        device_name=_DEVICE_NAME,
        area_name_by_id=_AREA_NAME_BY_ID,
    )
    assert inferences == []


def test_capped_at_max_insights() -> None:
    """Hard cap protects panel from a noisy install."""
    many = [
        _facts(
            f"device_tracker.phone_{i}", rx_rssi=-50, ap_mac=_KITCHEN_AP_MAC
        )
        for i in range(50)
    ]
    inferences = _infer_locations(
        many,
        mac_to_device_id=_MAC_TO_DEV,
        device_area=_DEVICE_AREA,
        device_name=_DEVICE_NAME,
        area_name_by_id=_AREA_NAME_BY_ID,
        max_insights=10,
    )
    assert len(inferences) == 10


def test_confidence_tiers_for_different_signal_strengths() -> None:
    """Verify the dBm → confidence mapping at boundary values."""
    test_cases = [
        (-30, 0.80),   # very close
        (-50, 0.80),   # boundary: very close
        (-51, 0.60),   # one below → probably
        (-65, 0.60),   # boundary: probably
        (-66, 0.45),   # one below → maybe
        (-75, 0.45),   # boundary: maybe
        (-76, None),   # below maybe → skipped
    ]
    for dbm, expected_conf in test_cases:
        inferences = _infer_locations(
            [_facts(
                f"device_tracker.test_{abs(dbm)}",
                rx_rssi=dbm,
                ap_mac=_KITCHEN_AP_MAC,
            )],
            mac_to_device_id=_MAC_TO_DEV,
            device_area=_DEVICE_AREA,
            device_name=_DEVICE_NAME,
            area_name_by_id=_AREA_NAME_BY_ID,
        )
        if expected_conf is None:
            assert inferences == [], f"expected skip for {dbm} dBm"
        else:
            assert len(inferences) == 1, f"expected insight for {dbm} dBm"
            assert inferences[0].confidence == expected_conf, (
                f"wrong confidence for {dbm} dBm"
            )


def test_resolve_ap_via_mac() -> None:
    assert (
        _resolve_ap(
            "AA:BB:CC:DD:EE:01",
            mac_to_device_id=_MAC_TO_DEV,
            device_name=_DEVICE_NAME,
        )
        == "ap_kitchen_dev"
    )


def test_resolve_ap_case_insensitive() -> None:
    assert (
        _resolve_ap(
            _KITCHEN_AP_MAC.upper(),
            mac_to_device_id=_MAC_TO_DEV,
            device_name=_DEVICE_NAME,
        )
        == "ap_kitchen_dev"
    )


def test_resolve_ap_via_name_fallback() -> None:
    """Asuswrt-style host name in attributes; matches device name."""
    assert (
        _resolve_ap(
            "kitchen",
            mac_to_device_id={},  # no MAC mapping
            device_name=_DEVICE_NAME,
        )
        == "ap_kitchen_dev"
    )


def test_resolve_ap_unknown_returns_none() -> None:
    assert (
        _resolve_ap(
            "completely-unknown",
            mac_to_device_id=_MAC_TO_DEV,
            device_name=_DEVICE_NAME,
        )
        is None
    )


# --- Insight construction ----------------------------------------------


def test_build_insight_payload_shape() -> None:
    """End-to-end: helper produces an Inference, detector builds an
    Insight with the v1.18 wifi_find payload shape."""
    detector = WifiFindDetector()
    cap_inference = _infer_locations(
        [_facts(
            "device_tracker.alice_phone",
            rx_rssi=-45,
            ap_mac=_KITCHEN_AP_MAC,
        )],
        mac_to_device_id=_MAC_TO_DEV,
        device_area=_DEVICE_AREA,
        device_name=_DEVICE_NAME,
        area_name_by_id=_AREA_NAME_BY_ID,
    )
    assert len(cap_inference) == 1
    insight = detector._build_insight(cap_inference[0])

    assert insight.kind is InsightKind.PATTERN_OBSERVATION
    assert insight.detector == "wifi_find"
    assert insight.area_id == "kitchen"
    assert insight.payload_format == "card"
    assert insight.confidence == 0.80
    # Payload sanity
    wf = insight.payload["_wifi_find"]
    assert wf["entity_id"] == "device_tracker.alice_phone"
    assert wf["proposed_area_id"] == "kitchen"
    assert wf["proposed_area_name"] == "Kitchen"
    assert wf["ap_device_id"] == "ap_kitchen_dev"
    assert wf["signal_dbm"] == -45
    assert wf["signal_attribute"] == "rx_rssi"
    assert wf["ap_attribute"] == "ap_mac"
    assert wf["confidence_tier"] == "very_close"
    # Title + explanation should mention concrete values, not boilerplate.
    assert "Kitchen" in insight.title
    assert "-45 dBm" in insight.title
    assert "Advisory only" in insight.explanation


def test_fingerprint_stable_across_scans() -> None:
    """Same entity + AP + area = same fingerprint = dedup works."""
    detector = WifiFindDetector()
    inferences = _infer_locations(
        [_facts("device_tracker.alice", rx_rssi=-45, ap_mac=_KITCHEN_AP_MAC)],
        mac_to_device_id=_MAC_TO_DEV,
        device_area=_DEVICE_AREA,
        device_name=_DEVICE_NAME,
        area_name_by_id=_AREA_NAME_BY_ID,
    )
    insight_a = detector._build_insight(inferences[0])
    insight_b = detector._build_insight(inferences[0])
    assert insight_a.id == insight_b.id


# --- scan() smoke test against pytest-homeassistant-custom-component ---


@pytest.mark.asyncio
async def test_scan_with_no_registries_returns_empty(hass) -> None:  # type: ignore[no-untyped-def]
    """An empty HA install — no devices, no entities — produces
    no insights but doesn't crash either."""
    from custom_components.ha_insights.detectors.base import DetectorContext

    ctx = DetectorContext(hass=hass)
    insights = await WifiFindDetector().scan(ctx)
    assert insights == []
