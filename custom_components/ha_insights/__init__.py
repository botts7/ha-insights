"""HA Insights integration for Home Assistant."""
from __future__ import annotations

import logging
import os
import time
from datetime import UTC, datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_STATE_CHANGED, Platform
from homeassistant.core import (
    CoreState,
    Event,
    HomeAssistant,
    ServiceCall,
    State,
    callback,
)
from homeassistant.helpers import entity_registry as er

from . import ws_api
from .config_flow import (
    get_allow_user_detectors,
    get_analytics_settings,
    get_audit_rollup_window_days,
    get_digest_settings,
    get_lookback_days,
    get_mobile_notify_policy,
    get_notify_mobile_targets,
    get_notify_settings,
    get_scan_interval_hours,
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

    # Bootstrap-window tracker. code review caught the original
    # design failing in practice: EVENT_HOMEASSISTANT_STARTED fires
    # AFTER all entity platforms have already written their restored
    # state, so a listener-only approach NEVER sees the fan-out
    # events as from_bootstrap. The marker has to be set BEFORE the
    # boot fan-out arrives at our listener.
    #
    # Two cases:
    #   (a) Integration set up during HA boot (cold start, restart,
    #       config-entry create on first install). hass.state is
    #       NOT yet CoreState.running — boot is still in progress.
    #       Mark the window NOW so events arriving at our state
    #       listener within the next N seconds are flagged.
    #   (b) Integration set up after HA finished booting (reload of
    #       this entry mid-session). hass.state IS running — there
    #       is no bootstrap fan-out to filter. Leave the marker
    #       unset so nothing gets flagged from_bootstrap.
    #
    # See docs/HA_EVENT_SEMANTICS.md Gotcha 5.
    _BOOTSTRAP_WINDOW_SEC = 10  # wider than 5 to absorb slow boots

    if hass.state is not CoreState.running:
        # Case (a) — we're loading during HA's startup. The boot
        # fan-out for entity platforms hasn't necessarily reached
        # us yet; mark the window now so it covers the inbound
        # state_changed events that follow.
        hass.data.setdefault(DOMAIN, {})["_bootstrap_until_ts"] = (
            datetime.now(tz=UTC).timestamp() + _BOOTSTRAP_WINDOW_SEC
        )
        # Also catch the STARTED event as a backstop — if anything
        # slipped past our setup-time mark, we extend the window
        # from STARTED + N seconds to cover any final stragglers
        # that arrive between our setup-time mark and the bus
        # truly settling.
        from homeassistant.const import EVENT_HOMEASSISTANT_STARTED

        @callback
        def _on_homeassistant_started(_event: Event) -> None:
            hass.data.setdefault(DOMAIN, {})["_bootstrap_until_ts"] = (
                datetime.now(tz=UTC).timestamp() + _BOOTSTRAP_WINDOW_SEC
            )

        entry.async_on_unload(
            hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED, _on_homeassistant_started
            )
        )
    # else: case (b) — running already, no bootstrap to mark.

    @callback
    def _on_state_changed(event: Event) -> None:
        new_state: State | None = event.data.get("new_state")
        if new_state is None:
            return
        old_state: State | None = event.data.get("old_state")
        domain = new_state.entity_id.split(".", 1)[0]
        entry_obj = entity_reg.async_get(new_state.entity_id)
        area_id = entry_obj.area_id if entry_obj else None
        # Pull context.user_id when present — set by HA for any change
        # originated via UI / voice / mobile app. None for automation
        # actions and integration polling. ManualHabitDetector uses
        # this to filter manual events vs system events.
        ctx_user = None
        ctx_id: str | None = None
        try:
            if getattr(new_state, "context", None) is not None:
                ctx_user = new_state.context.user_id
                # context.id is the correlation key for batch
                # operations — see Gotchas 1-3. Group toggles,
                # scene activations, and script runs produce N
                # state_changed events with the SAME context.id.
                ctx_id = getattr(new_state.context, "id", None)
        except Exception:  # noqa: BLE001
            ctx_user = None
            ctx_id = None

        # Mark events that fired within the bootstrap window WITH
        # old_state=None. HA's automation state trigger has this same
        # guard (homeassistant/helpers/trigger.py). Two-part check
        # because:
        #   - old_state=None alone can be a genuine "entity just
        #     appeared mid-session" (rare but possible)
        #   - bootstrap-window alone catches reloads firing into the
        #     buffer but doesn't include manual mid-session adds
        # The conjunction is what HA itself uses.
        from_bootstrap = False
        if old_state is None:
            bs_until = hass.data.get(DOMAIN, {}).get(
                "_bootstrap_until_ts"
            )
            if bs_until is not None:
                event_ts = (new_state.last_changed or datetime.now(tz=UTC)).timestamp()
                if event_ts <= bs_until:
                    from_bootstrap = True

        buffer_.add(
            StateEvent(
                timestamp=new_state.last_changed or datetime.now(tz=UTC),
                entity_id=new_state.entity_id,
                domain=domain,
                area_id=area_id,
                old_state=old_state.state if old_state else None,
                new_state=new_state.state,
                context_user_id=ctx_user,
                from_bootstrap=from_bootstrap,
                context_id=ctx_id,
            )
        )

    @callback
    def _on_entity_registry_updated(event: Event) -> None:
        # Keep pseudonym map + state buffer in sync with entity registry.
        action = event.data.get("action")
        if action == "update":
            changes = event.data.get("changes") or {}

            # unique_id reassignment (entity_id may stay the same): the
            # pseudonym was earned by the OLD underlying device. Drop it
            # so the new device gets a fresh pseudonym, otherwise cloud-
            # side LLM logs would conflate the two on next call.
            # v1.0 review (regression-fix follow-up).
            if "unique_id" in changes:
                ent_id = event.data.get("entity_id")
                if ent_id:
                    entry.async_create_background_task(
                        hass,
                        store.delete_entity_pseudonym(ent_id),
                        name=f"{DOMAIN}_invalidate_pseudonym_{ent_id}",
                    )

            # Rename: migrate the pseudonym + buffer entries so detectors and
            # any cached references survive the rename atomically.
            old_entity_id = changes.get("entity_id")
            new_entity_id = event.data.get("entity_id")
            if (
                not old_entity_id
                or not new_entity_id
                or old_entity_id == new_entity_id
            ):
                return
            buffer_.rename_entity(old_entity_id, new_entity_id)
            # entry-bound so unload cancels in-flight DB writes (review #12)
            entry.async_create_background_task(
                hass,
                store.rename_entity_pseudonym(old_entity_id, new_entity_id),
                name=f"{DOMAIN}_rename_pseudonym_{new_entity_id}",
            )
        elif action == "remove":
            # v1.0 review #9: a removed entity's pseudonym should not
            # linger forever. If the user re-creates an entity_id with a
            # different unique_id later, the new entity would inherit
            # the old one's pseudonym — confusing on cloud-side LLM logs
            # and a privacy footgun. Drop the pseudonym row on remove.
            removed_entity_id = event.data.get("entity_id")
            if removed_entity_id:
                entry.async_create_background_task(
                    hass,
                    store.delete_entity_pseudonym(removed_entity_id),
                    name=f"{DOMAIN}_delete_pseudonym_{removed_entity_id}",
                )

    unsub_state = hass.bus.async_listen(EVENT_STATE_CHANGED, _on_state_changed)
    unsub_registry = hass.bus.async_listen(
        "entity_registry_updated", _on_entity_registry_updated
    )

    # Notification listener: fire persistent_notification.create when a
    # high-confidence insight is added to the store. Gated by the
    # notify_on_insight + notify_threshold config options.
    # Also pushes to user-configured mobile-app notify services so
    # time-critical insights reach the user's pocket — users don't sit
    # watching the panel.
    notify_enabled, notify_threshold = get_notify_settings(entry)
    notify_mobile_targets = get_notify_mobile_targets(entry)
    notify_mobile_policy = get_mobile_notify_policy(entry)
    notify_entry_id = entry.entry_id

    @callback
    def _on_store_event(event_type: str, insight_obj) -> None:
        if event_type != "added" or insight_obj is None:
            return
        if not notify_enabled:
            return
        if insight_obj.confidence < notify_threshold:
            return
        # Fire asynchronously so the listener stays sync. Entry-bound so
        # unload cancels in-flight notify calls (review #12) — otherwise
        # a notify task spawned moments before unload could outlive the
        # entry and call into a closed store via _notify_insight's lookups.
        entry.async_create_background_task(
            hass,
            _notify_insight(
                hass,
                insight_obj,
                notify_mobile_targets,
                policy=notify_mobile_policy,
                entry_id=notify_entry_id,
                entry=entry,
            ),
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

    # v1.4: Community analytics — weekly POST of aggregate counts
    # to the project receiver. OFF by default; only fires when the
    # user explicitly opts in via the OptionsFlow. Schedule is
    # Monday 04:00 local (low-traffic, after the digest hour).
    analytics_enabled, analytics_endpoint = get_analytics_settings(entry)
    unsub_analytics = None
    if analytics_enabled:
        from homeassistant.helpers.event import async_track_time_change

        from .analytics import send_report

        @callback
        def _on_analytics_tick(_now) -> None:
            # ISO weekday 1=Monday. async_track_time_change doesn't
            # have a weekday filter, so we gate inside the callback.
            from datetime import datetime as _dt

            if _dt.now().isoweekday() != 1:
                return
            entry.async_create_background_task(
                hass,
                send_report(
                    hass,
                    entry,
                    store,
                    endpoint=analytics_endpoint or None,
                ),
                name=f"{DOMAIN}_analytics_send",
            )

        unsub_analytics = async_track_time_change(
            hass, _on_analytics_tick, hour=4, minute=0, second=0
        )

    # v1.4: Adaptive notification tuner. Schedules a daily nudge at
    # 03:00 local that reads recent dismiss/apply outcomes and
    # adjusts the mobile-push confidence floor accordingly. No-op
    # when the user hasn't picked the "adaptive" preset — keeps
    # the scheduler cheap.
    unsub_adaptive = None
    if notify_mobile_policy.get("adaptive"):
        from homeassistant.helpers.event import async_track_time_change

        from .notifications.adaptive import tune_adaptive_floor

        @callback
        def _on_adaptive_tick(_now) -> None:
            entry.async_create_background_task(
                hass,
                tune_adaptive_floor(hass, entry, store),
                name=f"{DOMAIN}_adaptive_tune",
            )

        unsub_adaptive = async_track_time_change(
            hass, _on_adaptive_tick, hour=3, minute=0, second=0
        )

    hass.data[DOMAIN][entry.entry_id] = {
        "store": store,
        "buffer": buffer_,
        "unsub_state": unsub_state,
        "unsub_registry": unsub_registry,
        "unsub_store": unsub_store,
        "unsub_digest": unsub_digest,
        "unsub_adaptive": unsub_adaptive,
        "unsub_analytics": unsub_analytics,
        "last_backfill": None,
        "backfill_running": False,
        # Seed for _on_options_updated's window-change detector. With
        # this set at setup time, the FIRST options change has a
        # baseline to compare against — without it, the old code
        # would unconditionally clear rollup progress on every save.
        "_known_rollup_window": get_audit_rollup_window_days(entry),
    }

    if not hass.data[DOMAIN].get(_WS_REGISTERED_FLAG):
        ws_api.async_register(hass)
        hass.data[DOMAIN][_WS_REGISTERED_FLAG] = True

    if not hass.data[DOMAIN].get(_SERVICES_REGISTERED_FLAG):
        _async_register_services(hass)
        hass.data[DOMAIN][_SERVICES_REGISTERED_FLAG] = True

    if not hass.data[DOMAIN].get(_PANEL_REGISTERED_FLAG):
        await _async_register_panel(hass)
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

    # Phase D: periodic scan scheduler. Only registered when the user has
    # configured a non-zero CONF_SCAN_INTERVAL_HOURS, AND only fires after
    # EVENT_HOMEASSISTANT_STARTED so we don't kick a heavy scan during
    # startup (the 2026-05-10 incident class). Cancel handle stashed in
    # entry_data so unload tears it down cleanly.
    scan_interval = get_scan_interval_hours(entry)
    if scan_interval > 0:
        from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
        from homeassistant.helpers.event import async_track_time_interval

        async def _scheduled_scan(_now=None) -> None:
            await _run_scheduled_scan(hass, entry.entry_id)

        async def _register_scheduler(_event=None) -> None:
            cancel = async_track_time_interval(
                hass, _scheduled_scan, timedelta(hours=scan_interval)
            )
            entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
            if isinstance(entry_data, dict):
                entry_data["scan_scheduler_cancel"] = cancel
            _LOGGER.info(
                "HA Insights periodic scan registered (every %dh)", scan_interval
            )

        if hass.is_running:
            await _register_scheduler()
        else:
            hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED, _register_scheduler
            )

    # v1.2: incremental rollup auto-scheduler. Opt-in via OptionsFlow
    # — default OFF until users explicitly enable it. When enabled,
    # we run one batch every 6 hours. Bounded to 25 entities/batch,
    # 8 chunks/entity, 120s budget. Single-flight lock guarantees a
    # manual click + the schedule can't pile up. Only registered
    # after EVENT_HOMEASSISTANT_STARTED + a 5-minute warmup so we
    # never kick the recorder during boot/state-firehose-catchup.
    from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
    from homeassistant.helpers.event import async_track_time_interval

    from .config_flow import get_audit_auto_rollup_enabled

    _ROLLUP_AUTO_INTERVAL = timedelta(hours=6)
    _ROLLUP_INITIAL_KICK_DELAY_SEC = 300  # 5 min — past HA's boot recorder catchup
    _ROLLUP_AUTO_BATCH_SIZE = 25

    async def _scheduled_rollup(_now=None) -> None:
        """Run one auto-rollup batch. Logs + swallows so the timer
        never dies on a single bad scan."""
        try:
            from .audit.rollup import (
                collect_audit_target_entities,
                run_rollup_batch,
            )
            from .config_flow import get_blocked_entities
            from .detectors import _load_existing_automations

            autos = await _load_existing_automations(hass)
            target_eids = collect_audit_target_entities(autos)
            if not target_eids:
                return
            blocked = get_blocked_entities(entry)
            entry_data_ = hass.data.get(DOMAIN, {}).get(entry.entry_id)
            if not entry_data_:
                return
            store_obj = entry_data_.get("store")
            if store_obj is None:
                return
            summary = await run_rollup_batch(
                hass,
                store_obj,
                target_entity_ids=target_eids,
                blocked_entities=blocked,
                batch_size=_ROLLUP_AUTO_BATCH_SIZE,
            )
            _LOGGER.info(
                "audit auto-rollup: processed=%d errors=%d timed_out=%d "
                "next_due=%d duration=%ss skipped_inflight=%s",
                summary.get("entities_processed", 0),
                summary.get("errors", 0),
                len(summary.get("timed_out_entities", []) or []),
                summary.get("next_due_count", 0),
                summary.get("batch_duration_sec", 0),
                summary.get("skipped_inflight", False),
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("audit auto-rollup failed: %s", err)

    async def _initial_rollup_kick() -> None:
        """Delayed first-run. Lives long enough past boot that the
        recorder is no longer catching up on the state firehose.
        Uses entry.async_create_background_task so it cancels
        cleanly on unload."""
        import asyncio as _asyncio

        await _asyncio.sleep(_ROLLUP_INITIAL_KICK_DELAY_SEC)
        await _scheduled_rollup()

    async def _register_rollup_scheduler(_event=None) -> None:
        cancel = async_track_time_interval(
            hass, _scheduled_rollup, _ROLLUP_AUTO_INTERVAL
        )
        entry_data_ = hass.data.get(DOMAIN, {}).get(entry.entry_id)
        if isinstance(entry_data_, dict):
            entry_data_["rollup_scheduler_cancel"] = cancel
        _LOGGER.info(
            "HA Insights audit rollup auto-scheduler registered "
            "(every %s, initial kick in %ds)",
            _ROLLUP_AUTO_INTERVAL,
            _ROLLUP_INITIAL_KICK_DELAY_SEC,
        )
        entry.async_create_background_task(
            hass, _initial_rollup_kick(), "ha_insights_initial_rollup"
        )

    if get_audit_auto_rollup_enabled(entry):
        if hass.is_running:
            await _register_rollup_scheduler()
        else:
            hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED, _register_rollup_scheduler
            )
    else:
        _LOGGER.debug(
            "audit auto-rollup disabled (opt-in via OptionsFlow)"
        )

    # OptionsFlow change listener. When the user bumps
    # `audit_rollup_window_days`, prune any rollups computed against
    # a different window so the next batch refills from scratch.
    # Reload the entry so other options take effect.
    async def _on_options_updated(
        hass_: HomeAssistant, entry_: ConfigEntry
    ) -> None:
        # the previous version called
        # clear_rollup_progress() on EVERY options change — toggling
        # a notification preset wiped weeks of rollup cursor work,
        # forcing a full refill from recorder on the next pass.
        # Only clear progress when the window ACTUALLY changed
        # (the cursor's bucket layout depends on window_days; any
        # other option change is window-orthogonal).
        try:
            from .config_flow import get_audit_rollup_window_days

            new_window = get_audit_rollup_window_days(entry_)
            entry_data = hass_.data.get(DOMAIN, {}).get(entry_.entry_id) or {}
            current_store = entry_data.get("store")
            old_window = entry_data.get("_known_rollup_window")
            if (
                current_store is not None
                and old_window is not None
                and old_window != new_window
            ):
                deleted = await current_store.prune_rollups_with_wrong_window(
                    new_window
                )
                # Clear progress ONLY on window change — the cursor
                # was earned against the old window; new buckets
                # must rebuild against the new window.
                progress_cleared = await current_store.clear_rollup_progress()
                if deleted or progress_cleared:
                    _LOGGER.info(
                        "audit: pruned %d rollup rows + %d progress cursors "
                        "after window change %d → %d days",
                        deleted,
                        progress_cleared,
                        old_window,
                        new_window,
                    )
            # Update the "last seen window" marker so the next options
            # change knows whether to compare.
            if isinstance(entry_data, dict):
                entry_data["_known_rollup_window"] = new_window
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("options-updated rollup prune skipped: %s", err)
        await hass_.config_entries.async_reload(entry_.entry_id)

    entry.async_on_unload(entry.add_update_listener(_on_options_updated))

    # Mobile-app notification action listener. When the user taps
    # "Dismiss" on a mobile notification, the mobile_app integration
    # fires `mobile_app_notification_action` with action == our id.
    # We resolve the tag → insight_id and dismiss it in-store so the
    # panel and the notification stay coherent.
    @callback
    def _on_mobile_action(event: Event) -> None:
        data = event.data or {}
        if data.get("action") != "HA_INSIGHTS_DISMISS":
            return
        tag = data.get("tag", "")
        if not isinstance(tag, str) or not tag.startswith("ha_insights_"):
            return
        insight_id = tag[len("ha_insights_") :]
        if not insight_id:
            return
        entry.async_create_background_task(
            hass,
            store.dismiss_insight(insight_id),
            name=f"{DOMAIN}_dismiss_from_mobile_{insight_id}",
        )

    entry.async_on_unload(
        hass.bus.async_listen(
            "mobile_app_notification_action", _on_mobile_action
        )
    )

    # Restore Repairs entries from the persisted insights as soon as
    # the integration loads. Without this, every HA restart would leave
    # the Repairs surface empty until the next scheduled scan ran.
    # Lightweight — just a registry diff against insights already in
    # SQLite. Errors swallowed so a bad Repairs sync can't block setup.
    async def _restore_repairs_on_boot() -> None:
        try:
            from .audit.repairs import sync_audit_issues

            current_insights = await store.list_insights(
                include_dismissed=False,
                include_applied=False,
                include_snoozed=False,
            )
            audit_insights = [
                i for i in current_insights if i.detector == "automation_audit"
            ]
            counters = sync_audit_issues(hass, audit_insights)
            if counters.get("created") or counters.get("updated"):
                _LOGGER.debug(
                    "Repairs restore on boot: %d created, %d refreshed",
                    counters.get("created", 0),
                    counters.get("updated", 0),
                )
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Repairs restore on boot skipped: %s", err)

    entry.async_create_background_task(
        hass, _restore_repairs_on_boot(), "ha_insights_restore_repairs"
    )

    return True


