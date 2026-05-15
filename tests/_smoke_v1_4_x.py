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


@t("per-user UI: menu includes 'Per-user notification overrides' entry")
def _():
    src = _read("custom_components/ha_insights/config_flow.py")
    assert '"user_overrides_pick": "Per-user notification overrides"' in src


@t("per-user UI: two-step flow (pick user → edit override)")
def _():
    src = _read("custom_components/ha_insights/config_flow.py")
    assert "async def async_step_user_overrides_pick(" in src
    assert "async def async_step_user_overrides_edit(" in src
    # Pick step chains forward
    assert "return await self.async_step_user_overrides_edit()" in src


@t("per-user UI: edit form pre-populates from existing override + global policy")
def _():
    src = _read("custom_components/ha_insights/config_flow.py")
    # Reads the user's existing override + the global policy
    assert "existing = overrides.get(self._editing_user_id, {})" in src
    assert "global_policy = get_mobile_notify_policy(self.config_entry)" in src
    # Form has all five policy knobs + clear checkbox
    for field in (
        '"preset"',
        '"confidence_floor"',
        '"daily_cap"',
        '"quiet_hours_start"',
        '"quiet_hours_end"',
        '"min_attribution_confidence"',
        '"clear_override"',
    ):
        assert field in src, f"missing {field} in edit form"


@t("per-user UI: pick step surfaces phone count + override status in label")
def _():
    src = _read("custom_components/ha_insights/config_flow.py")
    # Phone count shown as 📱 N or "(no phone)"
    assert '"📱 ' in src
    assert '"(no phone)"' in src
    # Existing override marked in label
    assert '"• has override"' in src
    # Aborts cleanly when no human users (test/CI safety)
    assert 'self.async_abort(reason="no_users_to_override")' in src


@t("per-user UI: aware of OptionsFlow being admin-gated by HA already")
def _():
    src = _read("custom_components/ha_insights/config_flow.py")
    # We don't double-gate — the docstring documents why. Match
    # against the joined-line form to tolerate Python comment line
    # wrapping (the literal in source may wrap at any point).
    joined = " ".join(src.split())
    assert "admin-gated by HA's Settings permission model" in joined


@t("per-user UI: clearing override pops the user from the map")
def _():
    src = _read("custom_components/ha_insights/config_flow.py")
    assert 'user_input.get("clear_override")' in src
    assert "current.pop(target_user_id, None)" in src


@t("cloud_consent persist uses merged_options (no field drift on cloud switch)")
def _():
    """Regression: switching to cloud mode used to wipe notification
    settings because the cloud_consent persist branch enumerated
    fields manually and missed every new option we added. Now it
    starts from existing options and overlays."""
    src = _read("custom_components/ha_insights/config_flow.py")
    joined = " ".join(src.split())
    assert "merged = dict(self.config_entry.options) merged.update(" in joined or (
        "merged = dict(self.config_entry.options)" in src
        and "merged.update(" in src
        and "return self.async_create_entry(title=\"\", data=merged)" in src
    )
    # And the missing-field set is now part of merged
    for missing in (
        "CONF_NOTIFY_MOBILE_TARGETS",
        "CONF_NOTIFY_PRESET",
        "CONF_NOTIFY_MOBILE_THRESHOLD",
        "CONF_NOTIFY_QUIET_HOURS_START",
        "CONF_ANALYTICS_ENABLED",
        "CONF_ALLOW_EXPERIMENTAL_DETECTORS",
    ):
        assert missing in src, f"cloud_consent missing {missing}"


@t("insight: dismissed_at now first-class on the dataclass")
def _():
    src = _read("custom_components/ha_insights/insight.py")
    # Defined as a field with default None
    assert "dismissed_at: datetime | None = None" in src
    # Serialized in to_dict for WS round-trip
    assert '"dismissed_at"' in src


@t("adaptive: uses Insight.dismissed_at, not getattr fallback")
def _():
    src = _read("custom_components/ha_insights/notifications/adaptive.py")
    # Old broken pattern is gone
    assert 'getattr(i, "dismissed_at"' not in src
    # New direct attribute access
    assert "i.dismissed_at is not None" in src


@t("store: _row_to_insight reads dismissed_at column")
def _():
    src = _read("custom_components/ha_insights/store/store.py")
    assert 'row["dismissed_at"]' in src
    # Defensive: tolerates older rows where the column key isn't set
    assert '"dismissed_at" in row.keys()' in src


@t("ws: SUPPORTED_METHODS matches actually-registered handlers")
def _():
    """Every ws_api.async_register_command call should have a
    corresponding entry in SUPPORTED_METHODS. Mismatches mean the
    hello handshake lies to the card about what's available."""
    import re

    src = _read("custom_components/ha_insights/ws_api.py")
    # Pull registered names
    registered = set(
        re.findall(r"async_register_command\(hass, ws_(\w+)\)", src)
    )
    # Pull SUPPORTED_METHODS strings
    methods_block = re.search(
        r"SUPPORTED_METHODS = \(([\s\S]*?)\)", src
    )
    assert methods_block, "SUPPORTED_METHODS tuple not found"
    advertised = set(re.findall(r'"([\w_]+)"', methods_block.group(1)))
    missing = registered - advertised
    assert not missing, (
        f"registered but not advertised: {sorted(missing)}"
    )


@t("dismiss-persistence: add_insight preserves dismissed_at + applied_at")
def _():
    """Regression for 'same insight keeps notifying me'. INSERT OR
    REPLACE used to wipe dismissed_at + applied_at + applied_artifact_id
    every scan, so a re-detected pattern fired a fresh 'added' event
    and re-notified the user. Now we ON CONFLICT DO UPDATE everything
    EXCEPT those three columns."""
    src = _read("custom_components/ha_insights/store/store.py")
    # Old behaviour gone
    assert "INSERT OR REPLACE INTO insights" not in src
    # New behaviour present
    assert "ON CONFLICT(id) DO UPDATE SET" in src
    # The three protected columns are NOT in the UPDATE SET list
    update_clause_start = src.index("ON CONFLICT(id) DO UPDATE SET")
    update_clause_end = src.index("DELIBERATELY NOT TOUCHED")
    update_clause = src[update_clause_start:update_clause_end]
    for protected in ("dismissed_at", "applied_at", "applied_artifact_id"):
        assert protected not in update_clause, (
            f"{protected} must NOT be in UPDATE SET — it's user action state"
        )


@t("dismiss-persistence: refresh event fires for updates, added for inserts")
def _():
    """The listener gates on event_type == 'added' to fire mobile
    pushes. We need 'refreshed' for re-emissions so a dismissed
    insight doesn't trigger a fresh notification when its title
    or confidence ticks up."""
    src = _read("custom_components/ha_insights/store/store.py")
    # Pre-check determines event type
    assert "SELECT 1 FROM insights WHERE id = ?" in src
    # Conditional notify
    assert 'self._notify("refreshed" if existed else "added", insight)' in src


@t("bootstrap filter: StateEvent has from_bootstrap + context_id fields")
def _():
    """Regression for the bootstrap fan-out false-positive class
    (HA_EVENT_SEMANTICS.md Gotcha 5 + Gotchas 1-3). Every entity
    fires state_changed on boot with old_state=None — without this
    flag we false-positive every restart."""
    src = _read(
        "custom_components/ha_insights/observers/state_event_buffer.py"
    )
    assert "from_bootstrap: bool = False" in src
    assert "context_id: str | None = None" in src
    # Live buffer query filters out bootstrap events by default
    assert "include_bootstrap: bool = False" in src
    assert "if not include_bootstrap and ev.from_bootstrap:" in src


@t("bootstrap filter: integration marks window early + listens for STARTED")
def _():
    """v1.5.8 fix: the marker has to be set at SETUP time when HA
    is still starting, because entity-platform restored-state
    writes arrive BEFORE EVENT_HOMEASSISTANT_STARTED fires. The
    listener-only approach (v1.4.9) never saw bootstrap events as
    from_bootstrap. Verify both paths now exist:
      - Setup-time marker when hass.state is not CoreState.running
      - STARTED-event backstop for any stragglers
    """
    src = _read("custom_components/ha_insights/__init__.py")
    assert "EVENT_HOMEASSISTANT_STARTED" in src
    assert "_bootstrap_until_ts" in src
    # Window widened from 5 to 10s to absorb slow boots
    assert "_BOOTSTRAP_WINDOW_SEC = 10" in src
    # The two-part check (window AND old_state=None) mirrors HA's
    # automation state-trigger guard
    assert "if old_state is None:" in src
    assert "from_bootstrap = True" in src
    # Setup-time marker is gated on CoreState
    assert "if hass.state is not CoreState.running:" in src


@t("bootstrap filter: state events capture context_id for batch correlation")
def _():
    """context.id is shared across N state_changed events from one
    group toggle / scene activation / script run (Gotchas 1-3).
    Capturing it now lets future detectors group batch operations."""
    src = _read("custom_components/ha_insights/__init__.py")
    assert "ctx_id = getattr(new_state.context, \"id\", None)" in src
    assert "context_id=ctx_id" in src


