"""Mobile-app insight notifications.

Pushes high-confidence insights to one or more `notify.mobile_app_*`
services so users actually see them on their phone, not just in the
panel. Pairs with the existing `persistent_notification` flow — both
fire from the same store-listener hook so they stay in sync.

Behaviour:
  - Disabled by default. Users opt in via the OptionsFlow by listing
    one or more `notify.*` service names (mobile_app_iphone, etc).
  - Includes an `actions` payload with two buttons:
      * "Open Insights" → opens the panel via URI action.
      * "Dismiss" → fires an HA event the integration listens for.
  - Uses a per-insight tag so re-emissions replace the existing
    notification rather than stacking (Android/iOS support tags).
  - Best-effort. Any failure logs and moves on; we never propagate
    notification failures back into the scan path.

Anti-spam gates (applied IN ORDER before any push fires):

  1. Confidence floor — `policy["confidence_floor"]`. The shared
     `notify_threshold` already gates the persistent_notification at
     a lower bar; this is a stricter floor specifically for the
     mobile channel.
  2. Attribution-confidence gate —
     `policy["min_attribution_confidence"]`. When the insight HAS
     a target_user_id, its confidence in *that attribution* must be
     above the floor or we don't push (avoids waking the wrong
     person). Insights without a target_user_id are unaffected;
     they go to the household-level configured targets.
  3. Quiet hours — local-hour window during which non-urgent pushes
     are deferred to the daily digest (always-fires path).
  4. Daily cap — per local-day, per-user (or "household" for
     unattributed). Excess pushes roll into the digest.

The state for daily-cap counting lives in the in-memory dict
`_DAILY_COUNTERS` keyed by (entry_id, target_user_id_or_household,
local_date). Resets organically when the day rolls over because
no entry exists for the new date until the first push attempt.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from ..insight import Insight

_LOGGER = logging.getLogger(__name__)

# URI scheme that opens HA Insights panel inside the mobile app.
# Mobile-app integration treats `/<panel_path>` paths as in-app links.
_PANEL_DEEP_LINK = "/ha-insights"

# (entry_id, user_key, local_date) -> count of mobile pushes fired today.
# `user_key` is target_user_id when attributed, else the literal
# string "household".
#
# old comment claimed "day rollover happens
# naturally" — true that NEW pushes use today's date as the key,
# but yesterday's entries were never removed. A long-running
# install accumulated ~1 entry per user per day forever. Pruned
# at every push attempt below (cheap O(N) over current keys).
_DAILY_COUNTERS: dict[tuple[str, str, date], int] = defaultdict(int)
# How many days of counters to retain. Anything older than this
# gets dropped at push time. 7 is generous for the use-case
# (only today's count matters for the daily cap) but lets the
# get_daily_push_count helper answer "did you push to user X
# yesterday?" if anything ever needs it.
_DAILY_COUNTER_RETENTION_DAYS = 7


def _prune_old_daily_counters(today: date) -> None:
    """Drop counter entries older than _DAILY_COUNTER_RETENTION_DAYS.
    Called at push time so a long-running install doesn't accumulate
    a row per user per day forever."""
    from datetime import timedelta as _td

    cutoff = today - _td(days=_DAILY_COUNTER_RETENTION_DAYS)
    stale = [k for k in _DAILY_COUNTERS if k[2] < cutoff]
    for k in stale:
        _DAILY_COUNTERS.pop(k, None)


def _build_payload(insight: Insight) -> dict[str, Any]:
    """Compose the data sent to a notify.mobile_app_* service."""
    confidence_pct = round(insight.confidence * 100)
    pretty_kind = insight.kind.value.replace("_", " ")
    return {
        "title": f"HA Insights — {pretty_kind} ({confidence_pct}%)",
        "message": insight.title,
        "data": {
            # Tag lets the OS replace prior notification for the same
            # insight on re-emission. iOS + Android both honor this.
            "tag": f"ha_insights_{insight.id}",
            # Tap target — opens the panel.
            "url": _PANEL_DEEP_LINK,
            "clickAction": _PANEL_DEEP_LINK,
            "actions": [
                {
                    "action": "URI",
                    "title": "Open",
                    "uri": _PANEL_DEEP_LINK,
                },
                {
                    "action": "HA_INSIGHTS_DISMISS",
                    "title": "Dismiss",
                    # Fired as event ha_insights_action; listener in
                    # __init__ updates the store.
                    "destructive": True,
                },
            ],
            # Grouping — all HA Insights notifications collapse into a
            # single stack on Android. Helps avoid notification spam.
            "group": "ha_insights",
            "channel": "HA Insights",
            "importance": "high",
        },
    }


def _in_quiet_hours(
    local_hour: int, *, start: int, end: int
) -> bool:
    """True iff `local_hour` falls inside the quiet-hours window.
    Handles wrap-around (start > end means the window crosses midnight).
    end == start means "no quiet hours" — always returns False."""
    if start == end:
        return False
    if start < end:
        return start <= local_hour < end
    # Wrap: e.g. 22..7 → [22,23] ∪ [0,7).
    return local_hour >= start or local_hour < end


async def fire_mobile_notifications(
    hass: HomeAssistant,
    insight: Insight,
    *,
    notify_services: list[str],
    policy: dict[str, Any] | None = None,
    entry_id: str = "default",
    entry: Any | None = None,
) -> None:
    """Send `insight` to each notify.* service, gated by the policy.

    When `insight.target_user_id` is set, the call is rerouted to
    ONLY that user's mobile_app services (intersected with
    `notify_services` if non-empty so user opt-out is still
    honored). This is the multi-user safeguard.

    `policy` is the dict returned by `get_mobile_notify_policy`.
    None means "no gates" — used by older callers; do not omit
    in new code. Suppressed pushes are logged so the user can
    diagnose silent insights.
    """
    from .user_routing import resolve_notify_targets

    # Per-user policy override: if the insight is attributed to a
    # specific user AND we have the entry handle, recompute the
    # effective policy with that user's overlay. Older callers
    # that don't pass `entry` keep the global policy.
    target_user_id_for_policy = getattr(insight, "target_user_id", None)
    if entry is not None and target_user_id_for_policy is not None:
        try:
            from ..config_flow import resolve_effective_policy

            policy = resolve_effective_policy(
                entry, target_user_id_for_policy
            )
        except Exception:
            _LOGGER.debug(
                "Per-user policy resolution failed, falling back to global",
                exc_info=True,
            )

    pol = policy or {}
    floor = float(pol.get("confidence_floor", 0.0))
    # Adaptive mode: ask the tuner for the learned floor and use
    # that instead of the preset baseline. Floor stays clamped to
    # the safe band [0.7, 0.95] inside the tuner.
    if pol.get("adaptive"):
        try:
            from .adaptive import get_adaptive_floor

            floor = get_adaptive_floor(hass, entry_id, floor)
        except Exception:
            _LOGGER.debug(
                "Adaptive floor lookup failed, falling back to "
                "baseline %.2f",
                floor,
                exc_info=True,
            )
    min_attr_conf = float(pol.get("min_attribution_confidence", 0.0))
    daily_cap = int(pol.get("daily_cap", 0))
    quiet_start = int(pol.get("quiet_hours_start", 0))
    quiet_end = int(pol.get("quiet_hours_end", 0))

    # Gate 1: mobile-specific confidence floor.
    if insight.confidence < floor:
        _LOGGER.debug(
            "HA Insights mobile push skipped (insight %s): "
            "confidence %.2f < mobile floor %.2f",
            insight.id,
            insight.confidence,
            floor,
        )
        return

    # Gate 2: attribution confidence (only when an insight HAS a
    # target_user_id — household-level insights pass through).
    target_user_id = getattr(insight, "target_user_id", None)
    attr_conf = getattr(insight, "target_user_id_confidence", None)
    if target_user_id is not None and attr_conf is not None:
        if attr_conf < min_attr_conf:
            _LOGGER.info(
                "HA Insights mobile push skipped (insight %s): "
                "attribution confidence %.2f for user_id=%s below "
                "floor %.2f — won't risk waking the wrong person",
                insight.id,
                attr_conf,
                target_user_id,
                min_attr_conf,
            )
            return

    # Gate 3: quiet hours (local time).
    local_now = dt_util.as_local(dt_util.utcnow())
    if _in_quiet_hours(local_now.hour, start=quiet_start, end=quiet_end):
        _LOGGER.info(
            "HA Insights mobile push deferred (insight %s): "
            "%02d:00 falls inside quiet hours %02d:00..%02d:00 "
            "(local). Will surface in the next daily digest.",
            insight.id,
            local_now.hour,
            quiet_start,
            quiet_end,
        )
        return

    # Resolve effective targets BEFORE the daily-cap check so we
    # count a "real push that would have happened" rather than a
    # ghost no-op.
    effective_targets = resolve_notify_targets(
        hass, notify_services, target_user_id=target_user_id
    )
    if not effective_targets:
        if target_user_id is not None:
            _LOGGER.info(
                "HA Insights mobile push for insight %s skipped: "
                "target_user_id=%s has no registered mobile_app "
                "devices (or none in user's allowlist)",
                insight.id,
                target_user_id,
            )
        return

    # Gate 4: daily cap (0 = unlimited).
    user_key = target_user_id or "household"
    today = local_now.date()
    counter_key = (entry_id, user_key, today)
    # code review #14: prune stale entries so we don't leak memory
    # at ~1 entry per user per day forever in a long-running install.
    _prune_old_daily_counters(today)
    if daily_cap > 0 and _DAILY_COUNTERS[counter_key] >= daily_cap:
        _LOGGER.info(
            "HA Insights mobile push for insight %s deferred: "
            "user=%s already received %d pushes today (cap=%d). "
            "Will surface in the next daily digest.",
            insight.id,
            user_key,
            _DAILY_COUNTERS[counter_key],
            daily_cap,
        )
        return

    payload = _build_payload(insight)
    fired_any = False
    for raw_target in effective_targets:
        target = raw_target.strip()
        if not target.startswith("notify."):
            _LOGGER.debug(
                "Skipping non-notify mobile target %r (must start with "
                "'notify.')",
                target,
            )
            continue
        service = target.split(".", 1)[1]
        try:
            await hass.services.async_call(
                "notify",
                service,
                payload,
                blocking=False,
            )
            fired_any = True
        except Exception:
            _LOGGER.exception(
                "Failed to send HA Insights mobile notification via %s",
                target,
            )

    # Only bump the counter once per insight, not once per phone —
    # the count tracks notification *events* the user experiences
    # (which collapse via tag), not service-call fan-out.
    if fired_any:
        _DAILY_COUNTERS[counter_key] += 1


def get_daily_push_count(
    entry_id: str, user_key: str, local_date: date | None = None
) -> int:
    """Test/diagnostic helper — current count for a counter key.
    Used by the adaptive tuner + smoke tests."""
    key = (entry_id, user_key, local_date or dt_util.as_local(dt_util.utcnow()).date())
    return _DAILY_COUNTERS.get(key, 0)


def reset_daily_counter_for_entry(entry_id: str) -> None:
    """Clear in-memory counters for one entry. Called from unload
    so a reloaded entry starts fresh (otherwise a hot-reload could
    inherit yesterday's stale count if the day hadn't rolled)."""
    keys = [k for k in _DAILY_COUNTERS if k[0] == entry_id]
    for k in keys:
        _DAILY_COUNTERS.pop(k, None)


__all__ = [
    "fire_mobile_notifications",
    "get_daily_push_count",
    "reset_daily_counter_for_entry",
]
