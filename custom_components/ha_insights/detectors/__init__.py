"""Detector registry. Auto-imports sibling modules so they self-register.

The discovery + import side effects are sync I/O (`pkgutil.iter_modules`
does `os.listdir`; `importlib.import_module` does file I/O), so they
must NOT run on the event loop. v1.0 review caught this — HA logs
"blocking call to listdir" warnings on every cold start. Moved off
the import path so callers explicitly run discovery via the executor.
"""
from __future__ import annotations

import asyncio
import importlib
import logging
import pkgutil
from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING

from homeassistant.core import CoreState, HomeAssistant

from .base import DETECTORS, Detector, DetectorContext, register_detector

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from ..observers.state_event_buffer import StateEvent
    from ..store import InsightStore

_LOGGER = logging.getLogger(__name__)

# Per-detector wall-clock budget. A detector that exceeds this is logged
# and skipped — we cannot hard-cancel a Python thread, but we stop awaiting
# it so the rest of the scan + the event loop can proceed.
_DETECTOR_TIMEOUT_SEC = 30.0

# v1.12.10 — Confidence floor for "filler" suppression. Insights with
# `conflicts_with` (already automated) OR `_timing_assessment.timing_class
# == "device_likely"` (managed by device's own logic) below this
# confidence are pure noise: the user can't apply them (the action is
# already covered) and can't trust the pattern (low confidence).
# Real-install testing 2026-05-17 produced ~5 such filler insights at
# 10-15% confidence on every scan. Caught alongside the v1.12.9
# state_shift false positive fix.
_FILLER_INSIGHT_MAX_CONFIDENCE: float = 0.50


def _is_low_confidence_filler(insight: object) -> bool:
    """Return True when an insight should be dropped as filler.

    The user explicitly tested v1.12.8 and reported these filler
    types in their panel:
      - schedule at 10% on switch.main_room_led_bar with
        `🔁 already automated` pill
      - streak at 11% on light.back_garden_lights with
        `🤖 device-managed` pill
      - streak at 10% on switch.inverter with `🤖 device-managed`

    None had action value: the pattern is either already automated
    or device-internal logic, AND the detector wasn't even confident
    in the pattern itself. Drop them rather than make the user
    filter them out by hand.

    v1.12.12 fix: previously this checked only
    `_timing_assessment.timing_class == "device_likely"`, but the
    card's actual "🤖 device-managed" pill triggers across SIX signal
    classes (3 strong + 4 soft stacked). A streak with
    `persistence_class=fixed_cycle` (e.g. user's inverter at 10%)
    rendered the pill but escaped this filter. Now reads the
    canonical `_is_device_managed` field stamped by
    `HumanLikelihoodFeatures.payload_keys()` — or falls back to a
    full recompute via `is_device_managed()` so older stored
    insights (pre-v1.12.12) without the canonical field are still
    correctly filtered.
    """
    confidence = getattr(insight, "confidence", 1.0)
    if confidence >= _FILLER_INSIGHT_MAX_CONFIDENCE:
        return False  # confidence is good enough on its own
    # Shadowed by existing automation?
    conflicts = getattr(insight, "conflicts_with", ())
    if conflicts:
        return True
    # Device-managed verdict — canonical field first, then full
    # recompute for legacy payloads.
    payload = getattr(insight, "payload", None)
    if isinstance(payload, dict):
        canonical = payload.get("_is_device_managed")
        if canonical is True:
            return True
        if canonical is None:
            # Pre-v1.12.12 payload — recompute from the assessment
            # blocks to match the card's actual rendering rule.
            from ..lib.device_managed_signal import is_device_managed

            if is_device_managed(payload):
                return True
    return False


class _FrozenBufferView:
    """Read-only iterable view over a buffer snapshot.

    Drop-in replacement for `StateEventBuffer` from a detector's POV —
    every detector only calls `.query(since=...)`, so that's the only
    method we implement. Iterates a frozen tuple snapshot taken on the
    event loop, so worker threads can scan without touching the live
    deque.

    Filter responsibilities (applied transparently in `query`):
      - `blocked_entities`: events for these entity_ids never reach
        any detector. The user's privacy floor + their scan-scope
        opt-out are unified — consistent with what users expect
        "block this entity" to mean.
      - `area_filter`: if non-empty, only events whose `area_id` is
        in the set pass through. Empty set = no area scoping (current
        default for installs that haven't configured CONF_SCAN_AREAS).

    GIL discipline:
      Even though the detector runs in a worker thread, CPython's GIL
      means it competes with the main event loop for execution. The
      GIL auto-releases every ~5ms (sys.getswitchinterval), but a
      thread can re-grab it instantly, starving the loop. To make the
      worst case predictable, query() explicitly yields the GIL via
      `time.sleep(0)` every _GIL_YIELD_EVERY events.
    """

    __slots__ = ("_area_filter", "_blocked_entities", "_events")

    # Yield the GIL every N events. Tuned for ~1ms wall-clock between
    # yields on representative hardware — frequent enough that the
    # main loop never waits long, infrequent enough that the modulo
    # overhead is invisible against the per-event work detectors do.
    _GIL_YIELD_EVERY = 2_000

    def __init__(
        self,
        events: tuple[StateEvent, ...],
        *,
        blocked_entities: frozenset[str] = frozenset(),
        area_filter: frozenset[str] = frozenset(),
    ) -> None:
        self._events = events
        self._blocked_entities = blocked_entities
        self._area_filter = area_filter

    def query(
        self,
        *,
        entity_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        include_bootstrap: bool = False,
    ) -> Iterator[StateEvent]:
        """Mirror StateEventBuffer.query semantics over the snapshot.

        `include_bootstrap=False` (default) skips events that fired
        during HA's boot fan-out (every entity platform writing its
        restored state in the first ~5 seconds with old_state=None).
        Without this, every restart looks like a correlated burst —
        cooccurrence flags every "B follows A within 1s" pair,
        frequency_anomaly + streak detect a "midnight startup
        routine", etc. See docs/HA_EVENT_SEMANTICS.md Gotcha 5.

        Detectors that genuinely want to OBSERVE bootstrap events
        (a future "boot health" detector, e.g.) can opt back in
        with include_bootstrap=True.
        """
        import time as _time

        for i, ev in enumerate(self._events):
            if i and i % self._GIL_YIELD_EVERY == 0:
                _time.sleep(0)
            if ev.entity_id in self._blocked_entities:
                continue
            if self._area_filter and ev.area_id not in self._area_filter:
                continue
            if entity_id is not None and ev.entity_id != entity_id:
                continue
            if since is not None and ev.timestamp < since:
                continue
            if until is not None and ev.timestamp >= until:
                continue
            if not include_bootstrap and getattr(ev, "from_bootstrap", False):
                continue
            yield ev

    def __len__(self) -> int:
        return len(self._events)


