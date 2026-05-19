"""UnavailableDeviceFixItDetector — surface entities stuck unavailable/unknown.

v1.14.0 (May 2026). Pairs with [[ha_insights_connectivity_health]] roadmap.

## What it flags

Any entity whose current state is ``"unavailable"`` or ``"unknown"`` and
whose ``last_changed`` is ≥ 48 hours ago. That combination means the
entity entered the diagnostic state, and it's still there — not a
transient outage. The detector emits one anomaly insight per stuck
entity with structured diagnostic guidance: how long it's been stuck,
which integration owns it, plus a deeplink to the integration's
configuration page and a tiered suggested-action list.

## Why now (not just rely on HA's own UI)

HA shows entities in their unavailable state, but does NOT surface
the *duration* prominently. A motion sensor that's been dead for 6
weeks looks identical to one that just flickered offline. This
detector turns "you have 47 unavailable entities" into "8 of them
have been broken for >1 month — here's where to start."

## Confidence tiers

  - 48–72 h:  0.65 (might be a transient outage / power glitch)
  - 72–168 h: 0.78 (3–7 days; user has clearly not noticed)
  - 168–720 h: 0.88 (1–4 weeks; almost certainly broken)
  - 720+ h:   0.95 (4+ weeks; abandoned device or dead hardware)

## Excluded domains

Domains where unavailable/unknown is expected or where the detector
would just add noise. Keep this list short; users can blocklist
specific entities through the existing privacy controls.

  - ``automation`` / ``script`` / ``scene`` / ``zone`` — never have
    these states; if they do, HA is broken, not the device.
  - ``sun`` — derived; transient unknown is a calculation lag.
  - ``persistent_notification`` — UI scaffolding.

``device_tracker`` and ``person`` are NOT excluded — phones going
genuinely "unavailable" (vs not_home / unknown) usually means the
companion app stopped reporting, which IS actionable.

## Skip rules

  - Entity in ``ctx.blocked_entities`` → skipped
  - Entity registry says ``disabled_by`` is set → skipped
    (user already disabled it)
  - Entity registry says ``hidden_by`` is set → skipped
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from ..insight import Insight, InsightKind
from .base import Detector, DetectorContext, Maturity, register_detector

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, State

_LOGGER = logging.getLogger(__name__)

# Trip the detector at 48 hours stuck. Tunable later if real-install
# feedback says lots of legitimate devices have brief multi-hour
# outages (cloud APIs, ISP flaps, etc.).
_HOURS_THRESHOLD = 48

# How far back to query recorder when the live `last_changed` is
# suspect (post-restart reset). HA's recorder retention defaults to
# 10 days; we'd query 14 to also catch installs with extended
# retention. Entities continuously unavailable longer than this
# get a lower-bound timestamp at the start of the window, which
# still trips the 48-hour gate correctly.
_RECORDER_LOOKBACK_DAYS = 14

# How many entity_ids to feed `get_significant_states` per call.
# v1.14.9: on a 1,603-entity install, the single bulk call returned
# silently-empty results — likely a recorder query timing out or
# hitting an internal limit. Batches of 200 keep each call under
# ~1-2 seconds while staying well under any SQLite parameter limit.
# The total scan budget is 30s; up to ~15 batches fit.
_RECORDER_BATCH_SIZE = 200

# Confidence tiers by hours-stuck bucket.
_CONFIDENCE_48_72 = 0.65
_CONFIDENCE_72_168 = 0.78
_CONFIDENCE_168_720 = 0.88
_CONFIDENCE_720_PLUS = 0.95

# States that indicate "device is not reporting cleanly". These come
# from HA Core's STATE_UNAVAILABLE / STATE_UNKNOWN constants — copying
# the string values rather than importing to avoid a fragile Core
# import path.
_DIAGNOSTIC_STATES = frozenset({"unavailable", "unknown"})

# Domains where unavailable/unknown is expected behaviour. See module
# docstring for rationale.
_EXCLUDED_DOMAINS = frozenset({
    "automation",
    "script",
    "scene",
    "zone",
    "sun",
    "persistent_notification",
})


@register_detector
class UnavailableDeviceFixItDetector(Detector):
    """Emit one ANOMALY insight per entity stuck unavailable ≥48h."""

    name = "unavailable_device_fixit"
    kind = InsightKind.ANOMALY
    requires_recorder = False
    # v1.14: EXPERIMENTAL until we have real-install data on what a
    # reasonable threshold is + how often integrations legitimately
    # leave entities unavailable for >48 h.
    maturity = Maturity.EXPERIMENTAL
    description = (
        "Flag entities stuck in 'unavailable' or 'unknown' for 48+ hours "
        "with diagnostic guidance — integration, deeplink, suggested "
        "actions. Turns 'you have 47 unavailable entities' into 'here "
        "are the 8 that have been broken for >1 month, start with these.'"
    )

    async def scan(self, ctx: DetectorContext) -> list[Insight]:
        now = datetime.now(tz=UTC)
        cutoff = now - timedelta(hours=_HOURS_THRESHOLD)
        insights: list[Insight] = []

        e_reg = _try_entity_registry(ctx.hass)

        # Stage 1: gather all currently-unavailable candidates. Live
        # `last_changed` is the first-pass timestamp; entities whose
        # value falls inside (cutoff, now] are SUSPECT — HA recently
        # restarted and some integrations reset `last_changed` on boot
        # even when the entity was unavailable for weeks beforehand.
        # On a 3,378-entity install with 78 integrations, hardware
        # validation showed 1,603 unavailable entities ALL with
        # last_changed <1h after restart — the detector missed every
        # one because the live value lied.
        candidates: list[tuple[State, datetime]] = []
        suspect_eids: list[str] = []
        for state in ctx.hass.states.async_all():
            if state.state not in _DIAGNOSTIC_STATES:
                continue
            entity_id = state.entity_id
            if entity_id in ctx.blocked_entities:
                continue
            domain = entity_id.split(".", 1)[0]
            if domain in _EXCLUDED_DOMAINS:
                continue
            if e_reg is not None:
                entry = e_reg.async_get(entity_id)
                if entry is not None and (
                    entry.disabled_by is not None
                    or entry.hidden_by is not None
                ):
                    continue
            last_changed = getattr(state, "last_changed", None)
            if last_changed is None:
                continue
            candidates.append((state, last_changed))
            if last_changed > cutoff:
                suspect_eids.append(entity_id)

        # Stage 2: for SUSPECT entities, query recorder for the most
        # recent state that wasn't unavailable/unknown. That timestamp
        # is the true "unavailable_since" — entity has been continuously
        # unavailable ever since. Bulk query (one recorder call, not
        # one per entity).
        recorder_unavailable_since: dict[str, datetime] = {}
        if suspect_eids:
            recorder_unavailable_since = await _recorder_unavailable_since(
                ctx.hass,
                suspect_eids,
                lookback_days=_RECORDER_LOOKBACK_DAYS,
                now=now,
            )

        # Stage 3: compute effective unavailable_since per candidate.
        # min(live, recorder) so we prefer the older timestamp when
        # recorder has a clearer picture.
        for state, live_last_changed in candidates:
            effective_since = live_last_changed
            recorder_ts = recorder_unavailable_since.get(state.entity_id)
            if recorder_ts is not None and recorder_ts < live_last_changed:
                effective_since = recorder_ts
            if effective_since > cutoff:
                continue
            insight = self._build_insight(
                state=state,
                last_changed=effective_since,
                now=now,
                ctx=ctx,
                e_reg=e_reg,
            )
            if insight is not None:
                insights.append(insight)

        if insights:
            _LOGGER.debug(
                "UnavailableDeviceFixItDetector emitted %d insights "
                "(%d suspect entities resolved via recorder)",
                len(insights),
                len(suspect_eids),
            )
        return insights

    def _build_insight(
        self,
        *,
        state: State,
        last_changed: datetime,
        now: datetime,
        ctx: DetectorContext,
        e_reg,
    ) -> Insight | None:
        entity_id = state.entity_id
        friendly = state.attributes.get("friendly_name") or entity_id
        hours_stuck = int((now - last_changed).total_seconds() // 3600)

        if hours_stuck >= 720:
            confidence = _CONFIDENCE_720_PLUS
            severity_label = f"unavailable for {hours_stuck // 24} days"
        elif hours_stuck >= 168:
            confidence = _CONFIDENCE_168_720
            severity_label = f"unavailable for {hours_stuck // 24} days"
        elif hours_stuck >= 72:
            confidence = _CONFIDENCE_72_168
            severity_label = f"unavailable for {hours_stuck // 24} days"
        else:
            confidence = _CONFIDENCE_48_72
            severity_label = f"unavailable for {hours_stuck} hours"

        # Integration / area lookups — best-effort, all guarded.
        integration = _integration_for_entity(e_reg, entity_id)
        iot_class = (
            ctx.iot_class_by_integration.get(integration)
            if integration
            else None
        )
        area_id = _area_for_entity(e_reg, entity_id)

        title = f"`{friendly}` {severity_label} — diagnose connection"

        payload = {
            "kind": "unavailable_device_fixit",
            "entity_id": entity_id,
            "friendly_name": friendly,
            "current_state": state.state,
            "last_changed_iso": last_changed.isoformat(),
            "hours_unavailable": hours_stuck,
            "integration": integration,
            "iot_class": iot_class,
            "threshold_hours": _HOURS_THRESHOLD,
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
            "suggested_actions": _suggested_actions(
                domain=entity_id.split(".", 1)[0],
                integration=integration,
                iot_class=iot_class,
            ),
            "observations": [
                {
                    "kind": "unavailable_duration",
                    "summary": severity_label,
                    "hours_unavailable": hours_stuck,
                    "current_state": state.state,
                },
            ],
        }

        fingerprint = {
            "kind": "unavailable_device_fixit",
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


def _try_entity_registry(hass: HomeAssistant):
    """Return the entity registry or None if HA isn't fully set up.

    Defensive — same reasoning as in physical_device_link.py: tests
    feed MagicMock hass objects and registry calls would blow up.
    """
    try:
        from homeassistant.helpers import entity_registry as er

        return er.async_get(hass)
    except (ImportError, AttributeError, TypeError):
        return None


def _integration_for_entity(e_reg, entity_id: str) -> str | None:
    """Return the integration domain for an entity, e.g. 'zha', 'mqtt'."""
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


def _suggested_actions(
    *,
    domain: str,
    integration: str | None,
    iot_class: str | None,
) -> list[str]:
    """Tiered action list. Generic-first, then more specific based on
    integration class. Order matters — the card surfaces the top
    suggestion most prominently.
    """
    actions: list[str] = []

    # Universal first step.
    actions.append("Check the physical device — is it powered, charged, in range?")

    # IoT-class specific guidance.
    if iot_class == "cloud_push" or iot_class == "cloud_polling":
        actions.append(
            "Cloud integration — check the vendor's status page and "
            "your internet connection."
        )
    elif iot_class == "local_push" or iot_class == "local_polling":
        actions.append(
            "Local integration — check the device is on the same "
            "network segment and reachable."
        )

    # Domain-specific hints.
    if domain == "device_tracker" or domain == "person":
        actions.append(
            "If this is a phone, check the Home Assistant Companion "
            "app is running and has background permissions."
        )
    elif domain == "climate" or domain == "humidifier":
        actions.append(
            "HVAC devices often unavailability when their hub or "
            "bridge loses power — check the hub first."
        )

    # Integration restart — works for nearly everything.
    if integration:
        actions.append(
            f"Restart the integration: Settings → Devices & Services "
            f"→ {integration} → ⋮ → Reload."
        )
    else:
        actions.append(
            "Reload the entity's integration: Settings → Devices & "
            "Services → [integration] → ⋮ → Reload."
        )

    # Last resort.
    actions.append(
        "If the device is gone for good, remove the entity from the "
        "device's page so it stops cluttering your dashboards."
    )

    return actions


async def _recorder_unavailable_since(
    hass: HomeAssistant,
    entity_ids: list[str],
    *,
    lookback_days: int,
    now: datetime,
) -> dict[str, datetime]:
    """For each entity_id, return the timestamp of the MOST RECENT
    non-unavailable state in recorder history. Entity has been
    continuously unavailable since at least then.

    Why: HA restart resets ``state.last_changed`` for many
    integrations (Tuya cloud, polling-only integrations, etc.).
    Hardware validation on a 3,378-entity install showed all 1,603
    unavailable entities had post-restart timestamps even though
    many had been dead for weeks. The recorder's ``states`` table
    preserves the true history across restarts.

    If the entity has NO non-unavailable state in the lookback
    window, returns the start of the window — a conservative lower
    bound that still trips the 48-hour gate. Failures (recorder
    unavailable, query timeout, etc.) are swallowed and result in
    that entity being absent from the returned dict; the caller
    then falls back to the live ``last_changed`` for those.

    v1.14.9: chunks entity_ids into batches of ``_RECORDER_BATCH_SIZE``
    to avoid SQLite parameter limits + recorder query timeouts on
    large installs. The previous single-call approach silently
    returned empty results on a 1,603-entity install — failure was
    invisible because we logged at DEBUG. Logging bumped to INFO+
    so future bugs are diagnosable from HA's standard log view.

    Runs on the recorder's executor (per HA core review guidelines)
    so the query cooperates with concurrent writes.
    """
    if not entity_ids:
        return {}

    try:
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.history import (
            get_significant_states,
        )
    except ImportError:
        _LOGGER.info(
            "unavailable_device_fixit: recorder component unavailable; "
            "skipping recorder fallback (live last_changed only)"
        )
        return {}

    start = now - timedelta(days=lookback_days)
    out: dict[str, datetime] = {}

    # Chunk to avoid recorder-query stress on large installs.
    # SQLAlchemy / SQLite handle large IN-clauses fine up to ~32k
    # params, but the QUERY ITSELF (joining states_meta × states for
    # 1,000+ entities over 14 days) can be slow enough to trip the
    # 30s per-detector budget. Batches of 200 keep each query under
    # ~1-2 seconds on a typical install.
    batches = [
        entity_ids[i : i + _RECORDER_BATCH_SIZE]
        for i in range(0, len(entity_ids), _RECORDER_BATCH_SIZE)
    ]
    _LOGGER.info(
        "unavailable_device_fixit: querying recorder for %d suspect "
        "entities in %d batch(es), window=%dd",
        len(entity_ids),
        len(batches),
        lookback_days,
    )

    successful_batches = 0
    total_rows = 0
    failed_batches = 0

    try:
        recorder = get_instance(hass)
    except Exception:
        _LOGGER.warning(
            "unavailable_device_fixit: could not acquire recorder instance",
            exc_info=True,
        )
        return {}

    n_batches = len(batches)
    for batch_idx, batch in enumerate(batches):
        # `batch_eids` + `idx_label` are explicit parameters so the
        # inner closure doesn't capture the loop variable (ruff B023).
        def _query(
            batch_eids: list[str] = batch,
            idx_label: int = batch_idx + 1,
        ) -> dict[str, list] | None:
            try:
                return get_significant_states(
                    hass,
                    start,
                    now,
                    batch_eids,
                    significant_changes_only=False,
                    minimal_response=True,
                    no_attributes=True,
                )
            except Exception as err:
                _LOGGER.warning(
                    "unavailable_device_fixit: recorder query failed "
                    "for batch %d/%d (%d entities): %s",
                    idx_label,
                    n_batches,
                    len(batch_eids),
                    err,
                )
                return None

        try:
            result = await recorder.async_add_executor_job(_query)
        except Exception:
            _LOGGER.warning(
                "unavailable_device_fixit: failed to schedule recorder "
                "query for batch %d/%d",
                batch_idx + 1,
                n_batches,
                exc_info=True,
            )
            failed_batches += 1
            continue

        if not isinstance(result, dict):
            failed_batches += 1
            continue
        successful_batches += 1

        for eid in batch:
            rows = result.get(eid) or []
            total_rows += len(rows)
            most_recent_non_unavail: datetime | None = None
            for row in rows:
                row_state = _row_state_value(row)
                if row_state is None or row_state in _DIAGNOSTIC_STATES:
                    continue
                ts = _row_state_timestamp(row)
                if ts is None:
                    continue
                if (
                    most_recent_non_unavail is None
                    or ts > most_recent_non_unavail
                ):
                    most_recent_non_unavail = ts
            if most_recent_non_unavail is not None:
                out[eid] = most_recent_non_unavail
            elif rows:
                # Recorder has rows but ALL were unavailable/unknown —
                # entity has been continuously dead through the window.
                # Use start as a conservative lower bound.
                out[eid] = start
            # else: no recorder history at all → leave eid absent so
            # the caller falls back to live last_changed.

    _LOGGER.info(
        "unavailable_device_fixit: recorder query complete — "
        "%d/%d batches successful, %d total rows scanned, "
        "%d entities resolved (%d will fall back to live last_changed)",
        successful_batches,
        len(batches),
        total_rows,
        len(out),
        len(entity_ids) - len(out),
    )
    if failed_batches:
        _LOGGER.warning(
            "unavailable_device_fixit: %d/%d recorder batches FAILED",
            failed_batches,
            len(batches),
        )
    return out


def _row_state_value(row) -> str | None:
    """Extract the state value from one recorder row.

    Modern recorder returns State objects; ``minimal_response=True``
    returns dicts with a ``state`` key. Tolerate both.
    """
    if hasattr(row, "state"):
        s = row.state
        return s if isinstance(s, str) else None
    if isinstance(row, dict):
        s = row.get("state")
        return s if isinstance(s, str) else None
    return None


def _row_state_timestamp(row) -> datetime | None:
    """Extract the timestamp from one recorder row. Mirrors the
    pattern in ``audit/rollup.py:_state_timestamp`` for consistency."""
    if hasattr(row, "last_changed") and row.last_changed is not None:
        return row.last_changed
    if isinstance(row, dict):
        for key in ("last_changed", "last_updated"):
            v = row.get(key)
            if isinstance(v, str):
                try:
                    return datetime.fromisoformat(v.replace("Z", "+00:00"))
                except ValueError:
                    continue
            elif isinstance(v, datetime):
                return v
    return None
