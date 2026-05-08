"""Tests for the HA Insights config flow."""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.ha_insights.config_flow import (
    CONF_CLOUD_CONSENT,
    CONF_LLM_MODE,
    LlmMode,
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


async def test_single_instance_only(hass: HomeAssistant) -> None:
    """A second config flow on the same domain aborts as already_configured."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_LLM_MODE: LlmMode.OFF.value},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
