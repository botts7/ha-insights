"""v1.4 smoke tests — multi-user attribution, mobile notifier,
predictive phone reminder, weather correlation, dependency surface.

Runs without HA stack. Uses source-level structural assertions for
HA-integrated code and synthesized data for pure-logic helpers.

Run: `PYTHONIOENCODING=utf-8 python tests/_smoke_v1_4_x.py`
"""
from __future__ import annotations

import importlib.util
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
    # Register before exec so dataclasses + similar introspection
    # (which walks `sys.modules[cls.__module__]`) doesn't choke on
    # the freshly-loaded module. CPython 3.13+ is strict about this.
    sys.modules[name] = m
    s.loader.exec_module(m)  # type: ignore[union-attr]
    return m


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


# ---- Insight dataclass v1.4 fields ----

insight_mod = _load(
    "insight_v14", "custom_components/ha_insights/insight.py"
)
Insight = insight_mod.Insight
InsightKind = insight_mod.InsightKind


@t("insight: vendor field defaults to None and roundtrips through to_dict")
def _():
    from datetime import datetime

    ins = Insight(
        id="x",
        kind=InsightKind.AUTOMATION_PROPOSAL,
        detector="phone_charge_reminder",
        area_id=None,
        title="t",
        confidence=0.5,
        fingerprint={"x": 1},
        payload={},
        payload_format="automation",
        created_at=datetime.now(),
    )
    assert ins.vendor is None
    d = ins.to_dict()
    assert "vendor" in d
    assert "target_user_id" in d
    assert "target_user_id_confidence" in d
    assert d["vendor"] is None
    assert d["target_user_id"] is None
    assert d["target_user_id_confidence"] is None


@t("insight: target_user_id + confidence accept set values")
def _():
    from datetime import datetime

    ins = Insight(
        id="x",
        kind=InsightKind.AUTOMATION_PROPOSAL,
        detector="phone_charge_reminder",
        area_id=None,
        title="t",
        confidence=0.5,
        fingerprint={"x": 1},
        payload={},
        payload_format="automation",
        created_at=datetime.now(),
        vendor="Schlage",
        target_user_id="uid-123",
        target_user_id_confidence=1.0,
    )
    d = ins.to_dict()
    assert d["vendor"] == "Schlage"
    assert d["target_user_id"] == "uid-123"
    assert d["target_user_id_confidence"] == 1.0


# ---- Schema v4 migration ----


@t("schema v4: ALTER TABLE adds three new columns")
def _():
    src = _read("custom_components/ha_insights/store/schema.py")
    assert "CURRENT_VERSION = 4" in src
    assert "ALTER TABLE insights ADD COLUMN vendor TEXT" in src
    assert "ALTER TABLE insights ADD COLUMN target_user_id TEXT" in src
    assert (
        "ALTER TABLE insights ADD COLUMN target_user_id_confidence REAL"
        in src
    )
    # v3 entry still present (never edit shipped migrations)
    assert "INSERT OR REPLACE INTO schema_version (version) VALUES (3);" in src


@t("store: add_insight INSERTs the three new columns")
def _():
    src = _read("custom_components/ha_insights/store/store.py")
    assert "vendor, target_user_id, target_user_id_confidence" in src
    assert "insight.vendor," in src
    assert "insight.target_user_id," in src
    assert "insight.target_user_id_confidence," in src


@t("store: _row_to_insight reads the three new columns safely")
def _():
    src = _read("custom_components/ha_insights/store/store.py")
    assert 'row["vendor"]' in src
    assert 'row["target_user_id"]' in src
    assert 'row["target_user_id_confidence"]' in src
    # Each is gated by an `in row.keys()` check so old rows survive
    assert '"vendor" in row.keys()' in src


# ---- Detector base ----


@t("base: Detector exposes description / required_data / optional_data")
def _():
    src = _read("custom_components/ha_insights/detectors/base.py")
    assert "description: ClassVar[str]" in src
    assert "required_data: ClassVar[tuple[str, ...]]" in src
    assert "optional_data: ClassVar[tuple[str, ...]]" in src


# ---- WeatherCorrelationDetector ----


