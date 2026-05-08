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
    """

    hass: HomeAssistant
    detector_config: dict[str, Any] = field(default_factory=dict)
    area_filter: frozenset[str] = field(default_factory=frozenset)
    event_buffer: StateEventBuffer | None = None


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
