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
    if entity_dependencies:
        # Count edges so a one-line log gives a sense of scale; helps
        # diagnose "why is cooccurrence still finding this pair?"
        edge_count = sum(len(v) for v in entity_dependencies.values()) // 2
        _LOGGER.info(
            "HA Insights: built dependency map for %d entities (~%d edges)",
            len(entity_dependencies),
            edge_count,
        )

    # Load existing automations once per scan so we can:
    #   1. Pass to TriggerDriftDetector etc via ctx.existing_automations
    #   2. Mark detector emissions with conflicts_with after the run
    # Read off the loop via the helper (executor for YAML I/O); cheap.
    existing_automations = await _load_existing_automations(hass)
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
        # Group dedup: if N insights from this detector share fingerprint
        # (modulo entity_id) AND their entities all live under a common
        # scene/group, collapse them into one representative insight
        # tagged with "(+N similar members of <parent>)". Catches the
        # 7 garden lights all firing the same 17:34 streak — they
        # belong to one user routine, not seven.
        insights = _dedup_grouped_insights(insights, entity_dependencies)
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


def _find_common_container(
    entity_ids: list[str],
    entity_dependencies: dict[str, frozenset[str]],
) -> str | None:
    """Return a parent (scene, group, group_light) that contains every
    entity in entity_ids — or None if no single container covers them all.

    A "container" of entity X is any entity whose dependency set lists X
    as a member. The dep map is symmetric (parent ↔ child + sibling ↔
    sibling for small groups), but a TRUE container's dep set will
    contain ALL the input entities — siblings only have one of them
    (themselves). That distinguishes parents from siblings.
    """
    if len(entity_ids) < 2:
        return None
    # Intersection of all dep sets — entities present in every input's deps
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
    # Among common entities, find one whose own dep set contains every
    # input entity_id. That's the parent. Iterate sorted for stable
    # output across re-scans.
    for candidate in sorted(common):
        cand_deps = entity_dependencies.get(candidate, frozenset())
        if all(eid in cand_deps for eid in entity_ids):
            return candidate
    return None


def _dedup_grouped_insights(
    insights: list,
    entity_dependencies: dict[str, frozenset[str]],
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
    if not insights or not entity_dependencies:
        return insights

    from collections import defaultdict as _defaultdict

    from ..insight import Insight as _Insight  # local to avoid cycle

    # Group by fingerprint signature with entity_id stripped. Insights
    # without an entity_id key (cooccurrence) sit alone in their own
    # singleton bucket and pass through unchanged.
    import json as _json

    by_signature: dict[str, list] = _defaultdict(list)
    for ins in insights:
        if "entity_id" not in ins.fingerprint:
            # Use a unique key so it doesn't merge with anything
            by_signature[f"_solo_{id(ins)}"].append(ins)
            continue
        sig = {k: v for k, v in ins.fingerprint.items() if k != "entity_id"}
        sig_key = _json.dumps(sig, sort_keys=True, default=str)
        by_signature[sig_key].append(ins)

    result: list = []
    for group in by_signature.values():
        if len(group) < 2:
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
        parent = _find_common_container(eids, entity_dependencies)
        if parent is None:
            result.extend(group)
            continue

        # Merge: keep highest-confidence as representative, suffix title.
        rep = max(group, key=lambda g: g.confidence)
        others = len(group) - 1
        sorted_eids = sorted(eids)
        new_fp = {
            **rep.fingerprint,
            # Stable id across re-scans: parent + sorted-members list
            "_grouped_under": parent,
            "_member_entities": sorted_eids,
        }
        new_id = _Insight.compute_id(rep.kind, new_fp)
        new_title = (
            f"{rep.title} "
            f"(+{others} similar members of {parent})"
        )
        merged = replace(
            rep,
            id=new_id,
            fingerprint=new_fp,
            title=new_title,
        )
        result.append(merged)

    return result


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