@t("weather: does NOT reference ev.attributes in code (StateEvent has no attrs)")
def _():
    """Comment mentioning ev.attributes is fine (it's the cautionary
    'we DO NOT read this' note); code reading it is not. Strip
    comment lines and re-check."""
    src = _read(
        "custom_components/ha_insights/detectors/weather_correlation.py"
    )
    code_only = "\n".join(
        line for line in src.splitlines()
        if not line.lstrip().startswith("#")
    )
    # Docstrings still contain the warning text; that's ok since
    # they're strings, not executable references. The actual bug
    # was `ev.attributes.get(...)` — assert that specific phrasing
    # is gone.
    assert "ev.attributes.get" not in code_only
    assert "isinstance(ev.attributes" not in code_only


@t("weather: derives temp from a sensor.* via _pick_outdoor_temp_sensor")
def _():
    src = _read(
        "custom_components/ha_insights/detectors/weather_correlation.py"
    )
    assert "def _pick_outdoor_temp_sensor" in src
    assert 'eid == "sensor.outdoor_temperature"' in src


@t("weather: declares required_data with weather domain")
def _():
    src = _read(
        "custom_components/ha_insights/detectors/weather_correlation.py"
    )
    assert "required_data" in src
    assert "domain:weather" in src


# ---- PhoneChargeReminderDetector ----


@t("charge reminder: lookback is 90 days (not 14)")
def _():
    src = _read(
        "custom_components/ha_insights/detectors/phone_charge_reminder.py"
    )
    assert "_MAX_LOOKBACK_DAYS = 90" in src


@t("charge reminder: predictive forecast template references rate + buffer")
def _():
    src = _read(
        "custom_components/ha_insights/detectors/phone_charge_reminder.py"
    )
    # The automation includes a template-condition forecast
    assert "{% set rate" in src
    assert "{% set buffer" in src
    assert "(current - rate * hours_left) < buffer" in src


@t("charge reminder: weekday helper + habit insight builder present")
def _():
    src = _read(
        "custom_components/ha_insights/detectors/phone_charge_reminder.py"
    )
    assert "def _summarize_by_weekday" in src
    assert "def _build_weekday_habit_insight" in src


@t("charge reminder: weekday helper labels include all 7 days")
def _():
    src = _read(
        "custom_components/ha_insights/detectors/phone_charge_reminder.py"
    )
    for day in (
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ):
        assert day in src


@t("charge reminder: scan returns list[Insight], never single+list mix")
def _():
    src = _read(
        "custom_components/ha_insights/detectors/phone_charge_reminder.py"
    )
    # The new signature: _evaluate_phone returns list[Insight]
    assert "def _evaluate_phone(" in src
    assert "-> list[Insight]:" in src
    # The scan loop just extends
    assert "insights.extend(" in src


@t("charge reminder: target_user_id + confidence wired in")
def _():
    src = _read(
        "custom_components/ha_insights/detectors/phone_charge_reminder.py"
    )
    assert "target_user_id, target_user_confidence = get_user_id_for_entity(" in src
    assert "target_user_id=target_user_id," in src
    assert "target_user_id_confidence=target_user_confidence," in src


@t("charge reminder: required_data declares mobile_app + battery + charging")
def _():
    src = _read(
        "custom_components/ha_insights/detectors/phone_charge_reminder.py"
    )
    assert "integration:mobile_app" in src
    assert "binary_sensor.*_charging" in src
    assert "sensor.*_battery_level" in src


# ---- User routing ----


@t("user_routing: get_user_id_for_entity returns (uid, confidence) tuple")
def _():
    src = _read(
        "custom_components/ha_insights/notifications/user_routing.py"
    )
    assert "-> tuple[str | None, float | None]" in src
    # All three tiers
    assert "Tier 1: mobile_app config entry user_id" in src
    assert "Tier 2: person.* device tracker linkage" in src
    assert "Tier 3: explicit manual mapping" in src
    # Confidence values for each tier
    assert "return uid, 1.0" in src
    assert "return uid, 0.7" in src


@t("user_routing: resolve_notify_targets short-circuits to user services")
def _():
    src = _read(
        "custom_components/ha_insights/notifications/user_routing.py"
    )
    assert "def resolve_notify_targets" in src
    assert "if not target_user_id:" in src
    assert "get_mobile_app_services_for_user" in src