def _run_detector_in_thread(
    detector_cls: type[Detector], ctx: DetectorContext
) -> list:
    """Worker-thread entrypoint for one detector.

    Detectors are declared `async def scan` but their bodies are pure
    sync CPU work (no internal awaits). To run them off the event loop,
    we spin up a private event loop in the worker thread via
    `asyncio.run`. Cheap setup; no recursion into HA's loop.
    """
    return asyncio.run(detector_cls().scan(ctx))


def load_builtin_detectors() -> None:
    """Import every sibling module so it can self-register via decorator.

    Idempotent — registering the same Detector twice is a no-op (see
    `register_detector`'s same-class identity check). Safe to call
    multiple times across multi-entry setups; the call site uses a flag
    to limit it to once per HA boot anyway.

    Sync function — call via `hass.async_add_executor_job` from the
    event loop. Doing this on the loop trips HA's blocking-call
    detector and warns the user every startup.
    """
    for module_info in pkgutil.iter_modules(__path__):
        if module_info.name.startswith("_") or module_info.name == "base":
            continue
        importlib.import_module(f"{__name__}.{module_info.name}")


async def run_all_detectors(
    hass: HomeAssistant,
    ctx: DetectorContext,
    store: InsightStore,
    *,
    allow_during_setup: bool = False,
    entry: ConfigEntry | None = None,
    cancel_event: asyncio.Event | None = None,
    return_summary: bool = False,
) -> int | dict[str, int]:
    """Fan out a single scan pass across every registered detector.

    THE single chokepoint for running detectors against a buffer. All
    callers (service handler, future scheduler, post-backfill hook)
    must go through this so the off-loop discipline is enforced in one
    place — never inline a `for d in DETECTORS.values(): scan` loop.

    Threading model (post-2026-05-10 incident):
      Detectors do CPU-bound iteration over the event buffer (up to
      500K events × N entities). Even with yields between detectors,
      a single detector's hot path can starve the event loop for tens
      of seconds on a large install — that's how prod HA's WS API
      froze and frontend hung on the loading spinner.

      Each detector now runs on a worker thread via `asyncio.to_thread`.
      The buffer is snapshotted ONCE on the event loop (cheap O(n)
      tuple copy from the deque); all detectors then scan that
      immutable snapshot, so concurrent state-event appends to the
      live buffer can't race the scan. Insight inserts to the store
      happen back on the loop after each detector returns.

      Per-detector watchdog: 30s wall-clock budget. Exceeding it logs
      and skips that detector. Python can't hard-cancel a thread, so
      the runaway thread keeps consuming CPU until it returns — but
      the rest of the scan and the entire event loop are unaffected.

    Setup-phase guard:
      Refuses to run before `CoreState.running` (i.e. before HA has
      finished startup and `EVENT_HOMEASSISTANT_STARTED` has fired).
      Heavy CPU loops in the setup path are a recurring footgun even
      with threading — startup is bursty enough as-is. Defer triggers
      to STARTED. Pass `allow_during_setup=True` only if you genuinely
      understand the cost (e.g. a one-event smoke test).

    Returns the number of insights added.
    """
    if not allow_during_setup and hass.state is not CoreState.running:
        raise RuntimeError(
            "run_all_detectors() called before HA is fully started "
            f"(hass.state={hass.state}). Defer your trigger to "
            "EVENT_HOMEASSISTANT_STARTED, or pass allow_during_setup=True "
            "if you accept the event-loop-starvation risk."
        )

    # Layer 1 implicit blocklist: auto-skip diagnostic/config/noise-class
    # entities so a fresh install isn't immediately drowned in heartbeat
    # patterns and battery drift. Merged with the user's explicit blocklist
    # so explicit + implicit work additively.
    from .implicit_blocklist import build_implicit_blocklist

    implicit_blocked = await build_implicit_blocklist(hass)
    effective_blocked: frozenset[str] = ctx.blocked_entities | implicit_blocked

    # entity_id -> device_id map for "same-device pair" filtering in
    # cooccurrence detectors. A relay board's two channels firing
    # together produces 5 noisy "B follows A" insights at ~0s delta
    # that are really one hardware event. With this map the cooccurrence
    # detector can drop pairs that share a device_id.
    device_id_by_entity: dict[str, str | None] = {}
    try:
        from homeassistant.helpers import entity_registry as er

        registry = er.async_get(hass)
        for ent in registry.entities.values():
            device_id_by_entity[ent.entity_id] = ent.device_id
    except Exception:  # pragma: no cover — defensive
        pass  # cooccurrence falls back to its sub-second-delta filter

    # v1.2 — single authoritative entity-hierarchy view backed by HA's
    # registries (entity, device, area, floor, label) plus state-machine
    # group/scene relationships and script targets. Detectors increasingly
    # use this instead of the older scattered dicts; both coexist during
    # the migration. Cached on hass.data so ws_list can reuse without
    # rebuilding.
    from .hierarchy import build_hierarchy

    hierarchy = build_hierarchy(hass)
    _LOGGER.info(
        "HA Insights: built entity hierarchy "
        "(%d entities, %d devices, %d areas, %d floors, %d integrations)",
        len(hierarchy.device_of),
        len(hierarchy.entities_on_device),
        len(hierarchy.entities_in_area),
        len(hierarchy.entities_on_floor),
        len(hierarchy.entities_from_integration),
    )
    # Stash on hass.data so ws_list can reuse without re-walking the
    # registries. Expires implicitly when the next scan rebuilds.
    if entry is not None:
        from ..const import DOMAIN as _DOMAIN

        entry_data = hass.data.get(_DOMAIN, {}).get(entry.entry_id)
        if isinstance(entry_data, dict):
            entry_data["hierarchy"] = hierarchy

    # Entity dependency map. Walks the state machine looking for entities
    # that reference other entities via standard HA conventions:
    #   - attributes.entity_id is a list (groups, group_light, group_cover)
    #   - attributes.source / source_entity_id (statistics, utility_meter,
    #     integration sensors, derive sensors)
    # Pairs of entities connected by ANY dependency edge are dropped from
    # cooccurrence at pair-discovery — the second entity isn't really
    # "responding to" the first, it's just reflecting the same underlying
    # event.
    entity_dependencies = _build_entity_dependencies(hass)
    container_to_members = _build_container_map(hass)
    if entity_dependencies:
        # Count edges so a one-line log gives a sense of scale; helps
        # diagnose "why is cooccurrence still finding this pair?"
        edge_count = sum(len(v) for v in entity_dependencies.values()) // 2
        _LOGGER.info(
            "HA Insights: built dependency map for %d entities (~%d edges, "
            "%d containers)",
            len(entity_dependencies),
            edge_count,
            len(container_to_members),
        )

    # Load existing automations once per scan so we can:
    #   1. Pass to TriggerDriftDetector etc via ctx.existing_automations
    #   2. Mark detector emissions with conflicts_with after the run
    # Read off the loop via the helper (executor for YAML I/O); cheap.
    existing_automations = await _load_existing_automations(hass)

    # v1.5.22: load iot_class for every integration the hierarchy
    # knows about, on the MAIN event loop. Detectors that need it
    # (cross-integration audit) read from ctx.iot_class_by_integration
    # instead of awaiting async_get_integration from inside a
    # worker-thread event loop — that caused a deadlock-style hang
    # that hit the 30s detector budget on installs with many
    # integrations.
    iot_class_by_integration: dict[str, str] = {}
    try:
        from homeassistant.loader import async_get_integration

        domains = {
            d
            for d in hierarchy.integration_of.values()
            if isinstance(d, str) and d
        }
        # Yield to the loop between each integration load. async_get_integration
        # may schedule executor jobs for manifest reads; yielding keeps the
        # WS API responsive even if disk is slow on the user's install.
        for domain in domains:
            try:
                integration = await async_get_integration(hass, domain)
                iot_class = getattr(integration, "iot_class", None)
                if isinstance(iot_class, str):
                    iot_class_by_integration[domain] = iot_class
            except Exception:
                # Custom integration not installed / manifest missing —
                # skip and let the audit observation treat as unknown.
                continue
            await asyncio.sleep(0)
    except Exception:  # pragma: no cover — defensive
        _LOGGER.exception("HA Insights: iot_class load failed (non-fatal)")
    if existing_automations:
        _LOGGER.info(
            "HA Insights scan: %d existing automations loaded "
            "(for trigger_drift + duplicate annotation)",
            len(existing_automations),
        )

    # Snapshot the buffer ONCE on the loop, then hand the immutable
    # view to every detector. ~50 MB tuple-copy at the 500K cap — fast
    # enough to do on the loop, since it's a single memcpy of pointers.
    # The view also enforces blocked_entities and area_filter, so every
    # detector gets the same scoped data without per-detector code.
    snapshot_ctx = replace(
        ctx,
        blocked_entities=effective_blocked,
        device_id_by_entity=device_id_by_entity,
        existing_automations=existing_automations,
        entity_dependencies=entity_dependencies,
        container_to_members=container_to_members,
        hierarchy=hierarchy,
        iot_class_by_integration=iot_class_by_integration,
    )
    if ctx.event_buffer is not None:
        snapshot = ctx.event_buffer.snapshot()
        _LOGGER.info(
            "HA Insights scan: snapshotted %d events for thread-safe scan "
            "(blocked=%d explicit + %d implicit, area_filter=%d)",
            len(snapshot),
            len(ctx.blocked_entities),
            len(implicit_blocked),
            len(ctx.area_filter),
        )
        snapshot_ctx = replace(
            snapshot_ctx,
            event_buffer=_FrozenBufferView(
                snapshot,
                blocked_entities=effective_blocked,
                area_filter=ctx.area_filter,
            ),
            device_id_by_entity=device_id_by_entity,
            existing_automations=existing_automations,
            entity_dependencies=entity_dependencies,
        )

    enabled = None
    allow_experimental = False
    managed_externally_devices: frozenset[str] = frozenset()
    if entry is not None:
        # Lazy import to avoid circular at module-load time.
        from ..config_flow import (
            CONF_MANAGED_EXTERNALLY_DEVICES,
            get_allow_experimental_detectors,
            get_enabled_detectors,
        )

        enabled = get_enabled_detectors(entry)
        allow_experimental = get_allow_experimental_detectors(entry)
        # v1.7.7: user-marked devices to suppress entirely.
        raw_managed = entry.options.get(CONF_MANAGED_EXTERNALLY_DEVICES, [])
        if isinstance(raw_managed, (list, tuple, set)):
            managed_externally_devices = frozenset(
                d for d in raw_managed if isinstance(d, str)
            )

    buffer_size = (
        len(ctx.event_buffer.snapshot()) if ctx.event_buffer is not None else 0
    )
    # The snapshot above duplicates work done at ctx-build time, but is
    # cheap (~3ms at 340K events). Avoids threading the size through the
    # snapshot_ctx wrap above, which is harder to read.

    added = 0
    suppressed_as_duplicate = 0
    # Track which detectors completed end-to-end + the IDs they emitted.
    # After the loop we hand both to the store so it can sweep stale
    # active insights from JUST those detectors. Detectors that didn't
    # run (disabled, timed out, ceiling-skipped, canceled) keep their
    # historical insights — we have no fresh signal that those are stale.
    completed_detectors: set[str] = set()
    emitted_ids: set[str] = set()
    for name, detector_cls in DETECTORS.items():
        if cancel_event is not None and cancel_event.is_set():
            _LOGGER.info("HA Insights scan canceled by user before %r", name)
            break
        if enabled is not None and name not in enabled:
            _LOGGER.debug("Detector %r disabled by config; skipping", name)
            continue
        # Experimental gate. Detectors marked Maturity.EXPERIMENTAL
        # only run when the user has flipped the global opt-in OR
        # explicitly named the detector in CONF_ENABLED_DETECTORS.
        # Off by default so new installs aren't surprised by
        # unverified output. Lazy import — Maturity is only needed
        # if we have at least one EXPERIMENTAL detector registered.
        from .base import Maturity as _Maturity

        explicitly_enabled = enabled is not None and name in enabled
        if (
            getattr(detector_cls, "maturity", _Maturity.STABLE)
            == _Maturity.EXPERIMENTAL
            and not allow_experimental
            and not explicitly_enabled
        ):
            _LOGGER.debug(
                "Skipping experimental detector %r: opt-in required "
                "(set allow_experimental_detectors or add to "
                "CONF_ENABLED_DETECTORS)",
                name,
            )
            continue
        # Self-protective: skip detectors whose declared scale ceiling
        # is below current buffer size. User can override via explicit
        # opt-in in CONF_ENABLED_DETECTORS.
        max_buf = getattr(detector_cls, "max_buffer_for_full_scan", None)
        if max_buf is not None and buffer_size > max_buf and not explicitly_enabled:
            _LOGGER.info(
                "HA Insights skipping detector %r: buffer %d > scale ceiling %d. "
                "Enable explicitly via CONF_ENABLED_DETECTORS to force-run.",
                name,
                buffer_size,
                max_buf,
            )
            continue
        try:
            insights = await asyncio.wait_for(
                asyncio.to_thread(_run_detector_in_thread, detector_cls, snapshot_ctx),
                timeout=_DETECTOR_TIMEOUT_SEC,
            )
        except TimeoutError:
            _LOGGER.warning(
                "HA Insights detector %r exceeded %.0fs budget; skipping. "
                "The thread will continue until it returns naturally but "
                "won't block the event loop.",
                name,
                _DETECTOR_TIMEOUT_SEC,
            )
            continue
        except Exception:
            _LOGGER.exception("HA Insights detector %r failed", name)
            continue

        # This detector ran end-to-end. Track its name + emitted ids so
        # the post-loop sweep can replace its prior active insights.
        completed_detectors.add(name)

        # v1.7.7: user-marked-managed device suppression. Filter out any
        # insight that references an entity belonging to a device the
        # user has flagged "managed externally". Different from the
        # automatic DEVICE_LIKELY pill which only demotes confidence —
        # a user assertion is final. Insights from these devices never
        # enter the store. Stale active insights from a newly-flagged
        # device get cleaned up by the post-loop sweep on next scan.
        if managed_externally_devices:
            from ..lib.managed_externally import filter_insights as _filter_managed

            device_of_map: dict[str, str | None] = {}
            if hierarchy is not None:
                device_of_map = dict(hierarchy.device_of)
            elif device_id_by_entity:
                device_of_map = dict(device_id_by_entity)
            insights, suppressed_by_managed = _filter_managed(
                insights, managed_externally_devices, device_of_map
            )
            if suppressed_by_managed:
                _LOGGER.debug(
                    "Detector %r: dropped %d insights from user-managed devices",
                    name,
                    len(suppressed_by_managed),
                )

        # Group dedup: if N insights from this detector share fingerprint
        # (modulo entity_id) AND their entities all live under a common
        # scene/group, collapse them into one representative insight
        # tagged with "(+N similar members of <parent>)". Catches the
        # 7 garden lights all firing the same 17:34 streak — they
        # belong to one user routine, not seven.
        insights = _dedup_grouped_insights(
            insights,
            entity_dependencies,
            container_to_members,
            device_id_by_entity,
            hierarchy_for_dedup=hierarchy,
        )
        for insight in insights:
            # Annotate (don't suppress) insights that match an existing
            # automation — the user might want to know HA noticed the
            # pattern even if they already automated it (validates the
            # automation; lets them refine or replace). Card surfaces
            # `conflicts_with` as a "shadowed by automation" pill so the
            # user can filter them out if they want.
            #
            # Switched from suppress to annotate after a 1000-entity
            # install reported 0 insights post-restart — the broader
            # registry-based automation read was now catching most
            # patterns and dropping them silently, leaving the user
            # confused about whether anything was working.
            if existing_automations:
                from ..apply.conflict_scanner import find_conflicts

                # v1.5.24: pass hierarchy.members_of so the scanner
                # can expand group/scene entity_ids to their members.
                # Without this, `light.backyard_garden_lights` (a group)
                # never matched an existing automation that targeted
                # individual lights — both meant "same intent" but the
                # literal set-intersection missed it.
                conflicts = find_conflicts(
                    insight,
                    existing_automations,
                    members_of=container_to_members,
                )
                if conflicts:
                    suppressed_as_duplicate += 1
                    # v1.5.42: strip the trailing "Automate this?" CTA
                    # on shadowed insights at emission time so the
                    # canonical stored title reads cleanly for every
                    # downstream consumer — WS list, persistent_
                    # notification toast, mobile push, daily digest.
                    # The previous WS-layer strip ran post-cohort-
                    # merge with an end-anchored regex; cohort-merged
                    # titles ended in "(+N similar entities: ...)" and
                    # the regex no-op'd, leaking the contradictory CTA
                    # to every notification path. `strip_already_
                    # automated_cta` from lib/title_cleanup is suffix-
                    # aware.
                    from ..lib.title_cleanup import (
                        strip_already_automated_cta,
                    )

                    insight = replace(
                        insight,
                        conflicts_with=tuple(conflicts),
                        title=strip_already_automated_cta(insight.title),
                    )

            # v1.12.10 — drop low-confidence filler before persisting.
            # See `_is_low_confidence_filler` docstring for rationale.
            if _is_low_confidence_filler(insight):
                continue

            await store.add_insight(insight)
            emitted_ids.add(insight.id)
            added += 1

    if suppressed_as_duplicate:
        # We no longer suppress these — they're annotated with
        # conflicts_with and shown in the panel with a "shadowed" pill.
        # Naming kept for backwards compat with the WS response field.
        _LOGGER.info(
            "HA Insights scan: %d insights shadowed by existing automations "
            "(stored, marked, NOT suppressed — user can filter via panel)",
            suppressed_as_duplicate,
        )

    # Sweep stale active insights from the detectors that ran. Applied,
    # dismissed, and unexpired-snoozed insights are preserved (user
    # actions outweigh staleness). Detectors that didn't run keep their
    # prior insights untouched (no fresh signal).
    #
    # SAFETY: skip the sweep entirely if the buffer was nearly empty
    # during the scan. An empty buffer makes every detector return [],
    # which would then trigger sweeping ALL prior insights — silently
    # nuking the user's data. Common cause: integration reload created
    # a fresh empty buffer, user clicked Scan before backfill completed.
    # Threshold of 100 is generous; even a tiny install has >100 events
    # within minutes of normal operation.
    if buffer_size < 100:
        _LOGGER.warning(
            "HA Insights scan: buffer only had %d events; skipping the "
            "sweep step to protect existing insights from being deleted "
            "(probably a reload before backfill completed; click Backfill "
            "to repopulate, then Scan)",
            buffer_size,
        )
        swept = 0
    else:
        swept = await store.replace_active_insights_for_detectors(
            completed_detectors=frozenset(completed_detectors),
            emitted_ids=frozenset(emitted_ids),
        )
        if swept:
            _LOGGER.info(
                "HA Insights scan: swept %d stale active insights "
                "(no longer emitted by their detector)",
                swept,
            )

    # Sync audit findings to HA's Repairs registry so users see them
    # in Settings → Repairs alongside HA's standard issue notifications.
    # Idempotent — no-op when nothing changed. Errors are swallowed
    # inside sync_audit_issues so a Repairs failure can't break a scan.
    try:
        from ..audit.repairs import sync_audit_issues

        current_insights = await store.list_insights(
            include_dismissed=False,
            include_applied=False,
            include_snoozed=False,
        )
        sync_audit_issues(
            hass,
            [i for i in current_insights if i.detector == "automation_audit"],
        )
    except Exception as err:
        _LOGGER.debug("audit Repairs sync skipped: %s", err)

    if return_summary:
        return {
            "added": added,
            "swept_stale": swept,
            "suppressed_as_duplicate": suppressed_as_duplicate,
            "completed_detectors": len(completed_detectors),
        }
    return added