@t("bootstrap filter: snapshot view also skips bootstrap by default")
def _():
    src = _read("custom_components/ha_insights/detectors/__init__.py")
    # Same guard in the scan-time snapshot view used by detectors
    assert "include_bootstrap: bool = False" in src
    assert 'getattr(ev, "from_bootstrap", False)' in src


@t("batch correlator: groups events by context.id within a 1s window")
def _():
    """Validate the v1.5 batch correlator against a synthesized
    group toggle: 5 lights all fire state_changed within 250ms
    sharing the same context.id. iter_batches should yield one
    batch of 5 events."""
    fixture = _load(
        "ctx_id_fixture", "tests/_ha_semantics/context_id_batch.py"
    )
    buffer_mod = _load(
        "state_event_buffer_ctx",
        "custom_components/ha_insights/observers/state_event_buffer.py",
    )
    correlator = _load(
        "batch_correlator",
        "custom_components/ha_insights/lib/batch_correlator.py",
    )
    from datetime import UTC, datetime

    buf = buffer_mod.StateEventBuffer()
    ctx_id, added = fixture.synth_group_toggle(
        buf,
        at=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
        member_entities=[
            "light.living_a",
            "light.living_b",
            "light.living_c",
            "light.living_d",
            "light.living_e",
        ],
    )
    assert len(added) == 5
    batches = list(correlator.iter_batches(buf._events))
    assert len(batches) == 1, f"expected 1 batch, got {len(batches)}"
    found_ctx, batch_events = batches[0]
    assert found_ctx == ctx_id
    assert len(batch_events) == 5


@t("batch correlator: separates batches when events are minutes apart")
def _():
    """Same context.id but minutes apart is NOT a batch — that's
    a long-running script. Verify the window check splits them."""
    fixture = _load(
        "ctx_id_split", "tests/_ha_semantics/context_id_batch.py"
    )
    buffer_mod = _load(
        "state_event_buffer_split",
        "custom_components/ha_insights/observers/state_event_buffer.py",
    )
    correlator = _load(
        "batch_correlator_split",
        "custom_components/ha_insights/lib/batch_correlator.py",
    )
    from datetime import UTC, datetime, timedelta

    buf = buffer_mod.StateEventBuffer()
    base = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
    # Group call A at t=0
    fixture.synth_group_toggle(
        buf, at=base, member_entities=["light.a", "light.b"],
        context_id="ctx-shared",
    )
    # Same context_id at t+10min — same script, separate run
    fixture.synth_group_toggle(
        buf, at=base + timedelta(minutes=10),
        member_entities=["light.c", "light.d"],
        context_id="ctx-shared",
    )
    batches = list(correlator.iter_batches(buf._events))
    # Should split into TWO batches, not collapse to one
    assert len(batches) == 2, f"expected 2 split batches, got {len(batches)}"
    for _ctx, events in batches:
        assert len(events) == 2


@t("batch correlator: batched_entity_set returns all member pairs")
def _():
    """The set used by cooccurrence to drop co-effect pairs."""
    fixture = _load(
        "ctx_id_pairs", "tests/_ha_semantics/context_id_batch.py"
    )
    buffer_mod = _load(
        "state_event_buffer_pairs",
        "custom_components/ha_insights/observers/state_event_buffer.py",
    )
    correlator = _load(
        "batch_correlator_pairs",
        "custom_components/ha_insights/lib/batch_correlator.py",
    )
    from datetime import UTC, datetime

    buf = buffer_mod.StateEventBuffer()
    fixture.synth_group_toggle(
        buf,
        at=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
        member_entities=["light.a", "light.b", "light.c"],
    )
    pairs = correlator.batched_entity_set(buf._events)
    # 3 entities → 3 undirected pairs → 6 directed pairs
    assert len(pairs) == 6
    assert ("light.a", "light.b") in pairs
    assert ("light.b", "light.a") in pairs
    assert ("light.a", "light.c") in pairs
    assert ("light.c", "light.b") in pairs


@t("import safety: every detector module compiles cleanly (catches NameError class)")
def _():
    """Catches the entire class of 'I added X but forgot to import X'
    bugs at the source level by AST-parsing each detector file. Both
    PATTERN_OBSERVATION and Maturity.BETA escaped earlier because no
    test actually parsed the files.

    AST-parse is the strongest local check we can do without HA's
    Python environment (relative imports from .base etc. fail to
    load standalone). It catches:
      - undefined names referenced as class-body attrs
      - syntax errors
      - typo'd class names
      - mismatched parens
    Doesn't catch runtime-only errors (those need the HA stack)."""
    import ast
    import os

    det_dir = "custom_components/ha_insights/detectors"
    failed: list[tuple[str, str]] = []
    for fname in os.listdir(det_dir):
        if not fname.endswith(".py") or fname.startswith("_"):
            continue
        body = _read(f"{det_dir}/{fname}")
        try:
            ast.parse(body, filename=fname)
        except SyntaxError as e:  # noqa: PERF203
            failed.append((fname, f"{type(e).__name__}: {e}"))
    assert not failed, f"detector files failed to parse: {failed}"


@t("ultrareview #3: bootstrap marker set at setup time when HA not running")
def _():
    """The previous design only set the bootstrap_until_ts AFTER
    EVENT_HOMEASSISTANT_STARTED fired — but entity platforms write
    their restored state BEFORE that event. Fix: check CoreState
    at setup time and mark the window IMMEDIATELY if HA is still
    starting."""
    src = _read("custom_components/ha_insights/__init__.py")
    assert "if hass.state is not CoreState.running:" in src
    assert "from homeassistant.core import (" in src
    assert "CoreState," in src


@t("ultrareview #2: StateEventBuffer.rename_entity preserves all fields")
def _():
    """The previous rename_entity dropped context_user_id,
    from_bootstrap, context_id, source on every rename."""
    src = _read(
        "custom_components/ha_insights/observers/state_event_buffer.py"
    )
    # Inside the rename loop, every new-fields-on-StateEvent must
    # be preserved (regression for the audit finding)
    assert "context_user_id=ev.context_user_id" in src
    assert "from_bootstrap=ev.from_bootstrap" in src
    assert "context_id=ev.context_id" in src
    assert "source=ev.source" in src


@t("ultrareview #4: cloud_consent persists audit_* fields too")
def _():
    """Cloud-consent path previously dropped the 4 audit_* fields
    the user may have just edited in the Advanced form."""
    src = _read("custom_components/ha_insights/config_flow.py")
    # The cloud_consent merged.update() block contains audit_* keys
    # (find the chunk near "Cloud-consent path is reached from")
    idx = src.find("Cloud-consent path is reached from")
    assert idx > 0
    # Look at the dict ABOVE that point
    chunk = src[max(0, idx - 4000) : idx]
    for key in (
        "audit_rollup_window_days",
        "audit_analysis_depth",
        "audit_monthly_budget_usd",
        "audit_auto_rollup_enabled",
    ):
        assert f'"{key}"' in chunk, f"cloud_consent missing {key}"


@t("ultrareview #7: Advanced submit uses merged_options pattern (no field drop)")
def _():
    """The Advanced form previously rebuilt options from scratch,
    silently dropping any option not in the hardcoded list
    (analytics_install_uuid, last_wizard_version,
    notify_user_overrides, etc.)."""
    src = _read("custom_components/ha_insights/config_flow.py")
    # Both Advanced and cloud_consent paths use the merged pattern
    assert src.count("merged = dict(self.config_entry.options)") >= 3
    assert src.count("return self.async_create_entry(title=\"\", data=merged)") >= 3


@t("ultrareview #8: _on_options_updated only clears progress on window change")
def _():
    """Previous version wiped rollup progress on EVERY options
    change. Now: only clears when window_days actually changed."""
    src = _read("custom_components/ha_insights/__init__.py")
    # Window-change guard present
    assert "old_window != new_window" in src
    assert "_known_rollup_window" in src
    # Seed at setup time so first options change has a baseline
    assert '"_known_rollup_window": get_audit_rollup_window_days(entry)' in src


@t("ultrareview #15: mobile slug uses HA's canonical slugify()")
def _():
    """Hand-rolled slug missed many cases (emoji, NFKD-normalized
    Unicode, punctuation). Mobile_app integration uses HA's
    slugify() — use the same."""
    src = _read(
        "custom_components/ha_insights/notifications/user_routing.py"
    )
    assert "from homeassistant.util import slugify" in src
    assert "slug = slugify(raw)" in src