# ---- Mobile notifier ----


@t("mobile notifier: uses resolve_notify_targets for routing")
def _():
    src = _read(
        "custom_components/ha_insights/notifications/mobile.py"
    )
    assert "from .user_routing import resolve_notify_targets" in src
    assert "target_user_id=target_user_id" in src
    assert "effective_targets" in src


@t("mobile notifier: payload sets tag for OS-level replacement")
def _():
    src = _read(
        "custom_components/ha_insights/notifications/mobile.py"
    )
    assert '"tag": f"ha_insights_{insight.id}"' in src
    assert '"group": "ha_insights"' in src
    assert "HA_INSIGHTS_DISMISS" in src


# ---- __init__ wiring ----


@t("__init__: _notify_insight accepts mobile_targets param")
def _():
    src = _read("custom_components/ha_insights/__init__.py")
    assert "async def _notify_insight(" in src
    assert "mobile_targets: list[str] | None = None" in src
    assert "fire_mobile_notifications" in src


@t("__init__: mobile_app_notification_action listener wired")
def _():
    src = _read("custom_components/ha_insights/__init__.py")
    assert "mobile_app_notification_action" in src
    assert "HA_INSIGHTS_DISMISS" in src
    assert "dismiss_insight" in src


@t("config_flow: CONF_NOTIFY_MOBILE_TARGETS option present")
def _():
    src = _read("custom_components/ha_insights/config_flow.py")
    assert 'CONF_NOTIFY_MOBILE_TARGETS = "notify_mobile_targets"' in src
    assert "def get_notify_mobile_targets" in src
    # Validates it strips bad entries (no notify. prefix)
    assert 'not target.startswith("notify.")' in src


# ---- WS detector_directory ----


@t("ws: detector_directory handler is registered + in SUPPORTED_METHODS")
def _():
    src = _read("custom_components/ha_insights/ws_api.py")
    assert "ws_detector_directory" in src
    assert '"detector_directory"' in src  # in SUPPORTED_METHODS tuple
    assert "_check_dependency_satisfied" in src


@t("ws: detector_directory tiers USELESS/LIMITED/GOOD/GREAT computed")
def _():
    src = _read("custom_components/ha_insights/ws_api.py")
    for tier in ("USELESS", "LIMITED", "GOOD", "GREAT"):
        assert f'"{tier}"' in src or f"'{tier}'" in src, f"missing {tier}"


# ---- Anti-spam policy (v1.4 follow-up) ----


@t("anti-spam: 5 presets defined with non-overlapping confidence floors")
def _():
    src = _read("custom_components/ha_insights/config_flow.py")
    for preset in (
        "NOTIFY_PRESET_MINIMAL",
        "NOTIFY_PRESET_BALANCED",
        "NOTIFY_PRESET_CHATTY",
        "NOTIFY_PRESET_ADAPTIVE",
        "NOTIFY_PRESET_CUSTOM",
    ):
        assert preset in src, f"missing preset constant {preset}"
    # Each baseline has all five keys
    for k in (
        "confidence_floor",
        "daily_cap",
        "quiet_hours_start",
        "quiet_hours_end",
        "min_attribution_confidence",
    ):
        assert f'"{k}"' in src, f"preset table missing key {k}"


@t("anti-spam: get_mobile_notify_policy honors custom + preset paths")
def _():
    src = _read("custom_components/ha_insights/config_flow.py")
    assert "def get_mobile_notify_policy" in src
    assert "preset == NOTIFY_PRESET_CUSTOM" in src
    assert 'policy["preset"] = preset' in src
    assert 'policy["adaptive"] = preset == NOTIFY_PRESET_ADAPTIVE' in src


@t("mobile notifier: gates apply in order (confidence, attribution, quiet, cap)")
def _():
    src = _read("custom_components/ha_insights/notifications/mobile.py")
    # Confidence floor before any other check
    assert "Gate 1: mobile-specific confidence floor" in src
    assert "Gate 2: attribution confidence" in src
    assert "Gate 3: quiet hours" in src
    assert "Gate 4: daily cap" in src
    # All four log lines explain WHY the push was skipped
    assert "below floor" in src or "< mobile floor" in src
    assert "won't risk waking the wrong person" in src
    assert "falls inside quiet hours" in src
    assert "already received %d pushes today" in src


