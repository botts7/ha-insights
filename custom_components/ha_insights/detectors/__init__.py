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

    GIL discipline:
      Even though the detector runs in a worker thread, CPython's GIL
      means it competes with the main event loop for execution. The
      GIL auto-releases every ~5ms (sys.getswitchinterval), but a
      thread can re-grab it instantly, starving the loop. To make the
      worst case predictable, query() explicitly yields the GIL via
      `time.sleep(0)` every _GIL_YIELD_EVERY events. Cheap (single
      modulo + branch) and gives the event loop a guaranteed shot at
      the CPU on a regular cadence.
    """

    __slots__ = ("_events",)

    # Yield the GIL every N events. Tuned for ~1ms wall-clock between
    # yields on representative hardware — frequent enough that the
    # main loop never waits long, infrequent enough that the modulo
    # overhead is invisible against the per-event work detectors do.
    _GIL_YIELD_EVERY = 2_000

    def __init__(self, events: tuple[StateEvent, ...]) -> None:
        self._events = events

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
) -> int:
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

    # Snapshot the buffer ONCE on the loop, then hand the immutable
    # view to every detector. ~50 MB tuple-copy at the 500K cap — fast
    # enough to do on the loop, since it's a single memcpy of pointers.
    snapshot_ctx = ctx
    if ctx.event_buffer is not None:
        snapshot = ctx.event_buffer.snapshot()
        _LOGGER.info(
            "HA Insights scan: snapshotted %d events for thread-safe scan",
            len(snapshot),
        )
        snapshot_ctx = replace(ctx, event_buffer=_FrozenBufferView(snapshot))

    added = 0
    for name, detector_cls in DETECTORS.items():
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

        for insight in insights:
            await store.add_insight(insight)
            added += 1

    return added


__all__ = [
    "DETECTORS",
    "Detector",
    "DetectorContext",
    "load_builtin_detectors",
    "register_detector",
    "run_all_detectors",
]
