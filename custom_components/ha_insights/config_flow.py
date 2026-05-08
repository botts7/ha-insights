"""Config flow for HA Insights — bootstrap stub.

Full three-mode privacy wizard (Off / Local / Cloud + advanced) lands at
critical-path step 8 per docs/ARCHITECTURE.md.
"""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN


class HaInsightsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Single-instance bootstrap flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Single-step bootstrap. Replaced by full wizard at step 8."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is None:
            return self.async_show_form(step_id="user")

        return self.async_create_entry(title="HA Insights", data={})