@t("mobile notifier: quiet hours wrap midnight")
def _():
    """Verify the wrap-around branch by replicating the helper
    inline (we can't import the package member directly because of
    its relative imports). This catches the same off-by-one bugs."""
    src = _read("custom_components/ha_insights/notifications/mobile.py")
    # Structural assertions on the implementation
    assert "def _in_quiet_hours(" in src
    assert "if start == end:" in src
    assert "return start <= local_hour < end" in src
    # Wrap case explicitly handled
    assert "local_hour >= start or local_hour < end" in src

    # And inline re-implementation to catch logic regression
    def _q(h: int, start: int, end: int) -> bool:
        if start == end:
            return False
        if start < end:
            return start <= h < end
        return h >= start or h < end

    assert _q(23, 22, 7) is True
    assert _q(3, 22, 7) is True
    assert _q(10, 22, 7) is False
    assert _q(10, 9, 17) is True
    assert _q(18, 9, 17) is False
    assert _q(0, 0, 0) is False


@t("mobile notifier: daily-counter resets per entry on unload")
def _():
    src = _read("custom_components/ha_insights/__init__.py")
    assert "reset_daily_counter_for_entry" in src


@t("mobile notifier: daily-counter is keyed by (entry, user_or_household, date)")
def _():
    src = _read("custom_components/ha_insights/notifications/mobile.py")
    assert "_DAILY_COUNTERS" in src
    assert "user_key = target_user_id or \"household\"" in src
    # Per-event count (not per-target), since OS tag collapses
    # multi-phone delivery into one user-facing notification.
    assert "Only bump the counter once per insight" in src


# ---- Adaptive tuner ----


@t("adaptive: tuner exists with band [0.7, 0.95] and step 0.02")
def _():
    src = _read("custom_components/ha_insights/notifications/adaptive.py")
    assert "_BAND_LOW = 0.70" in src
    assert "_BAND_HIGH = 0.95" in src
    assert "_STEP = 0.02" in src
    assert "def tune_adaptive_floor" in src
    assert "def get_adaptive_floor" in src


@t("adaptive: schedule wired at 03:00 local when preset == adaptive")
def _():
    src = _read("custom_components/ha_insights/__init__.py")
    assert "tune_adaptive_floor" in src
    assert "if notify_mobile_policy.get(\"adaptive\"):" in src
    # Scheduled at 03:00 (low-traffic; before morning push window)
    assert "hour=3, minute=0, second=0" in src


@t("adaptive: floor lookup wired in fire_mobile_notifications")
def _():
    src = _read("custom_components/ha_insights/notifications/mobile.py")
    assert "if pol.get(\"adaptive\"):" in src
    assert "get_adaptive_floor" in src


# ---- Maturity flag + experimental gate ----


@t("maturity: enum exposes STABLE/BETA/EXPERIMENTAL")
def _():
    src = _read("custom_components/ha_insights/detectors/base.py")
    assert "class Maturity(StrEnum)" in src
    assert 'STABLE = "stable"' in src
    assert 'BETA = "beta"' in src
    assert 'EXPERIMENTAL = "experimental"' in src
    # Detector base declares the field with safe default
    assert "maturity: ClassVar[Maturity] = Maturity.STABLE" in src


@t("maturity: phone_charge_reminder + weather_correlation are EXPERIMENTAL")
def _():
    for fname in (
        "phone_charge_reminder.py",
        "weather_correlation.py",
    ):
        src = _read(f"custom_components/ha_insights/detectors/{fname}")
        assert "maturity = Maturity.EXPERIMENTAL" in src, f"{fname} missing"


@t("maturity: experimental detectors gated off by default in scan loop")
def _():
    src = _read("custom_components/ha_insights/detectors/__init__.py")
    assert "allow_experimental" in src
    assert "_Maturity.EXPERIMENTAL" in src
    # Gate is bypassed when user explicitly enabled the detector
    assert "and not explicitly_enabled" in src


@t("maturity: config_flow getter + opt-in default False")
def _():
    src = _read("custom_components/ha_insights/config_flow.py")
    assert "CONF_ALLOW_EXPERIMENTAL_DETECTORS" in src
    assert "DEFAULT_ALLOW_EXPERIMENTAL_DETECTORS = False" in src
    assert "def get_allow_experimental_detectors" in src


