"""Opt-in community analytics.

Sends anonymous metrics about detector outcomes to a community
endpoint so the project can iterate detectors based on real data —
e.g. "weather_correlation has a 4% apply rate, let's tighten the
threshold" or "phone_charge_reminder graduates from EXPERIMENTAL
to BETA, 67% of installs find it useful".

Privacy contract (binding — must NEVER be silently broken):
  - Sends only AGGREGATE COUNTS, never individual events.
  - No entity names, friendly names, area names, automation
    aliases, or any free-text user content.
  - No insight titles, descriptions, or payloads.
  - No HA user_ids, person.* attributes, or any identifier that
    could be cross-referenced with another data source.
  - Install identity is a per-entry random UUID generated locally
    and persisted in options. Cannot be linked to any HA Cloud
    account, GitHub user, or external identity.
  - Disabled by default — explicit opt-in via OptionsFlow only.
  - The exact payload is logged at DEBUG level the first time it
    fires so users can inspect what's being sent.

Schedule: once per week, at a randomized hour to spread load on
the receiver. Skipped silently when the opt-in is off.

Receiver: configurable endpoint URL with a sensible default. The
project's Cloudflare Worker validates schema, dedupes by
(install_uuid, iso_week), appends raw to a maintainer-only bucket,
and a separate daily ETL job computes public weekly aggregates.

See PLAN.md §17 Community Analytics for the receiver architecture
and access-control model.
"""
from __future__ import annotations

import logging
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .store import InsightStore

_LOGGER = logging.getLogger(__name__)

# Default community endpoint. Self-hosters can override via
# CONF_ANALYTICS_ENDPOINT in the OptionsFlow. The receiver lives
# outside this repo at ha-insights-analytics-worker; URL settled
# before the first analytics commit ships to community.
DEFAULT_ANALYTICS_ENDPOINT = "https://analytics.ha-insights.io/v1/report"
# Hard timeout — the integration must not block waiting on the
# community endpoint, regardless of how slow it is.
_REQUEST_TIMEOUT_SEC = 15.0
# How many days of insights to summarize per report. One week
# matches the iso_week dedup the receiver uses.
_REPORT_WINDOW_DAYS = 7


def get_or_create_install_uuid(
    entry: "ConfigEntry", hass: HomeAssistant | None = None
) -> str:
    """Return the stable per-entry install UUID, creating one if
    missing. Stored in options so it survives restarts but resets
    if the entry is removed + re-added (which is the correct
    behaviour — a brand-new entry is a brand-new install for
    analytics purposes).

    When `hass` is provided AND we generate a fresh UUID, we
    persist it back to the entry's options so the next call
    returns the same value. Without `hass` the new UUID is
    returned but not stored — caller is responsible for that
    (today: build_report_payload, which doesn't have hass at
    call-time without threading it through).
    """
    uid = entry.options.get("analytics_install_uuid")
    if isinstance(uid, str) and len(uid) == 36:
        return uid
    new_uid = str(uuid.uuid4())
    if hass is not None:
        # Fire-and-forget persist. async_update_entry is a callback
        # that mutates the entry in-place + triggers the options
        # listener. Done before the report POST so the second call
        # in the same week sees the persisted value.
        try:
            merged = dict(entry.options)
            merged["analytics_install_uuid"] = new_uid
            hass.config_entries.async_update_entry(entry, options=merged)
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "Failed to persist analytics_install_uuid", exc_info=True
            )
    return new_uid


