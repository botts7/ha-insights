"""Sensor platform — exposes the LLM privacy audit log to HA's UI.

`sensor.ha_insights_privacy_log` shows a daily count of outbound LLM calls.
State = call count over the trailing 24 hours. Attributes carry bytes-sent /
bytes-received / last-call timestamp / last-agent so users can graph them or
trigger automations on excess activity.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
)
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .store import InsightStore


_WINDOW = timedelta(days=1)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the privacy-log sensor for a config entry."""
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if not isinstance(data, dict) or "store" not in data:
        return
    sensor = PrivacyLogSensor(store=data["store"], entry_id=entry.entry_id)
    async_add_entities([sensor], update_before_add=True)


class PrivacyLogSensor(SensorEntity):
    """24-hour rolling count of outbound LLM calls + audit attributes."""

    _attr_has_entity_name = True
    _attr_name = "Privacy log"
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "calls"
    _attr_icon = "mdi:shield-eye"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, *, store: InsightStore, entry_id: str) -> None:
        self._store = store
        self._entry_id = entry_id
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_privacy_log"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="HA Insights",
            manufacturer="HA Insights",
            entry_type=DeviceEntryType.SERVICE,
        )
        self._calls = 0
        self._bytes_sent = 0
        self._bytes_received = 0
        self._last_call: datetime | None = None
        self._last_agent: str | None = None
        self._est_cost_usd_total: float = 0.0

    @property
    def native_value(self) -> int:
        return self._calls

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "last_call_timestamp": (
                self._last_call.isoformat() if self._last_call else None
            ),
            "bytes_sent_today": self._bytes_sent,
            "bytes_received_today": self._bytes_received,
            "last_agent": self._last_agent,
            # v0.9 phase 1C: rough USD cost estimate so users can spot
            # expensive Refine usage without leaving the dashboard.
            "est_cost_usd_today": self._est_cost_usd_total,
        }

    async def async_update(self) -> None:
        """Pull a fresh summary from the store. HA polls this on a schedule."""
        since = datetime.now(tz=UTC) - _WINDOW
        summary = await self._store.get_outbound_call_summary(since=since)
        self._calls = int(summary.get("call_count") or 0)
        self._bytes_sent = int(summary.get("bytes_sent_total") or 0)
        self._bytes_received = int(summary.get("bytes_received_total") or 0)
        last_ts = summary.get("last_call_timestamp")
        self._last_call = last_ts if isinstance(last_ts, datetime) else None
        last_agent = summary.get("last_agent")
        self._last_agent = last_agent if isinstance(last_agent, str) else None
        cost_total = summary.get("est_cost_usd_total")
        try:
            self._est_cost_usd_total = (
                float(cost_total) if cost_total is not None else 0.0
            )
        except (TypeError, ValueError):
            self._est_cost_usd_total = 0.0