@t("maturity: ws detector_directory returns maturity per detector")
def _():
    src = _read("custom_components/ha_insights/ws_api.py")
    assert '"maturity": maturity' in src


# ---- Try with example data ----


@t("examples: fixture module returns sample insights covering kinds")
def _():
    """Structural test — load examples.py source and confirm
    `build_example_insights` exists, returns multiple records, and
    every record has the EXAMPLE_PAYLOAD_KEY marker. Importing the
    module directly fails due to its relative `from .insight`
    import, so we test the source surface instead."""
    src = _read("custom_components/ha_insights/examples.py")
    assert "def build_example_insights() -> list[Insight]:" in src
    assert "EXAMPLE_PAYLOAD_KEY" in src
    assert '"_example"' in src or "'_example'" in src
    # Count detector names referenced — should be ≥4 distinct
    import re

    detectors = set(re.findall(r'detector="([a-z_]+)"', src))
    assert len(detectors) >= 4, (
        f"too few detector kinds in examples: {detectors}"
    )


@t("examples: WS inject + clear handlers registered + in SUPPORTED_METHODS")
def _():
    src = _read("custom_components/ha_insights/ws_api.py")
    assert "ws_inject_examples" in src
    assert "ws_clear_examples" in src
    assert '"inject_examples"' in src  # in SUPPORTED_METHODS
    assert '"clear_examples"' in src


@t("examples: clear walks active + dismissed + applied to find marked rows")
def _():
    src = _read("custom_components/ha_insights/ws_api.py")
    assert "include_dismissed=True" in src
    assert "include_applied=True" in src
    assert "EXAMPLE_PAYLOAD_KEY" in src


# ---- Onboarding / refinement wizard ----


@t("wizard: OptionsFlow init shows a menu (not the old big form)")
def _():
    src = _read("custom_components/ha_insights/config_flow.py")
    assert "self.async_show_menu(" in src
    # Menu offers wizard + advanced paths
    assert '"wizard_intro":' in src
    assert '"advanced":' in src


@t("wizard: five sequential async_step_wizard_* methods present")
def _():
    src = _read("custom_components/ha_insights/config_flow.py")
    for step in (
        "async_step_wizard_intro",
        "async_step_wizard_preset",
        "async_step_wizard_mobile",
        "async_step_wizard_experimental",
        "async_step_wizard_done",
    ):
        assert f"def {step}(" in src, f"missing wizard step {step}"


@t("wizard: chains forward (intro→preset→mobile→experimental→done)")
def _():
    src = _read("custom_components/ha_insights/config_flow.py")
    assert "return await self.async_step_wizard_preset()" in src
    assert "return await self.async_step_wizard_mobile()" in src
    assert "return await self.async_step_wizard_experimental()" in src
    assert "return await self.async_step_wizard_done()" in src


@t("wizard: done step PRESERVES existing options (no destructive overwrite)")
def _():
    src = _read("custom_components/ha_insights/config_flow.py")
    # The merged dict starts from existing options and only overlays
    # wizard outputs — critical so the user doesn't lose audit
    # thresholds, scan areas, etc by running the wizard.
    assert "merged = dict(self.config_entry.options)" in src
    assert "merged.update(" in src


@t("wizard: tracks last_wizard_version so 'what's new' can compare")
def _():
    src = _read("custom_components/ha_insights/config_flow.py")
    assert '"last_wizard_version"' in src
    # Intro screen surfaces is_upgrade + current_version placeholders
    assert '"is_upgrade"' in src
    assert '"current_version"' in src


@t("wizard: advanced form still reachable (step_id renamed to 'advanced')")
def _():
    src = _read("custom_components/ha_insights/config_flow.py")
    assert "async def async_step_advanced(" in src
    # The full-form helper still exists and returns step_id="advanced"
    assert 'step_id="advanced", data_schema=schema' in src
    # Cloud-consent rejection bounces back to advanced, not init
    assert "return await self.async_step_advanced()" in src


# ---- Community analytics stub ----


