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
DEFAULT_LOOKBACK_DAYS = 14
LOOKBACK_DAYS_RANGE = (0, 30)  # 0 disables backfill entirely
DEFAULT_NOTIFY_ON_INSIGHT = True
DEFAULT_NOTIFY_THRESHOLD = 0.8


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
        """Mode selection — single-instance integration."""
        if self.unique_id is None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()

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

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Mode + lookback + notification picker."""
        current_mode = get_active_mode(self.config_entry)
        current_lookback = get_lookback_days(self.config_entry)
        current_notify_on, current_notify_threshold = get_notify_settings(
            self.config_entry
        )

        if user_input is not None:
            self._mode = LlmMode(user_input[CONF_LLM_MODE])
            self._lookback = int(user_input.get(CONF_LOOKBACK_DAYS, current_lookback))
            self._notify_on = bool(
                user_input.get(CONF_NOTIFY_ON_INSIGHT, current_notify_on)
            )
            self._notify_threshold = float(
                user_input.get(CONF_NOTIFY_THRESHOLD, current_notify_threshold)
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
                    },
                )
            self._mode = None
            return await self.async_step_init()

        schema = vol.Schema({vol.Required(CONF_CLOUD_CONSENT, default=False): bool})
        return self.async_show_form(step_id="cloud_consent", data_schema=schema)
