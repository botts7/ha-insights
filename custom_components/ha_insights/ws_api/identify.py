"""WS handlers for the v1.10 Find My Device feature.

Four handlers + one helper, all related to making entities announce
themselves so the user can locate them physically:

  - ``ws_identify_capability`` — batch lookup. Returns each entity's
    available identify method (flash / brightness wiggle / strobe /
    chime / siren / switch toggle / NONE), name_quality score, dedup
    candidates, and perturbation eligibility. Read-only, **admin-gated**
    (response leaks the home's device topology).
  - ``ws_identify_entity`` — fires the identify signal for one entity.
    Chains the v1.10.9 critical-load keyword gate → v1.10.13 power-
    consumption gate → v1.10.11 device-graph LED substitution → v1.10.12
    vendor-native primitive → v1.10.9 BRIGHTNESS_WIGGLE / safe-strobe
    fallback. Power-cycling methods require explicit
    ``confirm_power_cycle=true``.
  - ``ws_perturbation_guide`` — returns the per-device_class touch-test
    instruction for the card.
  - ``ws_perturbation_test`` — opens a listening window, captures every
    state change on the candidates, runs z-score analysis, returns
    ranked result. Admin-gated.

Extracted from ``ws_api/__init__.py`` in v1.13.4 (step 2 of the v1.13
refactor) per the dependency-map memory finding that BLE / IDENTIFY /
MANAGED_DEVICES are the most-isolated handler groups (no cross-handler
coupling beyond the universal helpers in ``_helpers.py``). Imported
back into ``__init__`` for backwards-compat — handler names + the
``async_register`` registrations stay valid.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import callback

from ..const import DOMAIN
from ._helpers import _require_admin

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


# v1.10 Phase A — Find My Device: identify-capable orphans -------------


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/identify_capability",
        vol.Required("entity_ids"): [str],
    }
)
@websocket_api.async_response
async def ws_identify_capability(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return identify capabilities for a batch of entity_ids.

    **v1.12.7: now admin-gated.** The response leaks user-chosen
    friendly names (`name_quality.chosen_name`) AND the dedup
    `same_as` array (which exposes the home's device topology —
    which entities the system thinks are duplicates). A non-admin
    token shouldn't be able to enumerate either. Agent privacy
    review (2026-05-17) flagged this as the top regression
    introduced in v1.10.0; the fix is symmetric with
    `ws_set_device_managed` which has always been admin-only.

    Response shape:
      {
        "capabilities": {
          "<entity_id>": {
            "method": "flash_light" | "play_chime" | ... | "none",
            "description": "flash the light briefly",
            "supported": true,
            "name_quality": {
              "tier": "user_override" | "cloud" | ... | "mac_pattern",
              "score": 0.0-1.0,
              "chosen_name": "Kitchen Floor Lamp",
              "source": "tuya integration",
              "reason": "...",
            },
          },
          ...
        }
      }

    The `name_quality` block lets the card decide whether to even
    SHOW the 🔆 button. High-quality names ("Kitchen Floor Lamp")
    don't need identification — the user already knows what it is.
    Low-quality names ("ATC_a4c138") are exactly when 🔆 earns its
    keep.
    """
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    from ..lib.dedup_signals import (
        DeviceRecord,
        EntityRecord,
        find_dedup_candidates,
    )
    from ..lib.identify_capability import identify_capability_for
    from ..lib.name_quality import score_name_quality
    from ..lib.perturbation_capability import (
        is_perturbation_unsupported,
        perturbation_guide_for,
    )

    e_reg = er.async_get(hass)
    d_reg = dr.async_get(hass)

    # v1.10.3 — build the full entity/device projections ONCE so
    # find_dedup_candidates can do O(N) lookups per query entity
    # instead of O(N*M) registry scans.
    all_entity_records: dict[str, EntityRecord] = {}
    for er_ent in e_reg.entities.values():
        all_entity_records[er_ent.entity_id] = EntityRecord(
            entity_id=er_ent.entity_id,
            device_id=er_ent.device_id,
            original_name=er_ent.original_name,
        )
    all_device_records: dict[str, DeviceRecord] = {}
    for dev in d_reg.devices.values():
        all_device_records[dev.id] = DeviceRecord(
            device_id=dev.id,
            manufacturer=dev.manufacturer,
            model=dev.model,
            via_device_id=dev.via_device_id,
            connections=[(t, v) for t, v in (dev.connections or set())],
            identifiers=[(t, v) for t, v in (dev.identifiers or set())],
        )
    # Only collect state attributes for the requested entities + their
    # candidates' entities. Full-state collection would be wasteful
    # on huge installs.
    state_attrs: dict[str, dict[str, Any]] = {}

    entity_ids = msg["entity_ids"]
    capabilities: dict[str, dict[str, Any]] = {}
    for eid in entity_ids:
        if not isinstance(eid, str):
            continue
        state = hass.states.get(eid)
        snapshot: dict[str, Any] | None = None
        friendly_name: str | None = None
        if state is not None:
            snapshot = {"attributes": dict(state.attributes)}
            fn_attr = state.attributes.get("friendly_name")
            friendly_name = (
                fn_attr if isinstance(fn_attr, str) else None
            )
        cap = identify_capability_for(eid, snapshot)

        # Resolve registry data for name_quality scoring.
        er_entry = e_reg.async_get(eid)
        manufacturer: str | None = None
        model: str | None = None
        integration_domain: str | None = None
        name_by_user: str | None = None
        original_name: str | None = None
        if er_entry is not None:
            name_by_user = er_entry.name
            original_name = er_entry.original_name
            if er_entry.device_id is not None:
                dev = d_reg.async_get(er_entry.device_id)
                if dev is not None:
                    manufacturer = dev.manufacturer
                    model = dev.model
            # `platform` on EntityRegistryEntry is the integration
            # domain that created the entity.
            integration_domain = er_entry.platform

        nq = score_name_quality(
            eid,
            name_by_user=name_by_user,
            original_name=original_name,
            friendly_name=friendly_name,
            manufacturer=manufacturer,
            model=model,
            integration_domain=integration_domain,
        )

        # v1.10.3 — populate state_attrs lazily for this entity so
        # the IP/host signal can compare against others. Build only
        # the attrs we need — Map.get on missing is fine.
        if state is not None and eid not in state_attrs:
            ip_attr = state.attributes.get("ip_address")
            host_attr = state.attributes.get("host")
            if isinstance(ip_attr, str) or isinstance(host_attr, str):
                state_attrs[eid] = {
                    "ip_address": ip_attr,
                    "host": host_attr,
                }

        # Run dedup against the full registry projection. For the IP
        # signal to work bidirectionally we need state_attrs to also
        # cover the *candidate* side — populate any candidate that
        # has IP/host on its state. Cheap because we only touch each
        # state object once across the loop.
        dedup_candidates = find_dedup_candidates(
            eid,
            entity_records=all_entity_records,
            device_records=all_device_records,
            state_attributes=_collect_ip_attrs_for_candidates(
                hass, all_entity_records, eid, state_attrs
            ),
        )

        # v1.10.7 — surface device_class + perturbability so the card
        # doesn't have to maintain a parallel hardcoded list. Single
        # source of truth: lib/perturbation_capability.py.
        device_class_attr = (
            state.attributes.get("device_class") if state is not None else None
        )
        device_class = (
            device_class_attr.lower()
            if isinstance(device_class_attr, str)
            else None
        )
        perturbable = perturbation_guide_for(device_class) is not None
        perturbation_state: str
        if perturbable:
            perturbation_state = "supported"
        elif is_perturbation_unsupported(device_class):
            perturbation_state = "explicitly_unsupported"
        else:
            perturbation_state = "unknown"

        capabilities[eid] = {
            "method": cap.method.value,
            "description": cap.description,
            "supported": cap.method.value != "none",
            "device_class": device_class,
            "perturbable": perturbable,
            "perturbation_state": perturbation_state,
            "name_quality": {
                "tier": nq.tier.value,
                "score": nq.score,
                "chosen_name": nq.chosen_name,
                "source": nq.source,
                "reason": nq.reason,
            },
            "same_as": [
                {
                    "entity_id": c.entity_id,
                    "reason": c.reason,
                    "confidence": c.confidence,
                }
                for c in dedup_candidates
            ],
        }
    connection.send_result(msg["id"], {"capabilities": capabilities})