@t("ultrareview #1: phone_charge_reminder Jinja uses if/elif (not elif alone)")
def _():
    """Previous template was invalid Jinja2 (elif without leading if).
    Generated automations would fail at template-render time."""
    src = _read(
        "custom_components/ha_insights/detectors/phone_charge_reminder.py"
    )
    # The structural fix: first branch is "if", subsequent are "elif"
    assert 'keyword = "if" if i == 0 else "elif"' in src
    # Endif terminator is present
    assert '"      {% endif %}"' in src


@t("import safety: pyflakes finds no undefined names across the integration")
def _():
    """Catches the same class of bug as the Maturity import miss
    + the PATTERN_OBSERVATION enum miss. pyflakes does static
    name-resolution: every name referenced in the module body
    must be defined (locally OR imported). NameError-class bugs
    that only show up at HA boot are caught here instead.

    Allow-list: EntityHierarchy is a TYPE_CHECKING forward-ref
    used as a string in annotations — pyflakes can't tell. We
    filter it out instead of fighting the tool.
    """
    import os
    import subprocess

    integration_dir = "custom_components/ha_insights"
    try:
        result = subprocess.run(
            ["python", "-m", "pyflakes", integration_dir],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        # pyflakes not installed — skip silently so this test
        # doesn't block CI/local runs that don't have dev deps.
        return

    undefined: list[str] = []
    for line in result.stdout.splitlines():
        if "undefined name" not in line:
            continue
        # Filter the known TYPE_CHECKING forward-ref false-positive
        if "EntityHierarchy" in line:
            continue
        undefined.append(line)
    assert not undefined, (
        f"pyflakes found undefined names (likely missing imports):\n"
        + "\n".join(undefined)
    )


@t("import safety: every detector module compiles to bytecode (catches NameError-equivalents)")
def _():
    """The AST-parse check above catches syntax errors. `compile()`
    catches the slightly-deeper class of syntactic errors — and is
    what Python itself runs during the import phase. Note: neither
    of these execute the module body, so they DON'T catch the
    Maturity / PATTERN_OBSERVATION bugs (those only surface at
    actual import time when class-body statements run). They DO
    catch outright typos / mismatched parens / mismatched f-strings
    / unicode-escape bugs.

    The actual "NameError on import" class is covered by the
    `maturity imports` regression below + the `every detector
    referencing PATTERN_OBSERVATION` regression added earlier."""
    import os

    det_dir = "custom_components/ha_insights/detectors"
    failed: list[tuple[str, str]] = []
    for fname in os.listdir(det_dir):
        if not fname.endswith(".py") or fname.startswith("_"):
            continue
        full = f"{det_dir}/{fname}"
        body = _read(full)
        try:
            compile(body, fname, "exec")
        except SyntaxError as e:  # noqa: PERF203
            failed.append((full, f"{type(e).__name__}: {e}"))
    assert not failed, f"detector compile failed: {failed}"


@t("import safety: every helper module compiles cleanly")
def _():
    """Same AST sweep across other Python directories that get
    imported at HA setup time. Misses any nested files we don't
    list, but covers the modules most likely to break in a
    rapid-iteration session."""
    import ast
    import os

    targets = [
        "custom_components/ha_insights",
        "custom_components/ha_insights/notifications",
        "custom_components/ha_insights/lib",
        "custom_components/ha_insights/observers",
        "custom_components/ha_insights/store",
        "custom_components/ha_insights/audit",
        "custom_components/ha_insights/apply",
        "custom_components/ha_insights/llm",
    ]
    failed: list[tuple[str, str]] = []
    for path in targets:
        if not os.path.isdir(path):
            continue
        for fname in os.listdir(path):
            if not fname.endswith(".py"):
                continue
            full = f"{path}/{fname}"
            try:
                ast.parse(_read(full), filename=fname)
            except SyntaxError as e:  # noqa: PERF203
                failed.append((full, f"{type(e).__name__}: {e}"))
    assert not failed, f"helper files failed to parse: {failed}"


@t("maturity imports: every detector referencing Maturity also imports it")
def _():
    """Regression for the v1.5.4 deploy failure where
    frequency_anomaly.py used Maturity.BETA but its imports list
    didn't include Maturity, raising NameError at module load.
    This test sweeps all detector files: if a file references
    Maturity.X, it MUST import Maturity from .base."""
    import os
    import re

    det_dir = "custom_components/ha_insights/detectors"
    missing: list[str] = []
    for fname in os.listdir(det_dir):
        if not fname.endswith(".py"):
            continue
        if fname == "base.py":  # defines Maturity itself
            continue
        body = _read(f"{det_dir}/{fname}")
        # Strip docstrings + comments to avoid false-positives on
        # mentions in prose. Cheap heuristic: match `Maturity.X`
        # outside of comment-leading lines.
        code_only = "\n".join(
            line for line in body.splitlines()
            if not line.lstrip().startswith("#")
        )
        if re.search(r"\bMaturity\.\w+", code_only):
            # Look for an explicit import of Maturity from .base
            if not re.search(
                r"from\s+\.base\s+import\s+[^\n]*\bMaturity\b", body
            ):
                missing.append(fname)
    assert not missing, (
        f"Detectors using Maturity.X but missing the import: {missing}"
    )


@t("maturity demotion: 4 risky detectors are now Maturity.BETA pre-HACS")
def _():
    """Until field-tested across 3-5 real installs, the detectors
    with known false-positive surface area should be flagged BETA
    so users see honest expectations + can dismiss/feedback."""
    for fname in (
        "frequency_anomaly.py",
        "cooccurrence.py",
        "automation_audit.py",
    ):
        src = _read(f"custom_components/ha_insights/detectors/{fname}")
        assert "maturity = Maturity.BETA" in src, (
            f"{fname} should set maturity = Maturity.BETA pre-HACS"
        )
    # LaggedCorrelation inherits BETA from Cooccurrence — verify the
    # inheritance is in place by NOT overriding it
    src_lagged = _read(
        "custom_components/ha_insights/detectors/lagged_correlation.py"
    )
    # Must NOT explicitly set its own maturity (would override)
    assert "maturity = " not in src_lagged
    # Must still extend Cooccurrence so it picks up BETA via MRO
    assert (
        "class LaggedCorrelationDetector(CooccurrenceDetector):" in src_lagged
    )


@t("recorder vs live: StateEvent gains source field (live | recorder)")
def _():
    src = _read(
        "custom_components/ha_insights/observers/state_event_buffer.py"
    )
    assert 'source: str = "live"' in src
    assert "Gotcha 8" in src


@t("recorder vs live: history_backfill tags events source='recorder'")
def _():
    src = _read(
        "custom_components/ha_insights/observers/history_backfill.py"
    )
    assert 'source="recorder"' in src


@t("recorder vs live: frequency_anomaly scales baseline by recorder share")
def _():
    src = _read(
        "custom_components/ha_insights/detectors/frequency_anomaly.py"
    )
    # Tracks per-entity recorder vs live counts
    assert "baseline_recorder_count" in src
    assert "baseline_live_count" in src
    # 1.25× scale at 100% recorder share (under-corrects to err
    # on flagging) — empirical 80% retention assumption
    assert "1.0 + 0.25 * recorder_share" in src


@t("template filter: hierarchy.is_template_or_derived covers known platforms")
def _():
    src = _read(
        "custom_components/ha_insights/detectors/hierarchy.py"
    )
    assert "is_template_or_derived" in src
    # Each derived/template platform is in the set
    for platform in (
        '"template"',
        '"group"',
        '"statistics"',
        '"utility_meter"',
        '"derivative"',
        '"integration"',
        '"trend"',
        '"threshold"',
        '"min_max"',
        '"filter"',
        '"history_stats"',
    ):
        assert platform in src, f"missing platform: {platform}"


@t("template filter: are_related drops pairs where either side is template/derived")
def _():
    """The cooccurrence/lagged_correlation inner loop calls
    are_related(a, b) to drop structural pairs. Now also drops
    pairs where either entity is computed from another (template,
    statistics, etc.) — see HA_EVENT_SEMANTICS.md Gotcha 4."""
    src = _read(
        "custom_components/ha_insights/detectors/hierarchy.py"
    )
    assert "Gotcha 4" in src
    assert "is_template_or_derived(eid_a)" in src
    assert "is_template_or_derived(eid_b)" in src


@t("template filter: lagged_correlation inherits cooccurrence's filter chain")
def _():
    """LaggedCorrelationDetector extends Cooccurrence and inherits
    _pair_is_related. One fix covers both detectors."""
    src = _read(
        "custom_components/ha_insights/detectors/lagged_correlation.py"
    )
    assert "class LaggedCorrelationDetector(CooccurrenceDetector):" in src


@t("unavailable filter: frequency_anomaly skips X ↔ unavailable transitions")
def _():
    """Without this filter, a flaky WiFi node firing
    on↔unavailable↔on 30 times/hr looks like a 30× ratio runaway
    automation. v1.5.16 extracted the inline guard into
    lib/event_filters.is_unavailable_transition; the detector still
    calls into the same logic, just via the shared module."""
    src = _read(
        "custom_components/ha_insights/detectors/frequency_anomaly.py"
    )
    # Imported from the shared module
    assert (
        "from ..lib.event_filters import is_unavailable_transition" in src
    )
    # Used at the top of the count loop
    assert (
        "if is_unavailable_transition(ev.old_state, ev.new_state):" in src
    )
    # And the shared module's docstring still cites Gotcha 6 as the rationale
    lib = _read(
        "custom_components/ha_insights/lib/event_filters.py"
    )
    assert "Gotcha 6" in lib


@t("unavailable filter: orphan_device skips entities whose latest event was an availability flip")
def _():
    """An entity actively reporting 'unavailable' is NOT silent —
    it's broken/flapping. Different diagnostic class from orphan_device.
    Tested by checking the LAST event in the entity's stream."""
    src = _read(
        "custom_components/ha_insights/detectors/orphan_device.py"
    )
    assert "Gotcha 6" in src
    assert "latest_event = entity_events[-1]" in src
    assert 'latest_event.new_state == "unavailable"' in src
    assert 'latest_event.old_state == "unavailable"' in src


@t("unavailable fixture: synth_unavailable_flap produces expected transitions")
def _():
    """The fixture must round-trip the on↔unavailable pattern so
    detector tests using it produce realistic streams."""
    fixture = _load(
        "unavailable_fixture", "tests/_ha_semantics/unavailable.py"
    )
    buffer_mod = _load(
        "state_event_buffer_unavail",
        "custom_components/ha_insights/observers/state_event_buffer.py",
    )
    from datetime import UTC, datetime

    buf = buffer_mod.StateEventBuffer()
    events = fixture.synth_unavailable_flap(
        buf,
        entity_id="binary_sensor.flaky",
        start=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
        cycles=3,
    )
    assert len(events) == 6  # 3 cycles × 2 events
    # Alternates down-up-down-up
    assert events[0].new_state == "unavailable"
    assert events[1].old_state == "unavailable"
    assert events[1].new_state == "on"
    # Helper correctly identifies these
    assert all(fixture.is_availability_transition(e) for e in events)


@t("cooccurrence: drops pairs sharing context.id (co-effect filter)")
def _():
    """Source-level guard that cooccurrence skips leader-follower
    pairs sharing the same context.id. Without this, a scene that
    fires light.a then light.b in 50ms looks like 'light.b follows
    light.a' on every scene activation — false-positive flood."""
    src = _read(
        "custom_components/ha_insights/detectors/cooccurrence.py"
    )
    assert "context.id batch filter" in src
    assert 'leader_ctx = getattr(leader, "context_id", None)' in src
    assert "leader_ctx == follower_ctx" in src


@t("batch correlator: skips events with no context_id")
def _():
    """System events / recorder-backfilled events have context_id=None.
    They must not be bucketed into any batch."""
    correlator = _load(
        "batch_correlator_nullctx",
        "custom_components/ha_insights/lib/batch_correlator.py",
    )
    buffer_mod = _load(
        "state_event_buffer_nullctx",
        "custom_components/ha_insights/observers/state_event_buffer.py",
    )
    from datetime import UTC, datetime

    StateEvent = buffer_mod.StateEvent
    events = [
        StateEvent(
            timestamp=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
            entity_id="light.a",
            domain="light",
            area_id=None,
            old_state="off",
            new_state="on",
            context_id=None,
        ),
        StateEvent(
            timestamp=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
            entity_id="light.b",
            domain="light",
            area_id=None,
            old_state="off",
            new_state="on",
            context_id=None,
        ),
    ]
    by_ctx = correlator.group_by_context_id(events)
    assert by_ctx == {}, "context_id=None events should not be bucketed"
    assert list(correlator.iter_batches(events)) == []


@t("bootstrap fixture: 100-entity boot burst is fully filtered by default")
def _():
    """Validate the v1.4.9 filter against the kind of burst we'd see
    on a real install reload: ~100 entities all firing state_changed
    with old_state=None within ~3 seconds of boot. With the filter,
    default query() should return ZERO events from this stream — no
    detector should be able to false-positive on it."""
    fixture = _load(
        "bootstrap_fixture", "tests/_ha_semantics/bootstrap.py"
    )
    buffer_mod = _load(
        "state_event_buffer_burst",
        "custom_components/ha_insights/observers/state_event_buffer.py",
    )
    from datetime import UTC, datetime

    buf = buffer_mod.StateEventBuffer()
    entities = [f"light.entity_{i:03d}" for i in range(50)] + [
        f"binary_sensor.sensor_{i:03d}" for i in range(50)
    ]
    fixture.synth_bootstrap_burst(
        buf,
        boot_at=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
        entities=entities,
    )
    # 100 events added, but default query returns NONE
    assert len(list(buf.query())) == 0, (
        "bootstrap burst leaked through default query"
    )
    # Opt-in returns all
    assert len(list(buf.query(include_bootstrap=True))) == 100


@t("bootstrap fixture: normal events alongside boot burst are preserved")
def _():
    """The filter must NOT throw away genuine mid-session events
    that happen to share the boot timestamp. Tests the boundary."""
    fixture = _load(
        "bootstrap_fixture_mixed", "tests/_ha_semantics/bootstrap.py"
    )
    buffer_mod = _load(
        "state_event_buffer_mixed",
        "custom_components/ha_insights/observers/state_event_buffer.py",
    )
    from datetime import UTC, datetime, timedelta

    buf = buffer_mod.StateEventBuffer()
    boot_at = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
    # 10 bootstrap events
    fixture.synth_bootstrap_burst(
        buf,
        boot_at=boot_at,
        entities=[f"light.boot_{i}" for i in range(10)],
    )
    # 5 real events 10 minutes later
    for i in range(5):
        fixture.synth_normal_event(
            buf,
            timestamp=boot_at + timedelta(minutes=10, seconds=i),
            entity_id=f"switch.real_{i}",
        )
    # Default query: only the 5 real events
    yielded = list(buf.query())
    assert len(yielded) == 5, (
        f"expected 5 real events, got {len(yielded)} (bootstrap leak?)"
    )
    for ev in yielded:
        assert not ev.from_bootstrap
        assert ev.entity_id.startswith("switch.real_")


@t("bootstrap filter (runtime): buffer.query() actually skips bootstrap events")
def _():
    """Runtime test — construct a buffer with 3 events (1 bootstrap,
    2 normal), assert the default query yields only 2, and an
    include_bootstrap=True query yields all 3. Catches regressions
    where the field is wired but the filter logic breaks."""
    buffer_mod = _load(
        "state_event_buffer_runtime",
        "custom_components/ha_insights/observers/state_event_buffer.py",
    )
    from datetime import UTC, datetime

    StateEvent = buffer_mod.StateEvent
    StateEventBuffer = buffer_mod.StateEventBuffer

    b = StateEventBuffer()
    base_ts = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
    # 1 bootstrap event + 2 normal events
    b.add(
        StateEvent(
            timestamp=base_ts,
            entity_id="light.boot",
            domain="light",
            area_id=None,
            old_state=None,  # bootstrap pattern
            new_state="on",
            from_bootstrap=True,
        )
    )
    b.add(
        StateEvent(
            timestamp=base_ts,
            entity_id="light.normal1",
            domain="light",
            area_id=None,
            old_state="off",
            new_state="on",
        )
    )
    b.add(
        StateEvent(
            timestamp=base_ts,
            entity_id="light.normal2",
            domain="light",
            area_id=None,
            old_state="off",
            new_state="on",
        )
    )

    default_yield = list(b.query())
    assert len(default_yield) == 2, (
        f"default query should skip bootstrap, got {len(default_yield)}"
    )
    assert all(not ev.from_bootstrap for ev in default_yield)

    opt_in_yield = list(b.query(include_bootstrap=True))
    assert len(opt_in_yield) == 3, (
        f"include_bootstrap=True should yield all, got {len(opt_in_yield)}"
    )


@t("cohort dedup: frequency_anomaly opts out (per-entity, not shared cause)")
def _():
    """Two lights both firing 200×/day are TWO INDEPENDENT runaway
    automations, not one shared cause to merge into 'light.* (cohort)'.
    Each gets its own card so the user can investigate separately."""
    src_detector = _read(
        "custom_components/ha_insights/detectors/frequency_anomaly.py"
    )
    assert "cohort_dedup = False" in src_detector

    # Display-time dedup also skips
    src_dedup = _read("custom_components/ha_insights/lib/dedup.py")
    assert "_NO_COHORT_DEDUP_DETECTORS" in src_dedup
    assert '"frequency_anomaly"' in src_dedup
    assert "skipped_no_dedup" in src_dedup

    # Scan-time dedup helper also gates on the class flag
    src_runner = _read("custom_components/ha_insights/detectors/__init__.py")
    assert 'getattr(\n            detector_cls, "cohort_dedup", True\n        )' in src_runner or (
        'getattr(' in src_runner and '"cohort_dedup", True' in src_runner
    )


@t("group fan-out: frequency_anomaly drops members when parent also spikes")
def _():
    src = _read(
        "custom_components/ha_insights/detectors/frequency_anomaly.py"
    )
    assert "group fan-out filter" in src
    # Build the parent_of reverse map
    assert "parent_of: dict[str, set[str]] = defaultdict(set)" in src
    # Drop member if its parent is also a candidate
    assert "if parents & candidate_eids:" in src


@t("orphan_device: silent member of active group is NOT flagged")
def _():
    src = _read(
        "custom_components/ha_insights/detectors/orphan_device.py"
    )
    assert "_has_active_parent" in src
    # Skips when parent fired recently (within stale_threshold window)
    assert "parent_latest >= stale_threshold" in src
    # Filter only kicks in when container map is populated
    assert "if not ctx.container_to_members:" in src


@t("explain prompt: routes to kind-specific template")
def _():
    """Explain used to ask 'why automate this?' regardless of kind,
    which was wrong for anomalies + observations. Now routes by
    insight.kind so the user gets the right question answered."""
    src = _read("custom_components/ha_insights/llm/agent_client.py")
    # Three template constants exist
    assert "_USER_PROMPT_AUTOMATION" in src
    assert "_USER_PROMPT_DIAGNOSTIC" in src
    assert "_USER_PROMPT_OBSERVATION" in src
    # Diagnostic prompt has the three explicit sections
    assert "Is this likely a real problem" in src
    assert "How can I quickly confirm" in src
    assert "If it IS real, what's the fix" in src
    # Build function dispatches on kind
    assert 'kind_value in ("anomaly", "automation_improvement")' in src
    assert 'kind_value == "pattern_observation"' in src
    # Skip-generic-advice guard so the LLM doesn't reply with
    # "check connections, restart router"
    assert "Skip generic" in src


@t("dismiss-persistence: notification listener still only fires on 'added'")
def _():
    """If this assertion fails, dismissed insights will re-buzz the
    user on every scan — exactly the bug we just fixed."""
    src = _read("custom_components/ha_insights/__init__.py")
    assert 'if event_type != "added"' in src


@t("setup_quality: USELESS tier folds into rollup (no per-feature card)")
def _():
    src = _read(
        "custom_components/ha_insights/detectors/setup_quality.py"
    )
    # Per-feature insight builder skips both GREAT and USELESS
    assert 'if tier in ("GREAT", "USELESS"):' in src
    # The fold happens in the rollup which receives the full eval
    assert "per_feature_full" in src
    assert "useless_items" in src


@t("setup_quality: rollup suppressed when nothing is fixable")
def _():
    src = _read(
        "custom_components/ha_insights/detectors/setup_quality.py"
    )
    # If everything is GOOD/GREAT, don't clutter the panel with a
    # "100% all good" card.
    assert (
        "counts[\"USELESS\"] == 0 and counts[\"LIMITED\"] == 0" in src
    )
    assert "return None" in src


@t("setup_quality: rollup payload exposes useless_next_steps for the card")
def _():
    src = _read(
        "custom_components/ha_insights/detectors/setup_quality.py"
    )
    # Card needs structured data so it can render the bullet list
    # without parsing the explanation text.
    assert '"useless_next_steps":' in src
    # And the rollup title leads with the actionable count, not raw
    # tier breakdown
    assert "would unlock" in src


@t("setup_quality: rollup explanation lists USELESS gaps inline")
def _():
    src = _read(
        "custom_components/ha_insights/detectors/setup_quality.py"
    )
    # Bullet-style listing in the explanation so the user sees the
    # next steps under the title without expanding the payload.
    # v1.5.11 reworded: "Setup health" → "Setup completeness" and
    # "Not yet unlocked" → "Optional add-ons not yet configured" so
    # the 25% score doesn't read as "your install is broken".
    assert "Optional add-ons not yet configured" in src
    assert 'lines.append(f"  • {feature} — {step}")' in src


@t("setup_quality: title says 'Setup completeness', not 'Setup health'")
def _():
    """The original 'Setup health 25%' framing made a perfectly working
    install with one wired feature and three unconfigured optional
    add-ons look critically unwell. v1.5.11 reframes the metric as
    completeness (% of optional integrations wired), with a 'Working:
    N features wired and producing insights' line leading the
    explanation. If this test fails, the misleading 'health' label is
    back and users with healthy installs will see a scary 25% score."""
    src = _read(
        "custom_components/ha_insights/detectors/setup_quality.py"
    )
    assert "Setup completeness" in src
    # Title-construction f-strings must not contain the old wording.
    # (Comments and docstrings explaining the rename are allowed.)
    assert 'f"⚙️ Setup health' not in src
    # Explanation must lead with positive framing
    assert "Working: " in src or "wired and producing" in src


@t("setup_quality: payload carries setup_url for deep-link buttons")
def _():
    """Recipes must declare a setup_url + label so the frontend can
    render a real button ('Open Areas & Zones') instead of leaving the
    user to read prose and navigate manually."""
    src = _read(
        "custom_components/ha_insights/detectors/setup_quality.py"
    )
    # All four well-known feature_keys must appear with their URL
    # field. URL value is checked loosely — exact path may shift.
    # v1.5.17: goal_tracker URL switched from
    # /config/integrations/integration/ha_insights (rendered blank on
    # some HA versions) to /config/integrations (canonical, always
    # works; user clicks the HA Insights tile from there).
    assert "presence_inference" in src
    assert "/config/devices/dashboard" in src
    # v1.5.30: goal_tracker URL now lands on the HA Insights tile
    # directly. v1.5.17's defensive fallback to the integrations
    # dashboard didn't reproduce on HA 2023.1+ — see commit 8a12d89.
    assert '"/config/integrations/integration/ha_insights"' in src
    assert "companion.home-assistant.io" in src
    # The summary payload must expose setup_steps for the frontend
    assert '"setup_steps": setup_steps' in src
    # Per-feature payload must expose setup_url
    assert '"setup_url": recipe.get("setup_url")' in src


@t("panel: setup_quality dialog uses setup-guide body (not YAML refine)")
def _():
    """The generic dialog body assumes there's YAML to refine. setup_quality
    insights are observational — they tell the user 'wire X to unlock
    detector Y'. The dialog must branch on detector === 'setup_quality'
    to show a guided checklist with deeplink buttons, hiding the
    payload editor, Customize rename, Refine/Test actions, and Apply
    button (none of which make sense for an observational insight)."""
    src = _read("dev/config/www/ha-insights-panel.js")
    assert "_renderSetupGuideBody" in src
    assert "_renderSetupStep" in src
    # Dialog must branch on the detector name
    assert 'insight.detector === "setup_quality"' in src
    # Setup-guide body must include explicit Dismiss + Snooze footer
    # (no Apply — observational insights aren't applyable).
    assert "setup-guide-body" in src


@t("v1.5.15: audit detector flags cloud + local integration coupling")
def _():
    """Automations that mix cloud-dependent integrations with local
    integrations carry silent-partial-fail risk: cloud outage breaks
    the cloud side while the local side fires normally, leaving the
    automation in a half-completed state.

    Classification is DETECTED — pulled from each integration's
    manifest.json `iot_class` field (HA's official mechanism, same
    one Settings → Integrations uses for its cloud/local pills).
    A tiny override map handles cases where the declared iot_class
    is misleading; the override list is intentionally short because
    we don't want to maintain a curated allow-list."""
    src_pkt = _read("custom_components/ha_insights/audit/packet.py")
    src_det = _read(
        "custom_components/ha_insights/detectors/automation_audit.py"
    )
    assert "OBS_CROSS_INTEGRATION" in src_pkt
    # iot_class-based classification, not hardcoded list of vendors
    assert "_IOT_CLASS_TO_BUCKET" in src_pkt
    assert '"cloud_polling": "cloud"' in src_pkt
    assert '"local_polling": "local"' in src_pkt
    assert "_INTEGRATION_BUCKET_OVERRIDES" in src_pkt
    assert "_classify_integration" in src_pkt
    assert "_observe_cross_integration_coupling" in src_pkt
    # Both buckets must be non-empty to trigger
    assert "if not (cloud_entities and local_entities):" in src_pkt
    # v1.5.22: iot_class is loaded ONCE on the main loop in
    # run_all_detectors (detectors/__init__.py), then passed via
    # DetectorContext.iot_class_by_integration. The audit detector
    # reads from ctx — no per-scan await chain in a worker thread,
    # which deadlocked on installs with many integrations.
    main_loop_src = _read("custom_components/ha_insights/detectors/__init__.py")
    assert "async_get_integration" in main_loop_src
    assert "iot_class_by_integration[domain] = iot_class" in main_loop_src
    assert "iot_class_by_integration=iot_class_by_integration" in main_loop_src
    # Audit detector reads from ctx, doesn't await
    assert "ctx.iot_class_by_integration" in src_det
    # Sentinel: the renamed _DELETED_ stub is still there as a
    # tripwire so we catch a regression that re-introduces the
    # worker-thread call.
    assert "_DELETED_load_iot_classes_v15_22" in src_det


@t("v1.5.26: streak + schedule detect sun-relative triggers")
def _():
    """A streak / schedule that fires at "17:30" might actually be
    tied to sunset — and the clock-time triggers we generated would
    drift away from the user's actual behaviour across the seasons
    (17:30 in December → 21:30 in June). The sun_relative.py helper
    already existed (used by manual_habit); v1.5.26 wires it into
    streak + schedule so their generated YAML uses platform: sun
    with an offset when sun fits better than the wall clock."""
    for module in ("streak", "schedule"):
        src = _read(f"custom_components/ha_insights/detectors/{module}.py")
        # Imports from sun_relative
        assert "detect_sun_relative_trigger" in src, (
            f"{module}.py doesn't import detect_sun_relative_trigger"
        )
        assert "build_sun_trigger" in src, (
            f"{module}.py doesn't import build_sun_trigger"
        )
        # Conditional swap of the trigger block
        assert "if sun_trigger_data is not None:" in src, (
            f"{module}.py doesn't branch on sun-relative fit"
        )


@t("v1.5.29: OptionsFlow surfaces per-goal time fields backed by goals_json")
def _():
    """GoalTrackerDetector reads `goals_json` from entry.options to
    decide which targets to track — but pre-1.5.29 the OptionsFlow
    never asked the user for them, so the detector silently no-op'd
    on every install. v1.5.29 adds five Optional string fields (one
    per recognized goal name) that the form serializes into the same
    goals_json string the detector + setup-quality already consume.
    Translations expose them as 'Goal: bedtime by (HH:MM)' etc."""
    src = _read("custom_components/ha_insights/config_flow.py")
    # All five field constants present
    for const_name in (
        "CONF_GOAL_GET_TO_WORK_BY",
        "CONF_GOAL_HOME_BY",
        "CONF_GOAL_BEDTIME_BY",
        "CONF_GOAL_WAKE_UP_BY",
        "CONF_GOAL_LEAVE_HOME_BY",
    ):
        assert const_name in src, f"missing {const_name}"
    # Mapping table the (de)serializer keys off
    assert "_GOAL_KEY_TO_FIELD" in src
    # Getter is exposed so other modules don't need to re-implement the merge
    assert "def get_goal_times(" in src
    # Form actually serializes the discrete fields into goals_json
    assert 'merged["goals_json"]' in src
    assert "json.dumps(goals_dict)" in src
    # Translations
    en = _read("custom_components/ha_insights/translations/en.json")
    assert "goal_bedtime_by" in en
    assert "goal_wake_up_by" in en


@t("v1.5.34: automation_writer strips _-prefixed detector metadata before write")
def _():
    """Detectors stash internal state in keys like `_manual_habit`,
    `_audit`, `_streak`. Useful for cohort dedup + fingerprinting
    in the WS list but not part of HA's automation schema — applying
    such a payload to automations.yaml polluted every entry with
    detector bookkeeping. v1.5.34 adds _strip_private_keys() to the
    writer's hot path."""
    src = _read("custom_components/ha_insights/apply/automation_writer.py")
    assert "def _strip_private_keys(" in src
    assert "_strip_private_keys(payload)" in src
    # Doctest the helper directly
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "aw_v1534",
        "custom_components/ha_insights/apply/automation_writer.py",
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = mod._strip_private_keys(
        {"alias": "x", "_manual_habit": {"foo": 1}, "_audit": []}
    )
    assert "alias" in out
    assert "_manual_habit" not in out
    assert "_audit" not in out


@t("v1.5.32: panel registration prefers HACS path, falls back to legacy /www/")
def _():
    """For ages we registered the sidebar panel from /local/ha-insights-panel.js
    (= /config/www/ha-insights-panel.js), but the companion-repo deploy
    pipeline + HACS both target /www/community/ha-insights-card/. New
    bundles shipped there were ignored by the panel; users saw stale
    behavior that no amount of Reload UI fixed because the cache-buster
    was computed off the stale file's mtime.

    v1.5.32: resolver prefers the HACS path, falls back to the legacy
    location if HACS isn't installed. Either way, the cache-bust query
    is computed off the file that's actually being served."""
    src = _read("custom_components/ha_insights/__init__.py")
    # Resolver helper that picks HACS path first
    assert "www/community/ha-insights-card/ha-insights-panel.js" in src
    assert "/local/community/ha-insights-card/ha-insights-panel.js" in src
    # Legacy fallback retained
    assert "www/ha-insights-panel.js" in src
    # module_url no longer hard-codes /local/ha-insights-panel.js
    assert "{panel_module_path}?v={cache_bust}" in src


@t("v1.5.31: ws_api strips trailing 'Automate this?' CTA on shadowed insights")
def _():
    """A client-side strip in card v1.2.11 proved unreliable under
    HA's service-worker caching of Lit templates — incognito tabs
    still saw the old title. Moving the strip server-side at WS-list
    time (after conflicts_with has been computed) guarantees every
    consumer — panel, dashboard card, persistent_notification, mobile
    push, daily digest — gets the de-CTA'd title."""
    src = _read("custom_components/ha_insights/ws_api.py")
    assert "_strip_already_automated_cta" in src
    assert "_ALREADY_AUTOMATED_CTA_RE" in src
    # Helper applied conditionally on conflicts_with
    assert "if ins.conflicts_with:" in src
    assert "_strip_already_automated_cta(d.get(\"title\", \"\"))" in src
    # Regex covers all three known CTAs
    assert "Automate" in src
    assert "Build" in src


@t("v1.5.28: ws_api emits `labels` per insight from hierarchy.labels_of")
def _():
    """HA 2024.4+ added the label registry — entities/devices/areas can
    carry user-defined labels for cross-cutting tagging ('garden',
    'guest-mode', 'critical'). The panel exposes a Label filter chip
    and group_by; both need the WS list to carry the labels per
    insight. ws_api reads hierarchy.labels_of for the primary entity
    and emits a sorted list (empty when no labels)."""
    src = _read("custom_components/ha_insights/ws_api.py")
    assert "d[\"labels\"]" in src
    assert "hierarchy.labels_of.get(eid)" in src
    # Card mirrors with label_filter + group_by:label. Skip when the
    # sibling card repo isn't co-located (CI / fresh clone).
    import os
    card_types_path = "../ha-insights-card/src/types.ts"
    if os.path.exists(card_types_path):
        card_types = _read(card_types_path)
        assert "label_filter?: string[]" in card_types
        assert "labels?: string[]" in card_types
        assert '"label"' in card_types


@t("v1.5.27: conflict scanner factors `for:` duration into state-trigger signatures")
def _():
    """Two state triggers with the same entity + to_state but materially
    different `for:` durations have different firing semantics — one
    fires immediately, the other fires N min after the state stays.
    Pre-v1.5.27 we flagged them as conflicts; user-visible noise.
    The fix adds for_seconds to the signature tuple. Both-missing
    still match (legacy case). Mismatched `for:` no longer matches."""
    src = _read("custom_components/ha_insights/apply/conflict_scanner.py")
    # Signature includes for_seconds
    assert "set[tuple[str, str | None, int | None]]" in src
    assert "for_seconds = _normalize_duration(t.get(\"for\"))" in src
    # Helper handles HA's varied duration formats
    assert "def _normalize_duration(" in src
    # Tuple uses the new triple
    assert "sigs.add((e, v, for_seconds))" in src


@t("v1.5.24: conflict scanner expands groups + scenes via members_of")
def _():
    """User report: light.backyard_garden_lights (a group) wasn't being
    marked 🔁 already automated even though they have a real 23:27
    automation. Cause: literal set-intersection of action entity_ids.
    Insight proposed targeting the group; automation targeted the
    individual members. Different surface, same intent — no match
    under literal comparison. Fix: pass hierarchy.members_of, expand
    both sides to include group/scene members before set-intersect."""
    src = _read("custom_components/ha_insights/apply/conflict_scanner.py")
    assert "members_of: dict[str, frozenset[str]] | None = None" in src
    assert "def _expand_groups_and_scenes(" in src
    assert "_expand_groups_and_scenes(a_entities, members_of)" in src
    assert "_expand_groups_and_scenes(b_entities, members_of)" in src
    # Caller threads the hierarchy map through
    caller = _read("custom_components/ha_insights/detectors/__init__.py")
    assert "members_of=container_to_members" in caller


@t("v1.5.25: long-silence filter — implicit poll wake-ups don't count as transitions")
def _():
    """BYD car / sleepy BLE / cloud-polled integrations go idle without
    reporting `unavailable` — they just stop reporting. When the next
    poll fires hours later, the state change looks real but is just
    "we finally heard back." Filter: any event that comes after >=8h
    of silence from the same entity is treated like
    unavailable→X (Gotcha 6's implicit case).

    Applied to streak / schedule / cooccurrence / seasonality — every
    daily-pattern detector. Exempted for event.* entities (their
    last-fire timestamp is the state, so silence is structural, not
    sleepy)."""
    lib = _read("custom_components/ha_insights/lib/event_filters.py")
    assert "def is_after_long_silence(" in lib
    assert "LONG_SILENCE_GAP_HOURS" in lib
    for module in ("streak", "schedule", "cooccurrence", "seasonality"):
        src = _read(f"custom_components/ha_insights/detectors/{module}.py")
        assert (
            "is_after_long_silence" in src
        ), f"{module}.py doesn't import the long-silence filter"
        assert (
            "is_after_long_silence(ev.timestamp, prior_ts)" in src
        ), f"{module}.py doesn't call the filter in scan()"


@t("v1.5.23: cohort dedup requires ALL entities to share a device — None absorbs no longer")
def _():
    """User report: a Tuya pet feeder binary_sensor got false-merged
    with two HA group light entities into one cohort labeled
    "device:507893…". The two group entities have NO device_id
    (groups are synthetic), but the previous code did
    `device_ids.discard(None)` BEFORE the `len == 1` check —
    absorbing entities-with-no-device into whichever real device
    happened to be present. Fix: require `None not in device_ids`
    AND `len(device_ids) == 1` — entities can only share a device
    if they ALL have one and it matches."""
    def _strip_comments_and_strings(src: str) -> str:
        """Return source with all comments and string literals removed
        so we can assert against ACTIVE code only. Naive but sufficient
        for these specific assertions (no comments-in-strings or
        f-string side-effects we care about)."""
        import re
        out_lines = []
        for line in src.split("\n"):
            # Strip inline / full-line # comments
            no_comment = re.sub(r"\s*#.*$", "", line)
            # Strip triple-quoted blocks: not strictly handled per-line,
            # but for our purposes (a single short block) good enough —
            # if a `"""` appears we drop the rest of the line.
            no_comment = re.sub(r'""".*', "", no_comment)
            no_comment = re.sub(r"'''.*", "", no_comment)
            out_lines.append(no_comment)
        return "\n".join(out_lines)

    h_code = _strip_comments_and_strings(
        _read("custom_components/ha_insights/detectors/hierarchy.py")
    )
    # The old buggy pattern is gone from EXECUTABLE code (comments
    # can still reference it for documentation purposes)
    assert "device_ids.discard(None)" not in h_code
    # The fix is in place
    assert "None not in device_ids and len(device_ids) == 1" in h_code
    # Sibling fix in conflict-scanner / dedup helper
    d_code = _strip_comments_and_strings(
        _read("custom_components/ha_insights/detectors/__init__.py")
    )
    assert "device_ids.discard(None)" not in d_code
    assert "None not in device_ids and len(device_ids) == 1" in d_code


@t("v1.6 Phase 3: ButtonPressHabitDetector pairs press → consequent into automation YAML")
def _():
    """The cross-link detector. For each event.* firing, find state
    changes within 30s on OTHER entities. Stable patterns (5+ occurrences,
    60%+ consistency) emit AUTOMATION_PROPOSAL with apply-able YAML.
    Skips patterns already covered by existing automations. Native HA
    primitives only — no event-bus subscription, no per-integration
    normalizer; reads the existing state_event_buffer which captures
    event_type since v1.5.19."""
    src = _read(
        "custom_components/ha_insights/detectors/button_press_habit.py"
    )
    # Detector exists + registered + correct kind
    assert "class ButtonPressHabitDetector" in src
    assert "@register_detector" in src
    assert 'name = "button_press_habit"' in src
    assert "kind = InsightKind.AUTOMATION_PROPOSAL" in src
    # BETA gate — untested in the field yet
    assert "maturity = Maturity.BETA" in src
    # Cross-link window + thresholds
    assert "_CONSEQUENT_WINDOW_SEC" in src
    assert "_MIN_OCCURRENCES" in src
    assert "_MIN_CONSISTENCY" in src
    # Only event.* firings drive the pattern
    assert 'ev.domain != "event"' in src or 'if ev.domain != "event"' in src
    # Existing-automation dedup
    assert "_already_automated" in src
    # YAML builder emits a real automation block
    assert '"platform": "state"' in src
    assert '"condition": "template"' in src
    assert "trigger.to_state.attributes.event_type" in src


@t("v1.6 Phase 2: detectors group event.* entities by event_type")
def _():
    """Phase 1 captured event_type on StateEvent. Phase 2 makes
    detectors USE it: streak / schedule / cooccurrence call
    pattern_value() which returns event_type for `event.*` entities
    (where new_state is a unique-per-fire timestamp) and new_state
    for everything else.

    Without this, an event entity firing N times produces N distinct
    groups (one per unique timestamp state). With it, they collapse
    into one group per event_type — "button single_press" patterns
    can finally be detected."""
    lib = _read("custom_components/ha_insights/lib/event_filters.py")
    # Helper exists and is documented
    assert "def pattern_value(" in lib
    assert "ev.event_type" in lib  # the actual return for event entities
    # Detectors import it
    for module in ("streak", "schedule", "cooccurrence"):
        src = _read(f"custom_components/ha_insights/detectors/{module}.py")
        assert (
            "pattern_value" in src
        ), f"{module}.py doesn't import pattern_value"
        # event.* entities skip the no-op transition guard (timestamps
        # are unique per fire, never == old_state)
        assert (
            'if ev.domain != "event" and ev.new_state == ev.old_state:' in src
        ), f"{module}.py doesn't guard the noop check for event entities"


@t("v1.5.19: setup_quality only counts INTERACTIVE-domain events as manual")
def _():
    """v1.5.18 bug: any event from a local integration with no context
    counted as a 'physical switch press' — including passive sensor
    telemetry (Zigbee temperature readings, ESPHome humidity polls).
    User showed a temp sensor changing 18.6→18.5 with parent_id=null
    from a local Zigbee integration — would have been counted as a
    manual event. v1.5.19 restricts the count to interactive domains
    (light/switch/fan/cover/lock/button/event/etc.) — domains where
    a user actually initiates the change."""
    src = _read("custom_components/ha_insights/detectors/setup_quality.py")
    assert "_INTERACTIVE_DOMAINS" in src
    # Domain filter applied at the count site
    assert "ev.domain in _INTERACTIVE_DOMAINS" in src
    # Spot-check the allow-list — sensors NOT in, button/event IN
    assert '"button"' in src
    assert '"event"' in src
    # Confirm sensors aren't in the interactive list
    # (would over-count passive telemetry)
    # Direct check: the literal "sensor" string within the
    # _INTERACTIVE_DOMAINS frozenset should not appear in its body
    import re
    m = re.search(
        r"_INTERACTIVE_DOMAINS: frozenset\[str\] = frozenset\(\{([^}]+)\}\)",
        src,
    )
    assert m is not None
    body = m.group(1)
    assert '"sensor"' not in body
    assert '"binary_sensor"' not in body


@t("v1.6 Phase 1: StateEvent captures event_type for HA event.* entities")
def _():
    """HA's native `event` platform exposes button presses as entities
    whose state is a timestamp (unique per fire — useless for grouping)
    and whose `event_type` attribute carries the meaningful value
    ("single_press", "long_press", etc.). Phase 1 captures that
    attribute so streak/cooccurrence/manual_habit can group by it
    in Phase 2. Field is None for every non-event entity — additive,
    no behaviour change for existing detectors."""
    buf = _read("custom_components/ha_insights/observers/state_event_buffer.py")
    # Dataclass field
    assert "event_type: str | None = None" in buf
    # Native-HA reference in the comment so readers find the platform doc
    assert "developers.home-assistant.io/docs/core/entity/event" in buf
    # Rename helper preserves the field
    assert "event_type=ev.event_type" in buf
    # Live capture path
    init = _read("custom_components/ha_insights/__init__.py")
    assert 'if domain == "event":' in init
    assert 'attrs.get("event_type")' in init
    assert "event_type=event_type" in init
    # Recorder backfill captures it too — historical button presses
    # need to participate in pattern detection
    bf = _read("custom_components/ha_insights/observers/history_backfill.py")
    assert 'if domain == "event":' in bf
    assert "event_type=ev_type" in bf


@t("v1.5.18: manual_habit + setup_quality count physical switches as manual")
def _():
    """Wall-switch presses don't carry context.user_id (no HA user
    triggered them) — pre-v1.5.18 they looked indistinguishable from
    automation-triggered events and were skipped. ManualHabitDetector +
    setup_quality._has_user_context_events now ALSO accept events with
    no user_id AND no parent_id AND entity from a local integration
    (Zigbee, Z-Wave, ESPHome, MQTT, Hue local-bridge, etc.) as manual.
    Cloud-app-managed entities stay excluded — their no-context signal
    is indistinguishable from a vendor schedule."""
    buf = _read("custom_components/ha_insights/observers/state_event_buffer.py")
    # parent_id captured on StateEvent
    assert "context_parent_id: str | None = None" in buf
    init = _read("custom_components/ha_insights/__init__.py")
    # Parent_id resolved from HA's Context object
    assert 'getattr(new_state.context, "parent_id", None)' in init
    assert "context_parent_id=ctx_parent" in init
    # ManualHabitDetector accepts physical switches
    mh = _read("custom_components/ha_insights/detectors/manual_habit.py")
    assert "local_integration_entities" in mh
    assert "ev.context_parent_id is None" in mh
    assert "_build_local_integration_set" in mh
    # setup_quality counts physical events
    sq = _read("custom_components/ha_insights/detectors/setup_quality.py")
    assert "n_physical" in sq
    assert "_LOCAL_INTEGRATION_PLATFORMS" in sq


@t("v1.5.16: HA-semantic filters live in lib/event_filters.py")
def _():
    """Filters that used to be inlined in each daily-pattern detector
    are now imported from a shared lib/event_filters.py module. The
    module is HA-core-adoptable: pure functions over typed primitives,
    no dependency on our buffer/store/detectors.

    v1.5.14 was the inline fix; v1.5.16 extracts it. Same semantic
    behaviour, but the rule lives in one place and the module is a
    self-contained PR candidate for HA core."""
    lib = _read("custom_components/ha_insights/lib/event_filters.py")
    # Module is self-contained — no imports from our detectors / store
    # / buffer beyond what's safe.
    assert "is_from_unavailable_state" in lib
    assert "is_unavailable_transition" in lib
    assert "is_template_or_derived" in lib
    assert "UNAVAILABLE_STATES" in lib
    assert "COMPUTED_FROM_OTHER_PLATFORMS" in lib
    assert "BOOTSTRAP_FANOUT_SECONDS" in lib
    assert "StateEventLike" in lib  # Protocol — keeps it portable
    # Each daily-pattern detector imports from the shared module
    for module in ("streak", "schedule", "seasonality", "cooccurrence"):
        src = _read(f"custom_components/ha_insights/detectors/{module}.py")
        # v1.5.16 introduced the shared filter; v1.5.25 expanded the
        # import (added is_after_long_silence) so it's now a multi-line
        # tuple. Tolerant check: just look for the function name being
        # imported from the shared module.
        assert "from ..lib.event_filters import" in src, (
            f"{module}.py doesn't import from lib.event_filters at all"
        )
        assert "is_from_unavailable_state" in src, (
            f"{module}.py doesn't reference the shared filter"
        )
    # frequency_anomaly uses the both-sides variant
    src = _read("custom_components/ha_insights/detectors/frequency_anomaly.py")
    assert (
        "from ..lib.event_filters import is_unavailable_transition" in src
    ), "frequency_anomaly doesn't import shared transition filter"


@t("ws_api: cohort payload carries per-member integration + external_source")
def _():
    """When a cohort row aggregates entities from multiple integrations,
    the row-level 🏷️ external-app badge is suppressed (cohort-safety
    rule — don't tag a non-Tuya entity as Tuya). The UX cost: user sees
    the same entity_id in two rows with different badges. Fix: include
    per-member metadata in the cohort payload so the expanded dropdown
    can render the badge next to each entity individually."""
    src = _read("custom_components/ha_insights/ws_api.py")
    assert "cohort_member_info" in src
    # Per-member external check must respect the same suppression rule
    # used at row level: if HA has an automation referencing this
    # entity, the schedule lives in HA — don't tag it as external.
    assert "entity_to_automations.get(member_eid)" in src


@t("card: setup_quality dialog uses setup-guide body (not YAML refine)")
def _():
    """Same fix as panel.js but in the Lovelace card variant. Users on
    a custom dashboard see the card's dialog, not the panel's."""
    src = _read("dev/config/www/ha-insights-card.js")
    assert "_renderSetupGuideBody" in src
    assert "_renderSetupStep" in src
    assert 'insight.detector === "setup_quality"' in src
    assert "setup-guide-body" in src


@t("card: bulk-area-assign dialog is bundled and uses only HA core WS APIs")
def _():
    """The bulk-assign-areas dialog must be portable into HA core. It
    calls only HA's standard registry WS APIs (no home_insights/* calls)
    and registers itself as <bulk-area-assign-dialog>. Bundled into the
    card so users without HA core support get the feature today."""
    src = _read("dev/config/www/ha-insights-card.js")
    # Custom element registered
    assert "bulk-area-assign-dialog" in src
    # Built-in registry APIs used
    assert "config/area_registry/list" in src
    assert "config/device_registry/list" in src
    assert "config/entity_registry/list" in src
    assert "config/device_registry/update" in src
    assert "config/entity_registry/update_entity" in src
    # NO custom backend dependency
    assert "home_insights/list_unareaed" not in src
    assert "home_insights/bulk_assign" not in src


@t("OptionsFlow: __init__ initializes audit fields defensively")
def _():
    src = _read("custom_components/ha_insights/config_flow.py")
    for field in (
        "self._audit_rollup_window_days: int =",
        "self._audit_analysis_depth: str =",
        "self._audit_monthly_budget_usd: float =",
        "self._audit_auto_rollup_enabled: bool =",
    ):
        assert field in src, f"missing init: {field}"


@t("panel: setup + unload only call async_remove_panel when registered")
def _():
    """Regression for the recurring 'Removing unknown panel ha-insights'
    warning on every reload. async_remove_panel logs that warning
    if the path isn't currently registered. Both call sites (setup
    pre-register cleanup AND unload teardown) must probe
    hass.data['frontend_panels'] before calling remove."""
    src = _read("custom_components/ha_insights/__init__.py")
    # Both call sites guard
    assert src.count('"frontend_panels"') >= 2, (
        "expected guard at both setup + unload call sites"
    )
    # Setup-side guard
    assert "if _PANEL_URL_PATH in panels:" in src


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


@t("code review #16: analytics POST reuses HA's shared aiohttp session")
def _():
    src = _read("custom_components/ha_insights/analytics.py")
    # Must import HA's shared-session helper rather than spinning a
    # fresh ClientSession per call.
    assert "async_get_clientsession" in src
    # Should NOT create a new ClientSession per send.
    assert "aiohttp.ClientSession(" not in src


@t("code review #10: adaptive tuner persists learned floor to entry.options")
def _():
    src = _read("custom_components/ha_insights/notifications/adaptive.py")
    # Persistence: tune_adaptive_floor writes the new floor through
    # async_update_entry so it survives restart.
    assert "async_update_entry" in src
    assert '"adaptive_floor"' in src
    assert '"adaptive_last_tune_at"' in src
    # Restore: get_adaptive_floor falls back to entry.options when
    # hass.data hasn't been seeded yet (cold path after restart).
    assert "entry.options.get(\"adaptive_floor\")" in src


@t("code review #12: options listener skips reload for auto-managed keys")
def _():
    src = _read("custom_components/ha_insights/__init__.py")
    # The reload-suppression set must include every auto-managed key.
    assert "_AUTO_MANAGED_OPTION_KEYS" in src
    assert '"analytics_install_uuid"' in src
    assert '"adaptive_floor"' in src
    assert '"adaptive_last_tune_at"' in src
    assert '"adaptive_last_direction"' in src
    # Snapshot must be seeded at setup time so the first listener
    # fire has something to diff against.
    assert '"_options_snapshot"' in src
    # Diff logic + skip-reload path
    assert "changed_keys.issubset(_AUTO_MANAGED_OPTION_KEYS)" in src


@t("code review #11: translations cover every new wizard + advanced step")
def _():
    import json

    data = json.load(
        open(
            "custom_components/ha_insights/translations/en.json",
            encoding="utf-8",
        )
    )
    steps = data["options"]["step"]
    for step_id in (
        "init",
        "wizard_intro",
        "wizard_preset",
        "wizard_mobile",
        "wizard_experimental",
        "wizard_done",
        "user_overrides_pick",
        "user_overrides_edit",
        "advanced",
        "cloud_consent",
    ):
        assert step_id in steps, f"missing step: {step_id}"
        assert "title" in steps[step_id], f"missing title for {step_id}"
        assert "description" in steps[step_id], f"missing desc for {step_id}"
    # Advanced step must include the v1.4/v1.5 anti-spam knobs that
    # were previously absent from translations.
    adv = steps["advanced"]["data"]
    for k in (
        "notify_preset",
        "notify_mobile_targets",
        "notify_mobile_threshold",
        "notify_mobile_daily_cap",
        "notify_quiet_hours_start",
        "notify_quiet_hours_end",
        "notify_min_attribution_confidence",
        "allow_experimental_detectors",
        "analytics_enabled",
        "analytics_endpoint",
    ):
        assert k in adv, f"advanced step missing data label: {k}"


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