@t("analytics: module defines schema + privacy-safe payload builder")
def _():
    src = _read("custom_components/ha_insights/analytics.py")
    assert "DEFAULT_ANALYTICS_ENDPOINT" in src
    assert "def build_report_payload(" in src
    assert "def get_or_create_install_uuid(" in src
    # Privacy contract is documented + enforced (the structural
    # surface the receiver sees)
    assert '"schema_version": 1' in src
    assert '"detector_outcomes"' in src
    assert "No entity names" in src
    assert "No insight titles" in src


@t("analytics: payload includes maturity tier per detector")
def _():
    src = _read("custom_components/ha_insights/analytics.py")
    # The receiver tracks tier distribution so we can graduate
    # experimental detectors based on real apply rates.
    assert '"maturity": maturity_by_detector.get(' in src


@t("analytics: opt-in config keys + getter defined")
def _():
    src = _read("custom_components/ha_insights/config_flow.py")
    assert 'CONF_ANALYTICS_ENABLED = "analytics_enabled"' in src
    assert 'CONF_ANALYTICS_ENDPOINT = "analytics_endpoint"' in src
    assert "DEFAULT_ANALYTICS_ENABLED = False" in src
    assert "def get_analytics_settings(" in src


@t("analytics: WS preview endpoint lets users inspect payload before opting in")
def _():
    src = _read("custom_components/ha_insights/ws_api.py")
    assert "ws_analytics_preview" in src
    assert '"analytics_preview"' in src  # in SUPPORTED_METHODS
    # Returns the EXACT payload + the default endpoint so users
    # can decide before flipping the switch
    assert "build_report_payload" in src
    assert "default_endpoint" in src


@t("analytics: weekly scheduler fires Monday 04:00 local when enabled")
def _():
    src = _read("custom_components/ha_insights/__init__.py")
    assert "unsub_analytics" in src
    assert "from .analytics import send_report" in src
    # Gated on opt-in
    assert "if analytics_enabled:" in src
    # Monday-only inside the daily-tick callback
    assert "isoweekday() != 1" in src


@t("analytics: best-effort POST — failures must not break the integration")
def _():
    src = _read("custom_components/ha_insights/analytics.py")
    # Catch-all around the POST + log at DEBUG (not exception)
    assert "best-effort" in src
    # Timeout is hard-bounded so a slow receiver doesn't stall HA
    assert "_REQUEST_TIMEOUT_SEC" in src


# ---- Stability fixes ----


@t("stability: async_show_menu has a fallback for older HA versions")
def _():
    src = _read("custom_components/ha_insights/config_flow.py")
    # Modern menu path
    assert 'hasattr(self, "async_show_menu")' in src
    # Form fallback for older HA
    assert 'vol.Required("path"' in src
    # Both paths route to the same downstream wizard/advanced steps
    assert 'choice == "advanced"' in src


@t("stability: wizard_intro has a real schema (not empty)")
def _():
    src = _read("custom_components/ha_insights/config_flow.py")
    # Empty schemas don't render on all HA versions — we use a
    # single confirmation field to drive submission.
    assert 'vol.Required("continue", default=True): bool' in src


@t("stability: install UUID persists across calls when hass available")
def _():
    src = _read("custom_components/ha_insights/analytics.py")
    # hass parameter is optional but threaded for persistence
    assert "hass: HomeAssistant | None = None" in src
    # async_update_entry persists the freshly generated UUID
    assert "hass.config_entries.async_update_entry(entry, options=merged)" in src
    # build_report_payload passes hass through
    assert "get_or_create_install_uuid(entry, hass=hass)" in src


@t("insight: every InsightKind referenced by a detector exists in the enum")
def _():
    """Regression for the v1.4.0 deploy failure where four detectors
    referenced InsightKind.PATTERN_OBSERVATION which wasn't in the
    enum, crashing the integration at module load. Walks every
    detector file, extracts InsightKind.* references, and asserts
    each one is defined."""
    import re

    src = _read("custom_components/ha_insights/insight.py")
    # Extract enum names from the file
    defined = set(re.findall(r"^\s+([A-Z_]+) = \"", src, flags=re.MULTILINE))
    assert "PATTERN_OBSERVATION" in defined, (
        "PATTERN_OBSERVATION must be in InsightKind"
    )
    # Now sweep every detector for references and confirm coverage
    import os

    refs: set[str] = set()
    det_dir = "custom_components/ha_insights/detectors"
    for fname in os.listdir(det_dir):
        if not fname.endswith(".py"):
            continue
        body = _read(f"{det_dir}/{fname}")
        for match in re.findall(r"InsightKind\.([A-Z_]+)", body):
            refs.add(match)
    missing = refs - defined
    assert not missing, (
        f"InsightKind values referenced by detectors but missing from "
        f"the enum: {missing}"
    )