async def build_report_payload(
    hass: HomeAssistant,
    entry: "ConfigEntry",
    store: "InsightStore",
) -> dict[str, Any]:
    """Compose the weekly report. SAFE TO LOG — no PII, no payload
    content, no entity names. Returns the JSON body that would be
    POSTed to the receiver. Used directly by the reporter; also
    surfaced by the WS preview endpoint so users can see exactly
    what they're sending before they enable.
    """
    from .config_flow import (
        get_active_mode,
        get_allow_experimental_detectors,
        get_notify_preset,
    )

    install_uuid = get_or_create_install_uuid(entry, hass=hass)
    cutoff = datetime.now(tz=UTC) - timedelta(days=_REPORT_WINDOW_DAYS)
    try:
        all_in_window = await store.list_insights(
            include_dismissed=True,
            include_applied=True,
            include_snoozed=True,
        )
    except Exception:  # noqa: BLE001
        all_in_window = []
    # exclude example insights from the
    # community dataset. They're first-run demo content, not real
    # user outcomes — including them would pollute fleet-wide
    # apply / dismiss rate estimates.
    from .examples import EXAMPLE_PAYLOAD_KEY

    in_window = [
        i
        for i in all_in_window
        if i.created_at >= cutoff
        and not i.payload.get(EXAMPLE_PAYLOAD_KEY)
    ]

    # Per-detector counts: total fired + applied + dismissed.
    by_detector_fired: Counter[str] = Counter()
    by_detector_applied: Counter[str] = Counter()
    by_detector_dismissed: Counter[str] = Counter()
    for ins in in_window:
        by_detector_fired[ins.detector] += 1
        if ins.applied_at is not None:
            by_detector_applied[ins.detector] += 1
        elif getattr(ins, "dismissed_at", None) is not None:
            by_detector_dismissed[ins.detector] += 1

    # Maturity tier distribution — which tiers are emitting insights.
    # Looked up live from the registry; safe (detector names only,
    # which are public constants).
    try:
        from .detectors import DETECTORS
        from .detectors.base import Maturity

        maturity_by_detector = {
            name: getattr(cls, "maturity", Maturity.STABLE).value
            for name, cls in DETECTORS.items()
        }
    except Exception:  # noqa: BLE001
        maturity_by_detector = {}

    try:
        from homeassistant.loader import async_get_integration

        integration = await async_get_integration(hass, "ha_insights")
        integration_version = integration.version or "0.0"
    except Exception:  # noqa: BLE001
        integration_version = "0.0"

    return {
        "schema_version": 1,
        "install_uuid": install_uuid,
        "integration_version": integration_version,
        "ha_version": _ha_version(hass),
        "iso_week": _iso_week_label(),
        "report_window_days": _REPORT_WINDOW_DAYS,
        "config": {
            # Coarse policy shape only — no values that could
            # uniquely identify an install. The receiver uses these
            # to compare detector outcomes across installs that
            # picked the same mode.
            "llm_mode": get_active_mode(entry),
            "notify_preset": get_notify_preset(entry),
            "allow_experimental": get_allow_experimental_detectors(entry),
        },
        "detector_outcomes": [
            {
                "detector": name,
                "maturity": maturity_by_detector.get(name, "stable"),
                "fired": int(by_detector_fired[name]),
                "applied": int(by_detector_applied[name]),
                "dismissed": int(by_detector_dismissed[name]),
            }
            for name in sorted(
                set(by_detector_fired)
                | set(by_detector_applied)
                | set(by_detector_dismissed)
            )
        ],
        "totals": {
            "insights_in_window": len(in_window),
            "applied": sum(by_detector_applied.values()),
            "dismissed": sum(by_detector_dismissed.values()),
        },
    }


def _ha_version(hass: HomeAssistant) -> str:
    """HA version as a coarse "YYYY.M" string — drops the patch
    component so installs with the same minor release cluster
    together regardless of point updates."""
    try:
        from homeassistant.const import __version__ as HA_VERSION

        return ".".join(str(HA_VERSION).split(".")[:2])
    except Exception:  # noqa: BLE001
        return "unknown"


def _iso_week_label() -> str:
    """Current ISO week as "YYYY-Www" — matches what the receiver
    uses for dedup."""
    now = datetime.now(tz=UTC)
    year, week, _ = now.isocalendar()
    return f"{year}-W{week:02d}"


async def send_report(
    hass: HomeAssistant,
    entry: "ConfigEntry",
    store: "InsightStore",
    *,
    endpoint: str | None = None,
) -> dict[str, Any] | None:
    """Build + POST the weekly report. Best-effort — failures log
    at DEBUG and don't propagate. Returns the payload (already
    SAFE TO LOG) on success, None on transport failure.
    """
    payload = await build_report_payload(hass, entry, store)
    url = endpoint or DEFAULT_ANALYTICS_ENDPOINT
    try:
        # reuse HA's shared aiohttp session
        # instead of spinning up a fresh ClientSession per send.
        # The previous code created (and tore down) a full TCP /
        # TLS connection pool every Monday — fine for a once-weekly
        # call but wasteful, and ClientSession leaks if the
        # async-with body raises before close().
        # `async_get_clientsession(hass)` returns HA's shared
        # session (created once, reused everywhere), which is
        # exactly the right primitive for one-off HTTP calls.
        import aiohttp
        from homeassistant.helpers.aiohttp_client import (
            async_get_clientsession,
        )

        timeout = aiohttp.ClientTimeout(total=_REQUEST_TIMEOUT_SEC)
        session = async_get_clientsession(hass)
        async with session.post(url, json=payload, timeout=timeout) as resp:
            if resp.status >= 400:
                _LOGGER.debug(
                    "Analytics POST to %s returned %d", url, resp.status
                )
                return None
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Analytics POST failed (best-effort)", exc_info=True)
        return None
    return payload


__all__ = [
    "DEFAULT_ANALYTICS_ENDPOINT",
    "build_report_payload",
    "get_or_create_install_uuid",
    "send_report",
]
