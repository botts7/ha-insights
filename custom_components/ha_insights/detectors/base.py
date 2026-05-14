"""Detector ABC and registry — load-bearing community contract.

Subclass Detector to add a new kind of insight. Implementations live in
sibling modules of `detectors/` and call `register_detector(cls)` at
module-import time (typically as a class decorator).

The shape is semver-stable from v0.1. See docs/ARCHITECTURE.md.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, ClassVar

from ..insight import Insight, InsightKind
from ..observers.state_event_buffer import StateEventBuffer


class Maturity(StrEnum):
    """Three-tier maturity flag surfaced on every Detector.

    The flag answers the question "should I trust this detector's
    output?" — orthogonal to whether the detector is ENABLED.

      - STABLE: shipped in a prior release, no major bugs reported,
        verified against real data. Auto-enabled. No badge.
      - BETA: functionally complete + tested, but may have edges.
        Auto-enabled with a dismissable banner. 🟡 badge.
      - EXPERIMENTAL: works in theory, not field-verified. Disabled
        by default; user must explicitly opt in via the experimental
        toggle in OptionsFlow OR by adding the detector name to
        CONF_ENABLED_DETECTORS. 🧪 badge on every emitted insight,
        with a "was this useful?" prompt.

    Promotion path (manual for now, automatable once analytics
    lands): track apply / dismiss ratios per detector across the
    fleet; promote EXPERIMENTAL → BETA when ≥ N installs use it
    with ≥ X% apply rate and no HIGH-severity bugs in N weeks.
    """

    STABLE = "stable"
    BETA = "beta"
    EXPERIMENTAL = "experimental"

if TYPE_CHECKING:
    from homeassistant.core import Event, HomeAssistant


@dataclass(frozen=True)
class DetectorContext:
    """Per-scan context provided to a Detector.

    Carries everything a detector needs without forcing it to know about HA
    internals directly. Stable shape from v0.1; new optional fields will be
    appended as later steps add capabilities (recorder helper, redactor, etc.).

    Filter semantics (applied transparently inside FrozenBufferView at scan
    time — detectors don't need to honor these manually):
      - `area_filter`: empty = all areas; non-empty = only events whose
        `area_id` is in the set.
      - `blocked_entities`: events for these entity_ids are dropped from
        the scan entirely. Same set as the LLM redactor's blocklist —
        users expect "block this entity" to mean "don't scan it AND
        don't send it to the LLM" (privacy gap closed in this version).
    """

    hass: HomeAssistant
    detector_config: dict[str, Any] = field(default_factory=dict)
    area_filter: frozenset[str] = field(default_factory=frozenset)
    blocked_entities: frozenset[str] = field(default_factory=frozenset)
    event_buffer: StateEventBuffer | None = None
    # entity_id -> device_id map, populated once per scan from the entity
    # registry. Detectors use it to filter out "same-device" pairs that
    # are really just two views of the same physical hardware event
    # (relay channels firing together, multi-endpoint Zigbee devices,
    # sensor packs reporting simultaneously). None for entities without
    # a device (template sensors, helpers).
    device_id_by_entity: dict[str, str | None] = field(default_factory=dict)
    # All automations HA currently knows about (configuration.yaml +
    # automations.yaml + packages + UI-defined + blueprints). Loaded once
    # per scan. Used by the automation-linter detectors (trigger drift,
    # dead action, stale condition) and by run_all_detectors itself to
    # mark insights with conflicts_with.
    existing_automations: list[dict[str, Any]] = field(default_factory=list)
    # entity_id -> set of related entity_ids via DEPENDENCY relationships.
    # Built once per scan from the state machine. Captures multiple kinds
    # of entity-to-entity dependencies that all produce false-positive
    # co-occurrence patterns:
    #
    #   - Group membership: light.living_room (group) contains light.lamp_1,
    #     light.lamp_2 — children fire ~1s after the parent group action
    #   - Derived sensors: statistics, utility_meter, integration sensors
    #     report their source entity in attributes.source / source_entity_id
    #   - Aggregate binary sensors: byd_sealion_7_windows is an OR of all
    #     individual window sensors and changes when any of them does
    #
    # Any pair sharing a dependency edge is treated as "same root event,
    # observed twice" and dropped at the cooccurrence pair-discovery step.
    entity_dependencies: dict[str, frozenset[str]] = field(default_factory=dict)
    # Strict parent → members map (NOT symmetric). A subset of
    # entity_dependencies that captures only the container → contents
    # direction. Used by the RedundantTargetDetector to identify
    # automations targeting both a group AND its members. Values are
    # the entities the key entity contains; reverse lookup needs to
    # check entity_dependencies (which IS symmetric).
    container_to_members: dict[str, frozenset[str]] = field(default_factory=dict)
    # v1.2 — the authoritative entity hierarchy view built from HA's
    # registries. Replaces the scattered dicts above in Phase 3 of the
    # refactor; legacy fields keep working until then. See
    # detectors/hierarchy.py for query methods.
    hierarchy: "EntityHierarchy | None" = None  # noqa: F821 — forward ref
    # v1.5.22: iot_class per integration, loaded ON THE MAIN LOOP by
    # run_all_detectors before dispatching detectors to worker threads.
    # Earlier (v1.5.15) the audit detector loaded these inside its
    # async scan() — which ran on a worker thread via asyncio.run.
    # HA's loader.async_get_integration expects to be called from the
    # main event loop; calling it from a worker thread can deadlock
    # against hass.async_add_executor_job during manifest loading.
    # With 60+ integrations the sequential awaits compounded into the
    # automation_audit detector exceeding its 30s budget every scan.
    iot_class_by_integration: dict[str, str] = field(default_factory=dict)


class Detector(ABC):
    """Abstract base for all detectors.

    Subclasses must set the `name` and `kind` class attributes and implement
    `scan`. The class itself (not an instance) is what gets registered.
    """

    name: ClassVar[str]
    kind: ClassVar[InsightKind]
    requires_recorder: ClassVar[bool] = False
    # Maturity tier — see the Maturity enum docstring for the
    # semantics. Defaults to STABLE because the default makes the
    # detector visible. Brand-new detectors should explicitly set
    # this to BETA or EXPERIMENTAL until they've earned promotion.
    maturity: ClassVar[Maturity] = Maturity.STABLE
    # Human-readable summary surfaced in the OptionsFlow + WS for users
    # so they can decide if it's worth enabling. Should answer "what
    # does this detector actually do for me?" in one sentence.
    description: ClassVar[str] = ""
    # Hard dependencies — datapoints / integrations a user MUST have for
    # this detector to produce anything useful. Surfaced in the panel +
    # OptionsFlow so users aren't left wondering "why is this empty?".
    # Each entry is a short human-readable label; semantic forms tracked
    # via well-known prefixes the panel can render as chips:
    #
    #   "integration:mobile_app" — HA core integration name
    #   "entity:binary_sensor.<phone>_charging" — pattern/literal
    #   "entity_pattern:sensor.*_battery_level" — wildcard
    #   "domain:weather" — HA domain
    #   "feature:recorder" — special HA capability
    #
    # Empty = no special dependencies (detector works on whatever's
    # already in the buffer). Used by SetupQualityDetector to tier
    # USELESS / LIMITED / GOOD / GREAT per detector, and rendered in
    # the OptionsFlow detector picker.
    required_data: ClassVar[tuple[str, ...]] = ()
    # Optional datapoints that ELEVATE accuracy if present. Same format
    # as required_data. Surfaced as "GOOD vs GREAT" tier hints.
    optional_data: ClassVar[tuple[str, ...]] = ()
    domains_default_blocked: ClassVar[frozenset[str]] = frozenset(
        {"camera", "person", "device_tracker", "lock"}
    )
    # Per-domain "transient" state values — intermediate states that
    # appear only briefly during a transition. Detecting patterns over
    # them (e.g. "media_player buffers every Thursday at 21:51") is
    # noise: it's just the device passing through a state on its way
    # to the steady-state target. The user's actual decision was to
    # start playback, not to enter buffering. Detectors should treat
    # transient states as if they didn't fire.
    TRANSIENT_STATES_BY_DOMAIN: ClassVar[dict[str, frozenset[str]]] = {
        # `buffering` happens on every play start; `loading` on some platforms
        "media_player": frozenset({"buffering", "loading"}),
        # Covers transition through opening/closing on their way to open/closed
        "cover": frozenset({"opening", "closing"}),
        # Lock transition states; `jammed` is an error condition rather
        # than a steady state, which seasonality / streak shouldn't pattern on
        "lock": frozenset({"locking", "unlocking", "jammed"}),
        # Vacuums transition through `returning` between cleaning and docked
        "vacuum": frozenset({"returning"}),
        # Climate transitions through `idle` between heating/cooling cycles
        # — this one is tricky since `idle` is also the steady state for
        # off climates. Leaving climate out of the transient set for now.
    }
    # Self-protective skip threshold. If the snapshot is larger than this
    # (in event count), `run_all_detectors` skips this detector with a log
    # line rather than invoking it. Used by detectors with super-linear
    # complexity that can otherwise hit the 30s watchdog on large installs
    # AND leave a zombie thread consuming CPU after the watchdog skip
    # (Python can't kill threads). None = always run regardless of size.
    #
    # Users can opt back in via per-detector enable/disable: an entry in
    # CONF_ENABLED_DETECTORS forces the detector to run regardless of this
    # threshold (the threshold is a *default safety net*, not a hard cap).
    max_buffer_for_full_scan: ClassVar[int | None] = None
    # v1.4: opt out of the cohort dedup helper. Default True (current
    # behaviour). Set False for detectors where the dedup heuristic
    # masks the signal rather than reducing noise — frequency_anomaly
    # is the canonical case (two lights running away at 200×/day are
    # TWO INDEPENDENT runaway automations, not one shared cause to
    # merge into "light.* (cohort)"). The user needs to see each
    # entity individually to investigate.
    #
    # Detectors where the merge DOES make sense (shared root cause):
    #   - orphan_device (NVR offline → 34 silent cameras)
    #   - long_tail     (no auto-off → 12 lights left on)
    #   - schedule      (one routine → N entities firing together)
    #
    # Detectors where the merge MASKS the signal (per-entity):
    #   - frequency_anomaly (each runaway is its own problem)
    #   - …add more as we discover them
    cohort_dedup: ClassVar[bool] = True

    @abstractmethod
    async def scan(self, ctx: DetectorContext) -> list[Insight]:
        """Run a single scan pass and return any insights produced.

        Detectors should be idempotent: the same context should produce the
        same insights. Dedup happens at the store level via Insight.id.
        """

    def applies_to_event(self, event: Event) -> bool:
        """Whether this detector cares about a given state-change event.

        Default: yes. Override to opt out of fan-out for events your detector
        doesn't need (perf optimization on large installs).
        """
        return True


# --- Registry ---

DETECTORS: dict[str, type[Detector]] = {}


def register_detector(detector_cls: type[Detector]) -> type[Detector]:
    """Register a Detector subclass in the global registry.

    Idempotent for the same class. Re-registering a *different* class under an
    existing name raises ValueError. Usable as a class decorator:

        @register_detector
        class MyDetector(Detector):
            name = "my_detector"
            kind = InsightKind.ANOMALY
            ...
    """
    if not isinstance(detector_cls, type) or not issubclass(detector_cls, Detector):
        raise TypeError(f"{detector_cls!r} is not a Detector subclass")

    name = detector_cls.name
    existing = DETECTORS.get(name)
    if existing is None:
        DETECTORS[name] = detector_cls
    elif existing is not detector_cls:
        raise ValueError(
            f"Detector name {name!r} already registered to {existing!r}; "
            f"cannot re-register as {detector_cls!r}"
        )
    return detector_cls
