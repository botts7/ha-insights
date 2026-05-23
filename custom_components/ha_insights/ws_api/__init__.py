"""WebSocket API for HA Insights.

Stable contract from v0.1 (per docs/ARCHITECTURE.md). Cards consume:
  - home_insights/hello       -> handshake (version + supported methods)
  - home_insights/list        -> list insights (filterable)
  - home_insights/subscribe   -> live stream of change events
  - home_insights/dismiss     -> dismiss an insight
  - home_insights/snooze      -> snooze an insight
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from ..const import DOMAIN
from ..lib.title_cleanup import (
    strip_already_automated_cta as _strip_already_automated_cta,
)
from ._helpers import (
    _audit_attempts,
    _get_buffer,
    _get_store,
    _require_admin,
    _resolve_blocked_entities,
    _resolve_preferred_agent_id,
)

# v1.13.4-v1.13.7 steps 2-5 of the ws_api refactor — Find My Device,
# BLE live-find, ManagedDevices handlers, and REFINE helpers moved
# out to their own files. Imported back here so async_register + any
# external consumer keeps working.
from ._refine_helpers import _find_automation_by_id, _sanitize_yaml_safe
from .audit_suggest import ws_audit_suggest
from .ble_find import (
    ws_ble_capability,
    ws_ble_live_find,
)
from .chat import ws_chat_create_automation
from .companion_scan import (
    ws_companion_scan_sample,
    ws_companion_scan_subscribe,
    ws_companion_scan_unsubscribe,
)
from .hypothesize import ws_hypothesize
from .identify import (
    ws_identify_capability,
    ws_identify_entity,
    ws_perturbation_guide,
    ws_perturbation_test,
)
from .managed_devices import (
    _managed_devices_set,
    ws_list_managed_devices,
    ws_set_device_managed,
)
from .refine import (
    ws_apply_automation_refinement,
    ws_refine,
    ws_refine_automation,
    ws_refine_cost_estimate,
)
from .wifi_find_self import ws_wifi_find_capability, ws_wifi_find_self

# Re-export for any external consumer that's reaching into ws_api
# for these helpers. New code should import from `._helpers` directly.
__all__ = [
    "_audit_attempts",
    "_get_buffer",
    "_get_store",
    "_require_admin",
    "_resolve_blocked_entities",
    "_resolve_preferred_agent_id",
    "ws_apply_automation_refinement",
    "ws_audit_suggest",
    "ws_ble_capability",
    "ws_ble_live_find",
    "ws_chat_create_automation",
    "ws_companion_scan_sample",
    "ws_companion_scan_subscribe",
    "ws_companion_scan_unsubscribe",
    "ws_hypothesize",
    "ws_identify_capability",
    "ws_identify_entity",
    "ws_list_managed_devices",
    "ws_perturbation_guide",
    "ws_perturbation_test",
    "ws_refine",
    "ws_refine_automation",
    "ws_refine_cost_estimate",
    "ws_set_device_managed",
    "ws_wifi_find_capability",
    "ws_wifi_find_self",
]

_LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ..insight import Insight


WS_PROTOCOL_VERSION = 1


async def _record_verdict_safely(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    insight_id: str,
    kind: str,
) -> None:
    """Append a row to the verdict_history timeline.

    Best-effort: failures don't break the user-visible action because
    the underlying state mutation (dismiss/retire/apply/etc.) has
    already succeeded by the time we get here. v1.14.5a — feeds
    v1.14.5b AdaptiveFeedbackDetector.

    `kind` is the VerdictKind string value ('dismissed', 'retired',
    'applied', etc.); see lib/user_verdict_history.py.
    """
    try:
        from ..lib.environmental_fingerprint import (
            capture_environmental_fingerprint,
            fingerprint_to_dict,
            hash_user_id,
        )

        store = _get_store(hass)
        if store is None:
            return
        fp = capture_environmental_fingerprint(hass)
        user_id = getattr(getattr(connection, "user", None), "id", None)
        await store.record_verdict(
            insight_id,
            kind=kind,
            fingerprint=fingerprint_to_dict(fp),
            user_id_hash=hash_user_id(user_id),
        )
    except Exception:
        _LOGGER.debug(
            "Failed to record verdict timeline entry for %s/%s",
            insight_id,
            kind,
            exc_info=True,
        )


async def _get_integration_version(hass: HomeAssistant) -> str:
    """Resolve the integration version dynamically from manifest.json
    via HA's loader. NO local caching here — `async_get_integration`
    is itself cached by HA's loader (process-lifetime, invalidated on
    integration upgrade), and an extra layer just buys us a staleness
    bug: a previous version was cached on `hass.data[DOMAIN]` which
    `async_unload_entry` doesn't touch, so a reloaded integration
    after a manifest bump kept reporting the old version.
    """
    try:
        from homeassistant.loader import async_get_integration

        integration = await async_get_integration(hass, DOMAIN)
        return str(integration.version) if integration.version else "unknown"
    except Exception:
        return "unknown"

SUPPORTED_METHODS = (
    "hello",
    "list",
    "subscribe",
    "dismiss",
    "snooze",
    "apply",
    "undo",
    "scan_now",
    "cancel_scan",
    "purge_all",
    "explain",
    "refine",
    "test_actions",
    "backfill_status",
    "recorder_status",
    "export_dev_audit",
    "rollup_progress",
    "redaction_preview",
    "audit_log",
    "audit_suggest",
    "hypothesize",
    "refine_cost_estimate",
    "list_entries",
    # `dev_inject_event` is intentionally NOT here — debug-only handler,
    # not part of the client-discoverable API. Enforced by
    # test_supported_methods_match.py.
    "get_automation",
    "refine_automation",
    "apply_automation_refinement",
    "detector_directory",
    "inject_examples",
    "clear_examples",
    "analytics_preview",
    "list_ha_users",
    "get_user_overrides",
    "set_user_override",
    # v1.5.44: Suggested-Additions deterministic surface — server builds
    # candidate entities from Hierarchy + EventBuffer + ManualHabit, card
    # shows checkbox modal, user picks, apply via existing
    # `home_insights/apply` with new `additional_entity_ids` field.
    "suggest_additions",
    # v1.5.46: Retire lifecycle alongside Snooze / Dismiss. Retired
    # insights stay suppressed across re-detections — the user has
    # consciously decided this pattern is NOT something to automate.
    # Reversible via `unretire`.
    "retire",
    "unretire",
    # v1.7.7: per-device "managed externally" flag — Strategy 2 from
    # the device-internal-logic memory. User asserts "this device
    # handles its own logic" and insights from it are fully suppressed.
    "list_managed_devices",
    "set_device_managed",
    # v1.10 Phase A: Find My Device — make an entity announce itself.
    # `identify_capability` returns what method (flash / chime / etc.)
    # the entity supports; `identify_entity` actually triggers it.
    # Used by the bulk-area-assign dialog so the user can locate
    # devices with cryptic names before assigning them an area.
    "identify_capability",
    "identify_entity",
    # v1.10 Phase B: perturbation touch-test for passive sensors.
    # `perturbation_guide` returns the per-device_class instruction
    # the card shows ("touch with finger" / "breathe on it");
    # `perturbation_test` opens a listening window, watches every
    # entity of the same device_class, and returns ranked z-scores
    # so the user sees which entity actually spiked.
    "perturbation_guide",
    "perturbation_test",
    # v1.12 Find My Device — BLE live-find. `ble_capability` returns
    # whether an entity has a BLE address visible in the registry +
    # which proxies (if any) currently see it. `ble_live_find` is a
    # streaming subscription: opens a server-side BLE advertisement
    # callback, EMA-smooths RSSI, forwards live updates to the card
    # for the "warmer/colder" UI. Auto-unsubscribes on WS close.
    "ble_capability",
    "ble_live_find",
    # v1.13.2 — Blank-canvas automation chat. User types "turn on
    # porch light at sunset" → LLM generates YAML automation using
    # the existing Refine plumbing + failover chain. The differentiator
    # vs AI Agent HA: callers can pass `related_insight_ids` to weave
    # the user's actual habits (high-confidence detected patterns)
    # into the prompt as context. No prior insight required — works
    # on any free-form prompt.
    "chat_create_automation",
    # v1.15.0 — PWA companion-scanner stream (experimental). The
    # find-my-ha PWA streams BLE RSSI samples from the phone into
    # the live-find EMA pipeline. Three messages: subscribe / sample
    # / unsubscribe. Marked experimental — PWA is v0.2 / early-
    # access at the v1.15.0 release point. Stable contract:
    # find-my-ha/docs/WS_PROTOCOL.md.
    "companion_scan_subscribe",
    "companion_scan_sample",
    "companion_scan_unsubscribe",
    # v1.21 — Wi-Fi inverse-multilateration walking-find. Streams the
    # phone's per-AP RSSI as state changes; pairs with find-my-ha
    # v0.6.x for warmer/colder UX on non-BLE devices. Admin-gated.
    "wifi_find_self",
    # v1.21.1 — batch Wi-Fi-trackability query. Read-only, not admin-
    # gated. PWA pre-filters its entity picker so users don't pick a
    # mobile_app GPS-only tracker and only find out after Start.
    "wifi_find_capability",
)


@callback
def async_register(hass: HomeAssistant) -> None:
    """Register all WS handlers. Idempotent via the WS framework."""
    websocket_api.async_register_command(hass, ws_hello)
    websocket_api.async_register_command(hass, ws_list)
    websocket_api.async_register_command(hass, ws_subscribe)
    websocket_api.async_register_command(hass, ws_dismiss)
    websocket_api.async_register_command(hass, ws_snooze)
    websocket_api.async_register_command(hass, ws_apply)
    websocket_api.async_register_command(hass, ws_scan_now)
    websocket_api.async_register_command(hass, ws_cancel_scan)
    websocket_api.async_register_command(hass, ws_purge_all)
    websocket_api.async_register_command(hass, ws_explain)
    websocket_api.async_register_command(hass, ws_refine)
    websocket_api.async_register_command(hass, ws_test_actions)
    websocket_api.async_register_command(hass, ws_backfill_status)
    websocket_api.async_register_command(hass, ws_recorder_status)
    websocket_api.async_register_command(hass, ws_export_dev_audit)
    websocket_api.async_register_command(hass, ws_rollup_progress)
    websocket_api.async_register_command(hass, ws_redaction_preview)
    websocket_api.async_register_command(hass, ws_audit_log)
    websocket_api.async_register_command(hass, ws_undo)
    websocket_api.async_register_command(hass, ws_hypothesize)
    websocket_api.async_register_command(hass, ws_refine_cost_estimate)
    websocket_api.async_register_command(hass, ws_list_entries)
    websocket_api.async_register_command(hass, ws_dev_inject_event)
    websocket_api.async_register_command(hass, ws_get_automation)
    websocket_api.async_register_command(hass, ws_refine_automation)
    websocket_api.async_register_command(hass, ws_apply_automation_refinement)
    websocket_api.async_register_command(hass, ws_audit_suggest)
    websocket_api.async_register_command(hass, ws_detector_directory)
    websocket_api.async_register_command(hass, ws_inject_examples)
    websocket_api.async_register_command(hass, ws_clear_examples)
    websocket_api.async_register_command(hass, ws_analytics_preview)
    websocket_api.async_register_command(hass, ws_list_ha_users)
    websocket_api.async_register_command(hass, ws_get_user_overrides)
    websocket_api.async_register_command(hass, ws_set_user_override)
    websocket_api.async_register_command(hass, ws_suggest_additions)
    websocket_api.async_register_command(hass, ws_retire)
    websocket_api.async_register_command(hass, ws_unretire)
    # v1.23.0: bulk dismiss / retire for clearing batches of noise
    # (Discussion #104 — user had 105 Uptime Kuma items to dismiss).
    websocket_api.async_register_command(hass, ws_bulk_dismiss)
    websocket_api.async_register_command(hass, ws_bulk_retire)
    # v1.7.7: per-device "managed externally" flag
    websocket_api.async_register_command(hass, ws_list_managed_devices)
    websocket_api.async_register_command(hass, ws_set_device_managed)
    # v1.10 Phase A: Find My Device — identify-capable orphans
    websocket_api.async_register_command(hass, ws_identify_capability)
    websocket_api.async_register_command(hass, ws_identify_entity)
    # v1.10 Phase B: perturbation touch-test for passive sensors
    websocket_api.async_register_command(hass, ws_perturbation_guide)
    websocket_api.async_register_command(hass, ws_perturbation_test)
    # v1.12 BLE live-find
    websocket_api.async_register_command(hass, ws_ble_capability)
    websocket_api.async_register_command(hass, ws_ble_live_find)
    # v1.13.2 Blank-canvas automation chat
    websocket_api.async_register_command(hass, ws_chat_create_automation)
    # v1.15.0 PWA companion-scanner stream (experimental) — RSSI samples
    # from a phone-resident scanner threaded into the BLE live-find
    # smoothing pipeline. Stable contract docs:
    # find-my-ha/docs/WS_PROTOCOL.md.
    websocket_api.async_register_command(hass, ws_companion_scan_subscribe)
    websocket_api.async_register_command(hass, ws_companion_scan_sample)
    websocket_api.async_register_command(hass, ws_companion_scan_unsubscribe)
    # v1.21.0 Wi-Fi inverse-multilateration walking-find. Streams the
    # phone's per-AP RSSI as state changes; PWA renders warmer/colder
    # for non-BLE Wi-Fi-trackable devices. Admin-gated.
    websocket_api.async_register_command(hass, ws_wifi_find_self)
    # v1.21.1 batch capability query — read-only, not admin-gated. PWA
    # calls it on entering Wi-Fi mode to pre-filter the entity picker
    # to only entities with rx_rssi+ap_mac (or equivalents) actually
    # exposed in current state attributes.
    websocket_api.async_register_command(hass, ws_wifi_find_capability)


# Helpers _get_store / _get_buffer / _audit_attempts /
# _resolve_blocked_entities / _resolve_preferred_agent_id moved to
# ws_api/_helpers.py during the v1.13 refactor. Imported at the top
# of this module + re-exported via __all__ for backward compat.


# --- Handlers ---


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/hello",
        vol.Optional("card_version"): str,
    }
)
@websocket_api.async_response
async def ws_hello(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Handshake — return integration metadata + supported methods + privacy mode.

    Async so we can resolve the integration version via HA's
    public loader (`async_get_integration`) instead of hardcoding
    a string that drifts from manifest.json. The resolver caches
    after the first call.
    """
    from ..config_flow import get_active_mode

    privacy_mode = "off"
    for entry in hass.config_entries.async_entries(DOMAIN):
        privacy_mode = get_active_mode(entry)
        break
    integration_version = await _get_integration_version(hass)
    connection.send_result(
        msg["id"],
        {
            "integration_version": integration_version,
            "ws_protocol_version": WS_PROTOCOL_VERSION,
            "supported_methods": list(SUPPORTED_METHODS),
            "privacy_mode": privacy_mode,
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/list",
        vol.Optional("include_dismissed", default=False): bool,
        vol.Optional("include_applied", default=False): bool,
        vol.Optional("include_snoozed", default=False): bool,
        # v1.5.46: opt-in surface for retired insights, used by the
        # history / management view in the panel. Day-to-day list
        # stays clean by default.
        vol.Optional("include_retired", default=False): bool,
    }
)
@websocket_api.async_response
async def ws_list(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """List insights from the store, enriched with domain + device_class.

    Domain is split from the entity_id in each insight's fingerprint;
    device_class is looked up against the entity registry. Both feed
    the panel's filter-chip UI and are derived (not stored) so we don't
    need a schema migration.
    """
    store = _get_store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_set_up", "Store not initialized")
        return
    insights = await store.list_insights(
        include_dismissed=msg["include_dismissed"],
        include_applied=msg["include_applied"],
        include_snoozed=msg["include_snoozed"],
        include_retired=msg["include_retired"],
    )

    # v1.2: reuse the EntityHierarchy built by the most recent scan
    # (stashed on hass.data) instead of independently walking the
    # registries. Rebuild on-demand if missing (no scan yet, or
    # cache cleared by integration reload).
    hierarchy = None
    try:
        from ..detectors.hierarchy import build_hierarchy

        for entry_data_val in hass.data.get(DOMAIN, {}).values():
            if isinstance(entry_data_val, dict) and "hierarchy" in entry_data_val:
                hierarchy = entry_data_val["hierarchy"]
                break
        if hierarchy is None:
            hierarchy = build_hierarchy(hass)
    except Exception:
        hierarchy = None

    # Pull what ws_list specifically needs out of the hierarchy. Older
    # code paths still expect raw dicts so keep these names.
    if hierarchy is not None:
        device_class_by_entity: dict[str, str | None] = hierarchy.device_class_of
        platform_by_entity: dict[str, str | None] = hierarchy.integration_of
        device_of_by_entity: dict[str, str | None] = hierarchy.device_of
    else:
        device_class_by_entity = {}
        platform_by_entity = {}
        device_of_by_entity = {}

    # v1.7.7: snapshot the user's managed-externally device set + name
    # lookups so per-insight enrichment can show {device_id, name,
    # managed} for the detail-dialog toggle.
    managed_devices_set: set[str] = set()
    device_name_by_id: dict[str, str] = {}
    try:
        entries_for_managed = hass.config_entries.async_entries(DOMAIN)
        if entries_for_managed:
            managed_devices_set = _managed_devices_set(entries_for_managed[0])
        from homeassistant.helpers import device_registry as _dr

        d_reg = _dr.async_get(hass)
        for device in d_reg.devices.values():
            device_name_by_id[device.id] = (
                device.name_by_user or device.name or device.id[:8]
            )
    except Exception:
        pass

    # Build entity → list-of-automation-names map so each insight can
    # surface "🤖 used in 3 automations" with the actual aliases. Reads
    # the same source as the conflict scanner (HA's automation registry
    # + automations.yaml), then walks each automation's triggers and
    # actions to collect every entity_id mentioned.
    #
    # Scene/group expansion: an automation that targets `scene.evening`
    # or `light.outdoor_group_light` is logically "using" all the
    # underlying lights, even though the YAML only lists the parent. We
    # walk the state machine for any entity with `attributes.entity_id`
    # (scenes, group_lights, group_covers, binary_sensor.group, etc.)
    # and unfold each parent reference into its members so the pill
    # shows up on the LEAVES, not just the parent.
    entity_to_automations: dict[str, list[str]] = {}
    try:
        from ..apply.conflict_scanner import _as_list, _extract_target_entities
        from ..detectors import _load_existing_automations

        # v1.2: pull container + script-target relationships straight from
        # the cached hierarchy instead of re-walking the state machine.
        # Falls back to empty dicts if no scan has run yet.
        if hierarchy is not None:
            container_to_members: dict[str, frozenset[str]] = hierarchy.members_of
            # The hierarchy already folded script targets INTO members_of
            # (script.X → its action target entity_ids), so a separate
            # script_targets lookup isn't needed for expansion below.
            script_targets: dict[str, set[str]] = {}
        else:
            container_to_members = {}
            script_targets = {}

        def _expand(refs: set[str]) -> set[str]:
            """Expand parent containers → members. The hierarchy already
            folded script targets into members_of, so checking it covers
            both scenes and scripts uniformly. One-hop only."""
            out = set(refs)
            for eid in list(refs):
                out |= set(container_to_members.get(eid, frozenset()))
                # Legacy fallback if container_to_members is empty
                if not container_to_members and eid.startswith("script."):
                    out |= script_targets.get(eid, set())
            return out

        autos = await _load_existing_automations(hass)
        for auto in autos:
            label = auto.get("alias") or auto.get("id") or "(unnamed automation)"
            referenced: set[str] = set()
            # Trigger entity references
            for t in _as_list(auto.get("trigger")):
                if not isinstance(t, dict):
                    continue
                ti = t.get("entity_id")
                if isinstance(ti, str):
                    referenced.add(ti)
                elif isinstance(ti, list):
                    referenced.update(e for e in ti if isinstance(e, str))
            # Action target references — reuse the conflict scanner helper
            referenced |= _extract_target_entities(auto.get("action"))
            # Action SERVICE calls — `service: script.X` doesn't appear as
            # a target so _extract_target_entities misses it. Add explicitly.
            for action in _as_list(auto.get("action")):
                if not isinstance(action, dict):
                    continue
                svc = action.get("service")
                if isinstance(svc, str) and svc.startswith("script."):
                    # script.evening_lights → script.evening_lights (entity_id form)
                    referenced.add(svc)
            # Expand: scene → members, group light → bulbs, script → targets
            referenced = _expand(referenced)
            for eid in referenced:
                entity_to_automations.setdefault(eid, []).append(label)
    except Exception:
        pass  # additive enrichment; missing values just become empty lists

    def _entities_in_insight(ins) -> set[str]:
        """All entity_ids that appear in an insight's fingerprint or payload.
        Used to look up which existing automations reference any of them."""
        out: set[str] = set()
        for key in (
            "entity_id",
            "leader_entity_id",
            "follower_entity_id",
            "target_entity_id",
        ):
            v = ins.fingerprint.get(key)
            if isinstance(v, str) and "." in v:
                out.add(v)
        # Also walk action.target.entity_id in payload (long_tail, schedule, etc.)
        if isinstance(ins.payload, dict):
            try:
                from ..apply.conflict_scanner import _extract_target_entities

                out |= _extract_target_entities(ins.payload.get("action"))
            except Exception:
                pass
        return out

    # Two-way lookup so the same builder handles alias-labels and id-labels.
    # `find_conflicts` returns the automation's *id* (preferred) into
    # conflicts_with; `referenced_in_automations` (built above) records
    # the *alias*. Without id_to_alias, the conflicts_with path lost
    # its URL → 🔁 pill silently fell back to /config/automation/dashboard.
    alias_to_id: dict[str, str] = {}
    id_to_alias: dict[str, str] = {}
    try:
        from ..detectors import _load_existing_automations as _lea

        autos_for_ids = await _lea(hass)
        for auto in autos_for_ids:
            aid = auto.get("id")
            alias = auto.get("alias")
            if isinstance(aid, str):
                if isinstance(alias, str):
                    alias_to_id[alias] = aid
                    id_to_alias[aid] = alias
                else:
                    # No alias — id IS the visible label (older YAML).
                    alias_to_id[aid] = aid
                    id_to_alias[aid] = aid
    except Exception:
        pass

    def _build_automation_links(labels: list | tuple) -> list[dict]:
        """Resolve a list of automation labels (alias OR id) into
        [{id?, alias, url?}] entries the card can render as clickable
        chips. Accepts both forms because `conflicts_with` ships ids and
        `referenced_in_automations` ships aliases. Skips duplicates
        within a single insight."""
        seen_local: set[str] = set()
        out: list[dict] = []
        for label in labels:
            if not isinstance(label, str) or label in seen_local:
                continue
            seen_local.add(label)
            # Branch on whether the label looks like an id (matches a
            # known automation id) or an alias.
            aid: str | None = None
            alias_for_display = label
            if label in id_to_alias:
                # label IS an id; use its alias for display
                aid = label
                alias_for_display = id_to_alias[label]
            elif label in alias_to_id:
                # label is an alias; look up its id
                aid = alias_to_id[label]
                alias_for_display = label
            entry: dict[str, str] = {"alias": alias_for_display}
            if aid:
                entry["id"] = aid
                entry["url"] = f"/config/automation/edit/{aid}"
            out.append(entry)
        return out

    # Platforms whose entities commonly carry DEVICE-SIDE automation
    # logic that HA never sees: feeding schedules, vacuum schedules,
    # smart switch timers configured in the vendor app, thermostat
    # schedules pushed from the device's web UI, etc. If an insight's
    # entity is from one of these AND has no HA automation reference,
    # we tag it with external_source so the card can surface a
    # "🏷️ managed externally" pill — the user knows we noticed the
    # pattern but it's not something they should "automate in HA."
    _EXTERNAL_SCHEDULE_PLATFORMS = frozenset(
        {
            "tuya",
            "tuya_local",
            "localtuya",
            "smartlife",
            "ewelink",
            "ewelink_local",
            "smartthinq",
            "samsungtv_smart",
            "roborock",
            "xiaomi_vacuum",
            "miio",
            "midea_ac_lan",
            "homematic",
            "homematicip_local",
            "tasmota_irhvac",
            "shelly",
            # Robot pet feeders / cat boxes / aquaponic systems / etc.
            "petkit",
            "feeder",
        }
    )
    _EXTERNAL_PLATFORM_LABEL: dict[str, str] = {
        "tuya": "Tuya app",
        "tuya_local": "Tuya app",
        "localtuya": "Tuya app",
        "smartlife": "Smart Life app",
        "ewelink": "eWeLink app",
        "ewelink_local": "eWeLink app",
        "smartthinq": "LG ThinQ app",
        "roborock": "Roborock app",
        "xiaomi_vacuum": "Mi Home app",
        "miio": "Mi Home app",
        "midea_ac_lan": "Midea app",
        "homematic": "HomeMatic CCU",
        "homematicip_local": "HomeMatic CCU",
        "petkit": "PetKit app",
    }

    # v1.4: lookup table for detector maturity. The Detector class
    # exposes a class-level `maturity` attr (Maturity enum: stable /
    # beta / experimental). Card uses this to render BETA /
    # EXPERIMENTAL badges, so we surface it on every insight.
    try:
        from ..detectors import DETECTORS

        detector_maturity_by_name: dict[str, str] = {}
        for det_name, det_cls in DETECTORS.items():
            m = getattr(det_cls, "maturity", None)
            if m is not None:
                detector_maturity_by_name[det_name] = (
                    m.value if hasattr(m, "value") else str(m)
                )
    except Exception:
        detector_maturity_by_name = {}

    # v1.12.11: snapshot the entity registry once so the enrichment loop
    # can look up per-entity `created_at` for the newly-added badge.
    # Falls back to None (no badges) on older HA versions where
    # RegistryEntry doesn't carry created_at.
    entity_registry_snapshot = None
    try:
        from homeassistant.helpers import entity_registry as _er

        entity_registry_snapshot = _er.async_get(hass)
    except Exception:
        entity_registry_snapshot = None

    enriched: list[dict[str, Any]] = []
    for ins in insights:
        d = ins.to_dict()
        # Enrich with detector maturity so the card can render the
        # 🟡 BETA / 🧪 EXPERIMENTAL pill alongside confidence/integration.
        # Lookup is cheap (dict get) and matches the per-insight loop
        # the rest of the enrichment already runs.
        d["maturity"] = detector_maturity_by_name.get(ins.detector, "stable")
        # Pull primary entity_id from fingerprint. Different detectors use
        # different keys (entity_id, leader_entity_id, follower_entity_id).
        eid = (
            ins.fingerprint.get("entity_id")
            or ins.fingerprint.get("follower_entity_id")
            or ins.fingerprint.get("leader_entity_id")
        )
        if isinstance(eid, str) and "." in eid:
            d["domain"] = eid.split(".", 1)[0]
            d["device_class"] = device_class_by_entity.get(eid)
        else:
            d["domain"] = None
            d["device_class"] = None
        # v1.12.11: surface entity_age_days when the primary entity was
        # added within the last NEWLY_ADDED_THRESHOLD_DAYS days. The card
        # renders a "🆕 added N days ago" badge so users see the dataset-
        # window limit and don't take low-confidence insights on brand-
        # new entities at face value. Absent field → no badge.
        if isinstance(eid, str) and entity_registry_snapshot is not None:
            try:
                from ..lib.entity_age import (
                    days_since_added,
                    is_newly_added,
                )

                registry_entry = entity_registry_snapshot.async_get(eid)
                created_at = (
                    getattr(registry_entry, "created_at", None)
                    if registry_entry is not None
                    else None
                )
                if is_newly_added(created_at):
                    age = days_since_added(created_at)
                    if age is not None:
                        d["entity_age_days"] = age
            except Exception:
                # Best-effort enrichment — never fail ws_list if the
                # registry lookup or import raises.
                pass
        # v1.2 Phase 5: surface the three new filter axes — area, floor,
        # integration. IDs power filter equality; names power the chip
        # labels + group_by section headers. All five may be None when
        # the insight isn't pinned to a single entity (cohorts) or the
        # entity isn't in any area/floor.
        d["area_id"] = None
        d["area_name"] = None
        d["floor_id"] = None
        d["floor_name"] = None
        d["integration"] = None
        # v1.5.28: surface labels (HA 2024.4+) per insight so the panel
        # can filter / group by them. Labels are HA-native tags users
        # apply to entities/devices/areas; this lets installs that use
        # `label: outdoor` / `label: critical` / etc. slice insights
        # by their organizational taxonomy without manual filtering.
        d["labels"] = []
        if isinstance(eid, str) and hierarchy is not None:
            aid = hierarchy.area_of.get(eid)
            d["area_id"] = aid
            if aid:
                d["area_name"] = hierarchy.area_name_by_id.get(aid) or aid
            fid = hierarchy.floor_of.get(eid)
            d["floor_id"] = fid
            if fid:
                d["floor_name"] = hierarchy.floor_name_by_id.get(fid) or fid
            d["integration"] = hierarchy.integration_of.get(eid)
            labels = hierarchy.labels_of.get(eid)
            if labels:
                # Sorted for stable group_by ordering across scans.
                d["labels"] = sorted(labels)
        # v1.7.7: enrich with referenced devices + their managed-externally
        # state so the detail dialog can show per-device suppress toggles
        # without the card having to walk payload + device registry itself.
        # Deduplicated by device_id; entities with no device_id are
        # excluded (template sensors, helpers — can't be device-suppressed).
        referenced_device_ids: set[str] = set()
        for ref_entity in _entities_in_insight(ins):
            did = device_of_by_entity.get(ref_entity)
            if did:
                referenced_device_ids.add(did)
        d["referenced_devices"] = [
            {
                "device_id": did,
                "name": device_name_by_id.get(did, did[:8]),
                "managed": did in managed_devices_set,
            }
            for did in sorted(referenced_device_ids)
        ]
        # External-schedule hint. We only surface it when the entity is
        # NOT already tied to an HA automation — otherwise it's the
        # user's own automation doing the work and the pill is wrong.
        # v1.2: delegate the platform → vendor-label mapping to
        # hierarchy.is_externally_managed so the list stays canonical.
        #
        # COHORT SAFETY: the pill is per-insight-row, but a cohort row
        # represents multiple entities. If the rep is Tuya but a cohort
        # member is from `ble_monitor` (different integration), the pill
        # would falsely tag the BLE entity too. So we collect the
        # vendor labels for every member and only surface the pill when
        # they all agree. Mixed cohorts → no pill (the 🔌 integration
        # tag still appears for the rep, that's all we can safely say).
        d["external_source"] = None
        if isinstance(eid, str):
            cohort_member_ids: list[str] = []
            cohort_fp = ins.fingerprint.get("_member_entities")
            if isinstance(cohort_fp, (list, tuple)):
                cohort_member_ids = [
                    m for m in cohort_fp if isinstance(m, str) and "." in m
                ]
            entities_to_check = cohort_member_ids or [eid]
            # Suppress the pill if ANY entity in the cohort already has
            # an HA automation — same logic as before, applied across
            # all members.
            any_automated = bool(ins.conflicts_with) or any(
                entity_to_automations.get(e) for e in entities_to_check
            )
            if not any_automated and hierarchy is not None:
                vendors = {
                    hierarchy.is_externally_managed(e)
                    for e in entities_to_check
                }
                if len(vendors) == 1:
                    vendor = next(iter(vendors))
                    if vendor:
                        d["external_source"] = vendor
            elif not any_automated:
                # Legacy hierarchy-less path. Same single-vendor rule.
                vendors_legacy: set[str | None] = set()
                for e in entities_to_check:
                    platform = platform_by_entity.get(e)
                    if (
                        platform is not None
                        and platform in _EXTERNAL_SCHEDULE_PLATFORMS
                    ):
                        vendors_legacy.add(
                            _EXTERNAL_PLATFORM_LABEL.get(platform, platform)
                        )
                    else:
                        vendors_legacy.add(None)
                if len(vendors_legacy) == 1:
                    vendor_legacy = next(iter(vendors_legacy))
                    if vendor_legacy:
                        d["external_source"] = vendor_legacy
        # Which existing automations reference any of this insight's
        # entities? De-dup'd list of aliases. Empty when none.
        referenced_in: list[str] = []
        seen: set[str] = set()
        for ent in _entities_in_insight(ins):
            for label in entity_to_automations.get(ent, []):
                if label not in seen:
                    seen.add(label)
                    referenced_in.append(label)
        d["referenced_in_automations"] = referenced_in
        # Surface cohort members so the card can show an expand toggle
        # ("(+N similar entities)" → click to see the list).
        cohort = ins.fingerprint.get("_member_entities")
        d["cohort_members"] = (
            list(cohort)
            if isinstance(cohort, (list, tuple))
            else []
        )
        d["cohort_label"] = ins.fingerprint.get("_grouped_under")
        # v1.5.13: per-member metadata so the expanded cohort dropdown
        # can render a 🔌 integration + 🏷️ external-app badge next to
        # each entity_id. The row-level external_source pill (set above)
        # is suppressed for MIXED-vendor cohorts — but the user expects
        # to see the badge next to the entity that actually IS Tuya
        # even when a sibling isn't. Per-entity check: if HA already
        # has an automation referencing this entity, don't tag it as
        # externally managed (the user is driving it from HA).
        cohort_member_info: list[dict[str, Any]] = []
        if isinstance(cohort, (list, tuple)) and hierarchy is not None:
            for member_eid in cohort:
                if not isinstance(member_eid, str):
                    continue
                m_integration = hierarchy.integration_of.get(member_eid)
                m_external = (
                    None
                    if entity_to_automations.get(member_eid)
                    else hierarchy.is_externally_managed(member_eid)
                )
                cohort_member_info.append(
                    {
                        "entity_id": member_eid,
                        "integration": m_integration,
                        "external_source": m_external,
                    }
                )
        d["cohort_member_info"] = cohort_member_info
        # Carry the entity_id list of the entities involved (for dedup
        # at the end of this function — strips per-entity bits from
        # the title to group rows that should display together even
        # if the store has them as separate rows from an older
        # fingerprint schema).
        eids_for_dedup: list[str] = []
        for key in (
            "entity_id",
            "follower_entity_id",
            "leader_entity_id",
            "target_entity_id",
        ):
            v = ins.fingerprint.get(key)
            if isinstance(v, str) and "." in v:
                eids_for_dedup.append(v)
        d["_eids_for_dedup"] = eids_for_dedup
        # Structured automation links — both for `conflicts_with` (the
        # 🔁 strict-duplicate match) AND `referenced_in_automations`
        # (the 🤖 entity-context match). Card renders each as a
        # clickable chip → /config/automation/edit/{id} when id is
        # known, plain text otherwise. This addresses the user ask
        # "let me edit the existing automation instead of starting over."
        d["conflicts_with_links"] = _build_automation_links(ins.conflicts_with)
        d["referenced_in_automations_links"] = _build_automation_links(
            referenced_in
        )
        # v1.5.31: strip the "Automate this?" / "Automate it?" / "Build
        # automation?" trailing CTA when the conflict scanner has already
        # matched this pattern to an existing automation. The 🔁 pill
        # tells the user the answer is "you already did" — keeping the
        # question in the title reads as a contradictory CTA. Moved
        # server-side after a card-side fix in v1.2.11 proved unreliable
        # under HA's service-worker caching of Lit-compiled templates.
        # Notifications + mobile push + daily digest now benefit too.
        # `_strip_already_automated_cta` is pure-string; if the title
        # doesn't end in a known CTA we return it unchanged.
        if ins.conflicts_with:
            d["title"] = _strip_already_automated_cta(d.get("title", ""))
        enriched.append(d)

    # Display-time dedup: merge insights that share a normalized title
    # signature AND a discoverable container (shared device_id, common
    # state-machine parent, or heuristic same-domain cohort). Catches
    # insights stored before the scan-time dedup landed AND lets the
    # user see the merged view immediately, without waiting for a
    # rescan. Pure read-side transform — the store stays unchanged.
    enriched = _display_time_dedup(enriched, hass)

    connection.send_result(msg["id"], {"insights": enriched})


# ---------------------------------------------------------------------------
# Display-time dedup (v1.1 — runs in ws_list after enrichment)
#
# Pure-logic core lives in lib/dedup.py so it's testable without HA.
# This wrapper walks the entity registry to build the device_id map.
# ---------------------------------------------------------------------------


# v1.5.42: strip is canonical at detector-emission time (see
# detectors/__init__.py — applied after find_conflicts before
# store.add_insight). The call inside `ws_list` above stays as
# defense in depth for stored insights that pre-date v1.5.42.
# Helper imported from `lib.title_cleanup`.


def _normalize_title_for_dedup(title: str, eids: list[str]) -> str:
    """Backwards-compat shim — kept for any inline callers. New code
    should use lib.dedup.normalize_title_for_dedup directly."""
    from ..lib.dedup import normalize_title_for_dedup as _impl

    return _impl(title, eids)


def _display_time_dedup(
    enriched: list[dict[str, Any]], hass: HomeAssistant
) -> list[dict[str, Any]]:
    """Thin wrapper: walk HA's entity_registry once, hand off to the
    pure dedup helper in lib/dedup.py. All real logic lives there
    so it can be unit-tested without the HA stack.
    """
    from ..lib.dedup import display_time_dedup

    # Build device_id lookup for cross-entity device-shared dedup.
    device_id_by_entity: dict[str, str | None] = {}
    try:
        from homeassistant.helpers import entity_registry as er

        registry = er.async_get(hass)
        for ent in registry.entities.values():
            device_id_by_entity[ent.entity_id] = ent.device_id
    except Exception:
        pass

    return display_time_dedup(enriched, device_id_by_entity)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/explain",
        vol.Required("insight_id"): str,
        vol.Optional("agent_id"): vol.Any(str, None),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_explain(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """User-initiated LLM explanation. Redactor + agent + dereference + audit."""
    from ..config_flow import get_blocked_entities
    from ..llm import RedactionMode, Redactor, explain_insight

    store = _get_store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_set_up", "Store not initialized")
        return

    insight = await store.get_insight(msg["insight_id"])
    if insight is None:
        connection.send_error(
            msg["id"], "not_found", f"No insight {msg['insight_id']!r}"
        )
        return

    agent_id = msg.get("agent_id")
    blocked = _resolve_blocked_entities(hass, get_blocked_entities)
    preferred = _resolve_preferred_agent_id(hass)
    redactor = Redactor(
        store, mode=RedactionMode.AGGRESSIVE, blocked_entities=blocked
    )
    result = await explain_insight(
        hass,
        agent_id=agent_id,
        insight=insight,
        redactor=redactor,
        preferred_agent_id=preferred,
    )

    # Audit every attempt — failover may have made multiple round-trips
    # before landing on a working agent. Each round-trip is bytes that
    # left the network and MUST appear in the privacy log.
    await _audit_attempts(
        store, result.attempts, insight_id=insight.id, redactor=redactor
    )

    if not result.success:
        connection.send_error(
            msg["id"],
            "explain_failed",
            result.error or "Conversation agent returned no speech",
        )
        return

    # Persist the explanation onto the insight + notify subscribers
    await store._c.execute(
        "UPDATE insights SET explanation = ? WHERE id = ?",
        (result.explanation, insight.id),
    )
    await store._c.commit()
    refreshed = await store.get_insight(insight.id)
    store._notify("explained", refreshed)

    connection.send_result(
        msg["id"],
        {
            "explanation": result.explanation,
            "bytes_sent": result.bytes_sent,
            "bytes_received": result.bytes_received,
        },
    )




@websocket_api.websocket_command(
    {vol.Required("type"): "home_insights/purge_all"}
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_purge_all(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Privacy nuke: clear in-memory buffer + insights table + outbound-call log.

    Pseudonym map and applied-history snapshots are preserved by design.
    """
    store = _get_store(hass)
    buffer_ = _get_buffer(hass)
    if store is None or buffer_ is None:
        connection.send_error(msg["id"], "not_set_up", "Store/buffer not initialized")
        return
    events_dropped = buffer_.clear()
    counts = await store.purge_observations()
    # Sweep our Repairs entries too — a purge means the underlying
    # insights are gone, so the Repairs surface shouldn't keep
    # showing stale findings.
    try:
        from ..audit.repairs import clear_all_audit_issues

        cleared_repairs = clear_all_audit_issues(hass)
    except Exception:
        cleared_repairs = 0
    connection.send_result(
        msg["id"],
        {
            "events_dropped": events_dropped,
            "repairs_cleared": cleared_repairs,
            **counts,
        },
    )


@websocket_api.websocket_command(
    {vol.Required("type"): "home_insights/subscribe"}
)
@callback
def ws_subscribe(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Subscribe to insight change events (added / dismissed / snoozed)."""
    store = _get_store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_set_up", "Store not initialized")
        return

    sub_id = msg["id"]

    @callback
    def on_event(event_type: str, insight: Insight | None) -> None:
        connection.send_event(
            sub_id,
            {
                "action": event_type,
                "insight": insight.to_dict() if insight else None,
            },
        )

    unsub = store.add_listener(on_event)
    connection.subscriptions[sub_id] = unsub
    connection.send_result(sub_id)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/dismiss",
        vol.Required("insight_id"): str,
    }
)
@websocket_api.async_response
async def ws_dismiss(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Permanently dismiss an insight."""
    store = _get_store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_set_up", "Store not initialized")
        return
    success = await store.dismiss_insight(msg["insight_id"])
    if not success:
        connection.send_error(
            msg["id"], "not_found", f"No insight {msg['insight_id']!r}"
        )
        return
    await _record_verdict_safely(hass, connection, msg["insight_id"], "dismissed")
    # Mirror the dismiss into HA's Repairs registry if this insight
    # had a Repairs entry. Idempotent — no-op when no entry exists.
    try:
        from ..audit.repairs import clear_issue_for_insight

        clear_issue_for_insight(hass, msg["insight_id"])
    except Exception:
        pass
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/apply",
        vol.Required("insight_id"): str,
        vol.Optional("payload_override"): dict,
        # v1.5.44: Suggested-Additions deterministic path. Card POSTs a
        # list of entity_ids the user picked from the checkbox modal;
        # server runs append_entities_to_action_block on the payload
        # before validation, so the apply pipeline is unchanged (still
        # goes through L1 + L2 validators + AutomationWriter + Undo
        # snapshot). When unset, behavior is identical to v1.5.43.
        vol.Optional("additional_entity_ids"): [str],
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_apply(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Apply an insight: validate, write the automation, record snapshot.

    `payload_override` (added v0.3) lets the card apply a refined automation
    in place of the original. The override is validated identically and
    stamped with `description: "Refined by HA Insights"` so the lineage is
    visible in HA's automation editor.

    `additional_entity_ids` (added v1.5.44) is the deterministic path for
    Suggested-Additions. When supplied, server appends those entity_ids
    to the matching action item(s) via lib.automation_yaml before the
    existing validation pipeline runs. Same L1/L2 validators, same
    writer, same undo. Cross-domain additions in unknown service
    families come back as `unhandled_entity_ids` in the response so
    the card can route them to LLM Refine instead.

    Validation runs in two layers:
      L1 — offline schema check (required keys, types, mode enum)
      L2 — HA's own automation config validator (services exist,
           entities resolvable, trigger/condition/action shapes valid)
    Both must pass before we write. L2 catches "service light.turn_oN
    doesn't exist" (typo'd refinement) before it lands in
    automations.yaml as a broken automation.
    """
    from ..apply import (
        AutomationWriter,
        hash_config,
        validate_automation,
        validate_automation_online,
    )
    from ..lib.automation_yaml import append_entities_to_action_block

    store = _get_store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_set_up", "Store not initialized")
        return
    insight = await store.get_insight(msg["insight_id"])
    if insight is None:
        connection.send_error(
            msg["id"], "not_found", f"No insight {msg['insight_id']!r}"
        )
        return
    if insight.payload_format != "automation":
        connection.send_error(
            msg["id"],
            "unsupported_format",
            f"payload_format {insight.payload_format!r} not yet supported",
        )
        return

    override = msg.get("payload_override")
    if override is not None:
        # Stamp description so the user sees the lineage in HA's automation editor.
        # Don't mutate caller's dict.
        payload = {**override}
        payload.setdefault("description", "Refined by HA Insights")
    else:
        payload = insight.payload

    # v1.5.44: deterministic Suggested-Additions path. When the card
    # sent a list of additional entity_ids, run the YAML transform
    # BEFORE validation so the L1/L2 validators see the post-append
    # automation. Cross-domain candidates that don't fit the turn_on
    # pattern come back as unhandled — we surface that count in the
    # response so the card can offer to escalate them to LLM Refine.
    unhandled_additions: list[str] = []
    additional = msg.get("additional_entity_ids")
    if isinstance(additional, list) and additional:
        payload, unhandled_additions = append_entities_to_action_block(
            payload, [str(eid) for eid in additional]
        )
        # Mark lineage even on the deterministic path, so the user can
        # tell in HA's automation editor that we touched it.
        payload.setdefault("description", "Extended by HA Insights")

    # v1.0 review #10: serialize the validate -> write -> record_applied
    # pipeline so two near-simultaneous applies on overlapping entities
    # can't race in automations.yaml. Per-store lock is acquired by
    # bulk-apply too (the card iterates apply calls).
    async with store.apply_lock:
        errors = validate_automation(payload)
        if errors:
            connection.send_error(
                msg["id"], "invalid_payload", "; ".join(errors)
            )
            return

        online_errors = await validate_automation_online(hass, payload)
        if online_errors:
            connection.send_error(
                msg["id"],
                "ha_validation_failed",
                "; ".join(online_errors),
            )
            return

        writer = AutomationWriter(hass)
        auto_id = await writer.write(payload)
        snapshot = await writer.read(auto_id) or payload

        await store.record_applied(
            insight.id,
            artifact_kind="automation",
            artifact_id=auto_id,
            snapshot=snapshot,
            snapshot_hash=hash_config(snapshot),
        )
        await _record_verdict_safely(hass, connection, insight.id, "applied")

    # v1.5.46: Logbook entry so the apply shows up in HA's standard
    # activity timeline alongside the automation_reloaded / config-
    # updated events the writer already fires. Entity is the resulting
    # automation so the entry attaches to that automation's row in
    # the Logbook (clickable on phones / dashboards). Best-effort —
    # logbook may not be loaded on minimal HA installs; never fail
    # an apply because the activity log couldn't write.
    try:
        from homeassistant.components import logbook

        action = (
            "Extended"
            if msg.get("additional_entity_ids")
            else "Applied (refined)"
            if override is not None
            else "Applied"
        )
        logbook.async_log_entry(
            hass,
            name="HA Insights",
            message=f"{action} insight: {insight.title}",
            domain=DOMAIN,
            entity_id=f"automation.{auto_id}",
        )
    except Exception:
        pass

    connection.send_result(
        msg["id"],
        {
            "automation_id": auto_id,
            "refined": override is not None,
            # v1.5.44: surface unhandled additions so the card can offer
            # "X candidates need LLM Refine to add" follow-up flow.
            "unhandled_entity_ids": unhandled_additions,
        },
    )


# ---------------------------------------------------------------------------
# v1.5.44 — Suggested-Additions deterministic surface
# ---------------------------------------------------------------------------


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/suggest_additions",
        vol.Required("insight_id"): str,
    }
)
@websocket_api.async_response
async def ws_suggest_additions(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Build deterministic candidate-entity additions for an automation insight.

    Pure-local feature — no LLM required. The card opens a checkbox modal
    populated from this endpoint's response; user picks candidates; apply
    flows through `home_insights/apply` with the chosen entity_ids in
    `additional_entity_ids`.

    Strategy (per lib.candidate_entities):
      - Required entity_ids extracted from the insight's payload action block
      - Area-mates from `Hierarchy.entities_in_area`
      - Device-mates from `Hierarchy.entities_on_device`
      - Domain-siblings filtered by required-entity domains
      - Coactivators left empty in v1.5.44 (planned for v1.5.45 — needs
        EventBuffer ±5 s window query per required entity)
      - Action-target filter on (default-on, only actionable domains
        surface — sensors etc. silently dropped)
      - Per-entity opt-out (blocked_entities) honored
      - Tier classification (HIGH / MEDIUM / LOW) per CandidateEntity
        drives default-select state in the card UI

    Returns a flat list of candidate dicts with `entity_id`, `tier`,
    `reasons`, `category` fields so the card doesn't need to know the
    library's grouping structure.
    """
    from ..config_flow import get_blocked_entities
    from ..detectors.hierarchy import build_hierarchy
    from ..lib.coactivation import compute_coactivation_days
    from ..llm.candidate_entities import build_candidate_entities
    from ..llm.refiner import _collect_entity_ids

    store = _get_store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_set_up", "Store not initialized")
        return
    insight = await store.get_insight(msg["insight_id"])
    if insight is None:
        connection.send_error(
            msg["id"], "not_found", f"No insight {msg['insight_id']!r}"
        )
        return
    if insight.payload_format != "automation":
        connection.send_error(
            msg["id"],
            "unsupported_format",
            f"suggest_additions only supports payload_format='automation' "
            f"(got {insight.payload_format!r})",
        )
        return

    # Extract required entity_ids from the insight's automation YAML —
    # these are the entities the LLM/user MUST preserve, never appear as
    # candidates. Reuse the refiner's collector so we apply the same
    # field-recognition logic everywhere.
    required: set[str] = set()
    _collect_entity_ids(insight.payload, required)

    hierarchy = build_hierarchy(hass)
    blocked = _resolve_blocked_entities(hass, get_blocked_entities)

    # Full registry list is used for domain-sibling matching. Reuse
    # Hierarchy.area_of keys — that's every entity_id in the registry
    # (Hierarchy walked the entity registry to build it).
    all_eids = set(hierarchy.area_of.keys())

    # v1.5.45: coactivation signal — for each required entity, find
    # which OTHER entities the user manually toggles within ±5 s on
    # the same calendar day, in the 14-day buffer. Days-count goes
    # into `coactivation_days` so build_candidate_entities can promote
    # >=3-day matches into the HIGH-tier coactivator bucket.
    #
    # Falls back to None when no buffer is available (early-startup
    # window, or this entry didn't initialize one) — candidate_entities
    # simply skips the coactivator pass in that case.
    coactivation_days: dict[str, int] | None = None
    buffer = _get_buffer(hass)
    if buffer is not None:
        try:
            coactivation_days = compute_coactivation_days(
                buffer.snapshot(),
                anchor_entity_ids=required,
            )
        except Exception:  # pragma: no cover — signal is best-effort
            # A coactivation-counter failure must not block the
            # response. Other three signals (area / device / domain)
            # still produce useful candidates without it.
            coactivation_days = None

    candidates = build_candidate_entities(
        required_entity_ids=required,
        area_of=hierarchy.area_of,
        device_of=hierarchy.device_of,
        entities_in_area=hierarchy.entities_in_area,
        entities_on_device=hierarchy.entities_on_device,
        all_entity_ids=all_eids,
        coactivation_days=coactivation_days,
        blocked_entity_ids=blocked,
        action_target_only=True,
    )

    # Flatten the per-category groups into one list with a category tag.
    # The card sorts/groups its own way (typically by tier, with category
    # in the row chrome).
    flat: list[dict[str, Any]] = []
    for category, group in (
        ("coactivator", candidates.coactivators),
        ("device_mate", candidates.device_mates),
        ("area_mate", candidates.area_mates),
        ("domain_sibling", candidates.domain_siblings),
    ):
        for c in group:
            flat.append({
                "entity_id": c.entity_id,
                "tier": c.tier,
                "reasons": list(c.reasons),
                "category": category,
            })

    connection.send_result(
        msg["id"],
        {
            "insight_id": insight.id,
            "candidates": flat,
            "required_entity_ids": sorted(required),
            "total_count": candidates.total_count,
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/test_actions",
        vol.Required("insight_id"): str,
        vol.Optional("payload_override"): dict,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_test_actions(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Fire the action block of an insight without saving the automation.

    Mirrors HA's "Run Actions" button on the automation editor. Iterates
    `payload['action']` (or the override) and calls each as a real service
    call. Triggers and conditions are skipped. Returns a per-action summary
    so the card can toast successes or surface specific errors.

    This is a privileged operation — it has real side effects on the user's
    home. The card surfaces a one-line warning before the first test.
    """
    store = _get_store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_set_up", "Store not initialized")
        return
    insight = await store.get_insight(msg["insight_id"])
    if insight is None:
        connection.send_error(
            msg["id"], "not_found", f"No insight {msg['insight_id']!r}"
        )
        return

    payload = msg.get("payload_override") or insight.payload
    actions = payload.get("action")
    if not isinstance(actions, list) or not actions:
        connection.send_error(
            msg["id"], "no_actions", "Payload has no action list to test"
        )
        return

    results: list[dict[str, Any]] = []
    for index, action in enumerate(actions):
        if not isinstance(action, dict) or "service" not in action:
            results.append({
                "index": index,
                "ok": False,
                "error": "non-service actions (delay/choose/etc) skipped",
                "skipped": True,
            })
            continue

        service_str = action.get("service")
        if not isinstance(service_str, str) or "." not in service_str:
            results.append({
                "index": index,
                "ok": False,
                "error": f"invalid service: {service_str!r}",
            })
            continue

        domain, service = service_str.split(".", 1)
        target = action.get("target")
        # service_data assembly. HA's automation YAML supports two shapes:
        #   1. Flat:    {service: foo.bar, key1: v1, key2: v2}
        #   2. Wrapped: {service: foo.bar, data: {key1: v1, key2: v2}}
        # Both must produce a flat service_data for hass.services.async_call.
        reserved = {"service", "target", "alias", "metadata", "data"}
        service_data: dict[str, Any] = {}
        wrapped = action.get("data")
        if isinstance(wrapped, dict):
            service_data.update(wrapped)
        for k, v in action.items():
            if k in reserved:
                continue
            service_data[k] = v
        # Some legacy actions put entity_id directly at the action level.
        # Move it into target if no target was set.
        if target is None and "entity_id" in service_data:
            target = {"entity_id": service_data.pop("entity_id")}

        try:
            await hass.services.async_call(
                domain,
                service,
                service_data or None,
                target=target,
                blocking=True,
            )
            results.append({"index": index, "ok": True, "service": service_str})
        except Exception as err:
            results.append({
                "index": index,
                "ok": False,
                "service": service_str,
                "error": str(err),
            })

    ran = sum(1 for r in results if r.get("ok"))
    errors = [r for r in results if not r.get("ok") and not r.get("skipped")]
    connection.send_result(
        msg["id"],
        {"ran": ran, "results": results, "error_count": len(errors)},
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/undo",
        vol.Required("insight_id"): str,
        vol.Optional("force", default=False): bool,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_undo(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Reverse a previous apply: delete the automation, clear applied history.

    Drift protection: if the user has edited the automation in HA's UI
    since we wrote it, we refuse the undo unless `force=true` so the
    user's manual edits aren't silently lost. The drift error returns
    `code: "drift"` plus a side-by-side hint so the card can prompt
    "you've edited this — undo anyway?".
    """
    from ..apply import AutomationWriter, detect_drift

    store = _get_store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_set_up", "Store not initialized")
        return

    insight_id = msg["insight_id"]
    # v1.0 review #10: serialize against ws_apply / bulk-apply through
    # the same per-store lock. Without it, an undo racing with a fresh
    # apply on the same artifact could leave automations.yaml in a
    # half-written state.
    async with store.apply_lock:
        history = await store.get_applied_history(insight_id)
        if history is None:
            connection.send_error(
                msg["id"],
                "not_applied",
                f"Insight {insight_id!r} has no applied history",
            )
            return

        artifact_id = str(history["artifact_id"])
        snapshot = history["snapshot"]
        if not isinstance(snapshot, dict):
            connection.send_error(
                msg["id"], "corrupt_snapshot", "Stored snapshot is malformed"
            )
            return

        writer = AutomationWriter(hass)
        current = await writer.read(artifact_id)
        drift_detected = current is not None and detect_drift(snapshot, current)
        if drift_detected and not msg.get("force"):
            connection.send_error(
                msg["id"],
                "drift",
                (
                    "Automation has been edited since it was applied. Pass "
                    "force=true to undo anyway and lose those edits."
                ),
            )
            return

        deleted = (
            await writer.delete(artifact_id) if current is not None else True
        )
        if not deleted:
            connection.send_error(
                msg["id"],
                "delete_failed",
                f"Could not remove automation {artifact_id!r}",
            )
            return

        cleared = await store.clear_applied(insight_id)
    await _record_verdict_safely(hass, connection, insight_id, "undone")
    connection.send_result(
        msg["id"],
        {
            "automation_id": artifact_id,
            "drift_detected": drift_detected,
            "force_used": bool(msg.get("force")),
            "applied_cleared": cleared,
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/snooze",
        vol.Required("insight_id"): str,
        vol.Required("until"): str,
    }
)
@websocket_api.async_response
async def ws_snooze(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Snooze an insight until the given ISO timestamp."""
    store = _get_store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_set_up", "Store not initialized")
        return
    try:
        until = datetime.fromisoformat(msg["until"])
    except ValueError:
        connection.send_error(
            msg["id"], "invalid_time", "until must be ISO 8601 format"
        )
        return
    success = await store.snooze_insight(msg["insight_id"], until=until)
    if not success:
        connection.send_error(
            msg["id"], "not_found", f"No insight {msg['insight_id']!r}"
        )
        return
    await _record_verdict_safely(hass, connection, msg["insight_id"], "snoozed")
    connection.send_result(msg["id"])


# ---------------------------------------------------------------------------
# v1.5.46 — Retire / unretire lifecycle. Sibling to dismiss + snooze.
# Retire = user has consciously decided NOT to automate this pattern;
# survives re-detections of the same fingerprint until explicitly cleared.
# Filtered from ws_list by default; surfaced via include_retired=True.
# ---------------------------------------------------------------------------


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/retire",
        vol.Required("insight_id"): str,
    }
)
@websocket_api.async_response
async def ws_retire(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Retire an insight — permanent 'don't auto-suggest' decision."""
    store = _get_store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_set_up", "Store not initialized")
        return
    success = await store.retire_insight(msg["insight_id"])
    if not success:
        connection.send_error(
            msg["id"], "not_found", f"No insight {msg['insight_id']!r}"
        )
        return
    await _record_verdict_safely(hass, connection, msg["insight_id"], "retired")
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/unretire",
        vol.Required("insight_id"): str,
    }
)
@websocket_api.async_response
async def ws_unretire(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Un-retire an insight — reverse a prior retire decision."""
    store = _get_store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_set_up", "Store not initialized")
        return
    success = await store.clear_retired(msg["insight_id"])
    if not success:
        connection.send_error(
            msg["id"],
            "not_found",
            f"No insight {msg['insight_id']!r} or it wasn't retired",
        )
        return
    await _record_verdict_safely(hass, connection, msg["insight_id"], "unretired")
    connection.send_result(msg["id"])


# ---------------------------------------------------------------------------
# v1.23.0 — Bulk dismiss / retire. Discussion #104 (dziban303,
# 2026-05-22): user had 105 Uptime Kuma noise items to clear one click
# at a time. Mirror of the existing per-id WS handlers; takes a list
# of insight_ids and applies the same operation across them, returning
# a summary so the card can surface "97 dismissed, 8 not found".
#
# Single-shot WS message rather than a stream — the bulk size is
# bounded by the panel's render cap (200 by default, 1000 with paginate
# load-more). Always-admin-gated to mirror destructive ops elsewhere.
# ---------------------------------------------------------------------------


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/bulk_dismiss",
        vol.Required("insight_ids"): [str],
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_bulk_dismiss(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Dismiss a batch of insights in one round-trip.

    Returns: {dismissed: int, not_found: list[str]}. Errors are
    swallowed per-id so a single bad id doesn't abort the batch —
    the card can re-emit them via the regular per-id handler if it
    cares. Mirrors single ws_dismiss semantics: each successful
    dismiss writes a 'dismissed' verdict and clears any HA Repairs
    issue that was mirrored from the insight.
    """
    store = _get_store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_set_up", "Store not initialized")
        return
    insight_ids: list[str] = msg["insight_ids"]
    dismissed = 0
    not_found: list[str] = []
    try:
        from ..audit.repairs import clear_issue_for_insight as _clear_repair
    except Exception:  # pragma: no cover — defensive
        _clear_repair = None  # type: ignore[assignment]
    for iid in insight_ids:
        try:
            ok = await store.dismiss_insight(iid)
        except Exception:
            ok = False
        if not ok:
            not_found.append(iid)
            continue
        dismissed += 1
        await _record_verdict_safely(hass, connection, iid, "dismissed")
        if _clear_repair is not None:
            try:
                _clear_repair(hass, iid)
            except Exception:
                pass
    connection.send_result(
        msg["id"],
        {"dismissed": dismissed, "not_found": not_found},
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/bulk_retire",
        vol.Required("insight_ids"): [str],
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_bulk_retire(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Retire a batch of insights in one round-trip.

    Returns: {retired: int, not_found: list[str]}. Same swallow-and-
    continue semantics as ws_bulk_dismiss. Each successful retire
    writes a 'retired' verdict. Retire is the harder of the two —
    it's a permanent "don't auto-suggest" decision per-fingerprint —
    so the card should confirm intent before invoking this for a
    large batch.
    """
    store = _get_store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_set_up", "Store not initialized")
        return
    insight_ids: list[str] = msg["insight_ids"]
    retired = 0
    not_found: list[str] = []
    for iid in insight_ids:
        try:
            ok = await store.retire_insight(iid)
        except Exception:
            ok = False
        if not ok:
            not_found.append(iid)
            continue
        retired += 1
        await _record_verdict_safely(hass, connection, iid, "retired")
    connection.send_result(
        msg["id"],
        {"retired": retired, "not_found": not_found},
    )


@websocket_api.websocket_command(
    {vol.Required("type"): "home_insights/scan_now"}
)
@websocket_api.async_response
async def ws_scan_now(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Run all registered detectors immediately. Returns count of new insights.

    Cancellable via the home_insights/cancel_scan WS endpoint — that
    sets an asyncio.Event stashed in entry_data, which run_all_detectors
    checks between detectors and exits early on. Insights from already-
    completed detectors are kept.
    """
    import asyncio as _asyncio

    from ..config_flow import (
        get_blocked_entities,
        get_enabled_detectors,
        get_scan_areas,
    )
    from ..detectors import DETECTORS, DetectorContext, run_all_detectors

    store = _get_store(hass)
    buffer_ = _get_buffer(hass)
    if store is None or buffer_ is None:
        connection.send_error(msg["id"], "not_set_up", "Store/buffer not initialized")
        return

    # Pre-flight check: if the buffer is empty AND backfill is currently
    # running, scanning would emit 0 insights AND the auto-sweep would
    # delete every existing insight. Reject the scan with an actionable
    # error rather than silently nuking the store.
    backfill_running = any(
        d.get("backfill_running")
        for d in hass.data.get(DOMAIN, {}).values()
        if isinstance(d, dict)
    )
    if backfill_running and len(buffer_) == 0:
        connection.send_error(
            msg["id"],
            "backfill_in_progress",
            "HA Insights is still backfilling history. Wait for the "
            "Backfill toast to complete, then try Scan again. Scanning "
            "an empty buffer would clear all your existing insights.",
        )
        return

    # Resolve which entry to read config from. With multi-entry installs
    # we apply per-entry filters; for single-entry the loop runs once.
    new_count = 0
    swept_stale = 0
    suppressed_as_duplicate = 0
    detectors_actually_run: list[str] = []
    for entry_id, entry_data in hass.data.get(DOMAIN, {}).items():
        if not isinstance(entry_data, dict) or "buffer" not in entry_data:
            continue
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None:
            continue
        # Per-entry cancel event. Stashed in entry_data so the cancel
        # endpoint can find + set it. Cleared when the scan finishes
        # so a stale signal from a previous scan doesn't insta-cancel
        # the next one.
        cancel_event = _asyncio.Event()
        entry_data["scan_cancel_event"] = cancel_event
        ctx = DetectorContext(
            hass=hass,
            event_buffer=entry_data["buffer"],
            blocked_entities=get_blocked_entities(entry),
            area_filter=get_scan_areas(entry),
        )
        try:
            summary = await run_all_detectors(
                hass,
                ctx,
                entry_data["store"],
                entry=entry,
                cancel_event=cancel_event,
                return_summary=True,
                # User clicked the button. The setup-phase guard exists
                # to prevent AUTOMATIC scans during boot (the original
                # 2026-05-10 freeze). User-initiated scans are safe
                # under threading + watchdog + ceiling, so we let them
                # through even while hass.state==STARTING.
                allow_during_setup=True,
            )
        except RuntimeError as err:
            # Defensive: if a future code path forgets allow_during_setup,
            # surface a clean error instead of "Unknown error" via the
            # decorator's generic handler.
            connection.send_error(msg["id"], "scan_failed", str(err))
            return
        finally:
            entry_data.pop("scan_cancel_event", None)
        # summary is a dict when return_summary=True
        if isinstance(summary, dict):
            new_count += summary.get("added", 0)
            swept_stale += summary.get("swept_stale", 0)
            suppressed_as_duplicate += summary.get("suppressed_as_duplicate", 0)
        enabled = get_enabled_detectors(entry)
        names = (
            list(DETECTORS.keys())
            if enabled is None
            else [n for n in DETECTORS if n in enabled]
        )
        for n in names:
            if n not in detectors_actually_run:
                detectors_actually_run.append(n)

    connection.send_result(
        msg["id"],
        {
            "detectors_run": detectors_actually_run,
            "insights_emitted": new_count,
            "swept_stale": swept_stale,
            "suppressed_as_duplicate": suppressed_as_duplicate,
            "canceled": all(
                d.get("scan_canceled", False)
                for d in hass.data.get(DOMAIN, {}).values()
                if isinstance(d, dict)
            ),
        },
    )


@websocket_api.websocket_command(
    {vol.Required("type"): "home_insights/cancel_scan"}
)
@websocket_api.require_admin
@callback
def ws_cancel_scan(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Signal any in-flight scan to stop after the current detector returns.

    Python can't safely cancel a running thread, so the in-flight detector
    runs to completion (its result is still applied). All later detectors
    are skipped. The user gets back to a working UI within seconds rather
    than waiting out the full scan budget.
    """
    canceled_for = []
    for entry_id, entry_data in hass.data.get(DOMAIN, {}).items():
        if not isinstance(entry_data, dict):
            continue
        event = entry_data.get("scan_cancel_event")
        if event is not None:
            event.set()
            canceled_for.append(entry_id)
    connection.send_result(msg["id"], {"canceled_for": canceled_for})


@websocket_api.websocket_command(
    {vol.Required("type"): "home_insights/list_entries"}
)
@callback
def ws_list_entries(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the configured HA Insights entries.

    Multi-entry installs (v1.0 RC #7) run multiple independent insight
    scopes side by side. Cards default to the first entry — call this
    endpoint to discover them all and let the user pick. Single-entry
    installs return one row.
    """
    entries: list[dict[str, str]] = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        entries.append({"entry_id": entry.entry_id, "title": entry.title})
    connection.send_result(msg["id"], {"entries": entries})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/redaction_preview",
        vol.Required("insight_id"): str,
    }
)
@websocket_api.async_response
async def ws_redaction_preview(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Show the user exactly what would be sent to the LLM, no call made.

    Same redaction pipeline as `explain` and `refine` but stops before
    the conversation API. Returns:
      - redacted_payload: the dict that would be embedded in the prompt
      - entities_blocked: entity_ids stripped via per-entity opt-out
      - pseudonym_map: real-id -> pseudonym pairs (transparency)
      - attributes_stripped: attribute names dropped (gps, mac, secrets)
      - privacy_mode: which mode this preview reflects
    """
    from ..config_flow import get_blocked_entities
    from ..llm import RedactionMode, Redactor

    store = _get_store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_set_up", "Store not initialized")
        return
    insight = await store.get_insight(msg["insight_id"])
    if insight is None:
        connection.send_error(
            msg["id"], "not_found", f"No insight {msg['insight_id']!r}"
        )
        return

    blocked = _resolve_blocked_entities(hass, get_blocked_entities)
    redactor = Redactor(
        store, mode=RedactionMode.AGGRESSIVE, blocked_entities=blocked
    )
    redacted_payload, redaction_map = await redactor.redact_insight_payload(
        insight.payload
    )
    redacted_title, _ = await redactor.redact_text(insight.title)

    connection.send_result(
        msg["id"],
        {
            "redacted_title": redacted_title,
            "redacted_payload": redacted_payload,
            "entities_blocked": list(redaction_map.entities_blocked),
            "pseudonym_map": dict(redaction_map.entity_to_pseudonym),
            "attributes_stripped": list(redaction_map.attributes_stripped),
            "privacy_mode": str(redactor.mode),
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/audit_log",
        vol.Optional("limit", default=50): vol.All(int, vol.Range(min=1, max=500)),
    }
)
@websocket_api.async_response
async def ws_audit_log(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return recent outbound LLM calls for the audit log viewer."""
    store = _get_store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_set_up", "Store not initialized")
        return
    rows = await store.get_outbound_calls(limit=msg["limit"])
    connection.send_result(msg["id"], {"calls": rows})


@websocket_api.websocket_command(
    {vol.Required("type"): "home_insights/recorder_status"}
)
@websocket_api.async_response
async def ws_recorder_status(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return how far back HA's recorder retains state history.

    Surfaces three numbers so the card can show the user what's
    actually possible vs. what's configured:

      purge_keep_days       — what HA is configured to keep
                              (recorder.purge_keep_days, default 10)
      oldest_record_age_days — what's ACTUALLY in the DB right now
                              (may be less if purge ran recently, or
                              more if the user just lowered the keep
                              setting and purge hasn't caught up)
      available_window_days — min(the two above) — the safe number
                              to display + use for rollup window

    The user can then set audit_rollup_window_days up to this value
    in OptionsFlow. Going beyond it just queries empty windows.
    """
    purge_keep_days: int | None = None
    oldest_age_days: int | None = None
    configured_audit_window_days: int | None = None
    try:
        from ..config_flow import get_audit_rollup_window_days
        from ..const import DOMAIN

        # Single-entry default, but if multi-entry the max wins (the
        # rollup runs once against the largest window any entry wants).
        entries = list(hass.config_entries.async_entries(DOMAIN))
        if entries:
            configured_audit_window_days = max(
                get_audit_rollup_window_days(e) for e in entries
            )
    except Exception:
        pass

    try:
        from homeassistant.components.recorder import get_instance

        rec = get_instance(hass)
        # `keep_days` is the documented public attr; older HA
        # versions used `_keep_days`. Public form first.
        purge_keep_days = getattr(rec, "keep_days", None) or getattr(
            rec, "_keep_days", None
        )

        # Probe oldest data depth using ONLY public history API
        # (`get_significant_states`). HA-core review safe — no
        # `db_schema` / SQLAlchemy `select()` / private session
        # access. Walks a small set of candidate depths and finds
        # the deepest one that still returns data.
        def _probe_oldest_age_days() -> int | None:
            try:
                from homeassistant.components.recorder.history import (
                    get_significant_states,
                )
            except ImportError:
                return None
            from datetime import UTC as _UTC
            from datetime import datetime as _dt
            from datetime import timedelta as _td

            # Candidate depths in days. Walks from CLOSE to FAR
            # so we accumulate the deepest "yes" answer. Stops as
            # soon as a probe returns empty — that's our retention
            # ceiling. Each probe is a 1-hour slice with no entity
            # filter, so it's cheap (recorder reads one tiny page).
            probes_days = (
                1, 3, 7, 14, 30, 60, 90,
                120, 150, 180, 210, 270, 365,
            )
            now_dt = _dt.now(tz=_UTC)
            deepest_with_data: int | None = None
            for days in probes_days:
                start = now_dt - _td(days=days)
                end = start + _td(hours=1)
                try:
                    result = get_significant_states(
                        hass,
                        start,
                        end,
                        None,  # all entities — tiny probe slice
                        significant_changes_only=True,
                        minimal_response=True,
                        no_attributes=True,
                    )
                except Exception as err:
                    _LOGGER.debug(
                        "recorder_status: probe at %dd failed: %s",
                        days,
                        err,
                    )
                    break
                if result:
                    deepest_with_data = days
                    continue
                # Empty result → we're past retention. Stop.
                break
            return deepest_with_data

        # Route through the recorder's own executor so we serialize
        # against in-flight writes instead of fighting the default
        # pool.
        oldest_age_days = await rec.async_add_executor_job(
            _probe_oldest_age_days
        )
    except Exception as err:
        _LOGGER.debug("recorder_status: probe failed: %s", err)

    # Safe window is the smaller of the two when both known.
    available_window_days: int | None = None
    if purge_keep_days is not None and oldest_age_days is not None:
        available_window_days = min(int(purge_keep_days), oldest_age_days)
    elif purge_keep_days is not None:
        available_window_days = int(purge_keep_days)
    elif oldest_age_days is not None:
        available_window_days = oldest_age_days

    # Effective window = what the rollup will ACTUALLY cover. Even when
    # the user sets `audit_rollup_window_days = 180`, the recorder can
    # only return what it retains. Surface this explicitly so the card
    # can show "180 configured, 10 effective" instead of just one of
    # the numbers.
    effective_window_days: int | None = None
    if (
        configured_audit_window_days is not None
        and available_window_days is not None
    ):
        effective_window_days = min(
            configured_audit_window_days, available_window_days
        )
    elif configured_audit_window_days is not None:
        effective_window_days = configured_audit_window_days
    elif available_window_days is not None:
        effective_window_days = available_window_days

    connection.send_result(
        msg["id"],
        {
            "purge_keep_days": purge_keep_days,
            "oldest_record_age_days": oldest_age_days,
            "available_window_days": available_window_days,
            "configured_audit_window_days": configured_audit_window_days,
            "effective_window_days": effective_window_days,
        },
    )


@websocket_api.websocket_command(
    {vol.Required("type"): "home_insights/export_dev_audit"}
)
@websocket_api.async_response
async def ws_export_dev_audit(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """v1.12.15: return the redacted dev-audit bundle for diagnostics.

    Admin-only. Calls `lib/dev_audit.build_dev_audit_bundle` which
    captures install signature + per-detector activity + event buffer
    signature + config fingerprint — all redacted (no entity friendly
    names, no automation aliases, no IPs, no lat/long).

    Two intended uses:

    1. **Bug reports**: the user runs `home_insights/export_dev_audit`,
       attaches the JSON to a GitHub issue. Maintainers and the user
       community can reproduce the diagnostic context without the user
       having to manually enumerate their install.

    2. **LLM-driven verification**: the user pastes the JSON into a
       chat with their preferred AI assistant, asks "are any of my
       detectors silent for the wrong reason?" The schema (see
       `SCHEMA_VERSION` in `lib/dev_audit.py`) lets an LLM agent reason
       deterministically across detectors.

    The future v1.13 in-integration LLM audit will use the same builder
    + send to the user's chosen `LlmService` agent via the existing
    failover stack.
    """
    if not _require_admin(hass, connection, msg):
        return
    store = _get_store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_set_up", "Store not initialized")
        return
    try:
        from ..lib.dev_audit import build_dev_audit_bundle

        integration_version = await _get_integration_version(hass)
        # Pull the buffer from the first config entry's hass.data slot.
        # Multi-entry installs use the first entry's buffer for the
        # snapshot; the install-signature numbers below are install-wide
        # already, so this is fine for a diagnostic dump.
        buffer_ = None
        for entry_data in hass.data.get(DOMAIN, {}).values():
            if isinstance(entry_data, dict) and "buffer" in entry_data:
                buffer_ = entry_data["buffer"]
                break
        bundle = await build_dev_audit_bundle(
            hass,
            store,
            integration_version=integration_version,
            buffer=buffer_,
        )
    except Exception as exc:
        connection.send_error(
            msg["id"], "dev_audit_failed", f"Bundle build failed: {exc}"
        )
        return
    connection.send_result(msg["id"], bundle)


@websocket_api.websocket_command(
    {vol.Required("type"): "home_insights/rollup_progress"}
)
@callback
def ws_rollup_progress(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the current/last audit-rollup batch state.

    Sync `@callback` is safe — `get_rollup_progress` is a pure
    dict copy off module-level state with no I/O. Card polls this
    while a batch is in flight to render its progress bar.
    """
    from ..audit.rollup import get_rollup_progress

    connection.send_result(msg["id"], get_rollup_progress())


@websocket_api.websocket_command(
    {vol.Required("type"): "home_insights/backfill_status"}
)
@callback
def ws_backfill_status(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the current backfill status for the (single) config entry.

    Used by the card to surface a "Backfilled N events" toast on first
    connect after install. Returns {running, last}; `last` is the summary
    dict from the most recent run (or null if backfill has never run).
    """
    for entry_data in hass.data.get(DOMAIN, {}).values():
        if isinstance(entry_data, dict) and "buffer" in entry_data:
            connection.send_result(
                msg["id"],
                {
                    "running": bool(entry_data.get("backfill_running")),
                    "last": entry_data.get("last_backfill"),
                },
            )
            return
    connection.send_error(msg["id"], "not_set_up", "Integration not initialized")


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/_dev/inject_event",
        vol.Required("entity_id"): str,
        vol.Required("domain"): str,
        vol.Optional("area_id"): vol.Any(str, None),
        vol.Required("timestamp"): str,
        vol.Optional("old_state"): vol.Any(str, None),
        vol.Required("new_state"): str,
    }
)
@websocket_api.require_admin
@callback
def ws_dev_inject_event(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """DEV ONLY — push a synthetic state event into the buffer with a chosen timestamp.

    Used by dev/seed.py to backfill the rolling buffer for ScheduleDetector
    testing without needing access to HA's recorder. Not part of the stable
    public API; the underscore prefix marks it as dev-only.
    """
    from ..observers.state_event_buffer import StateEvent

    buffer_ = _get_buffer(hass)
    if buffer_ is None:
        connection.send_error(msg["id"], "not_set_up", "Buffer not initialized")
        return

    try:
        ts = datetime.fromisoformat(msg["timestamp"])
    except ValueError:
        connection.send_error(
            msg["id"], "invalid_time", "timestamp must be ISO 8601 format"
        )
        return

    event = StateEvent(
        timestamp=ts,
        entity_id=msg["entity_id"],
        domain=msg["domain"],
        area_id=msg.get("area_id"),
        old_state=msg.get("old_state"),
        new_state=msg["new_state"],
    )
    accepted = buffer_.add(event)
    connection.send_result(msg["id"], {"accepted": accepted})


# ---------------------------------------------------------------------------
# Existing-automation Refine flow (v1.1)
#
# Three endpoints that let the user refine an EXISTING automation with the
# LLM, instead of only refining new insights.
#
#   1. home_insights/get_automation { automation_id } -> {yaml, config, alias, id}
#      Loads the automation's current YAML so the card can show it as the
#      "before" view in the refine dialog.
#
#   2. home_insights/refine_automation { automation_id, feedback, agent_id? }
#      Loads the automation, treats it as a virtual insight payload, runs
#      it through the existing refine pipeline (redactor + LLM + dereference),
#      returns the refined YAML + diff_summary. NO file write yet — preview
#      only.
#
#   3. home_insights/apply_automation_refinement { automation_id, refined_config }
#      Writes the refined YAML back via AutomationWriter (same path as
#      Apply for new insights), then automation.reload picks it up.
#
# Mutating endpoints are admin-gated; get_automation is read-only.
# ---------------------------------------------------------------------------


# Concise variant — ~170 tokens, the default.
#
# Rule 5 was previously a hard "never remove entities" — too blunt:
# audit findings legitimately authorize specific removals, and a
# user typing "remove the dead lights" should be honored. The new
# wording defers to an AUTHORIZED EDITS section the caller appends



@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/get_automation",
        vol.Required("automation_id"): str,
    }
)
@websocket_api.async_response
async def ws_get_automation(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the current YAML config for an existing automation."""
    automation_id = msg["automation_id"]
    raw = await hass.async_add_executor_job(
        _find_automation_by_id, hass, automation_id
    )
    if raw is None:
        _LOGGER.warning(
            "ws_get_automation: no automation found for id/alias %r — "
            "lookup walked hass.data['automation'] AND automations.yaml "
            "with no match. Automation may live in a package or "
            "configuration.yaml — those aren't currently scanned.",
            automation_id,
        )
        connection.send_error(
            msg["id"],
            "not_found",
            f"No automation found with id/alias {automation_id!r}. "
            "If this automation lives in a package or configuration.yaml, "
            "the lookup can't reach it.",
        )
        return
    # Sanitize the raw_config dict so PyYAML.safe_dump can serialize
    # it downstream (HA injects Template / Selector / etc. objects
    # PyYAML can't represent → RepresenterError otherwise).
    raw = _sanitize_yaml_safe(raw)
    if not isinstance(raw, dict) or not raw:
        # Lookup returned a truthy-but-empty object (e.g. a stub
        # entity created before its raw_config was populated). Send
        # a clear error so the card warning banner has something
        # specific to display.
        _LOGGER.warning(
            "ws_get_automation: raw_config for %r is empty after "
            "sanitisation: %r",
            automation_id,
            raw,
        )
        connection.send_error(
            msg["id"],
            "empty_config",
            f"Automation {automation_id!r} exists but its raw_config "
            "is empty. HA may still be loading; try again in a few "
            "seconds.",
        )
        return
    try:
        import yaml as _yaml

        yaml_text = _yaml.safe_dump(
            raw, sort_keys=False, default_flow_style=False
        )
    except Exception as err:
        _LOGGER.warning(
            "ws_get_automation: yaml.safe_dump failed for %r: %s",
            automation_id,
            err,
        )
        yaml_text = str(raw)
    connection.send_result(
        msg["id"],
        {
            "id": raw.get("id"),
            "alias": raw.get("alias"),
            "yaml": yaml_text,
            "config": raw,
        },
    )


# ---------------------------------------------------------------------------
# AutomationAudit Phase C — LLM suggest for "report"-format audit insights
# ---------------------------------------------------------------------------




# -- Detector directory --

# Quick lookup so the panel + setup UI can say "this needs a
# mobile_app integration installed" or "we don't see a
# sensor.outdoor_temperature in your install — temperature axis
# disabled". One-line summary per detector with its declared
# required/optional data + a per-dependency satisfied bit.


def _check_dependency_satisfied(
    hass: HomeAssistant, dep: str
) -> bool:
    """Best-effort check for whether a declared dependency is
    currently satisfied. Always tolerant — returns False on any
    lookup error rather than raising into the WS layer.
    """
    try:
        if dep.startswith("integration:"):
            name = dep.split(":", 1)[1]
            return any(
                e.domain == name
                for e in hass.config_entries.async_entries(name)
            )
        if dep.startswith("entity:"):
            eid = dep.split(":", 1)[1]
            return hass.states.get(eid) is not None
        if dep.startswith("entity_pattern:"):
            import fnmatch as _fnmatch

            pat = dep.split(":", 1)[1]
            return any(
                _fnmatch.fnmatchcase(s.entity_id, pat)
                for s in hass.states.async_all()
            )
        if dep.startswith("domain:"):
            domain = dep.split(":", 1)[1]
            return any(
                s.entity_id.split(".", 1)[0] == domain
                for s in hass.states.async_all()
            )
        if dep.startswith("feature:"):
            feature = dep.split(":", 1)[1]
            if feature == "recorder":
                return "recorder" in hass.config.components
        return False
    except Exception:
        return False


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/detector_directory",
    }
)
@callback
def ws_detector_directory(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return every registered detector with its description,
    required/optional dependencies, and a per-dependency satisfied
    flag so users can see at a glance what they need to install or
    enable for a given detector to produce results.

    Panel uses this to render the OptionsFlow detector picker with
    tier hints (USELESS / LIMITED / GOOD / GREAT) — see
    SetupQualityDetector for the longer-form periodic surface.
    """
    from ..detectors import DETECTORS

    out: list[dict[str, Any]] = []
    for name in sorted(DETECTORS):
        cls = DETECTORS[name]
        required = tuple(getattr(cls, "required_data", ()) or ())
        optional = tuple(getattr(cls, "optional_data", ()) or ())
        required_status = [
            {"dependency": d, "satisfied": _check_dependency_satisfied(hass, d)}
            for d in required
        ]
        optional_status = [
            {"dependency": d, "satisfied": _check_dependency_satisfied(hass, d)}
            for d in optional
        ]
        # Coarse tier from the required-only satisfaction ratio.
        # Optional deps bump tier from GOOD → GREAT but don't gate.
        if not required:
            tier = "GOOD"  # no hard deps; works on whatever's in the buffer
        else:
            satisfied = sum(1 for r in required_status if r["satisfied"])
            ratio = satisfied / len(required)
            if ratio == 0:
                tier = "USELESS"
            elif ratio < 1.0:
                tier = "LIMITED"
            else:
                tier = "GOOD"
        if tier == "GOOD" and optional_status:
            if any(o["satisfied"] for o in optional_status):
                tier = "GREAT"
        # Maturity tier — defaults to "stable" for detectors that
        # don't declare it. The panel renders 🟡 BETA / 🧪 EXPERIMENTAL
        # badges from this value.
        maturity_obj = getattr(cls, "maturity", None)
        maturity = (
            maturity_obj.value
            if maturity_obj is not None and hasattr(maturity_obj, "value")
            else "stable"
        )
        out.append(
            {
                "name": name,
                "description": getattr(cls, "description", "") or "",
                "kind": getattr(cls, "kind", None).value
                if getattr(cls, "kind", None) is not None
                else None,
                "requires_recorder": bool(
                    getattr(cls, "requires_recorder", False)
                ),
                "required_data": required_status,
                "optional_data": optional_status,
                "tier": tier,
                "maturity": maturity,
            }
        )
    connection.send_result(msg["id"], {"detectors": out})


# -- Example data (first-run demo) --


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/inject_examples",
    }
)
@websocket_api.async_response
async def ws_inject_examples(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Populate the store with a curated set of EXAMPLE insights so a
    brand-new install can see what the panel looks like before its
    own data accumulates. Each example carries
    `payload._example = True` so the card can render an EXAMPLE pill
    and `clear_examples` can remove them in one query. Idempotent —
    re-injecting replaces existing examples with the same fingerprints.
    """
    store = _get_store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_set_up", "Store not initialized")
        return
    from ..examples import build_example_insights

    added = 0
    try:
        for ins in build_example_insights():
            await store.add_insight(ins)
            added += 1
    except Exception as err:
        _LOGGER.exception("inject_examples failed")
        connection.send_error(msg["id"], "inject_failed", str(err))
        return
    connection.send_result(msg["id"], {"injected": added})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/clear_examples",
    }
)
@websocket_api.async_response
async def ws_clear_examples(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Remove every example insight from the store. Looks for
    `payload._example = True` to identify them — real insights never
    set that key. Returns the deletion count.
    """
    store = _get_store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_set_up", "Store not initialized")
        return
    from ..examples import EXAMPLE_PAYLOAD_KEY

    removed = 0
    try:
        # No bulk-delete-by-payload helper in the store; walk the
        # active + dismissed lists, dismiss each example. The next
        # scan's sweep will GC them once we add a hard-delete API.
        # For now, dismissing is enough to hide from the panel.
        all_ins = await store.list_insights(
            include_dismissed=True,
            include_applied=True,
            include_snoozed=True,
        )
        for ins in all_ins:
            if ins.payload.get(EXAMPLE_PAYLOAD_KEY) is True:
                await store.dismiss_insight(ins.id)
                removed += 1
    except Exception as err:
        _LOGGER.exception("clear_examples failed")
        connection.send_error(msg["id"], "clear_failed", str(err))
        return
    connection.send_result(msg["id"], {"removed": removed})


# -- Community analytics preview --


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/analytics_preview",
    }
)
@websocket_api.async_response
async def ws_analytics_preview(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the EXACT payload that would be POSTed to the
    community analytics receiver. The user can inspect this in the
    panel BEFORE enabling — every field is auditable.

    Returns None (no transmission) — this is purely informational.
    """
    store = _get_store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_set_up", "Store not initialized")
        return
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        connection.send_error(
            msg["id"], "no_entry", "No HA Insights entry found"
        )
        return
    try:
        from ..analytics import (
            DEFAULT_ANALYTICS_ENDPOINT,
            build_report_payload,
        )

        payload = await build_report_payload(hass, entries[0], store)
        connection.send_result(
            msg["id"],
            {
                "payload": payload,
                "default_endpoint": DEFAULT_ANALYTICS_ENDPOINT,
            },
        )
    except Exception as err:
        _LOGGER.exception("analytics_preview failed")
        connection.send_error(msg["id"], "preview_failed", str(err))


# -- Per-user policy overrides (admin only) --


# _require_admin moved to ws_api/_helpers.py during the v1.13 refactor.


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/list_ha_users",
    }
)
@websocket_api.async_response
async def ws_list_ha_users(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the household's HA users with their mobile_app status.
    Admin-only. Used by the per-user-overrides admin panel so the
    admin can pick a user to override.
    """
    if not _require_admin(hass, connection, msg):
        return
    try:
        users = await hass.auth.async_get_users()
    except Exception as err:
        _LOGGER.exception("list_ha_users failed")
        connection.send_error(msg["id"], "list_failed", str(err))
        return
    # Build user_id → mobile_app device count to surface which users
    # actually have a registered phone (and so are routable).
    mobile_app_users: dict[str, int] = {}
    try:
        for cfg in hass.config_entries.async_entries("mobile_app"):
            uid = cfg.data.get("user_id")
            if isinstance(uid, str) and uid:
                mobile_app_users[uid] = mobile_app_users.get(uid, 0) + 1
    except Exception:
        pass
    out = [
        {
            "user_id": u.id,
            "name": u.name,
            "is_admin": u.is_admin,
            "system_generated": getattr(u, "system_generated", False),
            "mobile_app_device_count": mobile_app_users.get(u.id, 0),
        }
        for u in users
        # Filter out system-generated users (Supervisor, refresh
        # tokens, etc) — they aren't real humans.
        if not getattr(u, "system_generated", False)
    ]
    connection.send_result(msg["id"], {"users": out})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/get_user_overrides",
    }
)
@websocket_api.async_response
async def ws_get_user_overrides(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the current per-user policy overrides. Admin-only."""
    if not _require_admin(hass, connection, msg):
        return
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        connection.send_error(msg["id"], "no_entry", "No HA Insights entry")
        return
    from ..config_flow import (
        get_mobile_notify_policy,
        get_notify_user_overrides,
    )

    connection.send_result(
        msg["id"],
        {
            "global_policy": get_mobile_notify_policy(entries[0]),
            "overrides": get_notify_user_overrides(entries[0]),
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/set_user_override",
        vol.Required("user_id"): str,
        # null/missing keys mean "clear this override". An empty dict
        # also means "no override for this user" — same as missing.
        vol.Optional("override"): vol.Any(dict, None),
    }
)
@websocket_api.async_response
async def ws_set_user_override(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Set or clear a per-user policy override. Admin-only.

    Body shape:
      { user_id: "uuid",
        override: {confidence_floor: 0.85, daily_cap: 2, ...} | null }

    Pass `null` (or omit the field) to clear the override for that
    user. Only the known policy keys are kept; anything else is
    discarded silently.
    """
    if not _require_admin(hass, connection, msg):
        return
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        connection.send_error(msg["id"], "no_entry", "No HA Insights entry")
        return
    entry = entries[0]
    target_user_id = msg["user_id"]
    raw_override = msg.get("override")

    KNOWN_KEYS = {
        "confidence_floor",
        "daily_cap",
        "quiet_hours_start",
        "quiet_hours_end",
        "min_attribution_confidence",
        "preset",
    }

    from ..config_flow import (
        CONF_NOTIFY_USER_OVERRIDES,
        get_notify_user_overrides,
    )

    current = dict(get_notify_user_overrides(entry))
    if not raw_override:
        current.pop(target_user_id, None)
    else:
        cleaned = {
            k: v for k, v in raw_override.items() if k in KNOWN_KEYS
        }
        if cleaned:
            current[target_user_id] = cleaned
        else:
            # Empty after filtering — treat as a clear
            current.pop(target_user_id, None)

    merged_options = dict(entry.options)
    merged_options[CONF_NOTIFY_USER_OVERRIDES] = current
    hass.config_entries.async_update_entry(entry, options=merged_options)
    connection.send_result(msg["id"], {"overrides": current})


# v1.13.6 — ManagedDevices handlers (ws_list_managed_devices,
# ws_set_device_managed + helper _managed_devices_set) moved to
# ws_api/managed_devices.py during the v1.13 refactor (step 4).
# Imported at the top of this module and registered via async_register
# below; this comment stub preserves the section boundary for future
# readers.


# v1.13.4 — Find My Device handlers (ws_identify_capability,
# ws_identify_entity, ws_perturbation_guide, ws_perturbation_test +
# the _collect_ip_attrs_for_candidates helper) moved to ws_api/identify.py
# during the v1.13 refactor (step 2). They are imported at the top of
# this module and registered via async_register below; this comment
# stub preserves the section boundary for future readers.


# v1.13.5 — BLE live-find handlers (ws_ble_capability, ws_ble_live_find +
# helpers _ble_proxy_label / _seen_proxies_for) moved to ws_api/ble_find.py
# during the v1.13 refactor (step 3). They are imported at the top of this
# module and registered via async_register below; this comment stub
# preserves the section boundary for future readers.


# v1.13.2 — Blank-canvas automation chat -----------------------------