# Maximum group size where members are treated as siblings of each
# other. A 3-light bathroom group, a 4-cover blinds group: yes,
# co-firing IS noise to filter. A 50-member "all_motion" aggregate:
# no, those are independent physical events the user wants to know
# about. The cutoff should be wider than typical room groups but
# narrower than house-wide aggregates.
_MAX_GROUP_SIZE_FOR_SIBLING_FILTER = 6


def _common_entity_prefix(entity_ids: list[str]) -> str | None:
    """Longest common prefix across entity_ids (post-domain). Useful as a
    friendly device label when N entities all share the same name root,
    e.g. `binary_sensor.nvr_camera_*` (33 entities) or
    `switch.front_door_*` (3 entities). Returns None for prefixes < 4
    chars (too generic to be useful) or when the input set spans
    multiple domains.
    """
    if len(entity_ids) < 2:
        return None
    domains = {eid.split(".", 1)[0] for eid in entity_ids if "." in eid}
    if len(domains) != 1:
        return None
    domain = next(iter(domains))
    names = [eid.split(".", 1)[1] for eid in entity_ids if "." in eid]
    if not names:
        return None
    prefix = names[0]
    for n in names[1:]:
        while prefix and not n.startswith(prefix):
            prefix = prefix[:-1]
        if not prefix:
            return None
    prefix = prefix.rstrip("_")
    if len(prefix) < 4:
        return None
    return f"{domain}.{prefix}_*"


