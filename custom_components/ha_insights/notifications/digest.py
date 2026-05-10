"""Daily digest — once-per-day persistent_notification summary.

Aggregates insights added in the last 24h plus all currently-open insights
into a single notification. Fires at the configured hour (default 09:00
local). Suppressed when there's nothing new AND nothing open — silence
is golden.

The notification_id is date-stamped so the user gets at most one digest
per calendar day; re-fires on the same day replace rather than stack.
"""
from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util import dt as dt_util

from ..const import DOMAIN
from ..insight import Insight
from ..store import InsightStore

_LOGGER = logging.getLogger(__name__)

# How far back "new today" reaches when computing the digest. Tied to the
# scheduled hour: a 9am digest covers insights from yesterday 9am onward.
_NEW_WINDOW = timedelta(hours=24)

# How many insight titles to include verbatim in the digest body before
# rolling the rest into a "+ N more" line. Three keeps the notification
# scannable on mobile lock screens.
_MAX_TITLES = 3


def build_digest_message(
    *,
    new_insights: list[Insight],
    open_insights: list[Insight],
) -> str | None:
    """Compose the digest body. Returns None when there's nothing to say.

    Sorts new insights by confidence (desc) so the most-actionable hit
    the top of the title list. The "still open" tail counts insights
    that pre-date the window so users see lingering items they haven't
    addressed.
    """
    if not new_insights and not open_insights:
        return None

    lines: list[str] = []

    if new_insights:
        by_detector: Counter[str] = Counter(i.detector for i in new_insights)
        breakdown = ", ".join(
            f"{count} {detector}" for detector, count in by_detector.most_common()
        )
        lines.append(f"{len(new_insights)} new insight(s) today — {breakdown}")
        sorted_new = sorted(
            new_insights, key=lambda i: i.confidence, reverse=True
        )
        for ins in sorted_new[:_MAX_TITLES]:
            confidence_pct = round(ins.confidence * 100)
            lines.append(f"- {ins.title} ({confidence_pct}%)")
        remainder = len(new_insights) - _MAX_TITLES
        if remainder > 0:
            lines.append(f"- + {remainder} more")
    else:
        lines.append("No new insights today.")

    still_open = [i for i in open_insights if i not in new_insights]
    if still_open:
        lines.append("")
        lines.append(f"{len(still_open)} insight(s) still open from earlier.")

    lines.append("")
    lines.append("Open the HA Insights panel to review.")
    return "\n".join(lines)


async def fire_digest(
    hass: HomeAssistant,
    store: InsightStore,
    *,
    now: datetime | None = None,
) -> dict[str, int] | None:
    """Build and post a daily digest. Returns counts, or None if suppressed.

    `now` is overridable for tests; defaults to wall clock.
    """
    moment = now or datetime.now(tz=UTC)
    cutoff = moment - _NEW_WINDOW
    # notification_id is date-stamped — use local date so a digest fired
    # at 9 AM Pacific on May 10 doesn't end up with a notification_id
    # that conflicts with a digest fired at 9 AM Eastern on May 11 just
    # because UTC has rolled over for the eastern user. v1.0 review #2.
    moment_local = dt_util.as_local(moment)

    open_insights = await store.list_insights()
    new_insights = [i for i in open_insights if i.created_at >= cutoff]

    message = build_digest_message(
        new_insights=new_insights, open_insights=open_insights
    )
    if message is None:
        return None

    notification_id = f"ha_insights_digest_{moment_local.strftime('%Y%m%d')}"
    try:
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "HA Insights — daily digest",
                "message": message,
                "notification_id": notification_id,
            },
            blocking=False,
        )
    except Exception:
        _LOGGER.exception("HA Insights daily digest failed to fire")
        return None

    return {
        "new": len(new_insights),
        "open": len(open_insights),
    }


def schedule_digest(
    hass: HomeAssistant,
    store: InsightStore,
    *,
    hour: int,
) -> Callable[[], None]:
    """Register a daily callback that fires the digest at `hour:00` local.

    Returns the unsubscribe callable. The hour is interpreted in HA's
    configured timezone, matching the user's expectation that "9 AM"
    means their morning. async_track_time_change handles DST.
    """
    hour = max(0, min(23, int(hour)))

    @callback
    def _on_tick(_now: datetime) -> None:
        hass.async_create_task(
            fire_digest(hass, store),
            name=f"{DOMAIN}_digest_fire",
        )

    return async_track_time_change(
        hass, _on_tick, hour=hour, minute=0, second=0
    )


__all__ = [
    "build_digest_message",
    "fire_digest",
    "schedule_digest",
]


# Re-export type so callers don't have to import from collections.abc
DigestCallback = Callable[[], Awaitable[None]]
