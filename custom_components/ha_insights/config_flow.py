"""Config flow for HA Insights — three-mode privacy wizard.

Step 1: pick LLM mode (Off / Local / Cloud).
Step 2 (cloud only): explicit consent that pseudonymized data leaves the network.

OptionsFlow mirrors the same two steps so users can switch modes after
initial install without removing + re-adding the integration.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback

from .const import DOMAIN

CONF_LLM_MODE = "llm_mode"
CONF_CLOUD_CONSENT = "cloud_consent"
CONF_LOOKBACK_DAYS = "lookback_days"
# Storage key kept as "llm_block_entities" for backwards compat with existing
# installs, but as of v1.1 this list is honored by the SCAN PIPELINE TOO —
# blocked entities never enter a detector's input set. Closes the privacy
# gap users assumed already existed ("block this entity" now = "don't
# scan AND don't send to LLM").
CONF_LLM_BLOCK_ENTITIES = "llm_block_entities"
# v1.1: limit detectors to events from a specific subset of HA areas. Empty
# = all areas (today's behavior). Multi-select against the area registry.
CONF_SCAN_AREAS = "scan_areas"
# v1.1: per-detector enable/disable. Stored as a list of detector NAMES
# (matches DETECTORS dict keys: "schedule", "long_tail", etc.). None /
# missing key = "all enabled" (back-compat — installs upgraded from v1.0
# don't get any detectors silently disabled).
CONF_ENABLED_DETECTORS = "enabled_detectors"
# v1.1: periodic auto-scan in hours. 0 = manual-only (today's behavior;
# user must click Run Scan Now). 1+ = registered as
# async_track_time_interval after EVENT_HOMEASSISTANT_STARTED.
CONF_SCAN_INTERVAL_HOURS = "scan_interval_hours"
DEFAULT_SCAN_INTERVAL_HOURS = 0
SCAN_INTERVAL_HOURS_RANGE = (0, 168)  # 0 = off, up to weekly
CONF_NOTIFY_ON_INSIGHT = "notify_on_insight"
CONF_NOTIFY_THRESHOLD = "notify_threshold"
# Comma-separated list of `notify.*` service names that should receive
# new high-confidence insight pushes (mobile-app integration). Empty
# string = disabled, persistent_notification only. Time-critical
# insights need to reach the user's pocket; users don't sit on the
# panel waiting.
CONF_NOTIFY_MOBILE_TARGETS = "notify_mobile_targets"
DEFAULT_NOTIFY_MOBILE_TARGETS = ""
CONF_DIGEST_ENABLED = "digest_enabled"
CONF_DIGEST_HOUR = "digest_hour"
# v0.9 phase 9: per-install LLM agent preference. Empty string / None means
# "auto-pick" (Assist default first, then registry order). Otherwise this
# entity_id is tried first; failover still kicks in on its failure.
CONF_PREFERRED_AGENT_ID = "preferred_agent_id"
CONF_REFINE_COST_THRESHOLD_USD = "refine_cost_threshold_usd"
DEFAULT_REFINE_COST_THRESHOLD_USD = 0.05
# v1.0 review #3: user-supplied detectors are arbitrary Python that runs
# with full HA process privileges. Default off; the user must explicitly
# opt in via OptionsFlow before the loader picks anything up. AST scan
# adds a forbidden-imports check on top of the opt-in.
CONF_ALLOW_USER_DETECTORS = "allow_user_detectors"
DEFAULT_ALLOW_USER_DETECTORS = False
DEFAULT_LOOKBACK_DAYS = 14
LOOKBACK_DAYS_RANGE = (0, 30)  # 0 disables backfill entirely
DEFAULT_NOTIFY_ON_INSIGHT = True
DEFAULT_NOTIFY_THRESHOLD = 0.8
DEFAULT_DIGEST_ENABLED = True
DEFAULT_DIGEST_HOUR = 9
DIGEST_HOUR_RANGE = (0, 23)


class LlmMode(StrEnum):
    """LLM enrichment mode chosen at setup time."""

    OFF = "off"
    LOCAL = "local"
    CLOUD = "cloud"


_MODE_LABELS: dict[str, str] = {
    LlmMode.OFF.value: "Off — pattern detection only, no LLM",
    LlmMode.LOCAL.value: "Local LLM — data stays on your network",
    LlmMode.CLOUD.value: "Cloud LLM — pseudonymized data sent off-network",
}


def get_active_mode(entry: ConfigEntry) -> str:
    """Resolve the currently-active mode (options override data)."""
    return entry.options.get(
        CONF_LLM_MODE, entry.data.get(CONF_LLM_MODE, LlmMode.OFF.value)
    )


def get_audit_rollup_window_days(entry: ConfigEntry) -> int:
    """How many days of HA recorder history to materialize into the
    audit_rollups cache. Drives seasonal / day-of-week / month-of-year
    observation accuracy.

    Default 90 — enough to detect quarter-scale patterns without
    requiring the user to extend HA recorder beyond its default
    10-day retention. Bump to 365+ when the user has a year of
    recorder data and wants real seasonal detection
    (e.g. "heater only fires Nov-Mar").

    Range 7..180. The hard upper bound is intentionally tight while
    we don't yet have chunked backfill (v1.2). `get_significant_states`
    returns the whole window in one allocation, and `asyncio.wait_for`
    only cancels the awaiter, not the executor thread — so an over-
    sized query can still spike memory and OOM a Pi-class install
    even though the per-entity timeout fires. Lift to 730 in v1.2
    once we page the recorder week-by-week.
    """
    raw = entry.options.get("audit_rollup_window_days", 90)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 90
    return max(7, min(180, value))


def get_audit_analysis_depth(entry: ConfigEntry) -> str:
    """Verbosity of the audit_suggest / refine LLM prompts.

    "concise" (default) — ~150 token rules, minimal framing. Cheap.
    "indepth" — ~600 token rules with examples, requested reasoning
        steps, deeper regression checks. Better answers on tricky
        automations; ~4× more input tokens per call.

    Returned as a plain string so callers can compare directly.
    """
    raw = entry.options.get("audit_analysis_depth", "concise")
    return raw if raw in ("concise", "indepth") else "concise"


def get_audit_auto_rollup_enabled(entry: ConfigEntry) -> bool:
    """Whether the periodic auto-rollup scheduler is enabled.

    Default OFF. Auto-rollup runs the chunked incremental backfill
    every 6 hours so seasonal/day-of-week buckets stay fresh without
    the user needing to click 📅 Run audit rollup. Bounded by all
    the v1.2 safety rails (per-chunk timeout, per-entity wall clock,
    per-batch budget, single-flight lock, row-cap), but it's still
    background recorder I/O — opt-in respects users who prefer zero
    background load.
    """
    raw = entry.options.get("audit_auto_rollup_enabled", False)
    return bool(raw)


def get_audit_monthly_budget_usd(entry: ConfigEntry) -> float:
    """USD/month cap for the AutomationAudit background suggest
    batch. Default $5, range 0..50. Setting to 0 effectively
    disables the batch endpoint — the single-click 🤖 Suggest still
    works for explicit user actions."""
    raw = entry.options.get("audit_monthly_budget_usd", 5.0)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 5.0
    return max(0.0, min(50.0, value))


def get_lookback_days(entry: ConfigEntry) -> int:
    """Resolve the configured backfill lookback (options override data)."""
    raw = entry.options.get(
        CONF_LOOKBACK_DAYS,
        entry.data.get(CONF_LOOKBACK_DAYS, DEFAULT_LOOKBACK_DAYS),
    )
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_LOOKBACK_DAYS
    lo, hi = LOOKBACK_DAYS_RANGE
    return max(lo, min(hi, value))


def get_notify_settings(entry: ConfigEntry) -> tuple[bool, float]:
    """Resolve notification settings: (enabled, threshold).

    Threshold is clamped to [0, 1]. enabled defaults to True; users opt
    out via the OptionsFlow.
    """
    enabled_raw = entry.options.get(
        CONF_NOTIFY_ON_INSIGHT,
        entry.data.get(CONF_NOTIFY_ON_INSIGHT, DEFAULT_NOTIFY_ON_INSIGHT),
    )
    threshold_raw = entry.options.get(
        CONF_NOTIFY_THRESHOLD,
        entry.data.get(CONF_NOTIFY_THRESHOLD, DEFAULT_NOTIFY_THRESHOLD),
    )
    try:
        threshold = float(threshold_raw)
    except (TypeError, ValueError):
        threshold = DEFAULT_NOTIFY_THRESHOLD
    threshold = max(0.0, min(1.0, threshold))
    return bool(enabled_raw), threshold


def get_notify_mobile_targets(entry: ConfigEntry) -> list[str]:
    """Resolve the list of `notify.mobile_app_*` services to push new
    insights to. Returns an empty list when disabled.

    Stored as a comma- or whitespace-separated string in options so the
    OptionsFlow stays a simple text field; parsed here into the
    de-duplicated list the notifier consumes. Bad entries (missing
    `notify.` prefix) are dropped silently — `mobile.py` also guards
    so an empty list is a pure no-op.
    """
    raw = entry.options.get(
        CONF_NOTIFY_MOBILE_TARGETS,
        entry.data.get(
            CONF_NOTIFY_MOBILE_TARGETS, DEFAULT_NOTIFY_MOBILE_TARGETS
        ),
    )
    if not raw:
        return []
    text = str(raw).replace("\n", ",").replace(";", ",")
    seen: set[str] = set()
    out: list[str] = []
    for entry_raw in text.split(","):
        target = entry_raw.strip()
        if not target:
            continue
        if not target.startswith("notify."):
            continue
        if target in seen:
            continue
        seen.add(target)
        out.append(target)
    return out


def get_allow_user_detectors(entry: ConfigEntry) -> bool:
    """Resolve whether <config>/ha_insights_detectors/*.py files load.

    Off by default — user must opt in. Even when on, the loader's AST
    scan rejects modules with forbidden imports.
    """
    raw = entry.options.get(
        CONF_ALLOW_USER_DETECTORS,
        entry.data.get(CONF_ALLOW_USER_DETECTORS, DEFAULT_ALLOW_USER_DETECTORS),
    )
    return bool(raw)


def get_refine_cost_threshold(entry: ConfigEntry) -> float:
    """Resolve the per-Refine USD cost threshold above which the card
    prompts for confirmation. Clamped to [0, 10] — 0 means always confirm
    (cloud), 10 means effectively never. Local agents always cost $0 so
    the threshold never triggers there.
    """
    raw = entry.options.get(
        CONF_REFINE_COST_THRESHOLD_USD,
        entry.data.get(
            CONF_REFINE_COST_THRESHOLD_USD, DEFAULT_REFINE_COST_THRESHOLD_USD
        ),
    )
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_REFINE_COST_THRESHOLD_USD
    return max(0.0, min(10.0, value))


def get_preferred_agent_id(entry: ConfigEntry) -> str | None:
    """Resolve the user's persistent preferred LLM agent (or None for auto).

    Stored as an entity_id string in either entry.options or entry.data.
    Empty strings normalize to None so the auto-pick path runs cleanly.
    """
    raw = entry.options.get(
        CONF_PREFERRED_AGENT_ID,
        entry.data.get(CONF_PREFERRED_AGENT_ID),
    )
    if not isinstance(raw, str):
        return None
    raw = raw.strip()
    return raw or None


def get_digest_settings(entry: ConfigEntry) -> tuple[bool, int]:
    """Resolve daily-digest settings: (enabled, hour).

    Hour clamped to [0, 23]; enabled defaults to True. Users opt out via
    OptionsFlow. Hour is interpreted in HA's configured timezone.
    """
    enabled_raw = entry.options.get(
        CONF_DIGEST_ENABLED,
        entry.data.get(CONF_DIGEST_ENABLED, DEFAULT_DIGEST_ENABLED),
    )
    hour_raw = entry.options.get(
        CONF_DIGEST_HOUR,
        entry.data.get(CONF_DIGEST_HOUR, DEFAULT_DIGEST_HOUR),
    )
    try:
        hour = int(hour_raw)
    except (TypeError, ValueError):
        hour = DEFAULT_DIGEST_HOUR
    lo, hi = DIGEST_HOUR_RANGE
    hour = max(lo, min(hi, hour))
    return bool(enabled_raw), hour


def get_blocked_entities(entry: ConfigEntry) -> frozenset[str]:
    """Resolve the per-entity opt-out list.

    These entity_ids are NEVER scanned by any detector AND NEVER included
    in any LLM prompt — neither as pseudonyms nor as real values. Privacy
    floor below the redactor's mode-driven behavior. Unified scan + LLM
    scope as of v1.1; storage key (`llm_block_entities`) preserved for
    backwards compat with v1.0 installs.
    """
    raw = entry.options.get(
        CONF_LLM_BLOCK_ENTITIES,
        entry.data.get(CONF_LLM_BLOCK_ENTITIES, []),
    )
    if isinstance(raw, str):
        # Tolerate comma-separated strings from older configs
        items = [s.strip() for s in raw.split(",") if s.strip()]
    elif isinstance(raw, (list, tuple, set, frozenset)):
        items = [str(s).strip() for s in raw if str(s).strip()]
    else:
        items = []
    return frozenset(items)


def get_scan_areas(entry: ConfigEntry) -> frozenset[str]:
    """Resolve the area scope for detector scans.

    Empty set means "all areas" (the default). When non-empty, only events
    whose `area_id` is in the set reach detectors. Useful on large installs
    to limit scan scope to e.g. living areas only.
    """
    raw = entry.options.get(
        CONF_SCAN_AREAS,
        entry.data.get(CONF_SCAN_AREAS, []),
    )
    if isinstance(raw, (list, tuple, set, frozenset)):
        items = [str(s).strip() for s in raw if str(s).strip()]
    else:
        items = []
    return frozenset(items)


def get_enabled_detectors(entry: ConfigEntry) -> frozenset[str] | None:
    """Resolve which detectors are enabled.

    Returns None when the user has never customized this — meaning
    "all registered detectors run" (back-compat for v1.0 installs that
    upgrade in place). Returns a frozenset of detector names when
    customized. Use `is None` checks at call sites; never assume an
    empty frozenset means "all" (it means "none enabled" — valid state
    if the user explicitly disabled every detector).
    """
    raw = entry.options.get(CONF_ENABLED_DETECTORS, entry.data.get(CONF_ENABLED_DETECTORS))
    if raw is None:
        return None
    if isinstance(raw, (list, tuple, set, frozenset)):
        return frozenset(str(s).strip() for s in raw if str(s).strip())
    return None


def get_scan_interval_hours(entry: ConfigEntry) -> int:
    """Resolve the periodic auto-scan interval (0 = manual only)."""
    raw = entry.options.get(
        CONF_SCAN_INTERVAL_HOURS,
        entry.data.get(CONF_SCAN_INTERVAL_HOURS, DEFAULT_SCAN_INTERVAL_HOURS),
    )
    try:
        hours = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_SCAN_INTERVAL_HOURS
    lo, hi = SCAN_INTERVAL_HOURS_RANGE
    return max(lo, min(hi, hours))


def _detector_multiselect(hass: Any, current: list[str] | None) -> Any:
    """Schema field for "which detectors to run" — multi-select dropdown.

    Populated from the live DETECTORS registry. Defaults to "all enabled"
    if the user hasn't customized (None == all). Returns a SelectSelector
    so HA renders it as a multi-pick dropdown with friendly labels.
    """
    try:
        from homeassistant.helpers import selector

        # Lazy import to avoid circular: detectors -> config_flow -> detectors
        from .detectors import DETECTORS

        options = [
            selector.SelectOptionDict(value=name, label=_DETECTOR_LABELS.get(name, name))
            for name in sorted(DETECTORS.keys())
        ]
        return selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=options,
                mode=selector.SelectSelectorMode.DROPDOWN,
                multiple=True,
            )
        )
    except Exception:  # pragma: no cover — defensive fallback
        return list


def _area_multiselect(hass: Any) -> Any:
    """Schema field for "which areas to scan" — empty selection = all.

    AreaSelector handles all the registry lookups + label rendering for
    free; we just configure it for multi-pick.
    """
    try:
        from homeassistant.helpers import selector

        return selector.AreaSelector(
            selector.AreaSelectorConfig(multiple=True)
        )
    except Exception:  # pragma: no cover
        return list


_DETECTOR_LABELS: dict[str, str] = {
    "schedule": "Schedule (time-of-day routines)",
    "seasonality": "Seasonality (weekly patterns)",
    "frequency_anomaly": "Frequency Anomaly (today vs baseline)",
    "streak": "Streak (consecutive on/off days)",
    "long_tail": "Long Tail (entities left on too long)",
    "orphan_device": "Orphan Device (silent for too long)",
    "cooccurrence": "Co-occurrence (B follows A within seconds)",
    "lagged_correlation": "Lagged Correlation (B follows A within minutes)",
}


def _conversation_agent_selector(hass: Any) -> Any:
    """Schema field for the preferred conversation agent.

    Builds a SelectSelector dropdown populated from the entity registry
    at form-show time. Each conversation.* entity becomes an option,
    plus a leading "Auto-pick" empty-value entry. SelectSelector
    serializes cleanly (unlike EntitySelector wrapped in vol.Any),
    avoiding the 500 we hit on the first attempt.

    Falls back to a plain str field if the selector / entity_registry
    APIs aren't importable for some reason — keeps the feature
    functional even if HA's helper module shape drifts.
    """
    try:
        from homeassistant.helpers import entity_registry as er
        from homeassistant.helpers import selector

        registry = er.async_get(hass)
        options: list[Any] = [
            selector.SelectOptionDict(
                value="",
                label="Auto-pick (Assist default + failover)",
            )
        ]
        seen: set[str] = set()
        for reg_entry in sorted(
            registry.entities.values(), key=lambda e: e.entity_id
        ):
            if not reg_entry.entity_id.startswith("conversation."):
                continue
            # Skip the rule-based built-in — it's not a useful LLM choice
            if reg_entry.platform in {"homeassistant", "conversation"}:
                continue
            if reg_entry.entity_id in seen:
                continue
            seen.add(reg_entry.entity_id)
            friendly = (
                reg_entry.name
                or reg_entry.original_name
                or reg_entry.entity_id
            )
            # Prefix with the platform so the dropdown disambiguates between
            # similar entity_ids — e.g. a user with multiple Anthropic and
            # OpenAI models can tell at a glance which line is which without
            # matching tail strings.
            platform = (reg_entry.platform or "").strip()
            platform_label = f"[{platform}] " if platform else ""
            if friendly != reg_entry.entity_id:
                display = f"{platform_label}{friendly} ({reg_entry.entity_id})"
            else:
                display = f"{platform_label}{reg_entry.entity_id}"
            options.append(
                selector.SelectOptionDict(
                    value=reg_entry.entity_id, label=display
                )
            )
        return selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=options,
                mode=selector.SelectSelectorMode.DROPDOWN,
                custom_value=True,  # allow typing an entity_id not in the list
            )
        )
    except Exception:  # pragma: no cover — defensive fallback
        return str


class HaInsightsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Three-mode privacy wizard."""

    VERSION = 1

    def __init__(self) -> None:
        self._mode: LlmMode | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> HaInsightsOptionsFlow:
        return HaInsightsOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Mode selection.

        Multi-entry: each config entry runs an independent insight scope
        (its own store, buffer, panel-shared registry). Most installs run
        one entry; advanced users can add a second for a different area
        filter, lookback window, or LLM agent. We don't set a unique_id
        so HA permits multiple entries side-by-side.
        """
        if user_input is not None:
            self._mode = LlmMode(user_input[CONF_LLM_MODE])
            if self._mode is LlmMode.CLOUD:
                return await self.async_step_cloud_consent()
            return self._create_entry()

        schema = vol.Schema(
            {vol.Required(CONF_LLM_MODE, default=LlmMode.OFF.value): vol.In(_MODE_LABELS)}
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_cloud_consent(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirmation that user understands cloud-LLM data flow."""
        if user_input is not None:
            if user_input.get(CONF_CLOUD_CONSENT):
                return self._create_entry()
            # Refused: bounce back to mode selection
            self._mode = None
            return await self.async_step_user()

        schema = vol.Schema({vol.Required(CONF_CLOUD_CONSENT, default=False): bool})
        return self.async_show_form(step_id="cloud_consent", data_schema=schema)

    def _create_entry(self) -> ConfigFlowResult:
        mode = self._mode or LlmMode.OFF
        return self.async_create_entry(
            title="HA Insights",
            data={
                CONF_LLM_MODE: mode.value,
                CONF_LOOKBACK_DAYS: DEFAULT_LOOKBACK_DAYS,
                CONF_NOTIFY_ON_INSIGHT: DEFAULT_NOTIFY_ON_INSIGHT,
                CONF_NOTIFY_THRESHOLD: DEFAULT_NOTIFY_THRESHOLD,
                CONF_DIGEST_ENABLED: DEFAULT_DIGEST_ENABLED,
                CONF_DIGEST_HOUR: DEFAULT_DIGEST_HOUR,
                CONF_PREFERRED_AGENT_ID: "",
                CONF_REFINE_COST_THRESHOLD_USD: DEFAULT_REFINE_COST_THRESHOLD_USD,
                CONF_ALLOW_USER_DETECTORS: DEFAULT_ALLOW_USER_DETECTORS,
            },
        )


class HaInsightsOptionsFlow(OptionsFlow):
    """In-place mode switcher — Settings -> Devices & Services -> HA Insights -> Configure.

    HA injects `self.config_entry` automatically via the parent class; we
    must NOT set it explicitly (read-only since 2025.12).
    """

    def __init__(self) -> None:
        self._mode: LlmMode | None = None
        self._lookback: int = DEFAULT_LOOKBACK_DAYS
        self._notify_on: bool = DEFAULT_NOTIFY_ON_INSIGHT
        self._notify_threshold: float = DEFAULT_NOTIFY_THRESHOLD
        self._notify_mobile_targets: str = DEFAULT_NOTIFY_MOBILE_TARGETS
        self._digest_enabled: bool = DEFAULT_DIGEST_ENABLED
        self._digest_hour: int = DEFAULT_DIGEST_HOUR
        self._preferred_agent_id: str | None = None
        self._refine_cost_threshold: float = DEFAULT_REFINE_COST_THRESHOLD_USD
        self._allow_user_detectors: bool = DEFAULT_ALLOW_USER_DETECTORS
        self._enabled_detectors: list[str] | None = None
        self._scan_areas: list[str] = []
        self._scan_interval_hours: int = DEFAULT_SCAN_INTERVAL_HOURS

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Mode + lookback + notification picker."""
        current_mode = get_active_mode(self.config_entry)
        current_lookback = get_lookback_days(self.config_entry)
        current_notify_on, current_notify_threshold = get_notify_settings(
            self.config_entry
        )
        current_notify_mobile_targets = ", ".join(
            get_notify_mobile_targets(self.config_entry)
        )
        current_digest_on, current_digest_hour = get_digest_settings(
            self.config_entry
        )
        current_preferred = get_preferred_agent_id(self.config_entry) or ""
        current_refine_threshold = get_refine_cost_threshold(self.config_entry)
        current_allow_user_detectors = get_allow_user_detectors(self.config_entry)
        # Phase B/C/D scan controls. Default to "all detectors run" when the
        # user hasn't customized (preserve v1.0 → v1.1 upgrade behavior).
        current_enabled_detectors = get_enabled_detectors(self.config_entry)
        current_scan_areas = sorted(get_scan_areas(self.config_entry))
        current_scan_interval = get_scan_interval_hours(self.config_entry)
        # v1.1 audit options. All three default-safe when unset.
        current_rollup_window = get_audit_rollup_window_days(self.config_entry)
        current_audit_depth = get_audit_analysis_depth(self.config_entry)
        current_audit_budget = get_audit_monthly_budget_usd(self.config_entry)
        current_auto_rollup = get_audit_auto_rollup_enabled(self.config_entry)
        # When the user has never customized, present "all checked" so they
        # can clearly see what's on; the underlying CONF_ENABLED_DETECTORS
        # remains None (== all) until they explicitly drop a checkbox.
        try:
            from .detectors import DETECTORS as _DETECTORS  # noqa: N811

            all_detector_names = sorted(_DETECTORS.keys())
        except Exception:
            all_detector_names = []
        if current_enabled_detectors is None:
            enabled_default = all_detector_names
        else:
            enabled_default = sorted(current_enabled_detectors)

        if user_input is not None:
            self._mode = LlmMode(user_input[CONF_LLM_MODE])
            self._lookback = int(user_input.get(CONF_LOOKBACK_DAYS, current_lookback))
            self._notify_on = bool(
                user_input.get(CONF_NOTIFY_ON_INSIGHT, current_notify_on)
            )
            self._notify_threshold = float(
                user_input.get(CONF_NOTIFY_THRESHOLD, current_notify_threshold)
            )
            self._notify_mobile_targets = str(
                user_input.get(
                    CONF_NOTIFY_MOBILE_TARGETS,
                    current_notify_mobile_targets,
                )
            )
            self._digest_enabled = bool(
                user_input.get(CONF_DIGEST_ENABLED, current_digest_on)
            )
            self._digest_hour = int(
                user_input.get(CONF_DIGEST_HOUR, current_digest_hour)
            )
            preferred_raw = user_input.get(
                CONF_PREFERRED_AGENT_ID, current_preferred
            )
            self._preferred_agent_id = (
                str(preferred_raw).strip() or None
                if isinstance(preferred_raw, str)
                else None
            )
            self._refine_cost_threshold = float(
                user_input.get(
                    CONF_REFINE_COST_THRESHOLD_USD, current_refine_threshold
                )
            )
            self._allow_user_detectors = bool(
                user_input.get(
                    CONF_ALLOW_USER_DETECTORS, current_allow_user_detectors
                )
            )
            # Phase B: enabled detectors. If the user submits exactly the
            # same set as "all known detectors", store None to keep the
            # back-compat semantics (None == all). Otherwise store the
            # user's explicit list.
            raw_enabled = user_input.get(CONF_ENABLED_DETECTORS, enabled_default)
            if isinstance(raw_enabled, (list, tuple, set, frozenset)):
                normalized = sorted(str(s) for s in raw_enabled)
                if normalized == all_detector_names:
                    self._enabled_detectors = None
                else:
                    self._enabled_detectors = normalized
            else:
                self._enabled_detectors = None
            # Phase C: area scope.
            raw_areas = user_input.get(CONF_SCAN_AREAS, current_scan_areas)
            self._scan_areas = (
                [str(s) for s in raw_areas]
                if isinstance(raw_areas, (list, tuple, set, frozenset))
                else []
            )
            # Phase D: scan interval (hours).
            self._scan_interval_hours = int(
                user_input.get(CONF_SCAN_INTERVAL_HOURS, current_scan_interval)
            )
            # v1.1 audit options — stored as plain string keys (no CONF_*
            # constant) since getters look them up by literal name.
            self._audit_rollup_window_days = int(
                user_input.get(
                    "audit_rollup_window_days", current_rollup_window
                )
            )
            self._audit_analysis_depth = str(
                user_input.get(
                    "audit_analysis_depth", current_audit_depth
                )
            )
            self._audit_monthly_budget_usd = float(
                user_input.get(
                    "audit_monthly_budget_usd", current_audit_budget
                )
            )
            self._audit_auto_rollup_enabled = bool(
                user_input.get(
                    "audit_auto_rollup_enabled", current_auto_rollup
                )
            )
            if self._mode is LlmMode.CLOUD and current_mode != LlmMode.CLOUD.value:
                # Only require fresh consent if switching INTO cloud
                return await self.async_step_cloud_consent()
            return self.async_create_entry(
                title="",
                data={
                    CONF_LLM_MODE: self._mode.value,
                    CONF_LOOKBACK_DAYS: self._lookback,
                    CONF_NOTIFY_ON_INSIGHT: self._notify_on,
                    CONF_NOTIFY_THRESHOLD: self._notify_threshold,
                    CONF_NOTIFY_MOBILE_TARGETS: self._notify_mobile_targets,
                    CONF_DIGEST_ENABLED: self._digest_enabled,
                    CONF_DIGEST_HOUR: self._digest_hour,
                    CONF_PREFERRED_AGENT_ID: self._preferred_agent_id or "",
                    CONF_REFINE_COST_THRESHOLD_USD: self._refine_cost_threshold,
                    CONF_ALLOW_USER_DETECTORS: self._allow_user_detectors,
                    CONF_ENABLED_DETECTORS: self._enabled_detectors,
                    CONF_SCAN_AREAS: self._scan_areas,
                    CONF_SCAN_INTERVAL_HOURS: self._scan_interval_hours,
                    "audit_rollup_window_days": self._audit_rollup_window_days,
                    "audit_analysis_depth": self._audit_analysis_depth,
                    "audit_monthly_budget_usd": self._audit_monthly_budget_usd,
                    "audit_auto_rollup_enabled": self._audit_auto_rollup_enabled,
                },
            )

        lo, hi = LOOKBACK_DAYS_RANGE
        schema = vol.Schema(
            {
                vol.Required(CONF_LLM_MODE, default=current_mode): vol.In(_MODE_LABELS),
                vol.Required(
                    CONF_LOOKBACK_DAYS, default=current_lookback
                ): vol.All(vol.Coerce(int), vol.Range(min=lo, max=hi)),
                # Notification settings are Optional so existing config-flow
                # callers (and tests written before they were added) continue
                # to work without specifying them; defaults track current.
                vol.Optional(
                    CONF_NOTIFY_ON_INSIGHT, default=current_notify_on
                ): bool,
                vol.Optional(
                    CONF_NOTIFY_THRESHOLD, default=current_notify_threshold
                ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
                # Mobile push targets — comma-separated `notify.*` service
                # names (e.g. "notify.mobile_app_iphone, notify.mobile_app_pixel").
                # Empty disables mobile push; the persistent_notification
                # always fires. Time-critical insights need to reach the
                # user's phone, not just the panel.
                vol.Optional(
                    CONF_NOTIFY_MOBILE_TARGETS,
                    default=current_notify_mobile_targets,
                ): str,
                vol.Optional(
                    CONF_DIGEST_ENABLED, default=current_digest_on
                ): bool,
                vol.Optional(
                    CONF_DIGEST_HOUR, default=current_digest_hour
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=DIGEST_HOUR_RANGE[0], max=DIGEST_HOUR_RANGE[1]),
                ),
                # Preferred agent — dropdown of conversation.* entities
                # built from the registry. Empty value => auto-pick
                # (Assist default + failover).
                vol.Optional(
                    CONF_PREFERRED_AGENT_ID, default=current_preferred
                ): _conversation_agent_selector(self.hass),
                # Per-Refine cost threshold. Estimates over this trigger a
                # confirm dialog in the card. Local agents always cost $0
                # so the threshold never blocks them. 0 = always confirm,
                # 10 = effectively never.
                vol.Optional(
                    CONF_REFINE_COST_THRESHOLD_USD,
                    default=current_refine_threshold,
                ): vol.All(
                    vol.Coerce(float), vol.Range(min=0.0, max=10.0)
                ),
                # Custom-detector loader is gated off by default. Users
                # opting in have read the security note and accept that
                # arbitrary Python from <config>/ha_insights_detectors/
                # will run with full HA process privileges (subject to
                # the AST sandbox).
                vol.Optional(
                    CONF_ALLOW_USER_DETECTORS,
                    default=current_allow_user_detectors,
                ): bool,
                # Phase B: per-detector enable/disable. Defaults to the
                # full set when the user hasn't customized; explicit
                # selection persists their choice. If the user selects
                # exactly all known detectors, we treat that as "default"
                # (stores None) so future-added detectors are auto-enabled.
                vol.Optional(
                    CONF_ENABLED_DETECTORS, default=enabled_default
                ): _detector_multiselect(self.hass, enabled_default),
                # Phase C: area scope. Empty = all areas (default).
                vol.Optional(
                    CONF_SCAN_AREAS, default=current_scan_areas
                ): _area_multiselect(self.hass),
                # Phase D: periodic auto-scan. 0 = manual only (default
                # for v1.0 → v1.1 upgrades). 1 = every hour, etc.
                vol.Optional(
                    CONF_SCAN_INTERVAL_HOURS, default=current_scan_interval
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(
                        min=SCAN_INTERVAL_HOURS_RANGE[0],
                        max=SCAN_INTERVAL_HOURS_RANGE[1],
                    ),
                ),
                # v1.1 audit: how many days of recorder history to roll
                # up into seasonal / day-of-week buckets. Clamped 7..180
                # to keep get_significant_states allocations bounded
                # until v1.2 chunked backfill ships. 90 = default —
                # detects quarter-scale patterns; 180 catches half-year
                # rhythms; <30 mostly disables seasonal observations.
                vol.Optional(
                    "audit_rollup_window_days",
                    default=current_rollup_window,
                ): vol.All(
                    vol.Coerce(int), vol.Range(min=7, max=180)
                ),
                # Verbosity of the audit_suggest / refine LLM prompts.
                # "concise" ≈ 150 tokens of principles; "indepth" ≈ 600.
                # Stage-two refines force concise regardless to control
                # latency.
                vol.Optional(
                    "audit_analysis_depth",
                    default=current_audit_depth,
                ): vol.In(["concise", "indepth"]),
                # Monthly cloud-LLM spend cap for the audit subsystem.
                # Local agents bypass entirely. 0 = always allow.
                vol.Optional(
                    "audit_monthly_budget_usd",
                    default=current_audit_budget,
                ): vol.All(
                    vol.Coerce(float), vol.Range(min=0.0, max=100.0)
                ),
                # v1.2: opt-in periodic rollup auto-scheduler.
                # Default OFF so installs that don't want background
                # recorder reads get exactly that. When enabled,
                # bounded by all the v1.2 safety rails.
                vol.Optional(
                    "audit_auto_rollup_enabled",
                    default=current_auto_rollup,
                ): bool,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)

    async def async_step_cloud_consent(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Re-confirm cloud consent when switching INTO cloud mode."""
        if user_input is not None:
            if user_input.get(CONF_CLOUD_CONSENT):
                return self.async_create_entry(
                    title="",
                    data={
                        CONF_LLM_MODE: LlmMode.CLOUD.value,
                        CONF_LOOKBACK_DAYS: self._lookback,
                        CONF_NOTIFY_ON_INSIGHT: self._notify_on,
                        CONF_NOTIFY_THRESHOLD: self._notify_threshold,
                        CONF_DIGEST_ENABLED: self._digest_enabled,
                        CONF_DIGEST_HOUR: self._digest_hour,
                        CONF_PREFERRED_AGENT_ID: self._preferred_agent_id or "",
                        CONF_REFINE_COST_THRESHOLD_USD: self._refine_cost_threshold,
                        # v1.0 review #3 follow-up: this branch must mirror
                        # every field set in the init persist branch above.
                        # Forgetting one silently drops a setting whenever
                        # a user toggles it AND switches into Cloud mode in
                        # the same visit.
                        CONF_ALLOW_USER_DETECTORS: self._allow_user_detectors,
                        CONF_ENABLED_DETECTORS: self._enabled_detectors,
                        CONF_SCAN_AREAS: self._scan_areas,
                        CONF_SCAN_INTERVAL_HOURS: self._scan_interval_hours,
                    },
                )
            self._mode = None
            return await self.async_step_init()

        schema = vol.Schema({vol.Required(CONF_CLOUD_CONSENT, default=False): bool})
        return self.async_show_form(step_id="cloud_consent", data_schema=schema)
