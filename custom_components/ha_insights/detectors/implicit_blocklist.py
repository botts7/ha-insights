"""Layer-1 implicit blocklist — auto-skip noisy entity classes at scan time.

The user's per-entity blocklist (`CONF_LLM_BLOCK_ENTITIES`) handles
specific exceptions. This module handles the *defaults*: classes of
entities that are noise across every install, regardless of user
preferences.

Approach:
  - Walk the entity registry once at scan start (cheap; in-memory dict)
  - Collect entity_ids that fall into noise buckets:
    * `entity_category` is `diagnostic` or `config` (HA telemetry, not
      user behavior — RSSI graphs, "update available" sensors, etc)
    * `device_class` is in NOISE_DEVICE_CLASSES (heartbeats, drift)
    * disabled or hidden by anything (already excluded from UX, no
      reason to surface insights about them)
  - Return as a frozenset, merged into ctx.blocked_entities so the
    existing FrozenBufferView filter pipeline catches them in `query()`
    without per-detector code

The defaults are opt-out, not opt-in (per user feedback): a fresh
install matches user expectations of "useful pattern detection" out
of the box. Power users can disable via OptionsFlow when that's wired.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Device classes that are pure noise for pattern detection.
# These represent device-driven behavior (heartbeats, drift, polling),
# not user-decided actions. Patterns over them aren't actionable as
# automations even if real.
NOISE_DEVICE_CLASSES: frozenset[str] = frozenset(
    {
        # Battery-state churn — charge cycles aren't user behavior
        "battery",
        "battery_charging",
        # Connectivity / network state — heartbeats from integrations
        "connectivity",
        # Signal strength drift (Z-Wave, Zigbee RSSI)
        "signal_strength",
        # "Update available" notifications
        "update",
        # Device-reported error states
        "problem",
        # Tamper detection — security concern, not pattern
        "tamper",
        # Generic "running" status from misc integrations
        "running",
        # GPS jitter on trackers
        "moving",
    }
)

# Entity categories that should never produce pattern insights.
# DIAGNOSTIC = HA-internal telemetry (RSSI, last_seen, integration status)
# CONFIG = user-facing knobs (e.g. "switch to enable feature X"), not events
NOISE_ENTITY_CATEGORIES: frozenset[str] = frozenset({"diagnostic", "config"})


async def build_implicit_blocklist(hass: HomeAssistant) -> frozenset[str]:
    """Walk the entity registry, return the set of entity_ids to auto-skip.

    Cheap — the registry is an in-memory dict; this runs in microseconds
    on a 1000-entity install. Called once at the start of each scan via
    `run_all_detectors`. Result is merged into ctx.blocked_entities so
    the existing FrozenBufferView filter catches them.
    """
    try:
        from homeassistant.helpers import entity_registry as er
    except Exception:  # pragma: no cover — defensive
        _LOGGER.warning(
            "entity_registry unavailable; implicit blocklist skipped"
        )
        return frozenset()

    registry = er.async_get(hass)
    skip: set[str] = set()
    skip_diag = 0
    skip_class = 0
    skip_disabled = 0

    for entry in registry.entities.values():
        # Disabled or hidden entities are already excluded from the user's
        # UX — there's no reason to surface insights about them.
        if entry.disabled_by is not None or entry.hidden_by is not None:
            skip.add(entry.entity_id)
            skip_disabled += 1
            continue
        # Diagnostic / config entity categories are HA telemetry, not
        # user-decided behavior. Patterns over them aren't actionable.
        ec_value = (
            entry.entity_category.value
            if entry.entity_category is not None
            else None
        )
        if ec_value in NOISE_ENTITY_CATEGORIES:
            skip.add(entry.entity_id)
            skip_diag += 1
            continue
        # Effective device class: user override falls back to integration default
        effective_class = entry.device_class or entry.original_device_class
        if effective_class in NOISE_DEVICE_CLASSES:
            skip.add(entry.entity_id)
            skip_class += 1

    if skip:
        _LOGGER.info(
            "HA Insights implicit blocklist: %d entities skipped "
            "(%d diagnostic/config, %d noise-class, %d disabled/hidden)",
            len(skip),
            skip_diag,
            skip_class,
            skip_disabled,
        )
    return frozenset(skip)
