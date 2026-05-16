"""Unit tests for llm/candidate_entities.py — pure-logic, no HA needed.

Verifies the category-priority logic (coactivator > device-mate > area-mate
> domain-sibling), the blocklist contract, the per-category caps, and the
deterministic sorting.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from custom_components.ha_insights.llm.candidate_entities import (
    CandidateEntities,
    CandidateEntity,
    build_candidate_entities,
)


def _fixture_kitchen():
    """A small kitchen with main light + under-cabinet light + ceiling fan.

    Real-world enough to test the area-mate logic, simple enough to read.
    """
    return {
        "required_entity_ids": {"light.kitchen_main"},
        "area_of": {
            "light.kitchen_main": "kitchen",
            "light.kitchen_under_cabinet": "kitchen",
            "fan.kitchen_ceiling": "kitchen",
            "sensor.kitchen_motion": "kitchen",
            "light.living_room": "living",
        },
        "device_of": {
            "light.kitchen_main": "dev_main",
            "light.kitchen_under_cabinet": "dev_uc",
            "fan.kitchen_ceiling": "dev_fan",
            "sensor.kitchen_motion": "dev_motion",
            "light.living_room": "dev_lr",
        },
        "entities_in_area": {
            "kitchen": frozenset({
                "light.kitchen_main",
                "light.kitchen_under_cabinet",
                "fan.kitchen_ceiling",
                "sensor.kitchen_motion",
            }),
            "living": frozenset({"light.living_room"}),
        },
        "entities_on_device": {
            "dev_main": frozenset({"light.kitchen_main"}),
            "dev_uc": frozenset({"light.kitchen_under_cabinet"}),
            "dev_fan": frozenset({"fan.kitchen_ceiling"}),
            "dev_motion": frozenset({"sensor.kitchen_motion"}),
            "dev_lr": frozenset({"light.living_room"}),
        },
    }


def test_area_mates_collected():
    fx = _fixture_kitchen()
    result = build_candidate_entities(**fx)
    eids = [c.entity_id for c in result.area_mates]
    assert "light.kitchen_under_cabinet" in eids
    assert "fan.kitchen_ceiling" in eids
    assert "sensor.kitchen_motion" in eids
    # Required entity is never a candidate
    assert "light.kitchen_main" not in eids
    # Different-area entities are excluded
    assert "light.living_room" not in eids


def test_required_entities_never_appear():
    fx = _fixture_kitchen()
    fx["required_entity_ids"] = {
        "light.kitchen_main",
        "light.kitchen_under_cabinet",
    }
    result = build_candidate_entities(**fx)
    all_candidate_eids = result.all_entity_ids()
    assert "light.kitchen_main" not in all_candidate_eids
    assert "light.kitchen_under_cabinet" not in all_candidate_eids


def test_device_mates_outrank_area_mates():
    """When an entity is both on the same DEVICE and in the same AREA,
    it's categorized as device-mate (stronger signal)."""
    fx = _fixture_kitchen()
    # Put light.kitchen_under_cabinet on the SAME device as the required
    # entity (RGB strip with 2 channels, etc).
    fx["device_of"]["light.kitchen_under_cabinet"] = "dev_main"
    fx["entities_on_device"]["dev_main"] = frozenset({
        "light.kitchen_main",
        "light.kitchen_under_cabinet",
    })

    result = build_candidate_entities(**fx)
    device_mate_eids = [c.entity_id for c in result.device_mates]
    area_mate_eids = [c.entity_id for c in result.area_mates]
    assert "light.kitchen_under_cabinet" in device_mate_eids
    assert "light.kitchen_under_cabinet" not in area_mate_eids


