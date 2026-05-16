"""Adaptive notification tuner.

When the user picks "Adaptive" notification mode, this module runs a
daily nudge against the active confidence threshold based on the
user's recent dismiss / apply behaviour:

  - High dismiss rate ⇒ raise the threshold (we're being too chatty;
    fewer but better notifications).
  - High apply rate ⇒ lower the threshold (the user's engaging; let
    a bit more through).
  - Otherwise hold.

The override lives in `hass.data[DOMAIN][entry_id]["adaptive_floor"]`
and the mobile policy resolver reads it before falling back to the
preset baseline. Override is persisted as part of the entry's
options so it survives restart.

Bounds: [0.70, 0.95]. Step: 0.02 (so it takes ~10 days at the
extreme to fully traverse the band — the system doesn't react
violently to a single bad day).

Inputs (last 14 days from the store):
  - pushed_count: rough upper bound on mobile-pushed insights.
    We don't yet record per-insight push outcomes; for now we use
    "applied_at OR dismissed_at on insights created in the
    window" as a proxy. Replace with a delivered_at column if
    we ever need higher precision.
  - dismissed_count / applied_count: store reads.

Future:
  - Per-detector adaptive tuning (high dismiss on weather_correlation
    but low on phone_charge_reminder shouldn't push the global up).
  - Surface "current effective threshold" + "last adjustment" via
    the WS hello handshake so the panel can render a status pill.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant

from ..const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from ..store import InsightStore

_LOGGER = logging.getLogger(__name__)

_BAND_LOW = 0.70
_BAND_HIGH = 0.95
_STEP = 0.02
# Need at least this many "scored" insights in the window before the
# tuner is willing to nudge. Otherwise small numbers (1/2 dismissed
# means 50% rate) cause violent jumps.
_MIN_SAMPLES = 10
# Rolling lookback for the tuner. Two weeks is long enough to smooth
# day-of-week noise (weekend vs weekday usage spikes) without being
# so long that an old habit dominates new ones.
_LOOKBACK_DAYS = 14
# Dismiss rate above this raises threshold; apply rate above this
# lowers it. Hold otherwise.
_DISMISS_HEAVY = 0.6
_APPLY_HEAVY = 0.4


def get_adaptive_floor(
    hass: HomeAssistant, entry_id: str, baseline: float
) -> float:
    """Return the current adaptive-mode floor for an entry.

    Falls back to `baseline` when no override has been published —
    that's the case on first boot, or before the first tuner run.
    Bounded into the safe band defensively.

    after a restart, hass.data is empty but
    the learned floor MUST survive. We now check entry.options
    (the persistent record) as a second fallback, and rehydrate
    hass.data so subsequent calls within this run hit the fast path.
    """
    try:
        entry_data = hass.data.get(DOMAIN, {}).get(entry_id)
        if isinstance(entry_data, dict):
            override = entry_data.get("adaptive_floor")
            if isinstance(override, (int, float)):
                return max(_BAND_LOW, min(_BAND_HIGH, float(override)))

            # Cold-path: hass.data hadn't been seeded yet (e.g. first
            # call after restart, before the daily tick runs). Pull
            # from the persisted entry.options.
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry is not None:
                persisted = entry.options.get("adaptive_floor")
                if isinstance(persisted, (int, float)):
                    bounded = max(
                        _BAND_LOW, min(_BAND_HIGH, float(persisted))
                    )
                    # Seed hass.data so we don't pay the entry lookup
                    # cost on every push.
                    entry_data["adaptive_floor"] = bounded
                    return bounded
    except Exception:
        pass
    return baseline


async def tune_adaptive_floor(
    hass: HomeAssistant,
    entry: ConfigEntry,
    store: InsightStore,
) -> dict[str, float | int | str] | None:
    """Run one tuner pass. Reads recent store outcomes, decides
    whether to raise / lower / hold, persists the new floor.

    Returns a small summary dict for logging; None if there wasn't
    enough data to act on.
    """
    cutoff = datetime.now(tz=UTC) - timedelta(days=_LOOKBACK_DAYS)
    try:
        recent = await store.list_insights(
            include_dismissed=True,
            include_applied=True,
            include_snoozed=True,
        )
    except Exception:
        _LOGGER.debug("adaptive tuner: store read failed", exc_info=True)
        return None

    # exclude example insights injected via
    # `home_insights/inject_examples`. Those are first-run demo
    # content, not real user outcomes — counting their dismissals
    # would pollute the adaptive tuner's learned floor.
    from ..examples import EXAMPLE_PAYLOAD_KEY

    in_window = [
        i
        for i in recent
        if i.created_at >= cutoff
        and not i.payload.get(EXAMPLE_PAYLOAD_KEY)
    ]
    if len(in_window) < _MIN_SAMPLES:
        return None

    # Treat "applied" or "dismissed" as a scored outcome. Pending
    # insights count toward neither (the user hasn't acted yet —
    # we can't say if it was useful or annoying).
    applied = sum(1 for i in in_window if i.applied_at is not None)
    # v1.4: `dismissed_at` is now a first-class field on Insight, so
    # we can detect dismissals without a separate store query.
    dismissed = sum(
        1
        for i in in_window
        if i.applied_at is None and i.dismissed_at is not None
    )
    scored = applied + dismissed
    if scored < _MIN_SAMPLES:
        return None

    dismiss_rate = dismissed / scored if scored else 0.0
    apply_rate = applied / scored if scored else 0.0

    # Pull current floor (baseline if no override yet) — gotta
    # know what to nudge FROM. The baseline comes from the preset
    # which we don't import here to avoid the dependency; the
    # cache the caller hands in via `entry.options` is the source
    # of truth.
    from ..config_flow import (
        _NOTIFY_PRESETS,
        NOTIFY_PRESET_ADAPTIVE,
    )

    baseline = float(
        _NOTIFY_PRESETS[NOTIFY_PRESET_ADAPTIVE]["confidence_floor"]
    )
    current = get_adaptive_floor(hass, entry.entry_id, baseline)

    direction = "hold"
    new_floor = current
    if dismiss_rate >= _DISMISS_HEAVY:
        new_floor = min(_BAND_HIGH, current + _STEP)
        direction = "raise"
    elif apply_rate >= _APPLY_HEAVY:
        new_floor = max(_BAND_LOW, current - _STEP)
        direction = "lower"

    if abs(new_floor - current) < 1e-9 and direction == "hold":
        return {
            "direction": "hold",
            "current_floor": current,
            "dismiss_rate": round(dismiss_rate, 3),
            "apply_rate": round(apply_rate, 3),
            "samples": scored,
        }

    # Publish to hass.data so the next push reads the new value
    # immediately, AND persist to entry.options so the learned floor
    # survives an HA restart. code review #10 — without persistence,
    # the tuner restarted at the baseline every boot, so weeks of
    # learned dismiss/apply behaviour evaporated on each upgrade.
    tune_ts = datetime.now(tz=UTC).isoformat()
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if isinstance(entry_data, dict):
        entry_data["adaptive_floor"] = new_floor
        entry_data["adaptive_last_tune_at"] = tune_ts
        entry_data["adaptive_last_direction"] = direction

    # async_update_entry triggers the options-updated listener; the
    # listener has a special-case for "auto-managed" keys (analytics
    # UUID + adaptive_floor + adaptive_last_*) that skips the
    # otherwise-mandatory reload. See __init__._on_options_updated.
    try:
        merged = dict(entry.options)
        merged["adaptive_floor"] = float(new_floor)
        merged["adaptive_last_tune_at"] = tune_ts
        merged["adaptive_last_direction"] = direction
        hass.config_entries.async_update_entry(entry, options=merged)
    except Exception:
        _LOGGER.debug(
            "adaptive tuner: persist to entry.options failed",
            exc_info=True,
        )

    _LOGGER.info(
        "HA Insights adaptive tuner: %s floor %.3f → %.3f "
        "(dismiss=%.2f, apply=%.2f over %d samples in last %dd)",
        direction,
        current,
        new_floor,
        dismiss_rate,
        apply_rate,
        scored,
        _LOOKBACK_DAYS,
    )
    return {
        "direction": direction,
        "previous_floor": current,
        "current_floor": new_floor,
        "dismiss_rate": round(dismiss_rate, 3),
        "apply_rate": round(apply_rate, 3),
        "samples": scored,
    }


__all__ = ["get_adaptive_floor", "tune_adaptive_floor"]