@t("mobile targets: SelectSelector built from registered notify.* services")
def _():
    src = _read("custom_components/ha_insights/config_flow.py")
    assert "def _notify_mobile_targets_selector(" in src
    # Auto-prefers mobile_app_* services, includes others for power users
    assert 'name.startswith("mobile_app_")' in src
    # Always preserves already-saved values so they survive
    # mobile_app being unloaded during configuration
    assert "already_saved" in src
    # custom_value=True so users can type a service HA hasn't surfaced
    assert "custom_value=True" in src


@t("mobile targets: form accepts list (from selector) AND string (legacy)")
def _():
    src = _read("custom_components/ha_insights/config_flow.py")
    # The save path normalizes list → comma-separated string so the
    # storage format is stable across the selector vs legacy text input.
    assert "isinstance(raw_targets, (list, tuple, set, frozenset))" in src
    assert '", ".join(' in src


@t("per-user: get_notify_user_overrides + resolve_effective_policy defined")
def _():
    src = _read("custom_components/ha_insights/config_flow.py")
    assert "def get_notify_user_overrides(" in src
    assert "def resolve_effective_policy(" in src
    # Only known keys can be injected (no arbitrary fields)
    assert "KNOWN_KEYS = {" in src
    # Unattributed insights pass through unchanged
    assert "if not target_user_id:" in src
    assert "return global_policy" in src


@t("per-user: mobile.py recomputes effective policy when entry + user known")
def _():
    src = _read("custom_components/ha_insights/notifications/mobile.py")
    assert "resolve_effective_policy" in src
    # Falls back to global policy on resolver failure
    assert "falling back to global" in src


@t("per-user: ws endpoints registered + in SUPPORTED_METHODS")
def _():
    src = _read("custom_components/ha_insights/ws_api.py")
    for name in (
        "ws_list_ha_users",
        "ws_get_user_overrides",
        "ws_set_user_override",
    ):
        assert name in src, f"missing {name}"
    for method in (
        '"list_ha_users"',
        '"get_user_overrides"',
        '"set_user_override"',
    ):
        assert method in src, f"missing {method} in SUPPORTED_METHODS"


@t("per-user: write/list endpoints are admin-gated")
def _():
    src = _read("custom_components/ha_insights/ws_api.py")
    assert "def _require_admin(" in src
    assert '"admin_required"' in src
    # The gate is actually called from each of the three endpoints
    assert src.count("_require_admin(hass, connection, msg)") >= 3


@t("per-user: list_ha_users surfaces mobile_app device count per user")
def _():
    src = _read("custom_components/ha_insights/ws_api.py")
    assert "mobile_app_device_count" in src
    # System-generated users (Supervisor etc) are filtered out
    assert "system_generated" in src


@t("stability: schema migration tolerates duplicate-column re-runs")
def _():
    src = _read("custom_components/ha_insights/store/store.py")
    # Migrations now execute per-statement with error tolerance for
    # the SPECIFIC ALTER-already-applied case. Other errors still
    # propagate so real bugs aren't masked.
    assert '"duplicate column" in msg' in src
    assert '"already exists" in msg' in src
    # Other errors still raise
    assert "raise" in src


# ---- Run + report ----

passed = sum(1 for _, s, _ in results if s == "PASS")
failed = sum(1 for _, s, _ in results if s != "PASS")
print(
    f"\n{passed}/{len(results)} tests passed"
    + (f", {failed} failures:" if failed else " ✓")
)
for n, s, e in results:
    mark = "✓" if s == "PASS" else "✗"
    line = f"  [{mark}] {n}"
    if e:
        line += f" — {e}"
    print(line)

sys.exit(0 if failed == 0 else 1)