def _find_common_container(
    entity_ids: list[str],
    entity_dependencies: dict[str, frozenset[str]],
    container_to_members: dict[str, frozenset[str]] | None = None,
    device_id_by_entity: dict[str, str | None] | None = None,
) -> str | None:
    """Return a parent (scene, group, group_light) that contains every
    entity in entity_ids — or None if no single container covers them all.

    A "container" of entity X is any entity whose dependency set lists X
    as a member. The dep map is symmetric (parent ↔ child + sibling ↔
    sibling for small groups), but a TRUE container's dep set will
    contain ALL the input entities — siblings only have one of them
    (themselves). That distinguishes parents from siblings.

    Two cases handled:
      1. One of the inputs IS itself the parent of the others. E.g.,
         [light.porch_lights, light.porch] — porch_lights is the
         container, porch is its member. Returns light.porch_lights.
      2. A third-party container holds all inputs. E.g.,
         [light.lamp_a, light.lamp_b] both members of light.bedroom_group
         (which isn't itself in the input list). Returns
         light.bedroom_group.
    """
    if len(entity_ids) < 2:
        return None

    # Case 0: all inputs share the same HA `device_id`. Strongest signal
    # — entities literally living on the same physical device, even
    # when their fingerprints don't match a state-machine container
    # (e.g., NVR with 33 binary_sensors silent at once, front door
    # device with 3 mode switches). Use the longest common entity-id
    # prefix as a human-readable hint instead of a UUID.
    if device_id_by_entity:
        # v1.5.23 bugfix: don't discard None from the set — see
        # hierarchy.find_common_parent for the rationale. Tuya pet
        # feeder + two group lights got merged because the groups
        # have no device, and the previous code absorbed them.
        device_ids = {device_id_by_entity.get(eid) for eid in entity_ids}
        if None not in device_ids and len(device_ids) == 1:
            shared = next(iter(device_ids))
            if shared:
                prefix_label = _common_entity_prefix(entity_ids)
                if prefix_label:
                    return prefix_label
                return f"device:{shared}"

    # Case 1: one input is the parent of the others. Use the strict
    # container_to_members map so we know it's a real parent (not a
    # sibling false-positive).
    if container_to_members:
        for candidate in entity_ids:
            members = container_to_members.get(candidate, frozenset())
            if not members:
                continue
            if all(eid == candidate or eid in members for eid in entity_ids):
                return candidate

    # Case 2: third-party container. Intersection of dep sets, then pick
    # the one whose own deps contain every input.
    common: frozenset[str] | None = None
    for eid in entity_ids:
        deps = entity_dependencies.get(eid, frozenset())
        if common is None:
            common = deps
        else:
            common = common & deps
        if not common:
            return None
    if common is None:
        return None
    for candidate in sorted(common):
        cand_deps = entity_dependencies.get(candidate, frozenset())
        if all(eid in cand_deps for eid in entity_ids):
            return candidate
    return None