def test_coactivators_outrank_area_mates():
    """Observed co-firing is a stronger signal than topology."""
    fx = _fixture_kitchen()
    result = build_candidate_entities(
        **fx,
        coactivation_days={
            "sensor.kitchen_motion": 12,  # ≥ min_coactivation_days
            "fan.kitchen_ceiling": 2,     # < min, excluded
        },
    )
    coactivator_eids = [c.entity_id for c in result.coactivators]
    area_mate_eids = [c.entity_id for c in result.area_mates]
    # Sensor escalated to coactivator bucket
    assert "sensor.kitchen_motion" in coactivator_eids
    assert "sensor.kitchen_motion" not in area_mate_eids
    # Fan stayed in area-mate bucket (didn't meet min coactivation)
    assert "fan.kitchen_ceiling" in area_mate_eids
    assert "fan.kitchen_ceiling" not in coactivator_eids


def test_blocked_entities_never_appear():
    fx = _fixture_kitchen()
    result = build_candidate_entities(
        **fx,
        blocked_entity_ids={"sensor.kitchen_motion"},
        coactivation_days={"sensor.kitchen_motion": 14},  # would normally surface
    )
    assert "sensor.kitchen_motion" not in result.all_entity_ids()


def test_domain_siblings_when_all_entities_provided():
    fx = _fixture_kitchen()
    result = build_candidate_entities(
        **fx,
        all_entity_ids={
            "light.kitchen_main",
            "light.kitchen_under_cabinet",
            "fan.kitchen_ceiling",
            "sensor.kitchen_motion",
            "light.living_room",
            "light.bedroom_lamp",
            "switch.outlet_a",
        },
    )
    # light.living_room is a same-domain entity not in area or device buckets
    sibling_eids = [c.entity_id for c in result.domain_siblings]
    assert "light.living_room" in sibling_eids
    assert "light.bedroom_lamp" in sibling_eids
    # Different domain (switch.*) is excluded
    assert "switch.outlet_a" not in sibling_eids


def test_domain_siblings_skipped_when_no_all_entities():
    fx = _fixture_kitchen()
    result = build_candidate_entities(**fx)  # no all_entity_ids
    assert result.domain_siblings == []


def test_caps_enforced():
    """With many area-mates available, the cap clips the list."""
    fx = _fixture_kitchen()
    # Pad kitchen with 20 extra entities
    extra = {f"sensor.kitchen_extra_{i}" for i in range(20)}
    fx["entities_in_area"]["kitchen"] = frozenset(
        fx["entities_in_area"]["kitchen"] | extra
    )
    for eid in extra:
        fx["area_of"][eid] = "kitchen"
        fx["device_of"][eid] = f"dev_{eid}"
        fx["entities_on_device"][f"dev_{eid}"] = frozenset({eid})
    result = build_candidate_entities(**fx, caps={"area_mates": 4})
    assert len(result.area_mates) == 4


def test_deterministic_ordering():
    """Successive calls with the same input produce identical lists."""
    fx = _fixture_kitchen()
    r1 = build_candidate_entities(**fx)
    r2 = build_candidate_entities(**fx)
    assert [c.entity_id for c in r1.area_mates] == [
        c.entity_id for c in r2.area_mates
    ]


def test_empty_result_when_no_signals():
    """Required entity with no area, no device, no coactivation, no all_entities."""
    result = build_candidate_entities(
        required_entity_ids={"light.ghost"},
        area_of={"light.ghost": None},
        device_of={"light.ghost": None},
        entities_in_area={},
        entities_on_device={},
    )
    assert result.is_empty
    assert result.total_count == 0


def test_format_for_prompt_renders_categories():
    fx = _fixture_kitchen()
    result = build_candidate_entities(**fx)
    text = result.format_for_prompt()
    assert "light.kitchen_under_cabinet" in text
    assert "same area as light.kitchen_main" in text


def test_format_for_prompt_empty_returns_empty_string():
    empty = CandidateEntities()
    assert empty.format_for_prompt() == ""


