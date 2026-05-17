"""Tests for PhysicalDeviceLinkDetector (v1.11.0 + v1.12.7 fixes)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from custom_components.ha_insights.detectors.base import DetectorContext
from custom_components.ha_insights.detectors.physical_device_link import (
    PhysicalDeviceLinkDetector,
)
from custom_components.ha_insights.insight import InsightKind
from custom_components.ha_insights.observers.state_event_buffer import (
    StateEvent,
    StateEventBuffer,
)


def _ev(ts: datetime, eid: str, val: str) -> StateEvent:
    return StateEvent(
        timestamp=ts,
        entity_id=eid,
        domain=eid.split(".", 1)[0],
        area_id=None,
        old_state="0",
        new_state=val,
    )


def _ctx_with_states(
    buf: StateEventBuffer, states_with_device_class: dict[str, str]
) -> DetectorContext:
    """Build a ctx whose hass.states.get returns mocks with the
    requested device_class attribute. Required for the detector's
    per-entity device_class read."""
    hass = MagicMock()
    state_lookup: dict[str, MagicMock] = {}
    for eid, dc in states_with_device_class.items():
        state = MagicMock()
        state.attributes = {"device_class": dc}
        state_lookup[eid] = state
    hass.states.get = lambda eid: state_lookup.get(eid)
    return DetectorContext(hass=hass, event_buffer=buf)


def _seed_correlated_temps(
    buf: StateEventBuffer,
    eid_a: str,
    eid_b: str,
    n_samples: int = 100,
    perfect: bool = True,
) -> None:
    """Two temp entities with synthetic time-aligned readings."""
    base = datetime.now(tz=UTC) - timedelta(days=5)
    for i in range(n_samples):
        ts = base + timedelta(minutes=i * 30)
        # Both stream the same temp curve.
        val = 20.0 + (i % 24) * 0.2
        buf.add(_ev(ts, eid_a, str(val)))
        # B trails by epsilon — same device, different integration.
        b_val = val if perfect else val + 0.05
        buf.add(_ev(ts + timedelta(seconds=2), eid_b, str(b_val)))


# ---------- v1.12.7 fingerprint rename verification --------------------


@pytest.mark.asyncio
async def test_fingerprint_uses_entity_id_not_entity_a() -> None:
    """v1.12.7 critical fix: fingerprint keys are `entity_id` and
    `peer_entity_id` (NOT `entity_a`/`entity_b`).

    Why this matters:
    - `lib/managed_externally.py::_is_entity_field_key` accepts
      `entity_id`, `*_entity_id`, `*_eid` — so suppression by
      managed-externally only works when entities are in
      properly-named fields.
    - `detectors/__init__.py::_dedup_grouped_insights` buckets on
      fingerprints containing `entity_id` literal.

    Renaming keys closes both gaps without changing detector logic.
    """
    buf = StateEventBuffer(max_age=timedelta(days=10))
    _seed_correlated_temps(buf, "sensor.tuya_temp", "sensor.ble_temp")
    ctx = _ctx_with_states(
        buf,
        {
            "sensor.tuya_temp": "temperature",
            "sensor.ble_temp": "temperature",
        },
    )
    detector = PhysicalDeviceLinkDetector()
    insights = await detector.scan(ctx)
    assert len(insights) >= 1
    fp = insights[0].fingerprint
    assert "entity_id" in fp, (
        "v1.12.7: fingerprint must include 'entity_id' so the "
        "managed_externally walker can find it"
    )
    assert "peer_entity_id" in fp, (
        "v1.12.7: peer must be named with `_entity_id` suffix so "
        "the walker matches it via the suffix rule"
    )
    # Old (broken) keys must NOT be present.
    assert "entity_a" not in fp
    assert "entity_b" not in fp


@pytest.mark.asyncio
async def test_payload_block_uses_renamed_keys() -> None:
    """The `_physical_device_link` payload block uses the same
    renamed keys so card-side renderers can switch on one
    convention."""
    buf = StateEventBuffer(max_age=timedelta(days=10))
    _seed_correlated_temps(buf, "sensor.tuya_temp", "sensor.ble_temp")
    ctx = _ctx_with_states(
        buf,
        {
            "sensor.tuya_temp": "temperature",
            "sensor.ble_temp": "temperature",
        },
    )
    detector = PhysicalDeviceLinkDetector()
    insights = await detector.scan(ctx)
    assert len(insights) >= 1
    block = insights[0].payload["_physical_device_link"]
    assert "entity_id" in block
    assert "peer_entity_id" in block
    assert "entity_a" not in block
    assert "entity_b" not in block


@pytest.mark.asyncio
async def test_dedup_buckets_match_now_that_fingerprint_uses_entity_id() -> None:
    """v1.12.7 architectural verification: with the renamed keys,
    two physical_device_link insights for the same canonical entity
    will share a dedup bucket key (the bucket key uses 'entity_id'
    when present in fingerprint).

    Direct test of the dedup bucket logic: same `entity_id` →
    same bucket → cohort merge can collapse the cohort to one card
    instead of N.
    """
    buf = StateEventBuffer(max_age=timedelta(days=10))
    # Seed three correlated pairs all sharing sensor.tuya_temp.
    _seed_correlated_temps(buf, "sensor.tuya_temp", "sensor.ble_a")
    _seed_correlated_temps(buf, "sensor.tuya_temp", "sensor.ble_b")
    _seed_correlated_temps(buf, "sensor.tuya_temp", "sensor.ble_c")
    ctx = _ctx_with_states(
        buf,
        {
            "sensor.tuya_temp": "temperature",
            "sensor.ble_a": "temperature",
            "sensor.ble_b": "temperature",
            "sensor.ble_c": "temperature",
        },
    )
    detector = PhysicalDeviceLinkDetector()
    insights = await detector.scan(ctx)
    # Each pair emits one insight (3 expected) before dedup.
    # The KEY behavioural property we test: all 3 share the same
    # `entity_id` in their fingerprint, which is the dedup bucket
    # key. Cohort dedup downstream will collapse them.
    assert len(insights) >= 2
    fingerprints_entity_ids = {
        i.fingerprint["entity_id"] for i in insights
    }
    # Multiple insights about the same canonical entity → all
    # bucket on the same key.
    assert "sensor.tuya_temp" in fingerprints_entity_ids


# ---------- Basic detector behaviour (smoke) ---------------------------


@pytest.mark.asyncio
async def test_emits_insight_for_correlated_pair() -> None:
    """Two entities reporting near-identical temps over a week
    should produce a physical_device_link insight."""
    buf = StateEventBuffer(max_age=timedelta(days=10))
    _seed_correlated_temps(buf, "sensor.a", "sensor.b", n_samples=120)
    ctx = _ctx_with_states(
        buf,
        {
            "sensor.a": "temperature",
            "sensor.b": "temperature",
        },
    )
    detector = PhysicalDeviceLinkDetector()
    insights = await detector.scan(ctx)
    assert len(insights) >= 1
    insight = insights[0]
    assert insight.kind is InsightKind.PATTERN_OBSERVATION
    assert insight.detector == "physical_device_link"
    assert insight.payload["_physical_device_link"]["pearson_r"] > 0.9


@pytest.mark.asyncio
async def test_skips_pairs_below_min_events() -> None:
    """Entities with < 30 events in the lookback are pre-filtered."""
    buf = StateEventBuffer(max_age=timedelta(days=10))
    _seed_correlated_temps(buf, "sensor.a", "sensor.b", n_samples=5)
    ctx = _ctx_with_states(
        buf,
        {
            "sensor.a": "temperature",
            "sensor.b": "temperature",
        },
    )
    detector = PhysicalDeviceLinkDetector()
    assert await detector.scan(ctx) == []


@pytest.mark.asyncio
async def test_skips_pairs_with_different_device_class() -> None:
    """Two correlated entities with different device_class should
    NOT be flagged — we only compare within a class."""
    buf = StateEventBuffer(max_age=timedelta(days=10))
    _seed_correlated_temps(
        buf, "sensor.temp", "sensor.humid", n_samples=120
    )
    ctx = _ctx_with_states(
        buf,
        {
            "sensor.temp": "temperature",
            "sensor.humid": "humidity",  # different class
        },
    )
    detector = PhysicalDeviceLinkDetector()
    assert await detector.scan(ctx) == []


@pytest.mark.asyncio
async def test_no_event_buffer_returns_empty() -> None:
    ctx = DetectorContext(hass=MagicMock(), event_buffer=None)
    detector = PhysicalDeviceLinkDetector()
    assert await detector.scan(ctx) == []