def _dedup_grouped_insights(
    insights: list,
    entity_dependencies: dict[str, frozenset[str]],
    container_to_members: dict[str, frozenset[str]] | None = None,
    device_id_by_entity: dict[str, str | None] | None = None,
    hierarchy_for_dedup: EntityHierarchy | None = None,  # noqa: F821
) -> list:
    """Collapse insights that share a fingerprint (mod entity_id) AND
    whose entities live under the same group/scene container.

    Most detectors put a primary `entity_id` in their fingerprint
    (schedule, seasonality, streak, long_tail, frequency_anomaly).
    Co-occurrence uses leader/follower keys — those don't dedup here
    by design; co-occurrence's same-device + dependency filters already
    handle group fan-out at pair-discovery time.

    The merged output keeps the highest-confidence insight as the
    representative, with a "(+N similar members of <parent>)" suffix
    on its title so the user can see the rollup. The rest are dropped.
    Re-scans produce the same merged id (fingerprint includes the
    parent + sorted member list) so dedup is stable across runs.
    """
    if not insights:
        return insights
    # NOTE: the `not entity_dependencies` short-circuit that used to live
    # here was a bug. v1.2's hierarchy migration left entity_dependencies
    # sparse / empty on many installs (the relationships moved to the
    # central EntityHierarchy), and the guard made the dedup helper
    # return raw lists. Result: a 51-entity NVR-style orphan-device
    # cohort never merged. The hierarchy.find_common_parent path + the
    # heuristic same-domain co-fingerprint fallback both work fine
    # without entity_dependencies — its only consumer is the legacy
    # _find_common_container path, which already tolerates an empty map.

    # Group by fingerprint signature with entity_id stripped. Insights
    # without an entity_id key (cooccurrence) sit alone in their own
    # singleton bucket and pass through unchanged.
    import json as _json
    from collections import defaultdict as _defaultdict

    from ..insight import Insight as _Insight  # local to avoid cycle

    by_signature: dict[str, list] = _defaultdict(list)
    for ins in insights:
        if "entity_id" not in ins.fingerprint:
            # Use a unique key so it doesn't merge with anything
            by_signature[f"_solo_{id(ins)}"].append(ins)
            continue
        sig = {k: v for k, v in ins.fingerprint.items() if k != "entity_id"}
        sig_key = _json.dumps(sig, sort_keys=True, default=str)
        by_signature[sig_key].append(ins)

    # Threshold for the heuristic fallback. User's observation
    # ("multiple devices with the same long_tail duration are probably
    # part of the same routine/automation") matches reality: when 2+
    # entities share an EXACT fingerprint signature AND the same domain,
    # the timing/duration/threshold collision is so specific that
    # coincidence is implausible. Lowered from 3 → 2 to match user
    # intuition; reverse if false-positive merges show up in practice.
    HEURISTIC_MERGE_THRESHOLD = 2

    result: list = []
    for group in by_signature.values():
        if len(group) < 2:
            result.extend(group)
            continue
        # v1.4: detectors can opt out of cohort merging by setting
        # `cohort_dedup = False` on the class. frequency_anomaly is
        # the canonical case — merging two runaway automations into
        # "light.* (cohort)" hides which entity is flapping. The
        # detector name is the same across every insight in the
        # group (fingerprint signature includes "kind" via the
        # original full fingerprint), so checking just one is fine.
        first_detector_name = getattr(group[0], "detector", "")
        detector_cls = DETECTORS.get(first_detector_name)
        if detector_cls is not None and not getattr(
            detector_cls, "cohort_dedup", True
        ):
            result.extend(group)
            continue
        eids = [
            g.fingerprint["entity_id"]
            for g in group
            if isinstance(g.fingerprint.get("entity_id"), str)
        ]
        if len(eids) < 2:
            result.extend(group)
            continue
        # Primary path: discover a real shared container.
        # v1.2: prefer the central hierarchy's find_common_parent
        # (covers device, parent-self, third-party container in one
        # call). Fall back to the legacy helper during migration.
        if hierarchy_for_dedup is not None:
            parent = hierarchy_for_dedup.find_common_parent(eids)
        else:
            parent = _find_common_container(
                eids,
                entity_dependencies,
                container_to_members,
                device_id_by_entity,
            )
        merge_label: str | None = None
        if parent is not None:
            merge_label = parent
        elif len(eids) >= HEURISTIC_MERGE_THRESHOLD:
            # Fallback: same-domain co-fingerprint heuristic. The
            # garden lights case from a real install — 7 lights all
            # firing at 17:34 on 4 days in a row, no shared state-
            # machine parent because the user's setup uses separate
            # automations / sub-scripts / Adaptive Lighting / similar
            # external coordination my dep map can't see. Merging is
            # still the right move; the user's intent is "evening
            # outdoor lights" even if HA doesn't know that.
            domains = {eid.split(".", 1)[0] for eid in eids if "." in eid}
            if len(domains) == 1:
                merge_label = f"{next(iter(domains))}.* (cohort)"

        if merge_label is None:
            result.extend(group)
            continue

        # Merge: keep highest-confidence as representative, suffix title.
        rep = max(group, key=lambda g: g.confidence)
        others = len(group) - 1
        sorted_eids = sorted(eids)
        new_fp = {
            **rep.fingerprint,
            # Stable id across re-scans: parent + sorted-members list
            "_grouped_under": merge_label,
            "_member_entities": sorted_eids,
        }
        new_id = _Insight.compute_id(rep.kind, new_fp)
        new_title = (
            f"{rep.title} "
            f"(+{others} similar entities: {merge_label})"
        )
        merged = replace(
            rep,
            id=new_id,
            fingerprint=new_fp,
            title=new_title,
        )
        result.append(merged)

    return result


