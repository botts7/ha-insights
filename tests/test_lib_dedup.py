"""Pure-logic tests for lib/dedup.py.

These don't need HA installed — the dedup helper takes a plain
dict for device_id lookups instead of a hass object. Runs in any
stock Python via `python -m pytest tests/test_lib_dedup.py`.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

# Add the repo root so we can import custom_components.ha_insights.lib
sys.path.insert(0, str(Path(__file__).parent.parent))

# Conftest pulls in pytest_homeassistant_custom_component which needs
# Unix fcntl. Bypass it by disabling the conftest for THIS file.
collect_ignore = []


def _enriched(eid: str, *, n_days: int = 8, kind: str = "anomaly",
              detector: str = "orphan_device") -> dict[str, Any]:
    return {
        "id": f"id-{eid}",
        "kind": kind,
        "detector": detector,
        "title": f"{eid} hasn't reported in {n_days}d. Battery dead?",
        "confidence": 0.57,
        "domain": eid.split(".", 1)[0],
        "_eids_for_dedup": [eid],
    }


def test_collapse_35_same_domain():
    """The user-reported regression: 35 binary_sensor.home_nvr_* rows
    must merge into ONE cohort row with `(+34 similar entities: ...)`
    in the title."""
    from custom_components.ha_insights.lib.dedup import display_time_dedup

    enriched = [
        _enriched(f"binary_sensor.home_nvr_cam{i}_motion")
        for i in range(35)
    ]
    result = display_time_dedup(enriched, {})
    assert len(result) == 1, (
        f"Want 1 cohort row, got {len(result)}. "
        f"Titles: {[r['title'][:60] for r in result[:5]]}"
    )
    rep = result[0]
    assert "similar entities" in rep["title"], rep["title"]
    assert rep["cohort_label"], "cohort_label must be set"
    assert len(rep["cohort_members"]) == 35


def test_mixed_domains_split_into_two_cohorts():
    """35 binary_sensor + 11 switch rows with the same normalized
    title must split per-domain, not bucket together and bail out."""
    from custom_components.ha_insights.lib.dedup import display_time_dedup

    enriched = (
        [_enriched(f"binary_sensor.home_nvr_cam{i}_motion") for i in range(35)]
        + [_enriched(f"switch.home_nvr_profile_{i}") for i in range(11)]
    )
    result = display_time_dedup(enriched, {})
    assert len(result) == 2, (
        f"Want 2 cohorts (one per domain), got {len(result)}: "
        f"{[r['title'][:60] for r in result]}"
    )
    by_domain = {r["domain"]: r for r in result}
    assert by_domain["binary_sensor"]["cohort_members"]
    assert len(by_domain["binary_sensor"]["cohort_members"]) == 35
    assert len(by_domain["switch"]["cohort_members"]) == 11


def test_shared_device_uses_prefix_label():
    """When all entities share the same device_id, the cohort label
    is the longest common entity-id prefix (not the generic
    `domain.* (cohort)` fallback)."""
    from custom_components.ha_insights.lib.dedup import display_time_dedup

    device_map = {
        f"binary_sensor.front_door_zone_{i}": "device-front-door"
        for i in range(5)
    }
    enriched = [
        _enriched(f"binary_sensor.front_door_zone_{i}")
        for i in range(5)
    ]
    result = display_time_dedup(enriched, device_map)
    assert len(result) == 1
    rep = result[0]
    assert rep["cohort_label"] == "binary_sensor.front_door_zone_*", (
        f"want longest-prefix label, got {rep['cohort_label']!r}"
    )


def test_singleton_passes_through_untouched():
    from custom_components.ha_insights.lib.dedup import display_time_dedup

    enriched = [_enriched("light.kitchen")]
    result = display_time_dedup(enriched, {})
    assert len(result) == 1
    assert "_eids_for_dedup" not in result[0]
    assert "similar entities" not in result[0]["title"]
    assert "cohort_label" not in result[0]


def test_different_durations_dont_merge():
    """Two 8d entries + one 14d entry → cohort of 2 + singleton of 1."""
    from custom_components.ha_insights.lib.dedup import display_time_dedup

    enriched = [
        _enriched("binary_sensor.home_nvr_cam1_motion", n_days=8),
        _enriched("binary_sensor.home_nvr_cam2_motion", n_days=8),
        _enriched("binary_sensor.home_nvr_cam99_motion", n_days=14),
    ]
    result = display_time_dedup(enriched, {})
    assert len(result) == 2
    cohort = [r for r in result if "similar" in r["title"]]
    singleton = [r for r in result if "similar" not in r["title"]]
    assert len(cohort) == 1 and len(singleton) == 1
    assert "14d" in singleton[0]["title"]


def test_idempotent_on_re_application():
    """ws_list reapplies dedup every fetch. A second pass on the
    output of the first MUST produce the same result."""
    from custom_components.ha_insights.lib.dedup import display_time_dedup

    enriched = [
        _enriched(f"binary_sensor.home_nvr_cam{i}_motion")
        for i in range(5)
    ]
    pass1 = display_time_dedup(enriched, {})
    pass2 = display_time_dedup(pass1, {})
    assert len(pass1) == len(pass2) == 1
    assert pass1[0]["title"] == pass2[0]["title"], (
        "second pass changed the title — suffix double-append?"
    )


def test_empty_input():
    from custom_components.ha_insights.lib.dedup import display_time_dedup

    assert display_time_dedup([], {}) == []


def test_missing_eids_field_is_safe():
    """Older stored insights might not have _eids_for_dedup. Don't
    crash; treat as singletons."""
    from custom_components.ha_insights.lib.dedup import display_time_dedup

    enriched = [{
        "id": "stale",
        "kind": "anomaly",
        "detector": "orphan_device",
        "title": "Something fell silent",
        "confidence": 0.5,
        "domain": "sensor",
    }]
    result = display_time_dedup(enriched, {})
    assert len(result) == 1


def test_highest_confidence_picked_as_rep():
    """Of a merged bucket, the rep row should be the one with the
    highest confidence — its title (with suffix) is what the user
    sees."""
    from custom_components.ha_insights.lib.dedup import display_time_dedup

    enriched = [
        {**_enriched("binary_sensor.home_nvr_cam1_motion"), "confidence": 0.5},
        {**_enriched("binary_sensor.home_nvr_cam2_motion"), "confidence": 0.9},
        {**_enriched("binary_sensor.home_nvr_cam3_motion"), "confidence": 0.7},
    ]
    result = display_time_dedup(enriched, {})
    assert len(result) == 1
    # The rep should carry the 0.9 row's id
    assert result[0]["id"] == "id-binary_sensor.home_nvr_cam2_motion"


def test_longest_prefix_must_meet_min_length():
    """`light.a` + `light.b` share `light.` prefix but the name part
    is empty/too short — fallback to same-domain label."""
    from custom_components.ha_insights.lib.dedup import display_time_dedup

    device_map = {"light.a": "dev-x", "light.b": "dev-x"}
    enriched = [_enriched("light.a"), _enriched("light.b")]
    result = display_time_dedup(enriched, device_map)
    assert len(result) == 1
    # Single-char names can't form a meaningful prefix → falls back
    # to the `light.* (cohort)` label
    assert "(cohort)" in result[0]["cohort_label"]
