"""HA Insights integration for Home Assistant."""
from __future__ import annotations

from datetime import UTC, datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers import entity_registry as er

from . import ws_api
from .const import DOMAIN
from .observers.state_event_buffer import StateEvent, StateEventBuffer
from .store import InsightStore

PLATFORMS: list[str] = []

_WS_REGISTERED_FLAG = "_ws_registered"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up HA Insights from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Per-entry storage so multiple test config entries don't share state and
    # production cleanly separates DB if the user ever recreates the entry.
    storage_path = hass.config.path(f"{DOMAIN}_{entry.entry_id}.db")
    store = InsightStore(storage_path)
    await store.open()

    buffer_ = StateEventBuffer()

    entity_reg = er.async_get(hass)

    @callback
    def _on_state_changed(event: Event) -> None:
        new_state: State | None = event.data.get("new_state")
        if new_state is None:
            return
        old_state: State | None = event.data.get("old_state")
        domain = new_state.entity_id.split(".", 1)[0]
        entry_obj = entity_reg.async_get(new_state.entity_id)
        area_id = entry_obj.area_id if entry_obj else None

        buffer_.add(
            StateEvent(
                timestamp=new_state.last_changed or datetime.now(tz=UTC),
                entity_id=new_state.entity_id,
                domain=domain,
                area_id=area_id,
                old_state=old_state.state if old_state else None,
                new_state=new_state.state,
            )
        )

    @callback
    def _on_entity_registry_updated(event: Event) -> None:
        # Migrate buffer + pseudonym map on entity_id rename so detectors and
        # any cached references survive the rename atomically.
        action = event.data.get("action")
        if action != "update":
            return
        changes = event.data.get("changes") or {}
        old_entity_id = changes.get("entity_id")
        new_entity_id = event.data.get("entity_id")
        if not old_entity_id or not new_entity_id or old_entity_id == new_entity_id:
            return
        buffer_.rename_entity(old_entity_id, new_entity_id)
        hass.async_create_task(
            store.rename_entity_pseudonym(old_entity_id, new_entity_id)
        )

    unsub_state = hass.bus.async_listen(EVENT_STATE_CHANGED, _on_state_changed)
    unsub_registry = hass.bus.async_listen(
        "entity_registry_updated", _on_entity_registry_updated
    )

    hass.data[DOMAIN][entry.entry_id] = {
        "store": store,
        "buffer": buffer_,
        "unsub_state": unsub_state,
        "unsub_registry": unsub_registry,
    }

    if not hass.data[DOMAIN].get(_WS_REGISTERED_FLAG):
        ws_api.async_register(hass)
        hass.data[DOMAIN][_WS_REGISTERED_FLAG] = True

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry — closes the store and event listeners."""
    data = hass.data[DOMAIN].pop(entry.entry_id, None)
    if data is None:
        return True
    if "unsub_state" in data:
        data["unsub_state"]()
    if "unsub_registry" in data:
        data["unsub_registry"]()
    if "store" in data:
        await data["store"].close()
    return True