def _build_container_map(
    hass: HomeAssistant,
) -> dict[str, frozenset[str]]:
    """Strict parent → members map (NOT symmetric).

    A companion to _build_entity_dependencies, but unidirectional:
    only `container.entity_id → set of its members`. Used by
    RedundantTargetDetector to identify a container with confidence
    ("X has Y in its container map" definitively means Y is a member,
    vs the symmetric dep map where Y could just be a sibling).

    Source includes the same state-machine attributes as the dep map
    (entity_id / group_members / lights) plus script targets.
    """
    out: dict[str, set[str]] = {}
    try:
        for state in hass.states.async_all():
            for attr_name in ("entity_id", "group_members", "lights"):
                members_attr = state.attributes.get(attr_name)
                if not isinstance(members_attr, (list, tuple)):
                    continue
                members = {
                    m for m in members_attr
                    if isinstance(m, str) and "." in m
                }
                if members:
                    out.setdefault(state.entity_id, set()).update(members)
        # Scripts
        try:
            from .._script_targets import collect_script_targets

            for sid, targets in collect_script_targets(hass).items():
                if targets:
                    out.setdefault(sid, set()).update(targets)
        except Exception:  # pragma: no cover
            pass
    except Exception:  # pragma: no cover
        _LOGGER.exception("Failed to build container map")
        return {}
    return {k: frozenset(v) for k, v in out.items()}