def _collect_ip_attrs_for_candidates(
    hass: HomeAssistant,
    entity_records: dict[str, Any],
    me_eid: str,
    cache: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Ensure the cache has IP/host attrs for ANY entity that might
    match `me_eid` via the IP signal. Cheap — only touches entities
    whose state object exists and exposes an IP/host attribute."""
    # If the query entity itself has no IP/host, no IP-based match is
    # possible — skip the work entirely.
    if me_eid not in cache:
        return cache
    for other_eid in entity_records:
        if other_eid == me_eid or other_eid in cache:
            continue
        other_state = hass.states.get(other_eid)
        if other_state is None:
            continue
        ip_attr = other_state.attributes.get("ip_address")
        host_attr = other_state.attributes.get("host")
        if isinstance(ip_attr, str) or isinstance(host_attr, str):
            cache[other_eid] = {
                "ip_address": ip_attr,
                "host": host_attr,
            }
    return cache


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/identify_entity",
        vol.Required("entity_id"): str,
        vol.Optional("confirm_power_cycle", default=False): bool,
    }
)
@websocket_api.async_response
async def ws_identify_entity(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Fire the identify signal for one entity.

    Admin-gated because this calls arbitrary HA services (light.turn_on,
    media_player.play_media, etc.) — a non-admin token shouldn't be
    able to toggle every switch in the house via this endpoint.

    Two safety gates apply before the service calls run:

    1. **Critical-load keyword match** — entities whose entity_id or
       friendly_name suggests a critical load (fridge, server, EV
       charger, medical device, etc.) are refused outright. See
       ``lib/critical_load_keywords.py`` for the full list. The user
       cannot override this gate; they must rename the entity or use
       a different identify path.
    2. **Power-cycle confirmation** — methods that cut power
       (STROBE_LIGHT, SWITCH_TOGGLE, SIREN_CHIRP) require
       ``confirm_power_cycle=True`` in the request. The card shows a
       confirmation dialog before sending this flag. This forces the
       user to acknowledge that the device will be cycled — important
       on unlabelled gear or shared infra.

    Returns ``{"method": "<method>", "calls_made": N}`` on success,
    ``requires_confirmation`` with method info if the user hasn't
    confirmed a power-cycle yet, or an error code on terminal failure.
    """
    if not _require_admin(hass, connection, msg):
        return

    from asyncio import sleep as _async_sleep

    from homeassistant.helpers import (
        device_registry as dr,
    )
    from homeassistant.helpers import (
        entity_registry as er,
    )

    from ..lib.critical_load_keywords import is_critical_load
    from ..lib.critical_load_power import (
        DEFAULT_POWER_THRESHOLD_W,
        is_critical_by_power,
    )
    from ..lib.device_alternative_identifier import (
        SiblingEntity,
        pick_alternative_identifier,
    )
    from ..lib.identify_capability import (
        IdentifyMethod,
        identify_capability_for,
    )
    from ..lib.vendor_identify_strategy import vendor_identify_strategy_for

    # Methods that interrupt power → require explicit user confirmation
    # each time. BRIGHTNESS_WIGGLE / FLASH_LIGHT / PLAY_CHIME don't
    # cut power and are always safe.
    _POWER_CYCLE_METHODS: frozenset[IdentifyMethod] = frozenset(
        {
            IdentifyMethod.STROBE_LIGHT,
            IdentifyMethod.SWITCH_TOGGLE,
            IdentifyMethod.SIREN_CHIRP,
        },
    )

    original_entity_id: str = msg["entity_id"]
    confirm_power_cycle: bool = bool(msg.get("confirm_power_cycle", False))
    state = hass.states.get(original_entity_id)
    if state is None:
        connection.send_error(
            msg["id"],
            "unknown_entity",
            f"No state found for {original_entity_id}",
        )
        return

    friendly = state.attributes.get("friendly_name")
    is_critical, matched_kw = is_critical_load(
        original_entity_id,
        friendly if isinstance(friendly, str) else None,
    )
    if is_critical:
        connection.send_error(
            msg["id"],
            "critical_load_refused",
            (
                f"Refused: {original_entity_id} matches critical-load keyword "
                f"'{matched_kw}'. Toggling this could disrupt a fridge, "
                "server, EV charger, medical device, or similar. If "
                "this is safe to cycle, rename the entity to remove "
                "the keyword."
            ),
        )
        return

    # v1.10.13: live power-consumption gate. Refuses entities whose
    # linked power sensor reports above the threshold — catches
    # unlabelled critical loads (cryptic Zigbee IDs powering fridges,
    # network gear with SKU names, etc.). Only checked on power-
    # cycling domains (switch / siren) — lights and media players
    # have safe identify paths regardless of load.
    original_domain = original_entity_id.split(".", 1)[0]
    if original_domain in {"switch", "siren"}:
        power_critical, watts, power_sensor = is_critical_by_power(
            hass, original_entity_id, threshold_w=DEFAULT_POWER_THRESHOLD_W,
        )
        if power_critical:
            connection.send_error(
                msg["id"],
                "critical_load_refused",
                (
                    f"Refused: {original_entity_id} is currently drawing "
                    f"{watts:.0f} W (sensor {power_sensor}). Above the "
                    f"{DEFAULT_POWER_THRESHOLD_W:.0f} W safety gate — "
                    "this likely powers a fridge, server, EV charger, or "
                    "other load-carrying device. If this is safe to cycle, "
                    "the linked power sensor should drop below the gate "
                    "first."
                ),
            )
            return

    # v1.10.11: try to substitute the user's relay/contactor entity
    # for a safer same-device sibling (status LED, diagnostic light)
    # when one exists. Tesla Wall Connector / Shelly Plus 1 /
    # Sonoff with built-in LEDs all benefit — we flash the LED
    # instead of cycling the contactor / relay.
    substitution: dict[str, str] | None = None
    entity_id = original_entity_id
    try:
        registry = er.async_get(hass)
        original_entry = registry.async_get(original_entity_id)
    except Exception:
        original_entry = None
    if original_entry is not None and original_entry.device_id:
        sibling_pool: list[SiblingEntity] = []
        for entry in registry.entities.values():
            if entry.device_id != original_entry.device_id:
                continue
            if entry.entity_id == original_entity_id:
                continue
            sibling_state = hass.states.get(entry.entity_id)
            sibling_friendly: str | None = None
            if sibling_state is not None:
                fn = sibling_state.attributes.get("friendly_name")
                if isinstance(fn, str):
                    sibling_friendly = fn
            sibling_domain = entry.entity_id.split(".", 1)[0]
            cat_val = (
                entry.entity_category.value
                if entry.entity_category is not None
                else None
            )
            sibling_pool.append(
                SiblingEntity(
                    entity_id=entry.entity_id,
                    domain=sibling_domain,
                    friendly_name=sibling_friendly,
                    entity_category=cat_val,
                ),
            )
        alt = pick_alternative_identifier(original_entity_id, sibling_pool)
        if alt is not None and hass.states.get(alt.entity_id) is not None:
            # Re-check critical-load on the substitute — defensive,
            # an LED named "fridge_led" would be safe to cycle but
            # the rule is consistent.
            alt_state = hass.states.get(alt.entity_id)
            alt_friendly = (
                alt_state.attributes.get("friendly_name")
                if alt_state is not None
                else None
            )
            alt_critical, _ = is_critical_load(
                alt.entity_id,
                alt_friendly if isinstance(alt_friendly, str) else None,
            )
            if not alt_critical:
                entity_id = alt.entity_id
                state = alt_state  # use substitute's state for capability lookup
                substitution = {
                    "from": original_entity_id,
                    "to": alt.entity_id,
                    "reason": alt.reason,
                    "rule": alt.rule,
                }

    # v1.10.12: try vendor-native identify primitive first. ZHA's
    # Zigbee Identify cluster, Z-Wave Indicator CC, LIFX pulse,
    # Yeelight flow — all safer than our generic toggle / strobe.
    # We resolve the platform from the entity registry. ZHA also
    # needs the device's IEEE address (looked up from the device
    # registry's identifiers field).
    vendor_strategy = None
    vendor_used = False
    try:
        registry_entry = registry.async_get(entity_id)
    except Exception:
        registry_entry = None
    if registry_entry is not None:
        platform = registry_entry.platform
        strategy = vendor_identify_strategy_for(entity_id, platform)
        if strategy is not None and strategy.service_calls:
            # ZHA path: resolve IEEE from device registry identifiers.
            if platform == "zha" and registry_entry.device_id:
                try:
                    device_reg = dr.async_get(hass)
                    dev = device_reg.async_get(registry_entry.device_id)
                except Exception:
                    dev = None
                ieee: str | None = None
                if dev is not None:
                    for ident in dev.identifiers:
                        if isinstance(ident, tuple) and len(ident) == 2 and ident[0] == "zha":
                            ieee = ident[1]
                            break
                if ieee is None:
                    # Can't fire ZHA cluster command without IEEE;
                    # fall back to generic path silently.
                    strategy = None
                else:
                    # Patch the IEEE into the service call data.
                    patched_calls = []
                    for call in strategy.service_calls:
                        new_data = dict(call.get("data", {}))
                        if "ieee" in new_data and new_data["ieee"] is None:
                            new_data["ieee"] = ieee
                        patched_call = {**call, "data": new_data}
                        # Strip the internal hint marker before firing.
                        patched_call.pop("_resolve_ieee_from_entity", None)
                        patched_calls.append(patched_call)
                    # Re-wrap; the original strategy is frozen.
                    from ..lib.vendor_identify_strategy import (
                        VendorIdentifyStrategy as _VIS,
                    )
                    strategy = _VIS(
                        platform=strategy.platform,
                        method_label=strategy.method_label,
                        description=strategy.description,
                        service_calls=patched_calls,
                    )
            if strategy is not None:
                vendor_strategy = strategy

    cap = identify_capability_for(
        entity_id, {"attributes": dict(state.attributes)}
    )
    if cap.method == IdentifyMethod.NONE and vendor_strategy is None:
        connection.send_error(
            msg["id"],
            "not_identifiable",
            (
                f"{entity_id} has no built-in identify signal. Try "
                "the touch-test mode (v1.10 Phase B) for passive sensors."
            ),
        )
        return

    # Unify on a single "what we're going to fire" record. Vendor
    # strategy beats the generic capability if both apply — vendor
    # primitives don't power-cycle and don't trigger pairing modes.
    if vendor_strategy is not None:
        fire_calls = vendor_strategy.service_calls
        method_label = vendor_strategy.method_label
        description = vendor_strategy.description
        needs_confirm = False  # vendor primitives are always safe
        inter_delay_ms = 0
        vendor_used = True
    else:
        fire_calls = cap.service_calls
        method_label = cap.method.value
        description = cap.description
        needs_confirm = cap.method in _POWER_CYCLE_METHODS
        inter_delay_ms = cap.inter_call_delay_ms

    if needs_confirm and not confirm_power_cycle:
        connection.send_result(
            msg["id"],
            {
                "requires_confirmation": True,
                "method": method_label,
                "description": description,
                "substitution": substitution,
                "vendor_native": vendor_used,
                "warning": (
                    f"This will power-cycle {entity_id} "
                    f"({description}). If anything important is "
                    "downstream of this device (smart bulb on dumb "
                    "switch, network gear on outlet, etc.) it will "
                    "blink too. Re-send with confirm_power_cycle=true "
                    "to proceed."
                ),
            },
        )
        return

    calls_made = 0
    try:
        for i, call in enumerate(fire_calls):
            # Vendor strategies may use `target: {entity_id: X}` shape
            # while generic capabilities pass `entity_id` directly via
            # data. Honour whichever the call specifies; default to
            # injecting entity_id into data for back-compat.
            call_data = dict(call.get("data", {}))
            target = call.get("target")
            if target is None and "entity_id" not in call_data:
                call_data["entity_id"] = entity_id
            await hass.services.async_call(
                call["domain"],
                call["service"],
                call_data,
                target=target,
                blocking=False,
            )
            calls_made += 1
            # Pause between sequential calls (strobe / toggle rhythm).
            # Skip on the last call so we don't add a useless trailing
            # sleep before responding to the WS client.
            if inter_delay_ms > 0 and i + 1 < len(fire_calls):
                await _async_sleep(inter_delay_ms / 1000.0)
    except Exception as err:
        _LOGGER.warning(
            "identify_entity %s failed after %d/%d calls: %s",
            entity_id,
            calls_made,
            len(fire_calls),
            err,
        )
        connection.send_error(
            msg["id"],
            "service_call_failed",
            f"Identify failed after {calls_made}/{len(fire_calls)} calls: {err}",
        )
        return

    connection.send_result(
        msg["id"],
        {
            "method": method_label,
            "description": description,
            "calls_made": calls_made,
            "substitution": substitution,
            "vendor_native": vendor_used,
        },
    )


# v1.10 Phase B — perturbation touch-test ----------------------------


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/perturbation_guide",
        vol.Required("device_class"): str,
    }
)
@websocket_api.async_response
async def ws_perturbation_guide(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the perturbation instruction for one device_class.

    Read-only; not admin-gated. Card calls this when the user clicks
    the 👆 button for a passive-sensor row to learn what to ask the
    user to do (touch / breathe / shine light / etc.).

    Response shape:
      {
        "supported": true,
        "instruction": "Place a finger on the sensor...",
        "expected_delta": 2.0,
        "listening_window_s": 30,
        "perturb_duration_s": 15,
      }

    On unsupported / unknown device_class: `{"supported": false,
    "reason": "<why>"}`.
    """
    from ..lib.perturbation_capability import (
        is_perturbation_unsupported,
        perturbation_guide_for,
    )

    device_class = msg["device_class"]
    guide = perturbation_guide_for(device_class)
    if guide is not None:
        connection.send_result(
            msg["id"],
            {
                "supported": True,
                "device_class": guide.device_class,
                "instruction": guide.instruction,
                "expected_delta": guide.expected_delta,
                "listening_window_s": guide.listening_window_s,
                "perturb_duration_s": guide.perturb_duration_s,
            },
        )
        return
    reason = (
        f"`{device_class}` is a recognized device_class that "
        "deliberately doesn't support perturbation testing "
        "(e.g. PM2.5 is too slow; battery can't be perturbed; "
        "motion has its own 'wait for event' path)."
        if is_perturbation_unsupported(device_class)
        else (
            f"`{device_class}` isn't a recognized perturbable "
            "device_class. Try statistical correlation inference "
            "(v1.11) for unknown types."
        )
    )
    connection.send_result(
        msg["id"],
        {"supported": False, "reason": reason},
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/perturbation_test",
        vol.Required("device_class"): str,
        vol.Required("candidate_entity_ids"): [str],
        vol.Optional("listening_window_s", default=30): int,
        vol.Optional("z_threshold", default=3.0): float,
        vol.Optional("ambiguity_gap", default=1.5): float,
    }
)
@websocket_api.async_response
async def ws_perturbation_test(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Run a perturbation touch-test.

    Captures a baseline from each candidate's current state and
    last ~60s of state-change history (from the HA Insights event
    buffer if available; otherwise just a single sample). Opens a
    listening window for `listening_window_s` seconds, captures every
    state change on the candidates, runs the z-score analysis, and
    returns the ranked result.

    Admin-gated because the test ties up server resources for the
    duration and shouldn't be invokable by guest tokens.

    Response shape: see PerturbationResult fields, serialized to a
    dict + a `candidates: [...]` array of CandidateAssessment dicts.
    """
    if not _require_admin(hass, connection, msg):
        return

    import asyncio
    from datetime import UTC, datetime, timedelta

    from homeassistant.core import Event
    from homeassistant.helpers.event import async_track_state_change_event

    from ..lib.perturbation_detection import analyze_perturbation

    device_class = msg["device_class"]
    candidate_ids: list[str] = msg["candidate_entity_ids"]
    window_s: int = msg["listening_window_s"]
    z_threshold: float = msg["z_threshold"]
    ambiguity_gap: float = msg["ambiguity_gap"]

    if not candidate_ids:
        connection.send_error(
            msg["id"],
            "no_candidates",
            "candidate_entity_ids must be non-empty.",
        )
        return

    # ----- Baseline collection -----
    # Prefer the HA Insights event buffer when available (gives us
    # actual recent samples). Fall back to the current state value
    # as a single-sample baseline. The detection lib handles both
    # gracefully via _MIN_BASELINE_SAMPLES.
    baseline: dict[str, list[float]] = {}
    buffer_obj = None
    for entry_data in hass.data.get(DOMAIN, {}).values():
        if isinstance(entry_data, dict) and "buffer" in entry_data:
            buffer_obj = entry_data["buffer"]
            break
    baseline_cutoff = datetime.now(tz=UTC) - timedelta(seconds=60)
    for eid in candidate_ids:
        samples: list[float] = []
        if buffer_obj is not None:
            for ev in buffer_obj.query(
                since=baseline_cutoff,
                entity_id=eid,
            ):
                try:
                    samples.append(float(ev.new_state))
                except (TypeError, ValueError):
                    continue
        # Augment with the current state so we always have a "now"
        # reading even if the buffer has no recent activity.
        state = hass.states.get(eid)
        if state is not None:
            try:
                samples.append(float(state.state))
            except (TypeError, ValueError):
                pass
        baseline[eid] = samples

    # ----- Listening window -----
    test_samples: dict[str, list[float]] = {eid: [] for eid in candidate_ids}

    @callback
    def _record(event: Event) -> None:
        eid = event.data.get("entity_id")
        new_state = event.data.get("new_state")
        if eid is None or new_state is None:
            return
        try:
            value = float(new_state.state)
        except (TypeError, ValueError):
            return
        if eid in test_samples:
            test_samples[eid].append(value)

    unsub = async_track_state_change_event(hass, candidate_ids, _record)
    try:
        await asyncio.sleep(window_s)
    finally:
        unsub()

    # ----- Analyze -----
    result = analyze_perturbation(
        baseline_samples_per_entity=baseline,
        test_samples_per_entity=test_samples,
        z_threshold=z_threshold,
        ambiguity_gap=ambiguity_gap,
    )

    connection.send_result(
        msg["id"],
        {
            "device_class": device_class,
            "decision": result.decision,
            "top_match": result.top_match,
            "runner_up_gap": result.runner_up_gap,
            "reason": result.reason,
            "candidates": [
                {
                    "entity_id": c.entity_id,
                    "baseline_mean": c.baseline_mean,
                    "baseline_stddev": c.baseline_stddev,
                    "peak_value": c.peak_value,
                    "peak_delta": c.peak_delta,
                    "z_score": c.z_score,
                    "spike_detected": c.spike_detected,
                    "sample_count": c.sample_count,
                }
                for c in result.candidates
            ],
        },
    )


__all__ = [
    "ws_identify_capability",
    "ws_identify_entity",
    "ws_perturbation_guide",
    "ws_perturbation_test",
]
