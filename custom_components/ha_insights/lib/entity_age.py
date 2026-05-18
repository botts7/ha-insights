"""Pure helpers for the v1.12.11 newly-added entity badge.

The user reported (and v1.12.9 partially fixed) that detectors firing on
brand-new entities produce confusing recommendations: "shifted 7 days
ago" on an entity that only has 7 days of data is nonsense — the
"before" window is empty.

State_shift already gates internally. The badge surfaces the same
dataset-window awareness to the user so they understand WHY a detector
might stay quiet (or surface a hedged finding) on an entity that hasn't
been around long.

These helpers are pure functions so they're unit-testable without a
running Home Assistant. The HA `entity_registry` lookup lives in
`ws_api.py`; this module only does the math.
"""
from __future__ import annotations

from datetime import UTC, datetime

# How recently must an entity have been added before we surface the
# "newly added" badge? 14 days matches the short-term observation window
# the AutomationAuditDetector uses — once the entity has at least two
# weeks of data, most detectors have enough to make confident calls and
# the badge becomes noise.
NEWLY_ADDED_THRESHOLD_DAYS = 14


def days_since_added(
    created_at: datetime | None,
    *,
    now: datetime | None = None,
) -> int | None:
    """Return the integer days between `created_at` and `now`, or None.

    Returns None when:
    - `created_at` is None (older HA versions without the field)
    - `created_at` is not a datetime
    - `created_at` is in the future (clock skew, registry-restore weirdness)

    The result is floored to whole days; a 6-hour-old entity returns 0,
    matching how the badge reads naturally ("added today" when 0).
    """
    if created_at is None:
        return None
    if not isinstance(created_at, datetime):
        return None
    if now is None:
        now = datetime.now(tz=UTC)
    # Defensive: both must be tz-aware for subtraction to work cleanly.
    if created_at.tzinfo is None or now.tzinfo is None:
        return None
    delta = now - created_at
    if delta.total_seconds() < 0:
        # Future timestamp (clock skew). Treat as "unknown" rather than
        # surfacing a negative-days badge.
        return None
    return delta.days


def is_newly_added(
    created_at: datetime | None,
    *,
    now: datetime | None = None,
    threshold_days: int = NEWLY_ADDED_THRESHOLD_DAYS,
) -> bool:
    """True if the entity was added within `threshold_days`.

    Used by ws_list to decide whether to attach the `entity_age_days`
    field to the insight payload. We don't attach it for entities older
    than the threshold — keeping the payload lean (one fewer field per
    insight) and signaling "no badge" to the card by absence.
    """
    days = days_since_added(created_at, now=now)
    if days is None:
        return False
    return days <= threshold_days