def _build_entity_dependencies(
    hass: HomeAssistant,
) -> dict[str, frozenset[str]]:
    """Walk the state machine, return a symmetric entity → related-set map.

    Captures HA's standard entity-dependency conventions so cooccurrence
    can drop pairs that aren't really independent observations:

    1. Parent ↔ child group membership (always): `attributes.entity_id`
       lists members. Used by group.*, light.* (group_light), cover.*,
       binary_sensor.* (binary_sensor.group), universal_media_player, etc.
       The parent firing AND its members firing seconds later is the
       SAME root event; filter both directions.

    2. Sibling ↔ sibling membership (small groups only): if the group has
       ≤ _MAX_GROUP_SIZE_FOR_SIBLING_FILTER members, treat its members as
       siblings of each other. Catches room-light groups (3-6 lights all
       firing together when the group switch flips) without nuking
       cross-room patterns when the user has a house-wide aggregate
       sensor (all_motion, all_doors). On a power-user install,
       all_motion.entity_id might list every motion sensor — without
       this size cap the dependency filter killed 80%+ of real
       cross-room cooccurrence pairs.

    3. Derived sensors (always): `attributes.source` /
       `attributes.source_entity_id` from statistics, utility_meter,
       integration, derivative, template-on-source sensors.

    Returns a symmetric dict: if A depends on B, both directions are
    represented. Frozenset values keep the inner-loop lookup cheap.
    """
    from collections import defaultdict

    # Attribute names HA integrations use for "list of member entities":
    #   - entity_id: legacy group component, group_light, group_cover,
    #     binary_sensor.group, universal_media_player
    #   - group_members: media_player groups (Sonos, etc) per HA 2024+
    #   - lights: some Hue/zigbee2mqtt group lights expose this instead
    GROUP_MEMBER_ATTRS = ("entity_id", "group_members", "lights")
    raw: dict[str, set[str]] = defaultdict(set)
    try:
        for state in hass.states.async_all():
            # Group-style children — try every attribute name HA
            # integrations might use for the member list.
            for attr_name in GROUP_MEMBER_ATTRS:
                members_attr = state.attributes.get(attr_name)
                if not isinstance(members_attr, (list, tuple)):
                    continue
                members = [
                    m
                    for m in members_attr
                    if isinstance(m, str) and "." in m
                ]
                if not members:
                    continue
                # Parent ↔ child edge always (regardless of group size)
                for m in members:
                    raw[state.entity_id].add(m)
                    raw[m].add(state.entity_id)
                # Sibling ↔ sibling edge only for SMALL groups —
                # otherwise an all-house aggregate filters away every
                # legitimate cross-room cooccurrence pair.
                if 1 < len(members) <= _MAX_GROUP_SIZE_FOR_SIBLING_FILTER:
                    member_set = set(members)
                    for m in members:
                        raw[m] |= member_set - {m}
            # Source-style derived (always, no size cap — it's a
            # one-to-one source/derived relationship by definition)
            for attr in ("source", "source_entity_id"):
                src = state.attributes.get(attr)
                if isinstance(src, str) and "." in src:
                    raw[state.entity_id].add(src)
                    raw[src].add(state.entity_id)

        # Script targets — same parent ↔ child + sibling treatment as
        # state-machine groups. A script that turns on 7 lights groups
        # those lights logically even if they don't share a HA group
        # entity. Without this, the dedup helper can't merge insights
        # from entities co-targeted by a single script.
        try:
            from .._script_targets import collect_script_targets

            for script_eid, targets in collect_script_targets(hass).items():
                if not targets:
                    continue
                target_list = sorted(targets)
                for t in target_list:
                    raw[script_eid].add(t)
                    raw[t].add(script_eid)
                if 1 < len(targets) <= _MAX_GROUP_SIZE_FOR_SIBLING_FILTER:
                    target_set = set(targets)
                    for t in target_list:
                        raw[t] |= target_set - {t}
        except Exception:  # pragma: no cover — script expansion is best-effort
            pass
    except Exception:  # pragma: no cover — defensive
        _LOGGER.exception("Failed to build entity dependency map")
        return {}

    return {k: frozenset(v) for k, v in raw.items()}