def test_multiple_reasons_accumulate():
    """An entity in the same area AS WELL AS the same device of one required
    target — but a coactivator of ANOTHER required target — should land in
    the strongest bucket (coactivator) with at least the coactivator reason."""
    fx = _fixture_kitchen()
    fx["required_entity_ids"] = {"light.kitchen_main", "light.kitchen_under_cabinet"}
    # Make sensor.kitchen_motion a coactivator of one of them
    result = build_candidate_entities(
        **fx,
        coactivation_days={"sensor.kitchen_motion": 10},
    )
    sensor_in_coactivators = [
        c for c in result.coactivators if c.entity_id == "sensor.kitchen_motion"
    ]
    assert len(sensor_in_coactivators) == 1
    reasons = sensor_in_coactivators[0].reasons
    # Should have the area-mate reason AND the coactivator reason
    assert any("same area as" in r for r in reasons)
    assert any("fired within" in r for r in reasons)


def test_cross_domain_flagged_and_deprioritized():
    """The 'don't turn on the TV when everything else is lights' guard.

    A kitchen has 2 lights and 1 media_player. The automation is about
    lights. The media_player is an area-mate, but it's cross-domain.
    Expect: it shows up with a 'different domain' reason tag AND sorts
    AFTER same-domain area-mates.
    """
    result = build_candidate_entities(
        required_entity_ids={"light.kitchen_main"},
        area_of={
            "light.kitchen_main": "kitchen",
            "light.kitchen_under_cabinet": "kitchen",
            "media_player.kitchen_tv": "kitchen",
        },
        device_of={
            "light.kitchen_main": "dev_a",
            "light.kitchen_under_cabinet": "dev_b",
            "media_player.kitchen_tv": "dev_c",
        },
        entities_in_area={
            "kitchen": frozenset({
                "light.kitchen_main",
                "light.kitchen_under_cabinet",
                "media_player.kitchen_tv",
            }),
        },
        entities_on_device={
            "dev_a": frozenset({"light.kitchen_main"}),
            "dev_b": frozenset({"light.kitchen_under_cabinet"}),
            "dev_c": frozenset({"media_player.kitchen_tv"}),
        },
    )
    area_mate_eids = [c.entity_id for c in result.area_mates]
    # The light comes BEFORE the media_player in the sorted list
    assert area_mate_eids.index("light.kitchen_under_cabinet") < area_mate_eids.index(
        "media_player.kitchen_tv"
    )
    # The TV's reasons include the cross-domain tag the LLM can read
    tv_candidate = next(
        c for c in result.area_mates if c.entity_id == "media_player.kitchen_tv"
    )
    assert any("different domain" in r for r in tv_candidate.reasons)
    # The light's reasons do NOT include the cross-domain tag
    light_candidate = next(
        c for c in result.area_mates if c.entity_id == "light.kitchen_under_cabinet"
    )
    assert not any("different domain" in r for r in light_candidate.reasons)


def test_cross_domain_dropped_first_when_cap_hit():
    """When the cap clips the list, cross-domain candidates drop first."""
    area = frozenset({
        "light.kitchen_main",
        "light.kitchen_uc",
        "light.kitchen_pendant",
        "media_player.kitchen_tv",
    })
    result = build_candidate_entities(
        required_entity_ids={"light.kitchen_main"},
        area_of={eid: "kitchen" for eid in area},
        device_of={eid: f"dev_{eid}" for eid in area},
        entities_in_area={"kitchen": area},
        entities_on_device={f"dev_{eid}": frozenset({eid}) for eid in area},
        caps={"area_mates": 2},
    )
    eids = [c.entity_id for c in result.area_mates]
    # Cap is 2; we keep the two LIGHTS (same domain) and drop the TV
    assert len(eids) == 2
    assert "light.kitchen_uc" in eids
    assert "light.kitchen_pendant" in eids
    assert "media_player.kitchen_tv" not in eids


def test_all_entity_ids_returns_union():
    fx = _fixture_kitchen()
    result = build_candidate_entities(
        **fx,
        all_entity_ids={
            "light.kitchen_main",
            "light.kitchen_under_cabinet",
            "fan.kitchen_ceiling",
            "sensor.kitchen_motion",
            "light.living_room",
        },
    )
    union = result.all_entity_ids()
    # Required entity excluded
    assert "light.kitchen_main" not in union
    # Area-mates included
    assert "light.kitchen_under_cabinet" in union
    # Domain-sibling included
    assert "light.living_room" in union
