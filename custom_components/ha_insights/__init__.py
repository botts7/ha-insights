"""HA Insights integration for Home Assistant."""
from __future__ import annotations

import logging
import os
import time
from datetime import UTC, datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_STATE_CHANGED, Platform
from homeassistant.core import Event, HomeAssistant, ServiceCall, State, callback
from homeassistant.helpers import entity_registry as er

from . import ws_api
from .config_flow import (
    get_allow_user_detectors,
    get_digest_settings,
    get_lookback_days,
    get_notify_settings,
)
from .const import DOMAIN
from .notifications.digest import schedule_digest
from .observers.history_backfill import backfill as backfill_history
from .observers.state_event_buffer import StateEvent, StateEventBuffer
from .store import InsightStore

PLATFORMS: list[Platform] = [Platform.SENSOR]

_LOGGER = logging.getLogger(__name__)

_WS_REGISTERED_FLAG = "_ws_registered"
_SERVICES_REGISTERED_FLAG = "_services_registered"
_PANEL_REGISTERED_FLAG = "_panel_registered"
_USER_DETECTORS_LOADED_FLAG = "_user_detectors_loaded"
_BUILTIN_DETECTORS_LOADED_FLAG = "_builtin_detectors_loaded"
_PANEL_URL_PATH = "ha-insights"
_USER_DETECTORS_DIR = "ha_insights_detectors"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up HA Insights from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Built-in detector autoload — sync I/O (pkgutil + importlib), so run
    # via executor to avoid HA's blocking-call detector flagging us. Once
    # per HA boot is sufficient since registration is global.
    if not hass.data[DOMAIN].get(_BUILTIN_DETECTORS_LOADED_FLAG):
        from .detectors import load_builtin_detectors

        await hass.async_add_executor_job(load_builtin_detectors)
        hass.data[DOMAIN][_BUILTIN_DETECTORS_LOADED_FLAG] = True

    # Per-entry storage so multiple test config entries don't share state and
    # production cleanly separates DB if the user ever recreates the entry.
    storage_path = hass.config.path(f"{DOMAIN}_{entry.entry_id}.db")
    store = InsightStore(storage_path)
    await store.open()

    # If anything between here and the hass.data registration below raises,
    # the SQLite handle leaks. Wrap the body to ensure we always close on
    # partial failure. Multi-entry installs reload-on-error otherwise stack
    # open SQLite connections.
    try:
        return await _setup_entry_body(hass, entry, store)
    except Exception:
        await store.close()
        raise


