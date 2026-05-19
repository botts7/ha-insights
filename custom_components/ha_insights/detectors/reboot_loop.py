"""RebootLoopDetector — surface entities flipping unavailable on a regular cadence.

v1.14.1 (May 2026). Pairs with [[ha_insights_connectivity_health]] /
[[unavailable_device_fixit]] roadmap.

## What it flags

An entity whose `→ unavailable` transitions over the last 7 days form
a **regular** pattern: small coefficient-of-variation in their
inter-arrival times. Regularity is the signal that distinguishes a
**config-driven reboot loop** (e.g. a power-cycle schedule or a
watchdog timer firing every N hours) from random outages (ISP flaps,
cloud-API hiccups, power-glitches), which have Poisson-distributed
spacing and therefore high CV.

## Why not just use UnavailableDeviceFixIt's threshold

`UnavailableDeviceFixIt` flags an entity stuck >48h — a passive,
permanently-broken device. A reboot loop is the *opposite* signal:
the entity keeps coming back, but cycles often enough that it's
disruptive. Both are "your home automation is unhealthy" insights;
neither subsumes the other.

## The statistical test

Coefficient of variation (CV = stddev / mean) of inter-arrival times
between consecutive `→ unavailable` transitions.

  - CV ≥ 0.30: too random → skip (likely real outage pattern)
  - CV 0.20–0.30: moderately regular, confidence 0.65
  - CV 0.10–0.20: clearly regular, confidence 0.80
  - CV  < 0.10: tight regularity, confidence 0.92

Plus a sanity gate: median gap must be **<48 h**. A device that
reboots reliably every Sunday at 3am has CV near zero but isn't a
"loop" in the disruptive sense — it's an intentional weekly maintenance
window. The <48 h floor ensures we only flag short-cycle loops users
would actually want to fix.

Plus a minimum-count gate: **≥5 transitions** in the window. Fewer
than that and CV is too noisy to trust (5 samples → ~45% standard
error on stddev under Gaussian assumptions, much worse for Poisson).

## Forward-look

v1.15+ could use [[ha_insights_research_answers_v1]]'s changepoint
detector on the rolling CV to surface **when** a reboot loop began
(config-change attribution, not just current-state).

## Skip rules

Mirrors `UnavailableDeviceFixIt`:

  - Entity in `ctx.blocked_entities` → skipped
  - Entity in excluded domain (automation/script/scene/...) → skipped
  - Registry-disabled / registry-hidden → skipped
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from statistics import mean, median, pstdev
from typing import TYPE_CHECKING

from ..insight import Insight, InsightKind
from .base import Detector, DetectorContext, Maturity, register_detector

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Lookback window. 7 days matches the StateEventBuffer default
# retention; longer would require recorder access.
_LOOKBACK_DAYS = 7

# Minimum number of `→ unavailable` transitions needed to compute a
# trustworthy CV. Below this, the CV estimator's standard error
# blows up.
_MIN_TRANSITIONS = 5

# CV thresholds. Higher CV = more random spacing.
_CV_TIGHT = 0.10
_CV_CLEAR = 0.20
_CV_MAX = 0.30

# Confidence per CV bucket.
_CONFIDENCE_TIGHT = 0.92
_CONFIDENCE_CLEAR = 0.80
_CONFIDENCE_MODERATE = 0.65

# Max median inter-arrival time we'll flag as a "loop". Above this,
# the regularity is probably a scheduled weekly reboot the user wants.
_MAX_MEDIAN_GAP = timedelta(hours=48)

# States that count as "unavailable" — same set as
# UnavailableDeviceFixIt for consistency.
_DIAGNOSTIC_STATES = frozenset({"unavailable", "unknown"})

# Excluded domains — same rationale as UnavailableDeviceFixIt.
_EXCLUDED_DOMAINS = frozenset({
    "automation",
    "script",
    "scene",
    "zone",
    "sun",
    "persistent_notification",
})


@register_detector
class RebootLoopDetector(Detector):
    """Emit one ANOMALY insight per entity with a regular reboot cadence."""

    name = "reboot_loop"
    kind = InsightKind.ANOMALY
    requires_recorder = False
    # v1.14: EXPERIMENTAL. CV thresholds + min-transitions need
    # real-install tuning. Some integrations (cheap cloud cameras,
    # battery PIRs) drop out regularly without it being a "loop".
    maturity = Maturity.EXPERIMENTAL
    description = (
        "Flag entities whose availability flips form a regular cadence "
        "(CV < 0.30 of inter-arrival times). Signals a config-driven "
        "reboot loop or aggressive watchdog timer, not random outages."
    )

    async def scan(self, ctx: DetectorContext) -> list[Insight]:
        if ctx.event_buffer is None:
            return []

        now = datetime.now(tz=UTC)
        cutoff = now - timedelta(days=_LOOKBACK_DAYS)
        e_reg = _try_entity_registry(ctx.hass)
        insights: list[Insight] = []

        # Group `→ unavailable` transitions by entity. Single buffer
        # walk is cheaper than per-entity queries on large installs.
        flips_by_entity: dict[str, list[datetime]] = {}
        for ev in ctx.event_buffer.query(since=cutoff):
            if ev.entity_id in ctx.blocked_entities:
                continue
            if ev.domain in _EXCLUDED_DOMAINS:
                continue
            # Only count INTO unavailable — recovery transitions
            # (unavailable → on) would double the count and dilute CV.
            if ev.new_state not in _DIAGNOSTIC_STATES:
                continue
            if ev.old_state in _DIAGNOSTIC_STATES or ev.old_state is None:
                # old_state=None means bootstrap or first-seen — not a
                # real flip. Same-state transitions don't count either.
                continue
            flips_by_entity.setdefault(ev.entity_id, []).append(ev.timestamp)

        for entity_id, timestamps in flips_by_entity.items():
            if len(timestamps) < _MIN_TRANSITIONS:
                continue
            # Skip user-disabled / -hidden entities. Check here rather
            # than in the buffer walk so the registry isn't queried per
            # event (5 calls per entity flip would be wasteful).
            # `disabled_by` / `hidden_by` are RegistryEntryDisabler /
            # RegistryEntryHider StrEnum instances — *real* values are
            # always `isinstance(..., str)`. The isinstance guard also
            # rejects MagicMock proxies that spuriously test truthy in
            # unit tests (same defensive pattern as
            # physical_device_link.py).
            if e_reg is not None:
                entry = e_reg.async_get(entity_id)
                if entry is not None and (
                    isinstance(getattr(entry, "disabled_by", None), str)
                    or isinstance(getattr(entry, "hidden_by", None), str)
                ):
                    continue

            timestamps.sort()
            gaps = [
                (timestamps[i + 1] - timestamps[i]).total_seconds()
                for i in range(len(timestamps) - 1)
            ]
            if not gaps:
                continue
            mean_gap = mean(gaps)
            if mean_gap <= 0:
                continue  # defensive
            cv = pstdev(gaps) / mean_gap
            median_gap = timedelta(seconds=median(gaps))

            if cv >= _CV_MAX:
                continue  # too random
            if median_gap >= _MAX_MEDIAN_GAP:
                continue  # weekly maintenance, not a loop

            insight = self._build_insight(
                entity_id=entity_id,
                timestamps=timestamps,
                gaps_seconds=gaps,
                cv=cv,
                median_gap=median_gap,
                ctx=ctx,
                e_reg=e_reg,
                now=now,
            )
            if insight is not None:
                insights.append(insight)

        if insights:
            _LOGGER.debug("RebootLoopDetector emitted %d insights", len(insights))
        return insights

    def _build_insight(
        self,
        *,
        entity_id: str,
        timestamps: list[datetime],
        gaps_seconds: list[float],
        cv: float,
        median_gap: timedelta,
        ctx: DetectorContext,
        e_reg,
        now: datetime,
    ) -> Insight | None:
        state = ctx.hass.states.get(entity_id) if hasattr(ctx.hass, "states") else None
        friendly = (
            state.attributes.get("friendly_name") if state is not None else None
        ) or entity_id

        if cv < _CV_TIGHT:
            confidence = _CONFIDENCE_TIGHT
            regularity_label = "tightly regular"
        elif cv < _CV_CLEAR:
            confidence = _CONFIDENCE_CLEAR
            regularity_label = "clearly regular"
        else:
            confidence = _CONFIDENCE_MODERATE
            regularity_label = "moderately regular"

        integration = _integration_for_entity(e_reg, entity_id)
        area_id = _area_for_entity(e_reg, entity_id)

        median_gap_minutes = int(median_gap.total_seconds() // 60)
        median_gap_human = _format_duration(median_gap)
        flips_count = len(timestamps)

        title = (
            f"`{friendly}` reboots every ~{median_gap_human} ({regularity_label}) "
            f"— possible config issue"
        )

        payload = {
            "kind": "reboot_loop",
            "entity_id": entity_id,
            "friendly_name": friendly,
            "flips_count": flips_count,
            "lookback_days": _LOOKBACK_DAYS,
            "median_gap_minutes": median_gap_minutes,
            "median_gap_human": median_gap_human,
            "cv": round(cv, 3),
            "first_flip_iso": timestamps[0].isoformat(),
            "last_flip_iso": timestamps[-1].isoformat(),
            "integration": integration,
            "deeplink_url": (
                f"/config/integrations/integration/{integration}"
                if integration
                else None
            ),
            "deeplink_label": (
                f"Open {integration} integration"
                if integration
                else None
            ),
            "suggested_actions": _suggested_actions(integration),
            "observations": [
                {
                    "kind": "reboot_cadence",
                    "summary": (
                        f"{flips_count} availability flips in "
                        f"{_LOOKBACK_DAYS} d, median {median_gap_human} apart "
                        f"(CV {cv:.2f})"
                    ),
                    "cv": round(cv, 3),
                    "flips_count": flips_count,
                    "median_gap_minutes": median_gap_minutes,
                },
            ],
        }

        fingerprint = {
            "kind": "reboot_loop",
            "entity_id": entity_id,
        }

        return Insight(
            id=Insight.compute_id(InsightKind.ANOMALY, fingerprint),
            kind=InsightKind.ANOMALY,
            detector=self.name,
            area_id=area_id,
            title=title,
            confidence=confidence,
            fingerprint=fingerprint,
            payload=payload,
            payload_format="report",
            created_at=now,
        )


def _format_duration(td: timedelta) -> str:
    total_seconds = int(td.total_seconds())
    if total_seconds < 3600:
        return f"{total_seconds // 60} min"
    if total_seconds < 86400:
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        return f"{hours} h {minutes} min" if minutes else f"{hours} h"
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    return f"{days} d {hours} h" if hours else f"{days} d"


def _try_entity_registry(hass: HomeAssistant):
    try:
        from homeassistant.helpers import entity_registry as er

        return er.async_get(hass)
    except (ImportError, AttributeError, TypeError):
        return None


def _integration_for_entity(e_reg, entity_id: str) -> str | None:
    if e_reg is None:
        return None
    try:
        entry = e_reg.async_get(entity_id)
        if entry is None:
            return None
        platform = getattr(entry, "platform", None)
        return platform if isinstance(platform, str) else None
    except (AttributeError, TypeError):
        return None


def _area_for_entity(e_reg, entity_id: str) -> str | None:
    if e_reg is None:
        return None
    try:
        entry = e_reg.async_get(entity_id)
        if entry is None:
            return None
        aid = getattr(entry, "area_id", None)
        return aid if isinstance(aid, str) else None
    except (AttributeError, TypeError):
        return None


def _suggested_actions(integration: str | None) -> list[str]:
    """Loop-specific suggestions. Distinct from v1.14.0's because the
    failure mode is different — the device IS reaching HA but cycling.
    """
    actions: list[str] = []
    actions.append(
        "Check for a power-cycle schedule on the device or its smart "
        "plug — many users set a daily reboot that ends up looping "
        "every few hours after firmware drift."
    )
    actions.append(
        "Inspect the device's watchdog / keepalive settings. A "
        "watchdog timer firing every N hours will produce exactly "
        "this signature."
    )
    actions.append(
        "If the device is on a Zigbee / Z-Wave mesh, check signal "
        "strength to its parent node. Weak-mesh devices drop and "
        "rejoin in a regular cadence as the mesh re-routes."
    )
    if integration:
        actions.append(
            f"Review the {integration} integration's logs (Settings → "
            f"System → Logs, filter by '{integration}') for repeating "
            f"connection errors."
        )
    else:
        actions.append(
            "Review the entity's integration logs (Settings → System → "
            "Logs) for repeating connection errors."
        )
    actions.append(
        "If this is an ESPHome / Shelly / Tasmota device, OTA-update "
        "to the latest firmware — older firmware revisions sometimes "
        "ship with a memory leak that triggers a daily reboot."
    )
    return actions
