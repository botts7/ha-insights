"""Build a redacted "dev audit" snapshot of the install.

Purpose: let a human (or, opt-in, an LLM agent) verify that every
detector is firing for the right reasons — or silent for the right
reasons — given the install's actual data shape. The output is a
single JSON dict the user can paste into a chat, attach to a bug
report, or pipe to their LLM agent.

What it captures:
- Install signature: domain-bucketed entity counts, integration
  platforms in use, automation count, area/floor/label counts,
  recorder window, presence of mobile_app / weather entities.
- Per-detector activity: name, maturity tier, last-scan emission
  count, all-time emission count.
- Event buffer signature: 24h / 7d event counts + unique entities.
- Config fingerprint: which OptionsFlow knobs are set (without
  surfacing values — booleans + presence checks only).

What it does NOT capture:
- Entity friendly names, automation aliases, IP addresses, tokens,
  user emails, HA URLs, latitude/longitude.
- Specific entity_ids (only domain + bucketed count).
- Recorded events (just the count).

Pure-async function — no HA-side state writes, no network. Safe to
call on demand. Caller (`ws_api.ws_export_dev_audit`) handles the
admin gate + JSON serialisation.
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from ..observers.state_event_buffer import StateEventBuffer
    from ..store import InsightStore

_LOGGER = logging.getLogger(__name__)

# Bump when the output schema changes incompatibly. LLMs and bug-
# triage scripts pin against this so old/new bundles don't get
# mixed up.
SCHEMA_VERSION = 1


async def build_dev_audit_bundle(
    hass: HomeAssistant,
    store: InsightStore,
    *,
    integration_version: str,
    buffer: StateEventBuffer | None = None,
) -> dict[str, Any]:
    """Assemble the full dev-audit bundle. Pure read; never mutates."""
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "integration_version": integration_version,
        "install_signature": await _build_install_signature(hass),
        "detector_results": await _build_detector_results(store),
        "event_buffer_signature": _build_event_buffer_signature(buffer),
        "config_signature": _build_config_signature(hass),
        "redaction_notes": (
            "Entity friendly names, automation aliases, IPs, tokens, "
            "lat/long, and specific entity_ids are excluded. Counts + "
            "presence booleans only."
        ),
    }


async def _build_install_signature(hass: HomeAssistant) -> dict[str, Any]:
    """Domain counts + integration list + registry totals. No names."""
    states = hass.states.async_all()
    domain_counter: Counter[str] = Counter()
    for state in states:
        domain = state.entity_id.split(".", 1)[0]
        domain_counter[domain] += 1

    # Integration platforms in use, from the entity registry. Names
    # like "tuya", "mobile_app", "zwave_js" — useful for the LLM to
    # reason about what kinds of detectors should fire.
    integrations: set[str] = set()
    try:
        from homeassistant.helpers import entity_registry as er

        e_reg = er.async_get(hass)
        for entry in e_reg.entities.values():
            if entry.platform:
                integrations.add(entry.platform)
    except Exception as exc:
        _LOGGER.debug("dev_audit: entity_registry walk failed: %s", exc)

    # Area / floor / label registry totals. Floors + labels are HA
    # 2024.4+; treat them as 0 on older versions.
    area_count = 0
    floor_count = 0
    label_count = 0
    try:
        from homeassistant.helpers import area_registry as ar

        area_count = len(list(ar.async_get(hass).async_list_areas()))
    except Exception as exc:
        _LOGGER.debug("dev_audit: area_registry probe failed: %s", exc)
    try:
        from homeassistant.helpers import floor_registry as fr

        floor_count = len(list(fr.async_get(hass).async_list_floors()))
    except Exception as exc:
        _LOGGER.debug("dev_audit: floor_registry probe failed: %s", exc)
    try:
        from homeassistant.helpers import label_registry as lr

        label_count = len(list(lr.async_get(hass).async_list_labels()))
    except Exception as exc:
        _LOGGER.debug("dev_audit: label_registry probe failed: %s", exc)

    # Recorder window — best-effort. Most installs run the default
    # 10 days. We surface the configured purge_keep_days from the
    # recorder component if available.
    recorder_window_days: int | None = None
    try:
        recorder_data = hass.data.get("recorder_instance")
        if recorder_data is not None:
            recorder_window_days = getattr(
                recorder_data, "keep_days", None
            )
    except Exception as exc:
        _LOGGER.debug("dev_audit: recorder probe failed: %s", exc)

    return {
        "entity_count_total": len(states),
        "entity_counts_by_domain": dict(
            sorted(domain_counter.items(), key=lambda x: -x[1])
        ),
        "integrations": sorted(integrations),
        "integration_count": len(integrations),
        "area_count": area_count,
        "floor_count": floor_count,
        "label_count": label_count,
        "recorder_window_days": recorder_window_days,
        # Convenience booleans for the LLM — saves a lookup against
        # the integrations list.
        "has_mobile_app": "mobile_app" in integrations,
        "has_weather_entity": domain_counter.get("weather", 0) > 0,
        "has_person": domain_counter.get("person", 0) > 0,
        "has_device_tracker": domain_counter.get("device_tracker", 0) > 0,
        "has_button_entity": domain_counter.get("button", 0) > 0,
        "has_input_button": domain_counter.get("input_button", 0) > 0,
    }


async def _build_detector_results(
    store: InsightStore,
) -> dict[str, dict[str, Any]]:
    """Per-registered-detector activity summary.

    Walks the live insight store + the DETECTORS registry so disabled
    detectors still appear (with `enabled: false`). Lets the LLM tell
    "silent because no data" apart from "silent because the user
    explicitly turned it off".
    """
    from ..detectors import DETECTORS

    # Pull every insight (including dismissed/applied/snoozed/retired)
    # to compute the all-time count.
    all_time = await store.list_insights(
        include_dismissed=True,
        include_applied=True,
        include_snoozed=True,
        include_retired=True,
    )
    live = await store.list_insights()
    all_time_by_detector: Counter[str] = Counter()
    live_by_detector: Counter[str] = Counter()
    latest_by_detector: dict[str, datetime] = {}
    for ins in all_time:
        all_time_by_detector[ins.detector] += 1
        prev = latest_by_detector.get(ins.detector)
        if prev is None or ins.created_at > prev:
            latest_by_detector[ins.detector] = ins.created_at
    for ins in live:
        live_by_detector[ins.detector] += 1

    out: dict[str, dict[str, Any]] = {}
    for name, cls in DETECTORS.items():
        maturity = getattr(cls, "maturity", None)
        maturity_str = (
            maturity.value if hasattr(maturity, "value") else str(maturity)
            if maturity is not None
            else "stable"
        )
        latest = latest_by_detector.get(name)
        out[name] = {
            "maturity": maturity_str,
            "live_count": live_by_detector.get(name, 0),
            "all_time_count": all_time_by_detector.get(name, 0),
            "latest_emission_at": latest.isoformat() if latest else None,
            "requires_recorder": bool(
                getattr(cls, "requires_recorder", False)
            ),
        }
    return dict(sorted(out.items()))


def _build_event_buffer_signature(
    buffer: StateEventBuffer | None,
) -> dict[str, Any]:
    """How much activity is the short-term buffer seeing? Used to
    diagnose "no events, no patterns" silence."""
    if buffer is None:
        return {
            "buffer_attached": False,
            "events_24h": None,
            "events_7d": None,
            "unique_entities": None,
        }
    now = datetime.now(tz=UTC)
    cutoff_24h = now - timedelta(hours=24)
    cutoff_7d = now - timedelta(days=7)
    events_24h = 0
    events_7d = 0
    seen_entities: set[str] = set()
    try:
        for ev in buffer.iter_events():
            seen_entities.add(ev.entity_id)
            ts = getattr(ev, "ts_utc", None) or getattr(ev, "timestamp", None)
            if ts is None:
                continue
            if ts >= cutoff_24h:
                events_24h += 1
            if ts >= cutoff_7d:
                events_7d += 1
    except Exception as exc:
        _LOGGER.debug("dev_audit: buffer iteration failed: %s", exc)
    return {
        "buffer_attached": True,
        "events_24h": events_24h,
        "events_7d": events_7d,
        "unique_entities": len(seen_entities),
    }


def _build_config_signature(hass: HomeAssistant) -> dict[str, Any]:
    """OptionsFlow knob fingerprint — presence/cardinality only.

    Never surfaces the values (entity IDs, agent IDs, JSON blobs); only
    whether each knob is configured + how many items it contains.
    """
    from ..const import DOMAIN

    config_entries = hass.config_entries.async_entries(DOMAIN)
    if not config_entries:
        return {"config_entry_present": False}

    options = config_entries[0].options or {}
    return {
        "config_entry_present": True,
        "config_entry_count": len(config_entries),
        "audit_rollup_window_days": options.get(
            "audit_rollup_window_days"
        ),
        "audit_analysis_depth": options.get("audit_analysis_depth"),
        "lookback_days": options.get("lookback_days"),
        "min_confidence": options.get("min_confidence"),
        "preferred_agent_configured": bool(
            options.get("preferred_agent_id")
        ),
        "blocked_entities_count": len(
            options.get("blocked_entities") or []
        ),
        "managed_devices_count": len(
            options.get("managed_externally_devices") or []
        ),
        "notify_mobile_targets_count": len(
            options.get("notify_mobile_targets") or []
        ),
        "goals_configured": bool(options.get("goals_json")),
        "auto_llm_enabled": bool(options.get("auto_llm_enabled")),
        "privacy_mode": options.get("privacy_mode"),
        "analytics_opted_in": bool(options.get("analytics_opted_in")),
        "experimental_detectors_count": len(
            options.get("enabled_detectors") or []
        ),
    }