async def _setup_entry_body(
    hass: HomeAssistant, entry: ConfigEntry, store: InsightStore
) -> bool:
    """Inner body of async_setup_entry, isolated for store-leak guard."""
    lookback_days = get_lookback_days(entry)
    # Buffer max_age must >= lookback so backfilled events aren't immediately
    # eligible for prune (default buffer max is 7d, our default lookback 14d).
    buffer_max_age = timedelta(days=max(7, lookback_days))
    buffer_ = StateEventBuffer(max_age=buffer_max_age)

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

    # Notification listener: fire persistent_notification.create when a
    # high-confidence insight is added to the store. Gated by the
    # notify_on_insight + notify_threshold config options.
    notify_enabled, notify_threshold = get_notify_settings(entry)

    @callback
    def _on_store_event(event_type: str, insight_obj) -> None:
        if event_type != "added" or insight_obj is None:
            return
        if not notify_enabled:
            return
        if insight_obj.confidence < notify_threshold:
            return
        # Fire the notification asynchronously so the listener stays sync
        hass.async_create_task(
            _notify_insight(hass, insight_obj),
            name=f"{DOMAIN}_notify_{insight_obj.id}",
        )

    unsub_store = store.add_listener(_on_store_event)

    # Daily digest: scheduled callback at the configured local hour. Skipped
    # entirely when the user disables it. The callable returned by
    # async_track_time_change is the unsub.
    digest_enabled, digest_hour = get_digest_settings(entry)
    unsub_digest = (
        schedule_digest(hass, store, hour=digest_hour) if digest_enabled else None
    )

    hass.data[DOMAIN][entry.entry_id] = {
        "store": store,
        "buffer": buffer_,
        "unsub_state": unsub_state,
        "unsub_registry": unsub_registry,
        "unsub_store": unsub_store,
        "unsub_digest": unsub_digest,
        "last_backfill": None,
        "backfill_running": False,
    }

    if not hass.data[DOMAIN].get(_WS_REGISTERED_FLAG):
        ws_api.async_register(hass)
        hass.data[DOMAIN][_WS_REGISTERED_FLAG] = True

    if not hass.data[DOMAIN].get(_SERVICES_REGISTERED_FLAG):
        _async_register_services(hass)
        hass.data[DOMAIN][_SERVICES_REGISTERED_FLAG] = True

    if not hass.data[DOMAIN].get(_PANEL_REGISTERED_FLAG):
        _async_register_panel(hass)
        hass.data[DOMAIN][_PANEL_REGISTERED_FLAG] = True

    # User-supplied detectors: scan <config>/ha_insights_detectors/*.py once
    # per HA boot. The @register_detector decorator on each module side-
    # effects into the global DETECTORS dict, so subsequent scan_now calls
    # pick them up automatically. We run this AFTER ws / services / panel
    # so a broken user detector can't take any of those down.
    if not hass.data[DOMAIN].get(_USER_DETECTORS_LOADED_FLAG):
        from functools import partial
        from pathlib import Path

        from .detectors._user_loader import load_user_detectors

        # Off by default. User must explicitly opt in via OptionsFlow,
        # acknowledging the security model (see _user_loader docstring).
        allow = get_allow_user_detectors(entry)
        user_dir = Path(hass.config.path(_USER_DETECTORS_DIR))
        loaded = await hass.async_add_executor_job(
            partial(load_user_detectors, user_dir, allow=allow)
        )
        if loaded > 0:
            _LOGGER.info(
                "HA Insights: loaded %d user detector(s) from %s",
                loaded,
                user_dir,
            )
        elif not allow:
            _LOGGER.debug(
                "HA Insights: user detectors disabled (allow_user_detectors "
                "is off); skipping %s",
                user_dir,
            )
        hass.data[DOMAIN][_USER_DETECTORS_LOADED_FLAG] = True

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Schedule backfill as a background task so it doesn't block setup.
    # Skipped entirely if lookback_days == 0. We capture the task so
    # async_unload_entry can cancel it cleanly — otherwise a reload
    # mid-backfill would leak a coroutine that writes to a popped buffer.
    if lookback_days > 0:
        backfill_task = hass.async_create_background_task(
            _run_initial_backfill(hass, entry.entry_id, buffer_, lookback_days),
            name=f"{DOMAIN}_initial_backfill_{entry.entry_id}",
        )
        hass.data[DOMAIN][entry.entry_id]["backfill_task"] = backfill_task
    return True


async def _notify_insight(hass: HomeAssistant, insight) -> None:
    """Fire a persistent_notification announcing a new high-confidence insight.

    notification_id includes the insight id so re-emissions of the same
    insight (e.g. on a re-scan) replace the existing notification rather
    than stacking.
    """
    confidence_pct = round(insight.confidence * 100)
    try:
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": f"HA Insights: {insight.detector}",
                "message": (
                    f"{insight.title}\n\n"
                    f"Confidence: {confidence_pct}% — open the HA Insights "
                    "panel to review, refine, or apply."
                ),
                "notification_id": f"ha_insights_{insight.id}",
            },
            blocking=False,
        )
    except Exception:
        _LOGGER.exception("Failed to fire HA Insights notification")


async def _run_initial_backfill(
    hass: HomeAssistant,
    entry_id: str,
    buffer_: StateEventBuffer,
    lookback_days: int,
) -> None:
    """Run a one-shot backfill in the background and stash the summary."""
    entry_data = hass.data.get(DOMAIN, {}).get(entry_id)
    if isinstance(entry_data, dict):
        entry_data["backfill_running"] = True
    try:
        summary = await backfill_history(
            hass, buffer_, lookback_days=lookback_days
        )
    except Exception:
        _LOGGER.exception("HA Insights backfill failed")
        if isinstance(entry_data, dict):
            entry_data["backfill_running"] = False
        return
    if isinstance(entry_data, dict):
        entry_data["last_backfill"] = {
            "completed_at": datetime.now(tz=UTC).isoformat(),
            **summary,
        }
        entry_data["backfill_running"] = False
    _LOGGER.info(
        "HA Insights backfilled %d events from %d entities (%.1fs, %dd lookback)",
        summary["events_added"],
        summary["entities_seen"],
        summary["duration_seconds"],
        summary["lookback_days"],
    )