async def _load_existing_automations(hass: HomeAssistant) -> list[dict]:
    """Return EVERY automation HA knows about, in the trigger+action shape
    the conflict_scanner expects.

    Sources covered (in priority order):
      1. HA's automation component runtime state (configuration.yaml,
         packages, blueprints, UI-defined — basically every automation
         that resolves to an `automation.*` entity)
      2. automations.yaml file (catches automations registered but not
         yet exposed as entities — rare)

    Source 1 is the durable answer to the user's "this matches an
    automation but it's not in automations.yaml" complaint: any
    automation HA has actually loaded shows up there regardless of
    where in the config tree it was declared.

    Returns [] on any unexpected error — conflict suppression is
    best-effort; if we can't read the registry the scan still runs
    and just emits potentially-duplicate insights (cheaper than
    crashing the whole scan).
    """
    # Dedup strategy: an automation is uniquely keyed by EITHER its id
    # OR its alias. We track both and treat ANY collision in either
    # axis as a duplicate (same automation from a different source).
    # Anonymous automations (no id, no alias) can't be deduped — skip
    # them rather than letting the previous `or id(entry)` fallback
    # add them every time, which is what caused the user-reported
    # "TV Lights audited twice" bug.
    seen_ids: set[str] = set()
    seen_aliases: set[str] = set()
    automations: list[dict] = []
    dup_count = 0
    anon_count = 0

    def _is_duplicate(raw: dict) -> bool:
        nonlocal dup_count, anon_count
        raw_id = raw.get("id")
        raw_alias = raw.get("alias")
        if not raw_id and not raw_alias:
            anon_count += 1
            return True  # anonymous — can't dedupe, skip
        if raw_id and str(raw_id) in seen_ids:
            dup_count += 1
            return True
        if raw_alias and str(raw_alias) in seen_aliases:
            dup_count += 1
            return True
        if raw_id:
            seen_ids.add(str(raw_id))
        if raw_alias:
            seen_aliases.add(str(raw_alias))
        return False

    # Source 1: live automations from the automation component.
    # HA exposes them as `automation.*` entities. Walk the state machine
    # and pull each entity's config via the EntityComponent backref.
    # This catches automations from automations.yaml AND configuration.yaml
    # AND packages AND blueprints — every automation HA actually loaded.
    try:
        component = hass.data.get("automation")
        # `component` may be an EntityComponent OR an EntityPlatform
        # depending on HA version. Both expose `.entities`.
        entities_iter = None
        if hasattr(component, "entities"):
            entities_iter = component.entities
        elif isinstance(component, dict):
            entities_iter = component.values()

        if entities_iter is not None:
            for entry in entities_iter:
                # `raw_config` is the dict the automation was loaded from.
                # Different HA versions name this differently; try both.
                raw = (
                    getattr(entry, "raw_config", None)
                    or getattr(entry, "_raw_config", None)
                )
                if not isinstance(raw, dict):
                    continue
                if _is_duplicate(raw):
                    continue
                automations.append(raw)
    except Exception:
        _LOGGER.debug(
            "automation component data unavailable; falling back to "
            "automations.yaml only", exc_info=True,
        )

    # Source 2: automations.yaml file (covers rare cases where a YAML
    # entry is declared but not yet exposed as an entity).
    def _read_yaml() -> list[dict]:
        try:
            import os

            import yaml

            path = os.path.join(hass.config.config_dir, "automations.yaml")
            if not os.path.exists(path):
                return []
            with open(path, encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
            if loaded is None:
                return []
            if isinstance(loaded, list):
                return [item for item in loaded if isinstance(item, dict)]
            if isinstance(loaded, dict):
                return [loaded]
            return []
        except Exception:
            _LOGGER.exception("Could not load automations.yaml for conflict scan")
            return []

    yaml_entries = await hass.async_add_executor_job(_read_yaml)
    for raw in yaml_entries:
        if _is_duplicate(raw):
            continue
        automations.append(raw)

    if dup_count or anon_count:
        _LOGGER.debug(
            "_load_existing_automations: returning %d unique "
            "automations (dropped %d duplicates, %d anonymous)",
            len(automations),
            dup_count,
            anon_count,
        )
    return automations


__all__ = [
    "DETECTORS",
    "Detector",
    "DetectorContext",
    "load_builtin_detectors",
    "register_detector",
    "run_all_detectors",
]
