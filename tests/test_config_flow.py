"""Tests for the HA Insights config flow."""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_insights.config_flow import (
    CONF_CLOUD_CONSENT,
    CONF_LLM_MODE,
    CONF_LOOKBACK_DAYS,
    DEFAULT_LOOKBACK_DAYS,
    LlmMode,
    get_lookback_days,
)
from custom_components.ha_insights.const import DOMAIN


async def test_user_step_shows_mode_picker(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_off_mode_creates_entry_immediately(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_LLM_MODE: LlmMode.OFF.value},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_LLM_MODE] == LlmMode.OFF.value
    assert result["title"] == "HA Insights"
    assert result["data"][CONF_LOOKBACK_DAYS] == DEFAULT_LOOKBACK_DAYS


async def test_local_mode_creates_entry_immediately(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_LLM_MODE: LlmMode.LOCAL.value},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_LLM_MODE] == LlmMode.LOCAL.value


async def test_cloud_mode_requires_consent_step(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_LLM_MODE: LlmMode.CLOUD.value},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "cloud_consent"


async def test_cloud_consent_yes_creates_entry(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_LLM_MODE: LlmMode.CLOUD.value},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_CLOUD_CONSENT: True},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_LLM_MODE] == LlmMode.CLOUD.value


async def test_cloud_consent_no_returns_to_mode_picker(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_LLM_MODE: LlmMode.CLOUD.value},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_CLOUD_CONSENT: False},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"


def test_get_lookback_days_default() -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_LLM_MODE: LlmMode.OFF.value})
    assert get_lookback_days(entry) == DEFAULT_LOOKBACK_DAYS


def test_get_lookback_days_clamps_high() -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_LOOKBACK_DAYS: 999})
    assert get_lookback_days(entry) == 30


def test_get_lookback_days_clamps_low() -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_LOOKBACK_DAYS: -5})
    assert get_lookback_days(entry) == 0


def test_get_lookback_days_options_override() -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_LOOKBACK_DAYS: 7},
        options={CONF_LOOKBACK_DAYS: 21},
    )
    assert get_lookback_days(entry) == 21


def test_get_lookback_days_invalid_returns_default() -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_LOOKBACK_DAYS: "abc"})
    assert get_lookback_days(entry) == DEFAULT_LOOKBACK_DAYS


async def test_options_flow_includes_lookback_days(hass: HomeAssistant) -> None:
    """OptionsFlow Advanced sub-step exposes lookback_days for in-place editing.

    The init step now shows a menu (Quick wizard / per-user overrides /
    Advanced); lookback_days lives inside the Advanced form. This test
    walks: init-menu → Advanced → submit-new-lookback.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_LLM_MODE: LlmMode.OFF.value, CONF_LOOKBACK_DAYS: 14},
        unique_id=DOMAIN,
        title="HA Insights",
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "init"
    assert "advanced" in result["menu_options"]

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={"next_step_id": "advanced"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "advanced"
    schema_keys = {str(k) for k in result["data_schema"].schema}
    assert CONF_LOOKBACK_DAYS in schema_keys

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={CONF_LLM_MODE: LlmMode.OFF.value, CONF_LOOKBACK_DAYS: 21},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_LOOKBACK_DAYS] == 21


async def test_multi_entry_allowed(hass: HomeAssistant) -> None:
    """v1.0 RC #7: a second config entry creates a second independent scope.

    Most installs run one entry; advanced users want two (different area
    filters, separate lookback windows, separate LLM agents). HA permits
    multiple entries because we don't set a unique_id in async_step_user.
    """
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_LLM_MODE: LlmMode.OFF.value},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    first_entry_id = result["result"].entry_id

    # Second flow proceeds to CREATE_ENTRY too — no abort.
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_LLM_MODE: LlmMode.LOCAL.value},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    second_entry_id = result["result"].entry_id

    assert first_entry_id != second_entry_id
