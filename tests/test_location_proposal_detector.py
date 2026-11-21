"""Tests for LocationProposalDetector — issue #116 regression coverage.

Issue #116 ("'Location suggestions' seem broken"): users got location
proposals for devices that ALREADY had the recommended area set. Root
cause: the detector resolved an entity's area from the entity registry
entry's `area_id` ONLY. In HA the common way to assign a room is on
the DEVICE — every entity of that device then has `area_id=None` on
its own registry entry but still belongs to the device's area. Those
entities looked "unassigned" to the detector, so it proposed the very
area the device was already in.

The fix resolves the EFFECTIVE area (`entry.area_id or device.area_id`)
via `ctx.hierarchy.area_of` (built by `build_hierarchy` with exactly
that fallback) or, when no hierarchy is attached, by rebuilding the
same mapping from the entity + device registries.

These tests pin both paths:
  - hierarchy path: `ctx.hierarchy.area_of` already resolved (device
    fallback applied by build_hierarchy) — candidate must not fire.
  - fallback path: `ctx.hierarchy=None` + patched HA registries where
    the candidate's entity entry has area_id=None but its DEVICE has
    the area — candidate must not fire (this is the exact #116 repro).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.ha_insights.detectors.base import DetectorContext
from custom_components.ha_insights.detectors.hierarchy import EntityHierarchy
from custom_components.ha_insights.detectors.location_proposal import (
    LocationProposalDetector,
)
from custom_components.ha_insights.insight import InsightKind
from custom_components.ha_insights.observers.state_event_buffer import (
    StateEvent,
    StateEventBuffer,
)

_AREA_LR = "area_living_room"
_AREA_KITCHEN = "area_kitchen"


def _ev(ts: datetime, eid: str, val: str) -> StateEvent:
    return StateEvent(
        timestamp=ts,
        entity_id=eid,
        domain=eid.split(".", 1)[0],
        area_id=None,
        old_state="0",
        new_state=val,
    )


def _seed_correlated(buf: StateEventBuffer, eid: str, n: int = 100) -> None:
    """Seed a smooth diurnal temp curve (varies, so r is defined)."""
    base = datetime.now(tz=UTC) - timedelta(days=5)
    for i in range(n):
        ts = base + timedelta(minutes=i * 30)
        val = 20.0 + (i % 24) * 0.2
        buf.add(_ev(ts, eid, str(val)))


def _seed_uncorrelated(buf: StateEventBuffer, eid: str, n: int = 100) -> None:
    """Seed a pseudo-random stream — high variance, ~0 correlation
    against the smooth `_seed_correlated` curve."""
    base = datetime.now(tz=UTC) - timedelta(days=5)
    for i in range(n):
        ts = base + timedelta(minutes=i * 30)
        val = 20.0 + ((i * 2654435761) % 100) / 10.0
        buf.add(_ev(ts, eid, str(val)))


def _hass_with_device_class(device_classes: dict[str, str]) -> MagicMock:
    """MagicMock hass whose states carry the requested device_class."""
    hass = MagicMock()
    lookup: dict[str, MagicMock] = {}
    for eid, dc in device_classes.items():
        state = MagicMock()
        state.attributes = {"device_class": dc}
        lookup[eid] = state
    hass.states.get = lambda eid: lookup.get(eid)
    return hass


def _make_hierarchy(
    area_of: dict[str, str | None],
    area_names: dict[str, str] | None = None,
    device_classes: dict[str, str] | None = None,
) -> EntityHierarchy:
    return EntityHierarchy(
        area_of=dict(area_of),
        device_class_of=dict(device_classes or {}),
        entities_in_area={},
        area_name_by_id=dict(area_names or {}),
    )


def _patch_registries(monkeypatch: pytest.MonkeyPatch, *, entities, devices, areas):
    """Patch HA's registry `async_get` to return fakes.

    entities: {entity_id: (area_id, device_id)}
    devices:  {device_id: area_id}
    areas:    {area_id: name}
    """
    fake_entries = {
        eid: SimpleNamespace(entity_id=eid, area_id=aid, device_id=did)
        for eid, (aid, did) in entities.items()
    }
    fake_er = SimpleNamespace(
        entities=fake_entries,
        async_get=lambda eid: fake_entries.get(eid),
    )
    fake_devices = {
        did: SimpleNamespace(id=did, area_id=aid) for did, aid in devices.items()
    }
    fake_dr = SimpleNamespace(
        devices=fake_devices,
        async_get=lambda did: fake_devices.get(did),
    )
    fake_areas = {
        aid: SimpleNamespace(name=name) for aid, name in areas.items()
    }
    fake_ar = SimpleNamespace(
        areas=fake_areas,
        async_get_area=lambda aid: fake_areas.get(aid),
    )
    monkeypatch.setattr(
        "homeassistant.helpers.entity_registry.async_get", lambda hass: fake_er
    )
    monkeypatch.setattr(
        "homeassistant.helpers.device_registry.async_get", lambda hass: fake_dr
    )
    monkeypatch.setattr(
        "homeassistant.helpers.area_registry.async_get", lambda hass: fake_ar
    )


_SIBLINGS = ["sensor.temp_living_a", "sensor.temp_living_b"]
_CANDIDATE = "sensor.temp_esp32"  # belongs to a device already in Living Room


def _seed_living_room(buf: StateEventBuffer, candidate: str = _CANDIDATE) -> None:
    for eid in [*_SIBLINGS, candidate]:
        _seed_correlated(buf, eid)


def _dc_map(extra: dict[str, str] | None = None) -> dict[str, str]:
    dc = {eid: "temperature" for eid in [*_SIBLINGS, _CANDIDATE]}
    dc.update(extra or {})
    return dc


# ---------- Issue #116: device-level area inheritance -------------------


@pytest.mark.asyncio
async def test_device_area_inherited_entity_is_not_proposed_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE #116 repro (registry fallback path, hierarchy=None).

    The candidate entity's registry entry has area_id=None, but its
    DEVICE is assigned to Living Room — the standard HA UI flow. The
    entity is effectively already in Living Room, so NO proposal may
    be emitted even though it correlates perfectly with Living Room's
    tagged siblings (it would propose the area it's already in).
    """
    _patch_registries(
        monkeypatch,
        entities={
            # siblings: area set directly on the entity entries
            **{eid: (_AREA_LR, None) for eid in _SIBLINGS},
            # candidate: NO entity-level area, but its device is in LR
            _CANDIDATE: (None, "dev_esp32"),
        },
        devices={"dev_esp32": _AREA_LR},
        areas={_AREA_LR: "Living Room", _AREA_KITCHEN: "Kitchen"},
    )
    buf = StateEventBuffer(max_age=timedelta(days=10))
    _seed_living_room(buf)
    ctx = DetectorContext(
        hass=_hass_with_device_class(_dc_map()), event_buffer=buf, hierarchy=None
    )
    insights = await LocationProposalDetector().scan(ctx)
    assert insights == [], (
        "issue #116: entity whose DEVICE already has the area must not "
        "get a location proposal for that same area"
    )