async def _run_scheduled_scan(hass: HomeAssistant, entry_id: str) -> None:
    """Run a single scan pass for the given config entry. Logs + swallows.

    Used by the Phase D periodic scheduler. We never want a runaway
    detector or transient store error to break the recurring schedule —
    the next interval should still fire cleanly.
    """
    from .config_flow import get_blocked_entities, get_scan_areas
    from .detectors import DetectorContext, run_all_detectors

    entry_data = hass.data.get(DOMAIN, {}).get(entry_id)
    if not isinstance(entry_data, dict):
        return
    buffer_ = entry_data.get("buffer")
    store = entry_data.get("store")
    if buffer_ is None or store is None:
        return
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None:
        return
    try:
        ctx = DetectorContext(
            hass=hass,
            event_buffer=buffer_,
            blocked_entities=get_blocked_entities(entry),
            area_filter=get_scan_areas(entry),
        )
        added = await run_all_detectors(hass, ctx, store, entry=entry)
        _LOGGER.info("HA Insights scheduled scan complete: %d new insights", added)
    except Exception:  # noqa: BLE001
        _LOGGER.exception("HA Insights scheduled scan failed")


async def _notify_insight(
    hass: HomeAssistant,
    insight,
    mobile_targets: list[str] | None = None,
    *,
    policy: dict | None = None,
    entry_id: str = "default",
    entry: ConfigEntry | None = None,
) -> None:
    """Fire notifications announcing a new high-confidence insight.

    persistent_notification always fires (it's the in-HA toast). If the
    user configured one or more mobile-app notify targets, they receive
    the push too — gated by the anti-spam `policy` (confidence floor,
    attribution-confidence floor, quiet hours, daily cap). See
    notifications/mobile.py for the gate logic.

    notification_id includes the insight id so re-emissions of the same
    insight (e.g. on a re-scan) replace the existing notification rather
    than stacking; mobile notifier uses the same tag for the same reason.
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

    if mobile_targets:
        # Local import so circular import between __init__ and the
        # notifications subpackage isn't a problem at module load.
        from .notifications.mobile import fire_mobile_notifications

        await fire_mobile_notifications(
            hass,
            insight,
            notify_services=mobile_targets,
            policy=policy,
            entry_id=entry_id,
            entry=entry,
        )


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
async def _notify_audit_failure(
    hass: HomeAssistant,
    automation_id: str,
    alias: str | None,
    err: Exception,
) -> None:
    """Show a persistent_notification in HA's UI so a batch failure
    doesn't disappear into the logs. Users see the toast + can
    dismiss it from Settings → Notifications.
    """
    label = alias or automation_id
    await hass.services.async_call(
        "persistent_notification",
        "create",
        {
            "title": "HA Insights: audit suggest failed",
            "message": (
                f"Failed while suggesting improvements for "
                f"`{label}` (id {automation_id}): {err}.\n\n"
                "The batch stopped at this row. Other audit "
                "insights still apply via their Apply buttons. "
                "Click 🤖 Suggest on individual rows to retry one "
                "at a time."
            ),
            "notification_id": f"ha_insights_audit_fail_{automation_id}",
        },
        blocking=False,
    )


async def _emit_batch_summary_insight(
    store,
    *,
    processed: int,
    picked: int,
    spend_usd: float,
    cap_usd: float,
    budget_applies: bool,
) -> None:
    """Emit one summary insight after each audit_suggest_batch run
    so users see results in the panel, not just logs. Stable id —
    re-runs replace the previous summary instead of stacking."""
    from datetime import UTC, datetime as _dt

    from .insight import Insight, InsightKind

    fp = {"kind": "audit_suggest_batch_summary"}
    budget_note = (
        f"month-to-date ${spend_usd:.2f} of ${cap_usd:.2f}"
        if budget_applies
        else "local agent (no budget tracking)"
    )
    title = (
        f"Audit Suggest batch: ran {processed} of {picked} pending "
        f"audit insights · {budget_note}."
    )
    if processed == 0 and picked > 0:
        title = (
            f"Audit Suggest batch: 0 of {picked} processed — "
            "check Notifications for the first error."
        )
    await store.add_insight(
        Insight(
            id=Insight.compute_id(InsightKind.ANOMALY, fp),
            kind=InsightKind.ANOMALY,
            detector="audit_suggest_batch",
            area_id=None,
            title=title,
            confidence=0.5,
            fingerprint=fp,
            payload={
                "processed": processed,
                "picked": picked,
                "spend_usd": spend_usd,
                "cap_usd": cap_usd,
                "budget_applies": budget_applies,
                "advice": (
                    "This insight summarizes the most recent "
                    "audit_suggest_batch run. Dismiss it when you've "
                    "reviewed the suggestions. Re-running the service "
                    "replaces this insight with the new result."
                ),
            },
            payload_format="report",
            created_at=_dt.now(tz=UTC),
        )
    )


async def _emit_rollup_summary_insight(
    store, summary: dict,
) -> None:
    """Same pattern as the suggest-batch summary: one stable-id
    insight that updates on each rollup run."""
    from datetime import UTC, datetime as _dt

    from .insight import Insight, InsightKind

    fp = {"kind": "audit_rollup_summary"}
    processed = summary.get("entities_processed", 0)
    errors = summary.get("errors", 0)
    timed_out = len(summary.get("timed_out_entities") or [])
    next_due = summary.get("next_due_count", 0)
    duration = summary.get("batch_duration_sec", 0)
    skipped = summary.get("skipped_inflight", False)
    if skipped:
        title = (
            "Audit rollup skipped — a previous batch is still in "
            "flight. Try again in a moment."
        )
    else:
        parts = [f"Audit rollup: processed {processed} entities in {duration}s"]
        if errors:
            parts.append(f"{errors} error{'s' if errors != 1 else ''}")
        if timed_out:
            parts.append(f"{timed_out} timed out")
        if next_due > 0:
            parts.append(f"{next_due} more pending — run again to continue")
        else:
            parts.append("all target entities fresh")
        title = "; ".join(parts) + "."
    await store.add_insight(
        Insight(
            id=Insight.compute_id(InsightKind.ANOMALY, fp),
            kind=InsightKind.ANOMALY,
            detector="audit_rollup",
            area_id=None,
            title=title,
            confidence=0.4,
            fingerprint=fp,
            payload={
                **summary,
                "advice": (
                    "This summary updates each time you run "
                    "ha_insights.run_audit_rollup. Dismiss when done."
                ),
            },
            payload_format="report",
            created_at=_dt.now(tz=UTC),
        )
    )


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
        # Always go through run_all_detectors() so the yield discipline
        # is enforced in one place. See detectors/__init__.py for the
        # event-loop-starvation incident note.
        from .config_flow import get_blocked_entities, get_scan_areas
        from .detectors import DetectorContext, run_all_detectors

        for entry_id, entry_data in hass.data.get(DOMAIN, {}).items():
            if not isinstance(entry_data, dict):
                continue
            buffer_ = entry_data.get("buffer")
            store = entry_data.get("store")
            if buffer_ is None or store is None:
                continue
            entry = hass.config_entries.async_get_entry(entry_id)
            blocked = get_blocked_entities(entry) if entry else frozenset()
            areas = get_scan_areas(entry) if entry else frozenset()
            ctx = DetectorContext(
                hass=hass,
                event_buffer=buffer_,
                blocked_entities=blocked,
                area_filter=areas,
            )
            # User invoked the service directly — same logic as the WS
            # button: setup-phase guard exists for AUTOMATIC paths, not
            # explicit user action. Threading + watchdog keep it safe
            # even during HA startup.
            await run_all_detectors(
                hass, ctx, store, entry=entry, allow_during_setup=True
            )

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

    async def _run_audit_rollup(call: ServiceCall) -> None:
        """Manual rollup trigger — materialize recorder aggregates for
        the next batch of audit-target entities that need work.
        Defaults to 25 entities/batch, matching the auto-scheduler so
        a single click does meaningful work without 12 clicks to
        backfill a typical install. All safety rails apply (per-chunk
        timeout, per-entity wall clock, 120s batch budget, single-
        flight lock, 5000-row chunk cap). Caller may pass
        `batch_size` to override; capped at ROLLUP_BATCH_PER_RUN (50).
        """
        from .audit.rollup import (
            collect_audit_target_entities,
            run_rollup_batch,
        )
        from .detectors import _load_existing_automations

        autos = await _load_existing_automations(hass)
        target_eids = collect_audit_target_entities(autos)
        if not target_eids:
            _LOGGER.info("audit rollup: no audit-target entities found, nothing to do")
            return
        # Default 25 entities — same as the auto-scheduler so manual
        # and auto have predictable parity. Override via service data.
        _MANUAL_DEFAULT_BATCH = 25
        batch_size = int(call.data.get("batch_size") or _MANUAL_DEFAULT_BATCH)
        # Hard cap from outside — even if caller asks for 500, we
        # cap at the per-run config knob to protect HA.
        from .audit.rollup import ROLLUP_BATCH_PER_RUN
        batch_size = min(batch_size, ROLLUP_BATCH_PER_RUN)

        from .config_flow import get_blocked_entities

        for entry_id, entry_data in hass.data.get(DOMAIN, {}).items():
            if not isinstance(entry_data, dict) or "store" not in entry_data:
                continue
            entry = hass.config_entries.async_get_entry(entry_id)
            blocked = (
                get_blocked_entities(entry) if entry else frozenset()
            )
            store_obj = entry_data["store"]
            summary = await run_rollup_batch(
                hass,
                store_obj,
                target_entity_ids=target_eids,
                blocked_entities=blocked,
                batch_size=batch_size,
            )
            _LOGGER.info(
                "audit rollup: processed=%d errors=%d timed_out=%d "
                "budget_exceeded=%s next_due=%d duration=%ss "
                "skipped_inflight=%s",
                summary.get("entities_processed", 0),
                summary.get("errors", 0),
                len(summary.get("timed_out_entities", []) or []),
                summary.get("budget_exceeded", False),
                summary.get("next_due_count", 0),
                summary.get("batch_duration_sec", 0),
                summary.get("skipped_inflight", False),
            )
            await _emit_rollup_summary_insight(store_obj, summary)
            break  # one entry's store is shared; don't double-run

    async def _audit_suggest_batch(call: ServiceCall) -> None:
        """Run home_insights/audit_suggest against the next N
        report-format audit insights, in highest-confidence-first
        order. Gated by the per-month USD budget (default $5).

        Conservative defaults:
          batch_size: 3 (small)
          stop on first error
          single-flight via _AUDIT_BATCH_LOCK
          one config-entry's store at a time
        """
        from .audit.budget import (
            estimate_month_to_date,
            is_local_agent,
            is_within_budget,
        )
        from .config_flow import get_audit_monthly_budget_usd

        batch_size = max(1, min(10, int(call.data.get("batch_size") or 3)))
        for entry_id, entry_data in hass.data.get(DOMAIN, {}).items():
            if not isinstance(entry_data, dict) or "store" not in entry_data:
                continue
            store_obj = entry_data["store"]
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry is None:
                continue
            cap_usd = get_audit_monthly_budget_usd(entry)
            from .config_flow import get_preferred_agent_id as _gpa
            preferred_check = _gpa(entry)
            budget_applies = not is_local_agent(preferred_check)
            spend = await estimate_month_to_date(store_obj)
            if budget_applies and not is_within_budget(
                spend, monthly_cap_usd=cap_usd
            ):
                _LOGGER.info(
                    "audit suggest batch: month-to-date $%.2f exceeds "
                    "cap $%.2f — skipping batch (cloud agent)",
                    spend.estimated_usd,
                    cap_usd,
                )
                continue
            if not budget_applies:
                _LOGGER.debug(
                    "audit suggest batch: local agent %s — budget gate "
                    "disabled",
                    preferred_check,
                )
            # Pull report-format audit insights ordered by confidence.
            insights = await store_obj.list_insights(
                include_dismissed=False,
                include_applied=False,
                include_snoozed=False,
            )
            report_audits = [
                i for i in insights
                if i.detector == "automation_audit"
                and i.payload_format == "report"
            ]
            report_audits.sort(key=lambda i: i.confidence, reverse=True)
            picked = report_audits[:batch_size]
            if not picked:
                _LOGGER.info("audit suggest batch: nothing to suggest on")
                continue
            # Reuse the WS endpoint internally — same audit log, same
            # redactor, same caching path.
            from .audit.cache import compute_cache_key, get as cache_get
            from .audit.cache import put as cache_put
            from .insight import Insight, InsightKind
            from .llm import RedactionMode, Redactor, refine_insight
            from .config_flow import (
                get_blocked_entities,
                get_preferred_agent_id,
            )
            from .ws_api import _find_automation_by_id

            preferred = get_preferred_agent_id(entry)
            blocked = get_blocked_entities(entry) or frozenset()
            from datetime import UTC, datetime as _dt
            processed = 0
            for ins in picked:
                # Re-check budget between calls so we don't overrun
                # by N within a single batch when each call is big.
                # Skip the check entirely for local agents — no $.
                if budget_applies:
                    live_spend = await estimate_month_to_date(store_obj)
                    if not is_within_budget(
                        live_spend, monthly_cap_usd=cap_usd
                    ):
                        _LOGGER.info(
                            "audit suggest batch: budget exhausted mid-"
                            "batch after %d call(s)",
                            processed,
                        )
                        break
                payload = ins.payload or {}
                automation_id = payload.get("automation_id")
                if not automation_id:
                    continue
                observations = payload.get("observations") or []
                raw = await hass.async_add_executor_job(
                    _find_automation_by_id, hass, automation_id
                )
                if raw is None:
                    continue
                # Same sanitizer the WS endpoint uses — PyYAML can't
                # represent HA's Template / Selector / OrderedDict
                # injections. Flatten through JSON first.
                from .ws_api import _sanitize_yaml_safe

                raw = _sanitize_yaml_safe(raw)
                obs_kinds = [o.get("kind", "") for o in observations]
                # Include integration_version in the cache key so a
                # detector/prompt rewrite in a new release invalidates
                # cached LLM refinements for the same YAML automatically.
                from .ws_api import _get_integration_version

                _iv = await _get_integration_version(hass)
                cache_key = compute_cache_key(raw, obs_kinds, _iv)
                if cache_get(cache_key) is not None:
                    # Already cached — skip, no tokens needed
                    continue
                virtual = Insight(
                    id=Insight.compute_id(
                        InsightKind.AUTOMATION_PROPOSAL,
                        {"automation_id": automation_id,
                         "kind": "automation_audit_suggest"},
                    ),
                    kind=InsightKind.AUTOMATION_PROPOSAL,
                    detector="user_audit",
                    area_id=None,
                    title=f"Refine: {raw.get('alias') or automation_id}",
                    confidence=1.0,
                    fingerprint={
                        "automation_id": automation_id,
                        "kind": "automation_audit_suggest",
                    },
                    payload=raw,
                    payload_format="automation",
                    created_at=_dt.now(tz=UTC),
                )
                redactor = Redactor(
                    store_obj,
                    mode=RedactionMode.AGGRESSIVE,
                    blocked_entities=blocked,
                )
                feedback = "Audit findings:\n" + "\n".join(
                    f"- {o.get('text', '')}" for o in observations
                ) + "\n\nSuggest concrete YAML edits per finding."
                try:
                    result = await refine_insight(
                        hass,
                        agent_id=None,
                        insight=virtual,
                        redactor=redactor,
                        feedback=feedback,
                        preferred_agent_id=preferred,
                    )
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning(
                        "audit suggest batch: %s failed: %s",
                        automation_id,
                        err,
                    )
                    # Surface in HA UI so the user doesn't have to
                    # dig through logs.
                    await _notify_audit_failure(
                        hass, automation_id, raw.get("alias"), err
                    )
                    break  # Stop on first failure — backoff
                if result.success and result.refined_payload is not None:
                    cache_put(
                        cache_key,
                        refined_yaml=result.refined_payload,
                        rationale=result.rationale,
                        diff_summary=result.diff_summary,
                    )
                    processed += 1
                else:
                    break
            _LOGGER.info(
                "audit suggest batch: processed=%d of %d picked; "
                "month-to-date $%.2f / $%.2f",
                processed,
                len(picked),
                spend.estimated_usd,
                cap_usd,
            )
            # Surface the batch outcome ON THE PANEL as a single
            # insight so users see what happened without checking logs.
            await _emit_batch_summary_insight(
                store_obj,
                processed=processed,
                picked=len(picked),
                spend_usd=spend.estimated_usd,
                cap_usd=cap_usd,
                budget_applies=budget_applies,
            )
            break  # only one entry's store needed

    async def _reload_ui(call: ServiceCall) -> None:
        """Re-register the sidebar panel with a fresh cache-bust query
        string so deployed bundle changes land without an HA restart.

        Workflow: deploy new ha-insights-panel.js to /config/www/, call
        this service (or click the "🔄 Reload UI" panel button), then
        hard-refresh the browser. The browser sees a new module_url
        (different ?v=...) and skips its cache.
        """
        await _async_register_panel(hass)
        _LOGGER.info("HA Insights panel re-registered (cache-bust refreshed)")

    hass.services.async_register(DOMAIN, "purge_observations", _purge_observations)
    hass.services.async_register(DOMAIN, "scan_now", _scan_now)
    hass.services.async_register(DOMAIN, "backfill", _backfill)
    hass.services.async_register(DOMAIN, "reload_ui", _reload_ui)
    hass.services.async_register(DOMAIN, "run_audit_rollup", _run_audit_rollup)
    hass.services.async_register(DOMAIN, "audit_suggest_batch", _audit_suggest_batch)


async def _async_register_panel(hass: HomeAssistant) -> None:
    """Register the HA Insights sidebar panel.

    Loads /local/ha-insights-panel.js and mounts <ha-insights-panel>. The
    file is shipped via HACS (or copied manually to www/) — the integration
    just registers the URL path + sidebar metadata.

    The module_url is bumped with a cache-buster based on the panel JS
    file's mtime + size (mtime alone has second-precision collisions on
    fast deploys). HA's static handler serves /local/* with a 31-day
    Cache-Control, so without a fresh query string the browser can hold
    a stale build for weeks.

    CRITICAL: we ALWAYS `async_remove_panel` first so a fresh URL is
    re-registered. The previous version caught the "already registered"
    ValueError and swallowed it, which meant the URL was frozen at the
    first-ever startup mtime — config-entry reloads couldn't refresh the
    cache-buster, and only a full HA restart would let the browser see
    a new bundle. That was the user-reported "had to restart HA + disable
    cache" symptom.

    `os.path.getmtime` is sync I/O so it must run via the executor —
    HA's blocking-call detector flags every event-loop stat() as a
    warning otherwise. (v1.0 review #11.)
    """
    from homeassistant.components.frontend import (
        async_register_built_in_panel,
        async_remove_panel,
    )

    panel_path = hass.config.path("www/ha-insights-panel.js")

    def _read_signature() -> str:
        """Composite signature: mtime + size. Size catches edits that
        happen within a 1-second mtime window, which fast `npm run build
        && cp` cycles produce on local dev."""
        try:
            st = os.stat(panel_path)
            return f"{int(st.st_mtime)}-{st.st_size}"
        except OSError:
            return str(int(time.time()))

    cache_bust = await hass.async_add_executor_job(_read_signature)

    # Always unregister + re-register so the URL refreshes every time.
    # Only call `async_remove_panel` when the panel is ACTUALLY
    # registered — otherwise HA's frontend logs a "Removing unknown
    # panel ha-insights" warning every reload. The original comment
    # claimed remove was idempotent; the frontend module disagrees.
    # `hass.data["frontend_panels"]` is HA's authoritative registry
    # (see homeassistant/components/frontend/__init__.py); falling
    # back to a benign no-op if the structure isn't present.
    try:
        panels = hass.data.get("frontend_panels", {})
        if _PANEL_URL_PATH in panels:
            async_remove_panel(hass, _PANEL_URL_PATH)
    except Exception:  # noqa: BLE001 — defensive; never block setup over this
        _LOGGER.debug(
            "panel pre-remove probe raised", exc_info=True
        )

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
    _LOGGER.debug(
        "Registered HA Insights panel with cache-bust v=%s", cache_bust
    )


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
    if data.get("unsub_adaptive") is not None:
        data["unsub_adaptive"]()
    if data.get("unsub_analytics") is not None:
        data["unsub_analytics"]()
    # Phase D scheduler cleanup. Cancelling unregisters the time-interval
    # listener so we don't keep firing scans after unload.
    if data.get("scan_scheduler_cancel") is not None:
        data["scan_scheduler_cancel"]()
    # v1.2 auto-rollup scheduler cleanup. Same pattern.
    if data.get("rollup_scheduler_cancel") is not None:
        data["rollup_scheduler_cancel"]()
    # v1.4: drop in-memory mobile-push daily counter for this entry
    # so a reload doesn't inherit the in-flight day's count.
    try:
        from .notifications.mobile import reset_daily_counter_for_entry

        reset_daily_counter_for_entry(entry.entry_id)
    except Exception:  # noqa: BLE001
        _LOGGER.debug("daily-counter reset on unload skipped", exc_info=True)
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

        # Belt-and-braces: only call remove if the panel is still
        # in HA's registry. If a previous crash left our flag set
        # but HA already cleaned the panel up, calling remove would
        # log "unknown panel" again.
        panels = hass.data.get("frontend_panels", {})
        if _PANEL_URL_PATH in panels:
            async_remove_panel(hass, _PANEL_URL_PATH)
        hass.data[DOMAIN][_PANEL_REGISTERED_FLAG] = False
        # NOTE: Repairs entries are intentionally NOT cleared on
        # unload. HA's Repairs surface is expected to persist
        # across restarts, like any other integration's issues.
        # The actual sweep happens in `async_remove_entry` below,
        # which only fires on uninstall — not on restart or reload.
        # Clear module-level cached state so a reload picks up a clean
        # slate. None of these belong on the entry — they're shared
        # across the integration. Includes the rollup progress dict
        # (so the WS endpoint doesn't keep returning a previous load's
        # finished_ts/last_summary).
        try:
            from .audit.rollup import reset_progress as _reset_rollup_progress

            _reset_rollup_progress()
        except Exception:  # noqa: BLE001
            pass
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Called only on full uninstall (not on restart / reload).

    Sweep our Repairs entries so we don't leave orphan rows in
    HA's issue registry. Without this, an uninstalled HA Insights
    would still appear as unresolved Repairs forever.

    HA invokes this AFTER `async_unload_entry`, so the integration
    is already torn down — we just clean the registry.
    """
    try:
        from .audit.repairs import clear_all_audit_issues

        cleared = clear_all_audit_issues(hass)
        if cleared:
            _LOGGER.info(
                "HA Insights uninstall: cleared %d Repairs entries",
                cleared,
            )
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Repairs cleanup on uninstall failed: %s", err)
