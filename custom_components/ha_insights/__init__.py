"""HA Insights integration for Home Assistant."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import ws_api
from .const import DOMAIN
from .store import InsightStore

PLATFORMS: list[str] = []

_WS_REGISTERED_FLAG = "_ws_registered"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up HA Insights from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Per-entry storage so multiple test config entries don't share state and
    # production cleanly separates DB if the user ever recreates the entry.
    # Single-instance integration -> stable filename in production.
    storage_path = hass.config.path(f"{DOMAIN}_{entry.entry_id}.db")
    store = InsightStore(storage_path)
    await store.open()

    hass.data[DOMAIN][entry.entry_id] = {"store": store}

    # Register WS handlers once (single-instance integration; flag protects
    # against double-registration on a second setup call after unload).
    if not hass.data[DOMAIN].get(_WS_REGISTERED_FLAG):
        ws_api.async_register(hass)
        hass.data[DOMAIN][_WS_REGISTERED_FLAG] = True

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry — closes the store."""
    data = hass.data[DOMAIN].pop(entry.entry_id, None)
    if data and "store" in data:
        await data["store"].close()
    return True
