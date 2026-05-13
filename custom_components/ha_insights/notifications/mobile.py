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
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant

from ..insight import Insight

_LOGGER = logging.getLogger(__name__)

# URI scheme that opens HA Insights panel inside the mobile app.
# Mobile-app integration treats `/<panel_path>` paths as in-app links.
_PANEL_DEEP_LINK = "/ha-insights"


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


async def fire_mobile_notifications(
    hass: HomeAssistant,
    insight: Insight,
    *,
    notify_services: list[str],
) -> None:
    """Send `insight` to each entry in `notify_services` (e.g.
    ['notify.mobile_app_iphone']). Best-effort; per-service errors
    are logged and skipped.

    When `insight.target_user_id` is set, the call is rerouted to
    ONLY that user's mobile_app services (intersected with
    `notify_services` if non-empty so user opt-out is still
    honored). This is the multi-user safeguard: "your phone is
    about to die" must reach the phone's owner, not their housemate.

    Empty effective target list is a no-op — keeps the call site
    clean for users who haven't opted in and avoids broadcasting to
    the wrong person when user-routing finds no match.
    """
    from .user_routing import resolve_notify_targets

    target_user_id = getattr(insight, "target_user_id", None)
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
    payload = _build_payload(insight)
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
        except Exception:  # noqa: BLE001
            _LOGGER.exception(
                "Failed to send HA Insights mobile notification via %s",
                target,
            )


__all__ = ["fire_mobile_notifications"]
