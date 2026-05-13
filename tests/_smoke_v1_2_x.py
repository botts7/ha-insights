"""v1.2.x smoke test — runs without HA stack on Windows.

Direct-exec style (bypass pytest_homeassistant_custom_component which
needs Unix fcntl). Run: `python tests/_smoke_v1_2_x.py` from repo root.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)
sys.path.insert(0, REPO)

results: list[tuple[str, str, str | None]] = []


def t(name: str):
    def deco(fn):
        try:
            fn()
            results.append((name, "PASS", None))
        except AssertionError as e:
            results.append((name, "FAIL", str(e)))
        except Exception as e:  # noqa: BLE001
            results.append((name, "ERROR", f"{type(e).__name__}: {e}"))
        return fn
    return deco


def _load(name: str, path: str):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)  # type: ignore[union-attr]
    return m


# ---- Pure-logic: lib/dedup ----

dedup = _load("dedup", "custom_components/ha_insights/lib/dedup.py")
display_time_dedup = dedup.display_time_dedup


def _enriched(eid: str, *, n_days: int = 8, kind: str = "anomaly",
              detector: str = "orphan_device") -> dict:
    return {
        "id": f"id-{eid}", "kind": kind, "detector": detector,
        "title": f"{eid} hasn't reported in {n_days}d. Battery dead?",
        "confidence": 0.57, "domain": eid.split(".", 1)[0],
        "_eids_for_dedup": [eid],
    }


@t("dedup: 35 same-domain collapse to 1")
def _():
    enriched = [_enriched(f"binary_sensor.home_nvr_cam{i}_motion") for i in range(35)]
    r = display_time_dedup(enriched, {})
    assert len(r) == 1
    assert "similar entities" in r[0]["title"]


@t("dedup: 34 real home_nvr names collapse to 1")
def _():
    names = [
        "front_garden_dio", "front_garden_external", "front_garden_motion",
        "garage_dio", "garage_external", "garage_motion",
        "porch_dio", "porch_external", "porch_motion",
        "backyard_2_dio", "backyard_2_external", "backyard_2_motion",
        "backyard_dio", "backyard_external", "backyard_motion",
        "driveway_dio", "driveway_external", "driveway_motion",
        "north_side_dio", "north_side_external", "north_side_motion",
        "south_side_dio", "south_side_external", "south_side_motion",
        "alfresco_dio", "alfresco_external", "alfresco_motion",
        "lounge_dio", "lounge_external", "lounge_motion",
        "front_door_bell_audio", "front_door_bell_dio",
        "front_door_bell_external", "front_door_bell_motion",
    ]
    enriched = [_enriched(f"binary_sensor.home_nvr_{n}", n_days=9) for n in names]
    r = display_time_dedup(enriched, {})
    assert len(r) == 1, f"got {len(r)}"


@t("dedup: mixed-domain bucket splits 35+11")
def _():
    enriched = (
        [_enriched(f"binary_sensor.home_nvr_cam{i}_motion") for i in range(35)]
        + [_enriched(f"switch.home_nvr_profile_{i}") for i in range(11)]
    )
    r = display_time_dedup(enriched, {})
    assert len(r) == 2, f"got {len(r)}"


@t("dedup: lowercase kind buckets together (case-resilience fix)")
def _():
    a = _enriched("binary_sensor.home_nvr_cam1_motion"); a["kind"] = "ANOMALY"
    b = _enriched("binary_sensor.home_nvr_cam2_motion"); b["kind"] = "anomaly"
    r = display_time_dedup([a, b], {})
    assert len(r) == 1, f"got {len(r)}"


@t("dedup: idempotent on second pass")
def _():
    enriched = [_enriched(f"binary_sensor.cam{i}") for i in range(5)]
    p1 = display_time_dedup(enriched, {})
    p2 = display_time_dedup(p1, {})
    assert len(p1) == len(p2) == 1
    assert p1[0]["title"] == p2[0]["title"]


@t("dedup: highest confidence picked as rep")
def _():
    a = _enriched("binary_sensor.cam1"); a["confidence"] = 0.5
    b = _enriched("binary_sensor.cam2"); b["confidence"] = 0.9
    c = _enriched("binary_sensor.cam3"); c["confidence"] = 0.7
    r = display_time_dedup([a, b, c], {})
    assert len(r) == 1 and r[0]["id"] == "id-binary_sensor.cam2"


@t("dedup: shared device gives prefix label")
def _():
    dm = {f"binary_sensor.front_door_zone_{i}": "dev-fd" for i in range(5)}
    e = [_enriched(f"binary_sensor.front_door_zone_{i}") for i in range(5)]
    r = display_time_dedup(e, dm)
    assert len(r) == 1
    assert r[0]["cohort_label"] == "binary_sensor.front_door_zone_*"


@t("dedup: singleton passes through")
def _():
    r = display_time_dedup([_enriched("light.kitchen")], {})
    assert len(r) == 1
    assert "_eids_for_dedup" not in r[0]
    assert "cohort_label" not in r[0]


@t("dedup: different durations stay separate")
def _():
    e = [
        _enriched("binary_sensor.cam1", n_days=8),
        _enriched("binary_sensor.cam2", n_days=8),
        _enriched("binary_sensor.cam3", n_days=14),
    ]
    r = display_time_dedup(e, {})
    assert len(r) == 2


@t("dedup: empty input")
def _():
    assert display_time_dedup([], {}) == []


@t("dedup: missing _eids_for_dedup is safe")
def _():
    e = [{"id": "x", "kind": "anomaly", "detector": "orphan_device",
          "title": "lost", "confidence": 0.5, "domain": "sensor"}]
    r = display_time_dedup(e, {})
    assert len(r) == 1


# ---- Source-level guards (regressions we never want to ship again) ----

@t("audit: fingerprint excludes observation_kinds (duplicate-rows regression)")
def _():
    with open("custom_components/ha_insights/detectors/automation_audit.py", encoding="utf-8") as f:
        src = f.read()
    block = src.split("fingerprint: dict[str, Any] = {")[1].split("}")[0]
    assert "observation_kinds" not in block, (
        "observation_kinds re-added to audit fingerprint — would cause "
        "the v1.2.0 duplicate-audit-row regression"
    )


@t("audit rollup: min window guards present")
def _():
    src = open("custom_components/ha_insights/audit/rollup.py", encoding="utf-8").read()
    assert "_MIN_WINDOW_FOR_DOW = 28" in src
    assert "_MIN_WINDOW_FOR_DOM = 60" in src
    assert "_MIN_WINDOW_FOR_MOY = 365" in src


@t("repairs: clear NOT in unload_entry, IS in remove_entry")
def _():
    src = open("custom_components/ha_insights/__init__.py", encoding="utf-8").read()
    assert "async def async_remove_entry" in src
    unload_start = src.find("async def async_unload_entry")
    remove_start = src.find("async def async_remove_entry")
    unload_body = src[unload_start:remove_start]
    assert "clear_all_audit_issues" not in unload_body, (
        "unload_entry still clears Repairs — would wipe on every restart"
    )
    remove_body = src[remove_start:remove_start + 2000]
    assert "clear_all_audit_issues" in remove_body


@t("repairs: setup-time restore wired")
def _():
    src = open("custom_components/ha_insights/__init__.py", encoding="utf-8").read()
    assert "_restore_repairs_on_boot" in src


@t("translations: audit_finding title has unquoted {automation}")
def _():
    j = json.load(open("custom_components/ha_insights/translations/en.json"))
    title = j["issues"]["audit_finding"]["title"]
    assert "{automation}" in title
    assert "'{automation}'" not in title, (
        f"single-quoted placeholder reintroduced: {title!r}"
    )


@t("translations: 4 audit options present in OptionsFlow strings")
def _():
    j = json.load(open("custom_components/ha_insights/translations/en.json"))
    data = j["options"]["step"]["init"]["data"]
    for key in (
        "audit_rollup_window_days",
        "audit_analysis_depth",
        "audit_monthly_budget_usd",
        "audit_auto_rollup_enabled",
    ):
        assert key in data, f"missing translation: {key}"


@t("version: INTEGRATION_VERSION read dynamically from manifest")
def _():
    src = open("custom_components/ha_insights/ws_api.py", encoding="utf-8").read()
    assert "_get_integration_version" in src
    assert "async_get_integration" in src


@t("manifest: at v1.2.0")
def _():
    m = json.load(open("custom_components/ha_insights/manifest.json"))
    assert m["version"] == "1.2.0", f'manifest version {m["version"]} != 1.2.0'


@t("card: refresh-from-event handler exists")
def _():
    src = open("../ha-insights-card/src/ha-insights-card.ts", encoding="utf-8").read()
    assert "_refreshFromEvent" in src
    assert "ha-insights-refresh" in src


@t("panel: dispatches refresh after Scan/Purge/Backfill")
def _():
    src = open("../ha-insights-card/src/ha-insights-panel.ts", encoding="utf-8").read()
    count = src.count("ha-insights-refresh")
    assert count >= 3, f"only {count} dispatches found"


@t("ManualHabit: detector invariants present")
def _():
    src = open(
        "custom_components/ha_insights/detectors/manual_habit.py",
        encoding="utf-8",
    ).read()
    # 5+ days bar
    assert "_MIN_MANUAL_DAYS = 5" in src
    # Tolerance for manual time variance — relaxed because humans
    # don't act at the same minute every day
    assert "_TIME_STDDEV_MAX_MIN = 45.0" in src
    # Cross-reference bucket widened so habit at 07:42 collides
    # with existing automation at 07:15 (same "morning" hour)
    assert "_TIME_BUCKET_MINUTES = 60" in src
    # Weekday-only condition supported in builder
    assert "_WEEKDAYS_ONLY" in src
    # Domain → service map covers binary domains
    for needle in (
        '"light"', '"switch"', '"fan"',
        'light.turn_on', 'switch.turn_off', 'fan.turn_off',
    ):
        assert needle in src, f"missing service mapping: {needle}"
    # Cross-reference with existing automations to avoid duplicates
    assert "_signatures_of_existing_automations" in src
    # context_user_id is the manual/automation discriminator
    assert "context_user_id" in src
    # Title surfaces variance so the user knows the tolerance
    assert "± " in src or "±{" in src


@t("StateEvent: context_user_id field is preserved as optional")
def _():
    src = open(
        "custom_components/ha_insights/observers/state_event_buffer.py",
        encoding="utf-8",
    ).read()
    assert "context_user_id: str | None" in src
    # Live listener captures it from the HA event
    init_src = open(
        "custom_components/ha_insights/__init__.py", encoding="utf-8"
    ).read()
    assert "context.user_id" in init_src
    assert "context_user_id=ctx_user" in init_src


@t("RoutineDetector: invariants present")
def _():
    src = open(
        "custom_components/ha_insights/detectors/routine.py",
        encoding="utf-8",
    ).read()
    assert "_MIN_ROUTINE_SIZE = 3" in src
    assert "_MIN_ROUTINE_DAYS = 5" in src
    assert "_ROUTINE_PRESENCE_RATIO = 0.80" in src
    # Reuses ManualHabit's service map (no duplication)
    assert "from .manual_habit import _DOMAIN_SERVICE_MAP" in src
    # Friendly label per time of day
    assert "_routine_label" in src


@t("PresenceInferenceDetector: invariants present")
def _():
    src = open(
        "custom_components/ha_insights/detectors/presence_inference.py",
        encoding="utf-8",
    ).read()
    assert "_AREA_DOMINANCE_RATIO = 0.70" in src
    assert "_MIN_DAYS_FOR_INSIGHT = 5" in src
    # Skips polling-driven noisy domains
    assert "sensor" in src
    assert "climate" in src
    # Coalesces adjacent windows into ranges
    assert "_coalesce_ranges" in src
    # Looks up area names from registry
    assert "area_registry" in src


@t("sun_relative helper: detect_sun_relative_trigger present")
def _():
    src = open(
        "custom_components/ha_insights/detectors/sun_relative.py",
        encoding="utf-8",
    ).read()
    assert "def detect_sun_relative_trigger" in src
    # Bar is 60% of clock stddev — keeps the bar high
    assert "_TIGHTER_FIT_RATIO = 0.6" in src
    # Within ±2h of sun event for the correlation to be real
    assert "_MAX_OFFSET_MINUTES = 120" in src
    # Builds a ready-to-drop HA trigger dict
    assert "def build_sun_trigger" in src


# ---- Run + report ----

passed = sum(1 for _, s, _ in results if s == "PASS")
failed = sum(1 for _, s, _ in results if s != "PASS")
print(f"\n{passed}/{len(results)} tests passed" + (f", {failed} failures:" if failed else " ✓"))
for n, s, e in results:
    mark = "✓" if s == "PASS" else "✗"
    line = f"  [{mark}] {n}"
    if e:
        line += f" — {e}"
    print(line)

sys.exit(0 if failed == 0 else 1)