@callback
def _async_register_services(hass: HomeAssistant) -> None:
    """Register the user-callable services."""

    async def _purge_observations(_call: ServiceCall) -> None:
        for entry_data in hass.data.get(DOMAIN, {}).values():
            if not isinstance(entry_data, dict):
                continue
            buffer_ = entry_data.get("buffer")
            store = entry_data.get("store")
            if buffer_ is not None:
                buffer_.clear()
            if store is not None:
                await store.purge_observations()

    async def _scan_now(_call: ServiceCall) -> None:
        from .detectors import DETECTORS, DetectorContext

        for entry_data in hass.data.get(DOMAIN, {}).values():
            if not isinstance(entry_data, dict):
                continue
            buffer_ = entry_data.get("buffer")
            store = entry_data.get("store")
            if buffer_ is None or store is None:
                continue
            ctx = DetectorContext(hass=hass, event_buffer=buffer_)
            for detector_cls in DETECTORS.values():
                for insight in await detector_cls().scan(ctx):
                    await store.add_insight(insight)

    async def _backfill(call: ServiceCall) -> None:
        """Manual recorder backfill — re-runs for every active config entry."""
        for entry_id, entry_data in hass.data.get(DOMAIN, {}).items():
            if not isinstance(entry_data, dict) or "buffer" not in entry_data:
                continue
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry is None:
                continue
            lookback = int(call.data.get("lookback_days") or get_lookback_days(entry))
            if lookback <= 0:
                continue
            buffer_obj = entry_data["buffer"]
            entry_data["backfill_running"] = True
            try:
                summary = await backfill_history(
                    hass, buffer_obj, lookback_days=lookback
                )
            finally:
                entry_data["backfill_running"] = False
            entry_data["last_backfill"] = {
                "completed_at": datetime.now(tz=UTC).isoformat(),
                **summary,
            }
            _LOGGER.info(
                "HA Insights manual backfill: %d events / %d entities (%dd)",
                summary["events_added"],
                summary["entities_seen"],
                summary["lookback_days"],
            )

    hass.services.async_register(DOMAIN, "purge_observations", _purge_observations)
    hass.services.async_register(DOMAIN, "scan_now", _scan_now)
    hass.services.async_register(DOMAIN, "backfill", _backfill)


@callback
def _async_register_panel(hass: HomeAssistant) -> None:
    """Register the HA Insights sidebar panel.

    Loads /local/ha-insights-panel.js and mounts <ha-insights-panel>. The
    file is shipped via HACS (or copied manually to www/) — the integration
    just registers the URL path + sidebar metadata.

    The module_url is bumped with a cache-buster based on the panel JS
    file's mtime (falls back to startup time). HA's static handler serves
    /local/* with a 31-day Cache-Control, so without a fresh query string
    the browser can hold a stale build for weeks. Bumping on every HA
    setup makes "deploy new panel.js + restart HA" a clean update path.
    """
    from homeassistant.components.frontend import async_register_built_in_panel

    panel_path = hass.config.path("www/ha-insights-panel.js")
    try:
        cache_bust = int(os.path.getmtime(panel_path))
    except OSError:
        cache_bust = int(time.time())

    try:
        async_register_built_in_panel(
            hass,
            component_name="custom",
            sidebar_title="Insights",
            sidebar_icon="mdi:chart-arc",
            frontend_url_path=_PANEL_URL_PATH,
            config={
                "_panel_custom": {
                    "name": "ha-insights-panel",
                    "embed_iframe": False,
                    "trust_external": False,
                    "module_url": f"/local/ha-insights-panel.js?v={cache_bust}",
                },
            },
            require_admin=False,
        )
    except ValueError:
        # Already registered — we use a flag to avoid this but the API is
        # idempotent-by-error; swallow so duplicate setup doesn't crash.
        _LOGGER.debug("HA Insights panel already registered")


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry — closes the store and event listeners."""
    import asyncio
    import contextlib

    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unloaded:
        return False
    data = hass.data[DOMAIN].pop(entry.entry_id, None)
    if data is None:
        return True
    if "unsub_state" in data:
        data["unsub_state"]()
    if "unsub_registry" in data:
        data["unsub_registry"]()
    if "unsub_store" in data:
        data["unsub_store"]()
    if data.get("unsub_digest") is not None:
        data["unsub_digest"]()
    # Cancel any in-flight initial backfill before closing the store —
    # otherwise it'll write to a closed connection on its next flush.
    backfill_task = data.get("backfill_task")
    if backfill_task is not None and not backfill_task.done():
        backfill_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await backfill_task
    if "store" in data:
        await data["store"].close()
    # Unregister the panel only when the LAST entry unloads (other entries
    # still need it). We check whether any per-entry data remains.
    remaining = [
        v for v in hass.data.get(DOMAIN, {}).values() if isinstance(v, dict)
    ]
    if not remaining and hass.data.get(DOMAIN, {}).get(_PANEL_REGISTERED_FLAG):
        from homeassistant.components.frontend import async_remove_panel

        async_remove_panel(hass, _PANEL_URL_PATH)
        hass.data[DOMAIN][_PANEL_REGISTERED_FLAG] = False
    return True
