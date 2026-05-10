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
    from homeassistant.config_entries import ConfigEntry  # noqa: F401

    from ..observers.state_event_buffer import StateEvent
    from ..store import InsightStore

_LOGGER = logging.getLogger(__name__)

# Per-detector wall-clock budget. A detector that exceeds this is logged
# and skipped — we cannot hard-cancel a Python thread, but we stop awaiting
# it so the rest of the scan + the event loop can proceed.
_DETECTOR_TIMEOUT_SEC = 30.0


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

    __slots__ = ("_events", "_blocked_entities", "_area_filter")

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
    ) -> Iterator[StateEvent]:
        """Mirror StateEventBuffer.query semantics over the snapshot."""
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
    entry: "ConfigEntry | None" = None,  # noqa: F821 — string forward-ref
    cancel_event: "asyncio.Event | None" = None,
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
        )

    enabled = None
    if entry is not None:
        # Lazy import to avoid circular at module-load time.
        from ..config_flow import get_enabled_detectors

        enabled = get_enabled_detectors(entry)

    buffer_size = (
        len(ctx.event_buffer.snapshot()) if ctx.event_buffer is not None else 0
    )
    # The snapshot above duplicates work done at ctx-build time, but is
    # cheap (~3ms at 340K events). Avoids threading the size through the
    # snapshot_ctx wrap above, which is harder to read.

    # Load existing automations once so we can suppress insights that
    # duplicate them. Reads automations.yaml via executor to avoid
    # blocking the loop. Exceptions are non-fatal — if we can't read
    # the file, we just don't filter.
    existing_automations = await _load_existing_automations(hass)
    if existing_automations:
        _LOGGER.info(
            "HA Insights scan: %d existing automations loaded for "
            "duplicate suppression",
            len(existing_automations),
        )

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
        # Self-protective: skip detectors whose declared scale ceiling
        # is below current buffer size. User can override via explicit
        # opt-in in CONF_ENABLED_DETECTORS.
        max_buf = getattr(detector_cls, "max_buffer_for_full_scan", None)
        explicitly_enabled = enabled is not None and name in enabled
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
        except asyncio.TimeoutError:
            _LOGGER.warning(
                "HA Insights detector %r exceeded %.0fs budget; skipping. "
                "The thread will continue until it returns naturally but "
                "won't block the event loop.",
                name,
                _DETECTOR_TIMEOUT_SEC,
            )
            continue
        except Exception:  # noqa: BLE001
            _LOGGER.exception("HA Insights detector %r failed", name)
            continue

        # This detector ran end-to-end. Track its name + emitted ids so
        # the post-loop sweep can replace its prior active insights.
        completed_detectors.add(name)
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

                conflicts = find_conflicts(insight, existing_automations)
                if conflicts:
                    suppressed_as_duplicate += 1
                    insight = replace(
                        insight, conflicts_with=tuple(conflicts)
                    )
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

    if return_summary:
        return {
            "added": added,
            "swept_stale": swept,
            "suppressed_as_duplicate": suppressed_as_duplicate,
            "completed_detectors": len(completed_detectors),
        }
    return added


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
    seen_ids: set[str] = set()
    automations: list[dict] = []

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
                ident = raw.get("id") or raw.get("alias") or id(entry)
                if ident in seen_ids:
                    continue
                seen_ids.add(ident)
                automations.append(raw)
    except Exception:  # noqa: BLE001
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
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Could not load automations.yaml for conflict scan")
            return []

    yaml_entries = await hass.async_add_executor_job(_read_yaml)
    for raw in yaml_entries:
        ident = raw.get("id") or raw.get("alias")
        if ident is not None and ident in seen_ids:
            continue
        if ident is not None:
            seen_ids.add(ident)
        automations.append(raw)

    return automations


__all__ = [
    "DETECTORS",
    "Detector",
    "DetectorContext",
    "load_builtin_detectors",
    "register_detector",
    "run_all_detectors",
]
