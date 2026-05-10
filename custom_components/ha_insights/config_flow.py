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
CONF_LLM_BLOCK_ENTITIES = "llm_block_entities"
CONF_NOTIFY_ON_INSIGHT = "notify_on_insight"
CONF_NOTIFY_THRESHOLD = "notify_threshold"
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
    """Resolve the per-entity LLM opt-out list.

    These entity_ids are NEVER included in any LLM prompt — neither as
    pseudonyms nor as real values. Privacy floor below the redactor's
    mode-driven behavior.
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
        self._digest_enabled: bool = DEFAULT_DIGEST_ENABLED
        self._digest_hour: int = DEFAULT_DIGEST_HOUR
        self._preferred_agent_id: str | None = None
        self._refine_cost_threshold: float = DEFAULT_REFINE_COST_THRESHOLD_USD
        self._allow_user_detectors: bool = DEFAULT_ALLOW_USER_DETECTORS

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Mode + lookback + notification picker."""
        current_mode = get_active_mode(self.config_entry)
        current_lookback = get_lookback_days(self.config_entry)
        current_notify_on, current_notify_threshold = get_notify_settings(
            self.config_entry
        )
        current_digest_on, current_digest_hour = get_digest_settings(
            self.config_entry
        )
        current_preferred = get_preferred_agent_id(self.config_entry) or ""
        current_refine_threshold = get_refine_cost_threshold(self.config_entry)
        current_allow_user_detectors = get_allow_user_detectors(self.config_entry)

        if user_input is not None:
            self._mode = LlmMode(user_input[CONF_LLM_MODE])
            self._lookback = int(user_input.get(CONF_LOOKBACK_DAYS, current_lookback))
            self._notify_on = bool(
                user_input.get(CONF_NOTIFY_ON_INSIGHT, current_notify_on)
            )
            self._notify_threshold = float(
                user_input.get(CONF_NOTIFY_THRESHOLD, current_notify_threshold)
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
                    CONF_DIGEST_ENABLED: self._digest_enabled,
                    CONF_DIGEST_HOUR: self._digest_hour,
                    CONF_PREFERRED_AGENT_ID: self._preferred_agent_id or "",
                    CONF_REFINE_COST_THRESHOLD_USD: self._refine_cost_threshold,
                    CONF_ALLOW_USER_DETECTORS: self._allow_user_detectors,
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
                        # v1.0 review #3 follow-up: this branch was missing
                        # _allow_user_detectors. A user toggling the
                        # "allow detectors" flag in the same Configure
                        # visit as switching INTO Cloud mode would lose
                        # the toggle silently.
                        CONF_ALLOW_USER_DETECTORS: self._allow_user_detectors,
                    },
                )
            self._mode = None
            return await self.async_step_init()

        schema = vol.Schema({vol.Required(CONF_CLOUD_CONSENT, default=False): bool})
        return self.async_show_form(step_id="cloud_consent", data_schema=schema)
