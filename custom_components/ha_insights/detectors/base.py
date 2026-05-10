"""Detector ABC and registry — load-bearing community contract.

Subclass Detector to add a new kind of insight. Implementations live in
sibling modules of `detectors/` and call `register_detector(cls)` at
module-import time (typically as a class decorator).

The shape is semver-stable from v0.1. See docs/ARCHITECTURE.md.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar

from ..insight import Insight, InsightKind
from ..observers.state_event_buffer import StateEventBuffer

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


class Detector(ABC):
    """Abstract base for all detectors.

    Subclasses must set the `name` and `kind` class attributes and implement
    `scan`. The class itself (not an instance) is what gets registered.
    """

    name: ClassVar[str]
    kind: ClassVar[InsightKind]
    requires_recorder: ClassVar[bool] = False
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
