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

# v1.13.4 step 2 of the ws_api refactor — Find My Device handlers
# moved out to their own file. Imported back here so async_register
# + any external consumer keeps working.
from .identify import (
    ws_identify_capability,
    ws_identify_entity,
    ws_perturbation_guide,
    ws_perturbation_test,
)

# Re-export for any external consumer that's reaching into ws_api
# for these helpers. New code should import from `._helpers` directly.
__all__ = [
    "_audit_attempts",
    "_get_buffer",
    "_get_store",
    "_require_admin",
    "_resolve_blocked_entities",
    "_resolve_preferred_agent_id",
    "ws_identify_capability",
    "ws_identify_entity",
    "ws_perturbation_guide",
    "ws_perturbation_test",
]

_LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ..insight import Insight


WS_PROTOCOL_VERSION = 1


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
    {
        vol.Required("type"): "home_insights/hypothesize",
        vol.Required("insight_id"): str,
        vol.Optional("agent_id"): vol.Any(str, None),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_hypothesize(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """LLM hypothesis generator for ANOMALY-kind insights.

    Same redactor + agent + dereference + audit shape as ws_explain, but
    asks the LLM for plausible causes ("battery dead?", "stuck contact?",
    "runaway automation?") instead of "should I automate this?". Returns
    the response text directly — not persisted on the insight, since
    hypotheses are throwaway suggestions the user can re-roll on demand.
    """
    from ..config_flow import get_blocked_entities
    from ..insight import InsightKind
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

    if insight.kind is not InsightKind.ANOMALY:
        connection.send_error(
            msg["id"],
            "invalid_kind",
            "Hypothesize only works on ANOMALY-kind insights",
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
        prompt_kind="hypothesize",
        preferred_agent_id=preferred,
    )

    await _audit_attempts(
        store, result.attempts, insight_id=insight.id, redactor=redactor
    )

    if not result.success:
        connection.send_error(
            msg["id"],
            "hypothesize_failed",
            result.error or "Conversation agent returned no speech",
        )
        return

    connection.send_result(
        msg["id"],
        {
            "hypothesis": result.explanation,
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
        vol.Required("type"): "home_insights/refine",
        vol.Required("insight_id"): str,
        vol.Optional("agent_id"): vol.Any(str, None),
        vol.Optional("feedback"): vol.Any(str, None),
        # v1.0 RC #2: thread conversation_id from prior Refine on same
        # insight so the agent retains context across turns.
        vol.Optional("conversation_id"): vol.Any(str, None),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_refine(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """User-initiated LLM refinement of an automation insight.

    Pseudonymizes the payload, calls the configured Conversation agent,
    parses + dereferences + validates the response. Does NOT mutate the
    insight — the refined payload is returned for the card to preview, then
    applied via `home_insights/apply` with `payload_override` if accepted.
    """
    from ..llm import RedactionMode, Redactor, refine_insight

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
            f"refine only supports payload_format='automation' (got "
            f"{insight.payload_format!r})",
        )
        return

    from ..config_flow import get_blocked_entities

    blocked = _resolve_blocked_entities(hass, get_blocked_entities)
    preferred = _resolve_preferred_agent_id(hass)
    redactor = Redactor(
        store, mode=RedactionMode.AGGRESSIVE, blocked_entities=blocked
    )
    result = await refine_insight(
        hass,
        agent_id=msg.get("agent_id"),
        insight=insight,
        redactor=redactor,
        prior_explanation=insight.explanation,
        feedback=msg.get("feedback"),
        preferred_agent_id=preferred,
        conversation_id=msg.get("conversation_id"),
    )

    # Audit every attempt — failover may have made multiple round-trips
    # before landing on a working agent. Each round-trip is bytes that
    # left the network and MUST appear in the privacy log.
    await _audit_attempts(
        store, result.attempts, insight_id=insight.id, redactor=redactor
    )

    if not result.success:
        # Include a truncated raw_response so the user (and the card) can see
        # what the LLM actually returned when validation rejects the output.
        # Many LLMs produce shape-incomplete YAML even within token budget;
        # being able to inspect the raw text is essential for self-service
        # debugging.
        detail = result.error or "Refinement failed"
        if result.raw_response:
            snippet = result.raw_response.strip()
            if len(snippet) > 600:
                snippet = snippet[:600] + "…"
            detail = f"{detail}\n\nLLM said:\n{snippet}"
        connection.send_error(msg["id"], "refine_failed", detail)
        return

    connection.send_result(
        msg["id"],
        {
            "refined_payload": result.refined_payload,
            "rationale": result.rationale,
            "diff_summary": result.diff_summary,
            "bytes_sent": result.bytes_sent,
            "bytes_received": result.bytes_received,
            # Card threads this back on the next Refine for context.
            "conversation_id": result.conversation_id,
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
    connection.send_result(msg["id"])


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
    {
        vol.Required("type"): "home_insights/refine_cost_estimate",
        vol.Required("insight_id"): str,
        vol.Optional("feedback"): vol.Any(str, None),
        vol.Optional("agent_id"): vol.Any(str, None),
    }
)
@websocket_api.async_response
async def ws_refine_cost_estimate(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Server-side pre-flight: estimate token + USD cost of a Refine call.

    Runs the same redaction + prompt-build pipeline as ws_refine but stops
    before the LLM. Returns {tokens_in, tokens_out, cost_usd, agent_id,
    threshold_usd, requires_confirm} so the card can decide whether to
    show a "are you sure?" dialog before burning tokens.

    Output bytes are estimated from a typical refined-automation length
    (~800 bytes / ~200 tokens). The figure is rough by definition — we
    don't know the agent's actual response until we make the call — but
    it's the cheapest way to prevent expensive misclicks on Opus-tier
    models without round-tripping a real call.
    """
    from ..config_flow import get_blocked_entities
    from ..llm import RedactionMode, Redactor, build_refine_prompt
    from ..llm.agent_client import _list_agent_candidates
    from ..llm.cost import estimate_cost

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
            "cost estimate only supports payload_format='automation'",
        )
        return

    # Pre-build the prompt the same way refine_insight would, so the byte
    # count is realistic.
    blocked = _resolve_blocked_entities(hass, get_blocked_entities)
    redactor = Redactor(
        store, mode=RedactionMode.AGGRESSIVE, blocked_entities=blocked
    )
    redacted_payload, _ = await redactor.redact_insight_payload(insight.payload)

    redacted_explanation: str | None = None
    if insight.explanation:
        redacted_explanation, _ = await redactor.redact_text(insight.explanation)
    redacted_feedback: str | None = None
    feedback = msg.get("feedback")
    if feedback:
        redacted_feedback, _ = await redactor.redact_text(feedback)

    prompt = build_refine_prompt(
        redacted_payload,
        prior_explanation=redacted_explanation,
        feedback=redacted_feedback,
    )
    bytes_sent = len(prompt.encode("utf-8"))
    # Heuristic: a refined automation YAML response is ~800 bytes (~200 tokens).
    # If the model emits a long RATIONALE block first the figure is light;
    # if it abbreviates aggressively the figure is high. Mid-band estimate.
    bytes_received_est = 800

    requested = msg.get("agent_id")
    preferred = _resolve_preferred_agent_id(hass)
    candidates = _list_agent_candidates(
        hass, requested=requested, preferred=preferred
    )
    # The agent the cost will most likely fall on: the first non-None candidate.
    target_agent = next((c for c in candidates if c is not None), None)

    cost = estimate_cost(
        agent_id=target_agent,
        bytes_sent=bytes_sent,
        bytes_received=bytes_received_est,
    )

    threshold = _resolve_refine_cost_threshold(hass)
    requires_confirm = (
        target_agent is not None
        and float(cost["cost_usd"]) > threshold
        and cost["source"] != "local_free"
    )

    connection.send_result(
        msg["id"],
        {
            "agent_id": target_agent,
            "tokens_in": cost["tokens_in"],
            "tokens_out": cost["tokens_out"],
            "cost_usd": cost["cost_usd"],
            "cost_source": cost["source"],
            "threshold_usd": threshold,
            "requires_confirm": requires_confirm,
        },
    )


def _resolve_refine_cost_threshold(hass: HomeAssistant) -> float:
    """Pick the lowest threshold across active config entries.

    Lowest wins so a "be cautious" entry isn't bypassed by a more
    permissive one in a multi-entry future.
    """
    from ..config_flow import (
        DEFAULT_REFINE_COST_THRESHOLD_USD,
        get_refine_cost_threshold,
    )

    thresholds = [
        get_refine_cost_threshold(entry)
        for entry in hass.config_entries.async_entries(DOMAIN)
    ]
    return min(thresholds) if thresholds else DEFAULT_REFINE_COST_THRESHOLD_USD


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
# from findings or user feedback. When neither authorizes a
# removal, the conservative default holds.
_REFINE_PRINCIPLES_CONCISE = (
    "RULES:\n"
    "1. Default to no change. Empty diff_summary is a valid answer.\n"
    "2. Before editing, name one edge case the change could break. "
    "If unsure, KEEP the field.\n"
    "3. Don't change platform/from/to/for/attribute/condition/"
    "service/target shape unless a finding pinpoints it as buggy.\n"
    "4. Don't add weekday/time/sun conditions when a state trigger "
    "on the same entity already gates firing.\n"
    "5. You may ONLY make edits listed under AUTHORIZED EDITS below. "
    "If a finding lists an entity, you can act on THAT entity — "
    "don't generalise to others.\n"
    "6. Preserve mode:/max:/initial_state:/for:/templates/custom "
    "services + `action:` vs `service:` key style verbatim.\n"
    "7. Rationale: per change, name it + one edge case ruled out."
)

# In-depth variant — ~600 tokens. Same rules with examples + a
# requested reasoning protocol. Better for tricky automations.
_REFINE_PRINCIPLES_INDEPTH = """RULES (think through each before responding):

1. MINIMAL CHANGE IS DEFAULT. If no finding points to a CLEAR, SAFE
   fix, return original YAML with rationale explaining what you
   considered. Empty diff_summary with a no-change rationale is a
   valid, welcome outcome. Confidence in the user's existing setup
   beats your prior on what's idiomatic.

2. REGRESSION CHECK BEFORE EVERY EDIT. For each proposed change,
   answer in your rationale: "what edge case is the existing YAML
   handling that this edit could break?" Examples to consider:
    - `for:` durations preventing flicker on noisy sensors
    - `mode: single` / `max:` / `max_exceeded:` preventing queue
      buildup or race conditions
    - `initial_state` controlling behaviour at reboot
    - condition blocks guarding state combinations you can't see
    - template `entity_id:` lists computed at trigger time
    - explicit `service_data` / `target` shapes required by specific
      platforms (Hue scenes, MQTT JSON modes, etc.)
    - notification side-effects (persistent_notification.create,
      notify.* calls) the user relies on
   If you can't explain why a field is safe to remove, KEEP IT.

3. PRESERVE UNKNOWNS. Custom services, weird-looking templates,
   oddly-named entities, comments inside `description:` — preserve
   verbatim. Reformat is NOT improvement.

4. TRIGGER + STRUCTURE ARE LOAD-BEARING. Don't change `platform:`,
   `from:`, `to:`, `for:`, `attribute:`, `event_type:`, `event_data:`,
   `condition.condition`, `action[].service`, or `action[].target`
   shape unless a finding explicitly identifies a specific bug there.

5. DON'T DUPLICATE THE TRIGGER. A STATE trigger on entity X only
   fires when X changes. Adding a `weekday:` / `time:` / `sun:`
   condition that filters days X is naturally silent on is redundant
   noise. Conditions are for state INDEPENDENT of the trigger
   (someone home, sun position when not sun-triggered, etc.).

6. NEVER SILENTLY SWAP ENTITIES. If a finding says an entity is
   unavailable/missing, FLAG it in your rationale. Never guess a
   replacement entity_id and write it into YAML.

7. WALK YOUR REASONING IN `rationale`. For every change: name it,
   justify it against the findings, AND explicitly name one edge
   case you considered and ruled out. Reasoning quality > number
   of changes."""

# Backwards-compat alias. Most call sites use _REFINE_PRINCIPLES;
# new resolver code below switches based on depth.
_REFINE_PRINCIPLES = _REFINE_PRINCIPLES_CONCISE


def _principles_for(depth: str) -> str:
    """Return the principles block matching the configured depth."""
    return (
        _REFINE_PRINCIPLES_INDEPTH
        if depth == "indepth"
        else _REFINE_PRINCIPLES_CONCISE
    )


def _resolve_audit_depth(
    hass: HomeAssistant, override: str | None = None
) -> str:
    """Resolve depth: per-call override > first entry's OptionsFlow >
    'concise' default. Returns 'concise' or 'indepth'."""
    if override in ("concise", "indepth"):
        return override
    try:
        from ..config_flow import get_audit_analysis_depth

        for entry in hass.config_entries.async_entries(DOMAIN):
            return get_audit_analysis_depth(entry)
    except Exception:
        pass
    return "concise"


# Per-observation-kind one-line hints. Token-conscious — each is a
# verb-led action the LLM applies for that finding type. Add new
# kinds here; future hints SHOULD stay ≤ ~20 tokens each.
_OBS_KIND_HINTS: dict[str, str] = {
    "long_on_duration": (
        "→ raise/add `for:`. Don't touch triggers/conditions."
    ),
    "trigger_time_drift": (
        "→ shift `at:` by observed delta (5-min boundary). Nothing else."
    ),
    "entity_silent": (
        "→ FLAG in rationale. Never guess a replacement."
    ),
    "redundant_target": (
        "→ drop the listed member entries. Mechanical, tight scope."
    ),
    "trace_dormant": (
        "→ FLAG; suggest user disable. Don't rewrite logic."
    ),
    "trace_condition_blocks": (
        "→ loosen condition only if blocked runs were unintentional. "
        "Else KEEP."
    ),
    "trace_action_errors": (
        "→ FLAG the erroring step. Don't rewrite — no failing trace."
    ),
    "rollup_weekday_only": "→ CONTEXT ONLY. Don't add weekday condition.",
    "rollup_dow_dark_days": "→ CONTEXT ONLY. Don't add weekday condition.",
    "rollup_month_start_spike": "→ CONTEXT ONLY. No date condition.",
    "rollup_seasonal_silence": (
        "→ CONTEXT. Add `month:` cond ONLY if trigger is time/sun-based."
    ),
    "has_recent_insights": "→ CONTEXT. Related findings exist; don't act.",
}


def _build_audit_feedback(
    observations: list[dict[str, Any]],
    *,
    depth: str = "concise",
) -> str:
    """Audit feedback builder. `depth` chooses concise (~150 tok)
    vs indepth (~600 tok) principles."""
    findings: list[str] = []
    has_context_only = False
    has_actionable = False
    for obs in observations:
        kind = obs.get("kind") or ""
        text = (obs.get("text") or "").strip()
        is_context = bool((obs.get("metrics") or {}).get("context_only"))
        if is_context:
            has_context_only = True
        else:
            has_actionable = True
        findings.append(f"- {text}")
        hint = _OBS_KIND_HINTS.get(kind)
        if hint:
            findings.append(f"  {hint}")

    header = "FINDINGS:"
    if has_context_only and not has_actionable:
        header = (
            "ALL findings are CONTEXT-ONLY. Likely correct answer: "
            "no change.\nFINDINGS:"
        )

    # Derive the per-call authorization list. Rule 5 says "you may
    # ONLY make edits listed below" — this is "below".
    authorized = _authorized_edits_from_observations(observations)

    return "\n".join(
        [header, *findings, "", authorized, "", _principles_for(depth)]
    )


def _authorized_edits_from_observations(
    observations: list[dict[str, Any]],
) -> str:
    """Build an `AUTHORIZED EDITS:` block from the observation list.

    Each observation kind unlocks a specific edit class on a specific
    entity / step. Anything not listed is implicitly forbidden by
    Rule 5. This is the contextual-rule architecture the user
    requested — instead of a universal "never remove entities" rule,
    we tell the LLM exactly which removals / changes the findings
    actually justify.
    """
    lines: list[str] = []
    remove_targets: list[str] = []
    raise_for_targets: list[str] = []
    shift_triggers: list[tuple[str, str]] = []
    drop_redundant: list[tuple[str, list[str]]] = []
    disable_dormant = False
    investigate_action_errors = False
    loosen_conditions: list[str] = []

    for obs in observations:
        kind = obs.get("kind") or ""
        metrics = obs.get("metrics") or {}
        if (metrics or {}).get("context_only"):
            continue
        if kind == "entity_silent":
            eid = metrics.get("entity_id")
            if isinstance(eid, str):
                remove_targets.append(eid)
        elif kind == "long_on_duration":
            eid = metrics.get("entity_id")
            if isinstance(eid, str):
                raise_for_targets.append(eid)
        elif kind == "trigger_time_drift":
            tt = metrics.get("trigger_time")
            delta = metrics.get("delta_min")
            if isinstance(tt, str) and isinstance(delta, (int, float)):
                sign = "+" if delta > 0 else ""
                shift_triggers.append((tt, f"{sign}{delta:.0f} min"))
        elif kind == "redundant_target":
            container = metrics.get("container")
            members = metrics.get("redundant_members") or []
            if isinstance(container, str) and members:
                drop_redundant.append((container, list(members)))
        elif kind == "trace_dormant":
            disable_dormant = True
        elif kind == "trace_action_errors":
            investigate_action_errors = True
        elif kind == "trace_condition_blocks":
            step = metrics.get("step")
            if isinstance(step, str):
                loosen_conditions.append(step)

    if remove_targets:
        lines.append(
            "- REMOVE these entities from action targets (they are "
            f"unavailable / missing): {', '.join(sorted(set(remove_targets)))}"
        )
    if drop_redundant:
        for container, members in drop_redundant:
            lines.append(
                f"- REMOVE redundant members of {container} from action "
                f"targets: {', '.join(members)}"
            )
    if raise_for_targets:
        lines.append(
            "- RAISE the `for:` clause on actions targeting: "
            f"{', '.join(sorted(set(raise_for_targets)))}"
        )
    if shift_triggers:
        parts = [f"{t} by {d}" for t, d in shift_triggers]
        lines.append(
            "- SHIFT time trigger(s) toward observed reality: "
            + "; ".join(parts)
        )
    if disable_dormant:
        lines.append(
            "- FLAG the automation as dormant (no fires in 30d+). A "
            "safe edit is to set `initial_state: false` OR recommend "
            "disable in your rationale; don't rewrite logic."
        )
    if investigate_action_errors:
        lines.append(
            "- FLAG action-error steps in your rationale; DO NOT "
            "rewrite the failing action (no failing trace available)."
        )
    if loosen_conditions:
        lines.append(
            "- CONSIDER loosening these condition steps (most fires "
            f"blocked): {', '.join(loosen_conditions)}"
        )

    if not lines:
        return (
            "AUTHORIZED EDITS:\n"
            "- (none from findings — only safe meta-edits like fixing "
            "alias typos, normalising YAML formatting, or adding a "
            "clarifying `description:` are permitted. Do NOT touch "
            "triggers, conditions, or action targets.)"
        )
    return "AUTHORIZED EDITS:\n" + "\n".join(lines)


def _authorized_from_user_text(user_text: str) -> str:
    """Build an AUTHORIZED EDITS block for user-typed refines.

    Without specific findings, the user's request IS the authorisation.
    We don't try to parse it — just echo it as the canonical
    authority for what's allowed, in the prompt the LLM sees. The
    Refine principles already say "execute the request faithfully."
    """
    text = (user_text or "").strip()
    if not text:
        return (
            "AUTHORIZED EDITS:\n"
            "- (no specific request — apply only obvious bug fixes; "
            "default to no change if nothing is clearly broken.)"
        )
    return (
        "AUTHORIZED EDITS:\n"
        f"- Execute the user request: {text}\n"
        "- Only side-edits required to make that request work are "
        "permitted. Do NOT add unrequested restructuring."
    )


def _wrap_user_feedback(
    user_feedback: str,
    *,
    conversation_turn: int = 0,
    depth: str = "concise",
) -> str:
    """User-feedback wrap.

    Turn 0: USER request + AUTHORIZED EDITS (derived from request)
            + RULES (depth-aware).
    Turn N>0: USER request only — conversation_id thread carries
    the rules.
    """
    user_text = (user_feedback or "").strip()
    if conversation_turn > 0:
        return f"USER: {user_text or '(no follow-up text)'}"
    authorized = _authorized_from_user_text(user_text)
    user_section = (
        f"USER: {user_text}" if user_text
        else "USER: (no specific request — flag obvious bugs only; "
             "return no-change if nothing is clearly wrong.)"
    )
    return (
        user_section
        + "\n\n"
        + authorized
        + "\n\n"
        + _principles_for(depth)
    )


def _humanize_llm_error(raw: str) -> str:
    """Translate cryptic provider errors into actionable user guidance.

    Common cases we see in the audit pipeline:
      - Gemini hits its output budget mid-YAML → FinishReason.MAX_TOKENS.
        The default Google AI agent config caps `max_output_tokens` at
        ~8192; a full 200-line automation rewrite + rationale can blow
        through it.
      - OpenAI returns 'context_length_exceeded' on huge YAMLs.
      - Anthropic returns 'prompt is too long' / hits stop_reason of
        'max_tokens'.

    For each known failure mode we append a one-line tip pointing the
    user at the lever they can actually pull.
    """
    text = raw or ""
    lowered = text.lower()
    if "max_tokens" in lowered or "max-tokens" in lowered or "max tokens" in lowered:
        return (
            f"{text}\n\n"
            "→ The LLM ran out of output token budget mid-response. "
            "Try one of:\n"
            "  • Switch the panel's analysis-depth toggle to 'Concise' "
            "(top of the panel)\n"
            "  • Type a shorter / more specific follow-up so the model "
            "doesn't try to rewrite the whole YAML\n"
            "  • Raise `max_output_tokens` in your conversation agent's "
            "configuration (Settings → Devices & Services → your "
            "Google AI / OpenAI / Anthropic Conversation entry)"
        )
    if "context_length" in lowered or "prompt is too long" in lowered:
        return (
            f"{text}\n\n"
            "→ The prompt exceeded the model's context window. "
            "Switch to a model with a larger context (Claude Sonnet 4 "
            "or Gemini Pro), or shorten the automation YAML before "
            "auditing."
        )
    if "rate" in lowered and "limit" in lowered:
        return (
            f"{text}\n\n"
            "→ Rate-limited by the LLM provider. Wait a minute and try again."
        )
    return text


def _attempt_to_dict(attempt: Any) -> dict[str, Any]:
    """Serialize an AttemptAudit (frozen dataclass with no to_dict())
    into a JSON-safe dict. Both ws_refine_automation and
    ws_audit_suggest previously called .to_dict() which doesn't
    exist on the AttemptAudit class — masked until audit_suggest
    actually fired and tripped it.
    """
    from dataclasses import asdict, is_dataclass

    if is_dataclass(attempt) and not isinstance(attempt, type):
        return asdict(attempt)
    return {
        "chosen_agent_id": getattr(attempt, "chosen_agent_id", None),
        "bytes_sent": getattr(attempt, "bytes_sent", 0),
        "bytes_received": getattr(attempt, "bytes_received", 0),
        "success": getattr(attempt, "success", False),
    }


def _sanitize_yaml_safe(value: Any) -> Any:
    """Round-trip a value through JSON so PyYAML's safe_dump can
    represent it.

    HA's automation registry surfaces raw_config dicts that often
    include non-JSON Python types: `Template` objects, `Selector`,
    `mappingproxy`, OrderedDict subclasses, custom enums. PyYAML's
    `safe_dump` raises `RepresenterError("cannot represent an
    object", repr_of_value)` on those.

    Casting to JSON first with `default=str` collapses every unknown
    type to its string repr — losing fidelity for Templates (which
    become their `{{ … }}` source string) but keeping the prompt
    serializable, which is what the LLM pipeline needs.
    """
    import json as _json

    try:
        return _json.loads(_json.dumps(value, default=str))
    except Exception:
        return value


def _find_automation_by_id(
    hass: HomeAssistant, automation_id: str
) -> dict | None:
    """Look up an automation's raw_config dict by its id or alias.

    Walks both runtime state (hass.data["automation"]) AND automations.yaml.
    Returns the first match. None when no automation matches.
    """
    component = hass.data.get("automation")
    entities_iter = None
    if hasattr(component, "entities"):
        entities_iter = component.entities
    elif isinstance(component, dict):
        entities_iter = component.values()
    if entities_iter is not None:
        for entry in entities_iter:
            raw = (
                getattr(entry, "raw_config", None)
                or getattr(entry, "_raw_config", None)
            )
            if isinstance(raw, dict) and (
                str(raw.get("id")) == automation_id
                or raw.get("alias") == automation_id
            ):
                return raw
    # File-based fallback: walk automations.yaml AND any glob-loaded
    # config files (packages/, configuration.yaml inline `automation:`).
    # Package-defined automations were previously invisible to the
    # lookup; this catches them too.
    try:
        import glob as _glob
        import os as _os

        import yaml as _yaml

        candidate_paths: list[str] = []
        candidate_paths.append(
            _os.path.join(hass.config.config_dir, "automations.yaml")
        )
        candidate_paths.append(
            _os.path.join(hass.config.config_dir, "configuration.yaml")
        )
        # Common packages directory pattern. We don't try to read
        # arbitrary user-customised layouts — those are rare and the
        # warning banner explains the limitation.
        for p in _glob.glob(
            _os.path.join(hass.config.config_dir, "packages", "*.yaml")
        ):
            candidate_paths.append(p)
        for p in _glob.glob(
            _os.path.join(hass.config.config_dir, "packages", "**", "*.yaml"),
            recursive=True,
        ):
            candidate_paths.append(p)

        seen_paths: set[str] = set()
        for path in candidate_paths:
            if path in seen_paths or not _os.path.exists(path):
                continue
            seen_paths.add(path)
            try:
                with open(path, encoding="utf-8") as f:
                    loaded = _yaml.safe_load(f)
            except Exception:
                continue
            # Top-level automations.yaml ships a list directly.
            # configuration.yaml / packages have `automation:` as a key.
            candidates: list = []
            if isinstance(loaded, list):
                candidates = loaded
            elif isinstance(loaded, dict):
                auto_block = loaded.get("automation")
                if isinstance(auto_block, list):
                    candidates = auto_block
                elif isinstance(auto_block, dict):
                    candidates = [auto_block]
                else:
                    # Treat the top-level dict itself as a candidate
                    candidates = [loaded]
            for entry in candidates:
                if not isinstance(entry, dict):
                    continue
                if (
                    str(entry.get("id")) == automation_id
                    or entry.get("alias") == automation_id
                ):
                    return entry
    except Exception:
        pass
    return None


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


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/refine_automation",
        vol.Required("automation_id"): str,
        vol.Required("feedback"): str,
        vol.Optional("agent_id"): vol.Any(str, None),
        vol.Optional("conversation_id"): vol.Any(str, None),
        vol.Optional("analysis_depth"): vol.In(["concise", "indepth"]),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_refine_automation(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Run an existing automation through the LLM refine pipeline."""
    from datetime import UTC, datetime

    from ..config_flow import get_blocked_entities
    from ..insight import Insight, InsightKind
    from ..llm import RedactionMode, Redactor, refine_insight

    automation_id = msg["automation_id"]
    raw = await hass.async_add_executor_job(
        _find_automation_by_id, hass, automation_id
    )
    if raw is None:
        connection.send_error(
            msg["id"],
            "not_found",
            f"No automation with id/alias {automation_id!r}",
        )
        return
    # Sanitize the raw_config dict so PyYAML.safe_dump can serialize
    # it downstream (HA injects Template / Selector / etc. objects
    # PyYAML can't represent → RepresenterError otherwise).
    raw = _sanitize_yaml_safe(raw)

    virtual_fingerprint = {
        "automation_id": automation_id,
        "kind": "existing_automation_refinement",
    }
    virtual_insight = Insight(
        id=Insight.compute_id(
            InsightKind.AUTOMATION_PROPOSAL, virtual_fingerprint
        ),
        kind=InsightKind.AUTOMATION_PROPOSAL,
        detector="user_refine",
        area_id=None,
        title=(
            "Refine existing automation: "
            f"{raw.get('alias') or automation_id}"
        ),
        confidence=1.0,
        fingerprint=virtual_fingerprint,
        payload=raw,
        payload_format="automation",
        created_at=datetime.now(tz=UTC),
    )

    store = _get_store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_set_up", "Store not initialized")
        return

    blocked = _resolve_blocked_entities(hass, get_blocked_entities)
    redactor = Redactor(
        store, mode=RedactionMode.AGGRESSIVE, blocked_entities=blocked
    )
    preferred = _resolve_preferred_agent_id(hass)

    # Wrap the user's request with the regression-aware principles.
    # First turn gets the full preamble; follow-ups within the same
    # conversation_id get a lighter touch since the LLM remembers
    # the principles from turn 1.
    depth = _resolve_audit_depth(hass, msg.get("analysis_depth"))
    wrapped_feedback = _wrap_user_feedback(
        msg["feedback"],
        conversation_turn=1 if msg.get("conversation_id") else 0,
        depth=depth,
    )
    try:
        result = await refine_insight(
            hass,
            agent_id=msg.get("agent_id"),
            insight=virtual_insight,
            redactor=redactor,
            feedback=wrapped_feedback,
            preferred_agent_id=preferred,
        )
    except Exception as err:
        connection.send_error(
            msg["id"], "refine_failed", _humanize_llm_error(str(err))
        )
        return

    if not result.success or result.refined_payload is None:
        connection.send_error(
            msg["id"],
            "refine_failed",
            _humanize_llm_error(
                result.error or "LLM refinement returned no payload"
            ),
        )
        return

    try:
        import yaml as _yaml

        refined_yaml = _yaml.safe_dump(
            result.refined_payload,
            sort_keys=False,
            default_flow_style=False,
        )
        original_yaml = _yaml.safe_dump(
            raw, sort_keys=False, default_flow_style=False
        )
    except Exception:
        refined_yaml = str(result.refined_payload)
        original_yaml = str(raw)

    await _audit_attempts(
        store, result.attempts, insight_id=virtual_insight.id, redactor=redactor
    )

    connection.send_result(
        msg["id"],
        {
            "automation_id": automation_id,
            "alias": raw.get("alias"),
            "original_yaml": original_yaml,
            "refined_yaml": refined_yaml,
            "refined_config": result.refined_payload,
            "rationale": result.rationale,
            "diff_summary": result.diff_summary,
            "bytes_sent": result.bytes_sent,
            "bytes_received": result.bytes_received,
            "chosen_agent_id": result.chosen_agent_id,
            "conversation_id": result.conversation_id,
            "attempts": (
                [_attempt_to_dict(a) for a in result.attempts]
                if result.attempts else []
            ),
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/apply_automation_refinement",
        vol.Required("automation_id"): str,
        vol.Required("refined_config"): dict,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_apply_automation_refinement(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Write the refined automation YAML back to disk + reload."""
    from ..apply.automation_writer import AutomationWriter

    automation_id = msg["automation_id"]
    refined = msg["refined_config"]
    if not isinstance(refined, dict):
        connection.send_error(
            msg["id"],
            "bad_payload",
            "refined_config must be an automation dict",
        )
        return

    writer = AutomationWriter(hass)
    try:
        await writer.write(refined, auto_id=automation_id)
    except Exception as err:
        connection.send_error(msg["id"], "write_failed", str(err))
        return

    connection.send_result(
        msg["id"],
        {
            "automation_id": automation_id,
            "applied": True,
            "url": f"/config/automation/edit/{automation_id}",
        },
    )


# ---------------------------------------------------------------------------
# AutomationAudit Phase C — LLM suggest for "report"-format audit insights
# ---------------------------------------------------------------------------


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/audit_suggest",
        vol.Required("insight_id"): str,
        vol.Optional("analysis_depth"): vol.In(["concise", "indepth"]),
        # Two-stage refinement: when present, use this dict as the
        # starting YAML instead of the original automation. Pattern:
        # user clicks 📋 Preview on a deterministic audit, then asks
        # the LLM to further-refine the algorithm's output. The card
        # passes the algorithm's refined config here. Server prompt
        # frames it as "here is the YAML AFTER our deterministic
        # fixes; further-refine based on the observations + the
        # user's extra feedback."
        vol.Optional("seed_config"): dict,
        vol.Optional("extra_feedback"): str,
    }
)
@websocket_api.async_response
async def ws_audit_suggest(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Run an audit insight through the LLM refine pipeline to get
    concrete YAML edits. Only meaningful for audit insights whose
    payload_format is "report" — automation-format insights already
    have a deterministic refined YAML and ship with Apply directly.

    Pipeline:
      1. Load the audit insight from the store
      2. Check the content-hash cache (skip LLM on hit)
      3. Build a virtual Insight using the underlying automation YAML
      4. Synthesize "feedback" text from the observations
      5. Run through refine_insight (existing redactor + agent
         failover + audit log)
      6. Cache the result + return refined YAML / rationale / diff

    Privacy: same Redactor and same audit log as ws_refine_automation.
    No bespoke LLM path here — we reuse the proven pipeline.
    """
    from datetime import UTC
    from datetime import datetime as _dt

    from ..audit.cache import (
        CachedSuggestion,
        compute_cache_key,
    )
    from ..audit.cache import (
        get as cache_get,
    )
    from ..audit.cache import (
        put as cache_put,
    )
    from ..config_flow import get_blocked_entities
    from ..insight import Insight, InsightKind
    from ..llm import RedactionMode, Redactor, refine_insight

    insight_id = msg["insight_id"]
    store = _get_store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_set_up", "Store not initialized")
        return
    audit_insight = await store.get_insight(insight_id)
    if audit_insight is None:
        connection.send_error(
            msg["id"], "not_found", f"No audit insight with id {insight_id}"
        )
        return
    if audit_insight.detector != "automation_audit":
        connection.send_error(
            msg["id"],
            "wrong_kind",
            "audit_suggest only works on automation_audit insights",
        )
        return

    payload = audit_insight.payload or {}
    # Deterministic-fix audits (payload_format="automation") put the
    # refined YAML at the top level and stash audit metadata under
    # `_audit`. Report-format audits put automation_id + observations
    # at the top level. Handle BOTH shapes so the LLM-refine-further
    # flow off a 📋 Preview works.
    audit_meta = (
        payload.get("_audit") if isinstance(payload.get("_audit"), dict) else {}
    )
    automation_id = (
        payload.get("automation_id")
        or audit_meta.get("automation_id")
    )
    observations = (
        payload.get("observations")
        or audit_meta.get("observations")
        or []
    )
    if not automation_id:
        connection.send_error(
            msg["id"], "incomplete", "Audit insight is missing automation_id"
        )
        return

    # Load the current automation YAML from HA — the audit insight's
    # payload may be stale by the time the user clicks.
    raw = await hass.async_add_executor_job(
        _find_automation_by_id, hass, automation_id
    )
    if raw is None:
        connection.send_error(
            msg["id"],
            "not_found",
            f"No automation with id/alias {automation_id!r}",
        )
        return
    # Sanitize the raw_config dict so PyYAML.safe_dump can serialize
    # it downstream (HA injects Template / Selector / etc. objects
    # PyYAML can't represent → RepresenterError otherwise).
    raw = _sanitize_yaml_safe(raw)

    # Two-stage refinement: if the caller passed a seed_config (the
    # algorithm's already-refined YAML from a 📋 Preview), use THAT
    # as the starting point. The LLM further-refines it instead of
    # re-doing what the deterministic stage already handled. Saves
    # tokens, prevents the LLM from undoing safe edits.
    seed_config_raw = msg.get("seed_config")
    use_seed = isinstance(seed_config_raw, dict) and seed_config_raw
    if use_seed:
        starting_payload = _sanitize_yaml_safe(seed_config_raw)
        # Strip out any audit metadata the card may have left in
        # before sending — we don't want it inside the YAML sent to
        # the LLM.
        if isinstance(starting_payload, dict):
            starting_payload.pop("_audit", None)
    else:
        starting_payload = raw

    # Cache lookup. Cache key uses the EFFECTIVE starting payload so
    # a two-stage call with a different seed gets its own cache slot.
    observation_kinds = [o.get("kind", "") for o in observations]
    cache_extras = list(observation_kinds)
    extra_feedback = msg.get("extra_feedback") or ""
    if extra_feedback:
        cache_extras.append(f"extra_fb:{extra_feedback[:200]}")
    if use_seed:
        cache_extras.append("stage:two")
    # integration_version invalidates cached refinements when the
    # prompt logic / detector behavior changes in a new release.
    _iv = await _get_integration_version(hass)
    cache_key = compute_cache_key(starting_payload, cache_extras, _iv)
    cached = cache_get(cache_key)
    if isinstance(cached, CachedSuggestion):
        try:
            import yaml as _yaml

            cached_original = _yaml.safe_dump(
                starting_payload, sort_keys=False, default_flow_style=False
            )
            cached_refined = _yaml.safe_dump(
                cached.refined_yaml,
                sort_keys=False,
                default_flow_style=False,
            )
        except Exception:
            cached_original = str(starting_payload)
            cached_refined = str(cached.refined_yaml)
        connection.send_result(
            msg["id"],
            {
                "automation_id": automation_id,
                "alias": starting_payload.get("alias")
                if isinstance(starting_payload, dict)
                else None,
                "refined_config": cached.refined_yaml,
                "original_yaml": cached_original,
                "refined_yaml": cached_refined,
                "rationale": cached.rationale,
                "diff_summary": cached.diff_summary,
                "cached": True,
                "stage_two": use_seed,
                "bytes_sent": 0,
                "bytes_received": 0,
            },
        )
        return

    # Build the virtual insight + feedback text from observations.
    virtual_fingerprint = {
        "automation_id": automation_id,
        "kind": "automation_audit_suggest",
    }
    virtual_insight = Insight(
        id=Insight.compute_id(
            InsightKind.AUTOMATION_PROPOSAL, virtual_fingerprint
        ),
        kind=InsightKind.AUTOMATION_PROPOSAL,
        detector="user_audit",
        area_id=None,
        title=(
            "Refine existing automation based on audit findings: "
            f"{(starting_payload or {}).get('alias') if isinstance(starting_payload, dict) else automation_id}"  # noqa: E501
        ),
        confidence=1.0,
        fingerprint=virtual_fingerprint,
        payload=starting_payload,
        payload_format="automation",
        created_at=_dt.now(tz=UTC),
    )

    # Build via the use-case-aware helper. Per-observation-kind
    # hints + shared regression principles + dynamic "all
    # context-only" early-exit framing all live in one place.
    #
    # Stage-two calls force depth=concise to leave more output token
    # headroom for the model. Stage-two prompts re-include the YAML
    # (the algorithm's output), and Gemini's default max_output_tokens
    # is small enough that re-emitting a full YAML + verbose rationale
    # hits MAX_TOKENS. Concise principles are sufficient — the user
    # is iterating; they've already seen the rules once.
    depth = _resolve_audit_depth(hass, msg.get("analysis_depth"))
    effective_depth = "concise" if use_seed else depth
    feedback = _build_audit_feedback(observations, depth=effective_depth)
    if use_seed:
        # Frame the second-stage call: the LLM is iterating on the
        # algorithm's output, not starting from scratch.
        feedback = (
            "STAGE TWO. The YAML has already been fixed by our "
            "deterministic stage — build on it, don't undo it. "
            "Output the refined YAML and a 1-2 sentence rationale.\n\n"
            + feedback
        )
    if extra_feedback.strip():
        feedback += (
            "\n\nUSER ADDITIONAL REQUEST:\n"
            + extra_feedback.strip()
        )

    blocked = _resolve_blocked_entities(hass, get_blocked_entities)
    redactor = Redactor(
        store, mode=RedactionMode.AGGRESSIVE, blocked_entities=blocked
    )
    preferred = _resolve_preferred_agent_id(hass)

    try:
        result = await refine_insight(
            hass,
            agent_id=msg.get("agent_id"),
            insight=virtual_insight,
            redactor=redactor,
            feedback=feedback,
            preferred_agent_id=preferred,
        )
    except Exception as err:
        connection.send_error(
            msg["id"], "refine_failed", _humanize_llm_error(str(err))
        )
        return

    if not result.success or result.refined_payload is None:
        connection.send_error(
            msg["id"],
            "refine_failed",
            _humanize_llm_error(
                result.error or "LLM refinement returned no payload"
            ),
        )
        return

    # Cache + audit log.
    cache_put(
        cache_key,
        refined_yaml=result.refined_payload,
        rationale=result.rationale,
        diff_summary=result.diff_summary,
    )
    await _audit_attempts(
        store, result.attempts, insight_id=virtual_insight.id, redactor=redactor
    )

    # Render both sides as proper YAML so the side-by-side diff
    # is readable. JSON looks like garbage in a YAML context;
    # the user expects what they'd see in HA's automation editor.
    # For stage-two calls the "original" is the algorithm's output
    # (starting_payload), not the raw automation — that's what the
    # user is comparing the LLM's further-refinement against.
    diff_baseline = starting_payload if use_seed else raw
    try:
        import yaml as _yaml

        original_yaml_str = _yaml.safe_dump(
            diff_baseline, sort_keys=False, default_flow_style=False
        )
        refined_yaml_str = _yaml.safe_dump(
            result.refined_payload,
            sort_keys=False,
            default_flow_style=False,
        )
    except Exception:
        original_yaml_str = str(diff_baseline)
        refined_yaml_str = str(result.refined_payload)

    connection.send_result(
        msg["id"],
        {
            "automation_id": automation_id,
            "alias": raw.get("alias"),
            "refined_config": result.refined_payload,
            "original_yaml": original_yaml_str,
            "refined_yaml": refined_yaml_str,
            "rationale": result.rationale,
            "diff_summary": result.diff_summary,
            "cached": False,
            "bytes_sent": result.bytes_sent,
            "bytes_received": result.bytes_received,
            "chosen_agent_id": result.chosen_agent_id,
            "conversation_id": result.conversation_id,
            "attempts": (
                [_attempt_to_dict(a) for a in result.attempts]
                if result.attempts else []
            ),
        },
    )


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


# ---------- v1.7.7: per-device "managed externally" flag ------------------


def _managed_devices_set(entry) -> set[str]:
    """Read the user's current managed-externally device set."""
    from ..config_flow import CONF_MANAGED_EXTERNALLY_DEVICES

    raw = entry.options.get(CONF_MANAGED_EXTERNALLY_DEVICES, [])
    if not isinstance(raw, (list, tuple, set)):
        return set()
    return {d for d in raw if isinstance(d, str)}


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/list_managed_devices",
    }
)
@websocket_api.async_response
async def ws_list_managed_devices(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return currently-flagged devices with name + entity count.

    Admin-only. Used by the card's per-device toggle UI and the
    OptionsFlow management screen.
    """
    if not _require_admin(hass, connection, msg):
        return
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        connection.send_error(msg["id"], "no_entry", "No HA Insights entry")
        return
    entry = entries[0]
    flagged = _managed_devices_set(entry)
    if not flagged:
        connection.send_result(msg["id"], {"devices": []})
        return
    try:
        from homeassistant.helpers import device_registry as dr
        from homeassistant.helpers import entity_registry as er

        d_reg = dr.async_get(hass)
        e_reg = er.async_get(hass)
        entity_counts: dict[str, int] = {}
        for ent in e_reg.entities.values():
            if ent.device_id:
                entity_counts[ent.device_id] = entity_counts.get(ent.device_id, 0) + 1
        out: list[dict[str, Any]] = []
        for device_id in sorted(flagged):
            device = d_reg.async_get(device_id)
            if device is None:
                # Device deleted from HA but still in our flag list —
                # surface so the user can clean it up.
                out.append({
                    "device_id": device_id,
                    "name": f"<deleted: {device_id[:8]}…>",
                    "entity_count": 0,
                    "deleted": True,
                })
                continue
            out.append({
                "device_id": device_id,
                "name": device.name_by_user or device.name or device_id[:8],
                "manufacturer": device.manufacturer,
                "model": device.model,
                "entity_count": entity_counts.get(device_id, 0),
                "deleted": False,
            })
        connection.send_result(msg["id"], {"devices": out})
    except Exception as err:
        _LOGGER.exception("list_managed_devices failed")
        connection.send_error(msg["id"], "list_failed", str(err))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/set_device_managed",
        vol.Required("device_id"): str,
        vol.Required("managed"): bool,
    }
)
@websocket_api.async_response
async def ws_set_device_managed(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Add or remove a device from the managed-externally set.

    Admin-only. Returns the updated set. Idempotent — adding an
    already-flagged device or removing an absent one is a no-op.
    """
    if not _require_admin(hass, connection, msg):
        return
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        connection.send_error(msg["id"], "no_entry", "No HA Insights entry")
        return
    entry = entries[0]
    device_id = msg["device_id"]
    managed = msg["managed"]
    flagged = _managed_devices_set(entry)
    if managed:
        flagged.add(device_id)
    else:
        flagged.discard(device_id)
    from ..config_flow import CONF_MANAGED_EXTERNALLY_DEVICES

    merged_options = dict(entry.options)
    merged_options[CONF_MANAGED_EXTERNALLY_DEVICES] = sorted(flagged)
    hass.config_entries.async_update_entry(entry, options=merged_options)
    connection.send_result(
        msg["id"],
        {"managed_devices": sorted(flagged)},
    )


# v1.13.4 — Find My Device handlers (ws_identify_capability,
# ws_identify_entity, ws_perturbation_guide, ws_perturbation_test +
# the _collect_ip_attrs_for_candidates helper) moved to ws_api/identify.py
# during the v1.13 refactor (step 2). They are imported at the top of
# this module and registered via async_register below; this comment
# stub preserves the section boundary for future readers.


# v1.12 — BLE live-find ------------------------------------------------


def _ble_proxy_label(service_info: Any) -> str:
    """Render a BLE service_info into a short proxy label for the UI."""
    src = getattr(service_info, "source", None)
    if isinstance(src, str) and src:
        return src
    return "unknown"


def _seen_proxies_for(hass: HomeAssistant, address: str) -> list[str]:
    """Return labels of every BLE scanner currently seeing this
    address. Empty list when bluetooth integration isn't loaded or
    nothing's observing the device."""
    try:
        from homeassistant.components.bluetooth import (
            async_scanner_devices_by_address,
        )
    except ImportError:
        return []
    try:
        devices = async_scanner_devices_by_address(
            hass, address, connectable=False
        )
    except Exception:
        return []
    labels = [_ble_proxy_label(d) for d in devices]
    # Dedup while preserving order.
    seen = set()
    out: list[str] = []
    for label in labels:
        if label not in seen:
            out.append(label)
            seen.add(label)
    return out


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/ble_capability",
        vol.Required("entity_ids"): [str],
    }
)
@websocket_api.async_response
async def ws_ble_capability(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Batch BLE-capability query for the card.

    Mirrors `identify_capability` — read-only, not admin-gated.
    Card calls this once per dialog open to know which entities can
    show the 📡 BLE live-find button.

    Response per entity:
      {
        "is_trackable": true,
        "bluetooth_address": "AA:BB:CC:DD:EE:FF",
        "seen_by_proxies": ["esphome_kitchen_proxy", ...],
        "reason": "...",
      }
    """
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    from ..lib.ble_capability import ble_capability_for

    e_reg = er.async_get(hass)
    d_reg = dr.async_get(hass)

    capabilities: dict[str, dict[str, Any]] = {}
    for eid in msg["entity_ids"]:
        if not isinstance(eid, str):
            continue
        # Pull device connections from the registry.
        connections: list[tuple[str, str]] = []
        attrs: dict[str, Any] = {}
        er_ent = e_reg.async_get(eid)
        if er_ent is not None and er_ent.device_id is not None:
            dev = d_reg.async_get(er_ent.device_id)
            if dev is not None:
                connections = [
                    (t, v) for t, v in (dev.connections or set())
                ]
        state = hass.states.get(eid)
        if state is not None:
            attrs = dict(state.attributes)

        # First pass: get the address (proxies require an address).
        partial = ble_capability_for(
            eid,
            device_connections=connections,
            state_attributes=attrs,
            seen_by_proxies=None,
        )
        seen: list[str] = []
        if partial.bluetooth_address is not None:
            seen = _seen_proxies_for(hass, partial.bluetooth_address)
        # Re-evaluate with proxies so the `reason` reflects them.
        cap = ble_capability_for(
            eid,
            device_connections=connections,
            state_attributes=attrs,
            seen_by_proxies=seen,
        )
        capabilities[eid] = {
            "is_trackable": cap.is_trackable,
            "bluetooth_address": cap.bluetooth_address,
            "seen_by_proxies": list(cap.seen_by_proxies),
            "reason": cap.reason,
        }
    connection.send_result(msg["id"], {"capabilities": capabilities})


# EMA smoothing for live RSSI. alpha=0.3 gives an effective ~3s
# window at the typical 1Hz BLE advertisement rate — fast enough to
# track user movement, slow enough to kill multipath jitter.
_BLE_EMA_ALPHA: float = 0.3


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/ble_live_find",
        vol.Required("bluetooth_address"): str,
    }
)
@websocket_api.async_response
async def ws_ble_live_find(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Streaming RSSI subscription for the BLE live-find UI.

    Opens a server-side BLE advertisement callback for the given
    address. Each advertisement received forwards an event message
    to the WS client with raw + EMA-smoothed RSSI + which proxy
    saw it. Auto-unsubscribes when the WS connection closes or the
    client sends `unsubscribe_events`.

    Admin-gated — streaming subscriptions tie up server resources
    and the address parameter could leak fingerprint info about
    devices the user doesn't own.
    """
    if not _require_admin(hass, connection, msg):
        return

    try:
        from homeassistant.components.bluetooth import (
            BluetoothCallbackMatcher,
            BluetoothChange,
            async_register_callback,
        )
    except ImportError:
        connection.send_error(
            msg["id"],
            "no_bluetooth",
            "Home Assistant's bluetooth integration is not available "
            "in this install. Install and configure it (Settings → "
            "Devices & Services → Add Integration → Bluetooth) to "
            "enable BLE live-find.",
        )
        return

    raw_address = msg["bluetooth_address"]
    if not isinstance(raw_address, str) or len(raw_address) < 12:
        connection.send_error(
            msg["id"], "bad_address", "bluetooth_address looks invalid."
        )
        return
    address = raw_address.upper().replace("-", ":").replace("_", ":")

    # Per-subscription state (kept in this closure; cleaned up via
    # the cancel callback HA assigns when the WS unsubscribes).
    ema_state: dict[str, float | None] = {"value": None}

    @callback
    def _on_advertisement(
        service_info: Any,
        change: Any,
    ) -> None:
        # `change` is the BluetoothChange enum value; we don't act on
        # it here (we accept ADVERTISEMENT only via the registration
        # filter), but the callback signature requires it.
        del change
        if not hasattr(service_info, "address"):
            return
        if service_info.address.upper() != address:
            return
        try:
            raw_rssi = float(service_info.rssi)
        except (TypeError, AttributeError, ValueError):
            return
        prev = ema_state["value"]
        if prev is None:
            ema = raw_rssi
        else:
            ema = _BLE_EMA_ALPHA * raw_rssi + (1.0 - _BLE_EMA_ALPHA) * prev
        ema_state["value"] = ema
        connection.send_event(
            msg["id"],
            {
                "rssi_raw": int(raw_rssi),
                "rssi_smoothed": round(ema, 1),
                "scanner": _ble_proxy_label(service_info),
            },
        )

    try:
        cancel = async_register_callback(
            hass,
            _on_advertisement,
            BluetoothCallbackMatcher(address=address),
            BluetoothChange.ADVERTISEMENT,
        )
    except Exception as err:
        connection.send_error(
            msg["id"],
            "subscribe_failed",
            f"Could not subscribe to BLE advertisements: {err}",
        )
        return

    # Confirm the subscription is live; HA's WS framework calls our
    # `cancel` when the client unsubscribes or the connection drops.
    connection.subscriptions[msg["id"]] = cancel
    connection.send_result(msg["id"])


# v1.13.2 — Blank-canvas automation chat -----------------------------


# Skeleton "virtual insight" payload the LLM refines. Empty trigger
# + condition + action mean the LLM is free to populate everything;
# alias/mode placeholders give it a structural reference. Schema
# matches what apply_automation expects.
_CHAT_AUTOMATION_SKELETON: dict[str, Any] = {
    "alias": "New automation",
    "description": "",
    "mode": "single",
    "trigger": [],
    "condition": [],
    "action": [],
}


def _build_chat_feedback(
    user_prompt: str,
    related_insights: list[Any],
) -> str:
    """Compose the LLM feedback string from the user's free-form
    prompt plus any related insight context the caller passed.

    Related insights are surfaced as "I previously detected …"
    paragraphs so the LLM can ground YAML on the user's actual
    behaviour, not just the prose request. Each insight contributes
    its title + payload summary; full payloads aren't included
    because the redactor would have to walk them and a 5-insight
    bundle would blow the LLM token budget.
    """
    parts: list[str] = []
    parts.append(
        "The user has asked you to write a new Home Assistant automation. "
        "Their request is below. Produce a complete YAML automation "
        "that matches what they described — fill in all of trigger, "
        "condition, action, alias, mode. Use real entity_ids only if "
        "the user mentioned them by name."
    )
    parts.append(f"\nUser request:\n{user_prompt.strip()}")
    if related_insights:
        ctx_lines: list[str] = []
        for ins in related_insights[:5]:  # cap at 5 to bound tokens
            title = getattr(ins, "title", None) or ""
            confidence = getattr(ins, "confidence", 0.0)
            detector = getattr(ins, "detector", "")
            line = f"  - {title}"
            if confidence:
                line += f" (confidence {confidence:.2f}"
                if detector:
                    line += f" via {detector}"
                line += ")"
            ctx_lines.append(line)
        if ctx_lines:
            parts.append(
                "\nRelevant patterns I previously detected in this "
                "user's home (you may use these to ground the automation, "
                "but only if they match what the user asked):\n"
                + "\n".join(ctx_lines)
            )
    return "\n".join(parts)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/chat_create_automation",
        vol.Required("prompt"): vol.All(str, vol.Length(min=1, max=2000)),
        vol.Optional("agent_id"): vol.Any(str, None),
        vol.Optional("conversation_id"): vol.Any(str, None),
        vol.Optional("related_insight_ids", default=list): [str],
        vol.Optional("analysis_depth"): vol.In(["concise", "indepth"]),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_chat_create_automation(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Generate an automation YAML from a free-form user prompt.

    Closes the AI Agent HA competitive gap (May 2026 analysis). User
    types "turn on porch light at sunset" → we return YAML the card
    previews before applying via the existing `home_insights/apply`
    flow.

    Differentiator vs AI Agent HA: callers can pass
    `related_insight_ids` to surface high-confidence existing
    insights as LLM context. The card can pre-populate this from
    its current list view — e.g. "make me an automation for the
    pattern in insight schedule_porch_light_18:30" passes that
    insight's id so the LLM has both prose + concrete observed
    behaviour.

    Re-uses the existing `refine_insight` pipeline (same redactor,
    same Conversation-agent failover, same audit trail). Failures
    propagate through `_humanize_llm_error` so the card surfaces
    user-readable errors not stack traces.

    Privacy: full audit row per attempt via `_audit_attempts`,
    matching ws_refine + ws_refine_automation.
    """
    from datetime import UTC, datetime

    from ..config_flow import get_blocked_entities
    from ..insight import Insight, InsightKind
    from ..llm import RedactionMode, Redactor, refine_insight

    user_prompt: str = msg["prompt"]

    store = _get_store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_set_up", "Store not initialized")
        return

    # Resolve related insights for context. Bad / missing ids are
    # tolerated — silently dropped rather than failing the chat call.
    related_insights: list[Any] = []
    for ins_id in msg.get("related_insight_ids") or []:
        try:
            ins = await store.get_insight(ins_id)
        except Exception:
            ins = None
        if ins is not None:
            related_insights.append(ins)

    # Build a virtual insight wrapping the empty automation skeleton.
    # Same shape `ws_refine_automation` uses for refining existing
    # automations — the only difference is the skeleton payload vs
    # a populated raw_config.
    virtual_fingerprint = {
        "kind": "chat_create_automation",
        # Prompt hash isn't needed — every chat call gets a fresh
        # virtual id via the timestamp inside compute_id below.
        "timestamp_micros": int(datetime.now(tz=UTC).timestamp() * 1_000_000),
    }
    virtual_insight = Insight(
        id=Insight.compute_id(
            InsightKind.AUTOMATION_PROPOSAL, virtual_fingerprint,
        ),
        kind=InsightKind.AUTOMATION_PROPOSAL,
        detector="chat",
        area_id=None,
        title=(
            "Chat-created automation: " + (user_prompt[:80].strip() or "untitled")
        ),
        confidence=1.0,
        fingerprint=virtual_fingerprint,
        payload=dict(_CHAT_AUTOMATION_SKELETON),
        payload_format="automation",
        created_at=datetime.now(tz=UTC),
    )

    blocked = _resolve_blocked_entities(hass, get_blocked_entities)
    redactor = Redactor(
        store, mode=RedactionMode.AGGRESSIVE, blocked_entities=blocked,
    )
    preferred = _resolve_preferred_agent_id(hass)

    depth = _resolve_audit_depth(hass, msg.get("analysis_depth"))
    feedback = _wrap_user_feedback(
        _build_chat_feedback(user_prompt, related_insights),
        conversation_turn=1 if msg.get("conversation_id") else 0,
        depth=depth,
    )

    try:
        result = await refine_insight(
            hass,
            agent_id=msg.get("agent_id"),
            insight=virtual_insight,
            redactor=redactor,
            feedback=feedback,
            preferred_agent_id=preferred,
            conversation_id=msg.get("conversation_id"),
        )
    except Exception as err:
        connection.send_error(
            msg["id"], "chat_failed", _humanize_llm_error(str(err)),
        )
        return

    # Audit every attempt so failover round-trips appear in the
    # privacy log — matches ws_refine + ws_refine_automation.
    await _audit_attempts(
        store, result.attempts, insight_id=virtual_insight.id,
        redactor=redactor,
    )

    if not result.success or result.refined_payload is None:
        detail = result.error or "Chat-create returned no automation"
        if result.raw_response:
            snippet = result.raw_response.strip()
            if len(snippet) > 600:
                snippet = snippet[:600] + "…"
            detail = f"{detail}\n\nLLM said:\n{snippet}"
        connection.send_error(
            msg["id"], "chat_failed", _humanize_llm_error(detail),
        )
        return

    connection.send_result(
        msg["id"],
        {
            "refined_payload": result.refined_payload,
            "rationale": result.rationale,
            "diff_summary": result.diff_summary,
            "bytes_sent": result.bytes_sent,
            "bytes_received": result.bytes_received,
            "conversation_id": result.conversation_id,
            "related_insights_used": [
                {
                    "id": getattr(ins, "id", None),
                    "title": getattr(ins, "title", None),
                    "confidence": getattr(ins, "confidence", None),
                }
                for ins in related_insights
            ],
        },
    )
