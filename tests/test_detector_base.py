"""Tests for the Detector ABC and registry."""
from __future__ import annotations

from collections.abc import Iterator

import pytest

from custom_components.ha_insights.detectors.base import (
    DETECTORS,
    Detector,
    DetectorContext,
    register_detector,
)
from custom_components.ha_insights.insight import Insight, InsightKind


@pytest.fixture(autouse=True)
def clean_registry() -> Iterator[None]:
    """Restore registry between tests so leakage doesn't contaminate."""
    snapshot = dict(DETECTORS)
    DETECTORS.clear()
    yield
    DETECTORS.clear()
    DETECTORS.update(snapshot)


def test_detector_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        Detector()  # type: ignore[abstract]


def test_concrete_detector_can_be_instantiated() -> None:
    class StubDetector(Detector):
        name = "stub"
        kind = InsightKind.AUTOMATION_PROPOSAL

        async def scan(self, ctx: DetectorContext) -> list[Insight]:
            return []

    instance = StubDetector()
    assert instance.name == "stub"
    assert StubDetector.requires_recorder is False
    assert "lock" in StubDetector.domains_default_blocked
    assert "camera" in StubDetector.domains_default_blocked


def test_register_detector_adds_to_registry() -> None:
    @register_detector
    class StubDetector(Detector):
        name = "stub_a"
        kind = InsightKind.ANOMALY

        async def scan(self, ctx: DetectorContext) -> list[Insight]:
            return []

    assert DETECTORS["stub_a"] is StubDetector


def test_register_detector_is_idempotent_for_same_class() -> None:
    class StubDetector(Detector):
        name = "stub_b"
        kind = InsightKind.ANOMALY

        async def scan(self, ctx: DetectorContext) -> list[Insight]:
            return []

    register_detector(StubDetector)
    register_detector(StubDetector)  # second call should not raise
    assert DETECTORS["stub_b"] is StubDetector


def test_register_detector_rejects_collision() -> None:
    class StubA(Detector):
        name = "collision"
        kind = InsightKind.ANOMALY

        async def scan(self, ctx: DetectorContext) -> list[Insight]:
            return []

    class StubB(Detector):
        name = "collision"
        kind = InsightKind.ANOMALY

        async def scan(self, ctx: DetectorContext) -> list[Insight]:
            return []

    register_detector(StubA)
    with pytest.raises(ValueError, match="already registered"):
        register_detector(StubB)


def test_register_detector_rejects_non_subclass() -> None:
    class NotADetector:
        name = "fake"

    with pytest.raises(TypeError):
        register_detector(NotADetector)  # type: ignore[arg-type]


def test_register_detector_rejects_non_class() -> None:
    with pytest.raises(TypeError):
        register_detector("not_a_class")  # type: ignore[arg-type]


def test_applies_to_event_default_yes() -> None:
    class StubDetector(Detector):
        name = "stub_c"
        kind = InsightKind.ANOMALY

        async def scan(self, ctx: DetectorContext) -> list[Insight]:
            return []

    # Default impl ignores the event arg — None is fine for the default branch.
    assert StubDetector().applies_to_event(None) is True  # type: ignore[arg-type]