@pytest.mark.asyncio
async def test_device_area_inherited_entity_is_not_proposed_hierarchy() -> None:
    """Same scenario through the per-scan hierarchy snapshot, which is
    what run_all_detectors attaches in production (build_hierarchy
    already applies the entity→device fallback into area_of)."""
    hierarchy = _make_hierarchy(
        area_of={
            **{eid: _AREA_LR for eid in _SIBLINGS},
            _CANDIDATE: _AREA_LR,  # inherited from dev_esp32
        },
        area_names={_AREA_LR: "Living Room"},
        device_classes={_CANDIDATE: "temperature"},
    )
    buf = StateEventBuffer(max_age=timedelta(days=10))
    _seed_living_room(buf)
    ctx = DetectorContext(
        hass=_hass_with_device_class(_dc_map()), event_buffer=buf, hierarchy=hierarchy
    )
    insights = await LocationProposalDetector().scan(ctx)
    assert insights == []


@pytest.mark.asyncio
async def test_entity_level_area_override_is_not_proposed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Entity with an explicit entity-level area_id is not a candidate
    (pre-existing behaviour, pinned so the fix doesn't regress it)."""
    _patch_registries(
        monkeypatch,
        entities={
            **{eid: (_AREA_LR, None) for eid in _SIBLINGS},
            _CANDIDATE: (_AREA_KITCHEN, "dev_esp32"),  # entity-level override
        },
        devices={"dev_esp32": _AREA_LR},
        areas={_AREA_LR: "Living Room", _AREA_KITCHEN: "Kitchen"},
    )
    buf = StateEventBuffer(max_age=timedelta(days=10))
    _seed_living_room(buf)
    ctx = DetectorContext(
        hass=_hass_with_device_class(_dc_map()), event_buffer=buf, hierarchy=None
    )
    assert await LocationProposalDetector().scan(ctx) == []


# ---------- Positive controls: genuinely unassigned entities still fire --


@pytest.mark.asyncio
async def test_unassigned_entity_is_proposed_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Control for the fallback path: a truly unassigned entity (no
    entity area, no device area) that correlates with Living Room's
    tagged siblings DOES get a proposal for Living Room."""
    _patch_registries(
        monkeypatch,
        entities={
            **{eid: (_AREA_LR, None) for eid in _SIBLINGS},
            _CANDIDATE: (None, None),  # no device, no area — genuinely unassigned
        },
        devices={},
        areas={_AREA_LR: "Living Room"},
    )
    buf = StateEventBuffer(max_age=timedelta(days=10))
    _seed_living_room(buf)
    ctx = DetectorContext(
        hass=_hass_with_device_class(_dc_map()), event_buffer=buf, hierarchy=None
    )
    insights = await LocationProposalDetector().scan(ctx)
    assert len(insights) == 1
    ins = insights[0]
    assert ins.kind == InsightKind.PATTERN_OBSERVATION
    assert ins.detector == "location_proposal"
    assert ins.area_id == _AREA_LR
    assert ins.fingerprint["entity_id"] == _CANDIDATE
    assert ins.fingerprint["area_id"] == _AREA_LR
    proposal = ins.payload["_location_proposal"]
    assert proposal["proposed_area_id"] == _AREA_LR
    assert proposal["proposed_area_name"] == "Living Room"
    assert proposal["median_r"] >= 0.75
    assert "Living Room" in ins.title


@pytest.mark.asyncio
async def test_unassigned_entity_is_proposed_hierarchy() -> None:
    """Control for the hierarchy path: unassigned candidate + tagged
    siblings → one proposal. (On the pre-fix code this path never saw
    the hierarchy and fell through to the entity registry, where a
    mock hass yields a truthy area mock — so this also pins that the
    detector actually consumes ctx.hierarchy.area_of.)"""
    hierarchy = _make_hierarchy(
        area_of={
            **{eid: _AREA_LR for eid in _SIBLINGS},
            _CANDIDATE: None,
        },
        area_names={_AREA_LR: "Living Room"},
    )
    buf = StateEventBuffer(max_age=timedelta(days=10))
    _seed_living_room(buf)
    ctx = DetectorContext(
        hass=_hass_with_device_class(_dc_map()), event_buffer=buf, hierarchy=hierarchy
    )
    insights = await LocationProposalDetector().scan(ctx)
    assert len(insights) == 1
    assert insights[0].payload["_location_proposal"]["proposed_area_id"] == _AREA_LR


@pytest.mark.asyncio
async def test_device_tagged_siblings_count_as_tagged_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sibling side of the fix: siblings whose area comes from
    THEIR device (entity-level area_id=None) must still count as
    already-tagged, otherwise no proposal can ever fire on
    device-tagged rooms. Unassigned candidate correlates with two
    device-tagged Living Room sensors → proposal fires."""
    _patch_registries(
        monkeypatch,
        entities={
            # siblings: area only via their devices
            "sensor.temp_living_a": (None, "dev_hub_a"),
            "sensor.temp_living_b": (None, "dev_hub_b"),
            _CANDIDATE: (None, None),
        },
        devices={"dev_hub_a": _AREA_LR, "dev_hub_b": _AREA_LR},
        areas={_AREA_LR: "Living Room"},
    )
    buf = StateEventBuffer(max_age=timedelta(days=10))
    _seed_living_room(buf)
    ctx = DetectorContext(
        hass=_hass_with_device_class(_dc_map()), event_buffer=buf, hierarchy=None
    )
    insights = await LocationProposalDetector().scan(ctx)
    assert len(insights) == 1
    assert insights[0].payload["_location_proposal"]["proposed_area_id"] == _AREA_LR
    assert insights[0].payload["_location_proposal"]["n_siblings"] == 2


# ---------- Other guards -------------------------------------------------


@pytest.mark.asyncio
async def test_blocked_entity_is_not_proposed() -> None:
    hierarchy = _make_hierarchy(
        area_of={**{eid: _AREA_LR for eid in _SIBLINGS}, _CANDIDATE: None},
        area_names={_AREA_LR: "Living Room"},
    )
    buf = StateEventBuffer(max_age=timedelta(days=10))
    _seed_living_room(buf)
    ctx = DetectorContext(
        hass=_hass_with_device_class(_dc_map()),
        event_buffer=buf,
        hierarchy=hierarchy,
        blocked_entities=frozenset({_CANDIDATE}),
    )
    assert await LocationProposalDetector().scan(ctx) == []


@pytest.mark.asyncio
async def test_uncorrelated_entity_is_not_proposed() -> None:
    hierarchy = _make_hierarchy(
        area_of={**{eid: _AREA_LR for eid in _SIBLINGS}, _CANDIDATE: None},
        area_names={_AREA_LR: "Living Room"},
    )
    buf = StateEventBuffer(max_age=timedelta(days=10))
    for eid in _SIBLINGS:
        _seed_correlated(buf, eid)
    _seed_uncorrelated(buf, _CANDIDATE)
    ctx = DetectorContext(
        hass=_hass_with_device_class(_dc_map()), event_buffer=buf, hierarchy=hierarchy
    )
    assert await LocationProposalDetector().scan(ctx) == []


@pytest.mark.asyncio
async def test_non_sensor_domain_ignored() -> None:
    hierarchy = _make_hierarchy(
        area_of={**{eid: _AREA_LR for eid in _SIBLINGS}, "light.lamp": None},
        area_names={_AREA_LR: "Living Room"},
    )
    buf = StateEventBuffer(max_age=timedelta(days=10))
    for eid in _SIBLINGS:
        _seed_correlated(buf, eid)
    _seed_correlated(buf, "light.lamp")
    ctx = DetectorContext(
        hass=_hass_with_device_class({**_dc_map(), "light.lamp": "temperature"}),
        event_buffer=buf,
        hierarchy=hierarchy,
    )
    # light.* is not in _RELEVANT_DOMAINS → no candidates at all
    assert await LocationProposalDetector().scan(ctx) == []


@pytest.mark.asyncio
async def test_no_event_buffer_returns_empty() -> None:
    ctx = DetectorContext(hass=MagicMock(), event_buffer=None)
    assert await LocationProposalDetector().scan(ctx) == []


@pytest.mark.asyncio
async def test_proposal_is_advisory_and_never_auto_applies() -> None:
    """The insight must stay advisory: payload carries the proposal
    block but no apply artifact / automation is created."""
    hierarchy = _make_hierarchy(
        area_of={**{eid: _AREA_LR for eid in _SIBLINGS}, _CANDIDATE: None},
        area_names={_AREA_LR: "Living Room"},
    )
    buf = StateEventBuffer(max_age=timedelta(days=10))
    _seed_living_room(buf)
    ctx = DetectorContext(
        hass=_hass_with_device_class(_dc_map()), event_buffer=buf, hierarchy=hierarchy
    )
    insights = await LocationProposalDetector().scan(ctx)
    assert len(insights) == 1
    ins = insights[0]
    assert ins.applied_at is None
    assert ins.applied_artifact_id is None
    assert "Advisory only" in ins.explanation
