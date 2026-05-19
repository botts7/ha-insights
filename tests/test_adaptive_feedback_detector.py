"""Tests for AdaptiveFeedbackDetector — v1.14.6.

Covers:
  - No history → no insights
  - Dismiss + substantial delta → emit re-surface insight
  - Dismiss + no delta → skip (cooldown is what should_re_suggest enforces;
    we just trust the lib here)
  - Retire + automation_removed → emit (retire bar met)
  - Retire + sensor_added → skip (retire bar NOT met)
  - Currently-applied insight → skip
  - Originally-missing insight → skip
  - Active snooze → skip
  - Cooldown still in effect → skip
  - Hydration tolerates malformed rows
  - Payload structure (what_changed + human_summary + verdict_history_summary)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest

from custom_components.ha_insights.const import DOMAIN
from custom_components.ha_insights.detectors import adaptive_feedback as af_mod
from custom_components.ha_insights.detectors.adaptive_feedback import (
    AdaptiveFeedbackDetector,
)
from custom_components.ha_insights.detectors.base import DetectorContext
from custom_components.ha_insights.insight import Insight, InsightKind


@pytest.fixture(autouse=True)
def _patch_capture(monkeypatch):
    """Per-test replacement for capture_environmental_fingerprint so we
    don't have to set up the real HA registry. Tests opt in via
    `ctx.hass._current_fp` (an EnvironmentalFingerprint)."""
    from custom_components.ha_insights.lib.user_verdict_history import (
        EnvironmentalFingerprint,
    )

    def _fake_capture(hass):
        return getattr(hass, "_current_fp", EnvironmentalFingerprint())

    monkeypatch.setattr(
        af_mod, "capture_environmental_fingerprint", _fake_capture
    )


# ---------- Test scaffolding ----------------------------------------


@dataclass
class _FakeStore:
    """In-memory store stub matching the InsightStore methods we use."""

    histories: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    insights: dict[str, Insight] = field(default_factory=dict)
    raise_on_histories: bool = False

    async def get_all_verdict_histories(
        self,
    ) -> dict[str, list[dict[str, Any]]]:
        if self.raise_on_histories:
            raise RuntimeError("boom")
        return self.histories

    async def get_insight(self, insight_id: str) -> Insight | None:
        return self.insights.get(insight_id)


def _make_ctx(
    *,
    store: _FakeStore | None = None,
    current_fp=None,
) -> DetectorContext:
    """Build a DetectorContext with a fake hass.data[DOMAIN][entry]['store']."""
    hass = MagicMock()
    if store is not None:
        hass.data = {DOMAIN: {"entry_id": {"store": store}}}
    else:
        hass.data = {DOMAIN: {}}
    if current_fp is not None:
        hass._current_fp = current_fp
    return DetectorContext(hass=hass)


def _make_insight(
    insight_id: str = "abc",
    title: str = "Original",
    detector: str = "schedule",
    **overrides: Any,
) -> Insight:
    base: dict[str, Any] = {
        "id": insight_id,
        "kind": InsightKind.AUTOMATION_PROPOSAL,
        "detector": detector,
        "area_id": "kitchen",
        "title": title,
        "confidence": 0.85,
        "fingerprint": {"k": "v"},
        "payload": {"p": 1},
        "payload_format": "blueprint",
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    base.update(overrides)
    return Insight(**base)


def _verdict_row(
    *,
    insight_id: str,
    kind: str,
    when: datetime,
    fp: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "insight_id": insight_id,
        "kind": kind,
        "timestamp": when.timestamp(),
        "fingerprint": fp or {
            "automation_ids": [],
            "sensors_per_area": {},
            "active_integrations": [],
        },
        "user_id_hash": None,
    }


# ---------- Empty / null cases --------------------------------------


@pytest.mark.asyncio
async def test_no_store_returns_empty() -> None:
    ctx = _make_ctx(store=None)
    assert await AdaptiveFeedbackDetector().scan(ctx) == []


@pytest.mark.asyncio
async def test_no_histories_returns_empty() -> None:
    store = _FakeStore()
    ctx = _make_ctx(store=store)
    assert await AdaptiveFeedbackDetector().scan(ctx) == []


@pytest.mark.asyncio
async def test_store_raise_returns_empty() -> None:
    """Defensive: a broken store doesn't crash the scan."""
    store = _FakeStore(raise_on_histories=True)
    ctx = _make_ctx(store=store)
    assert await AdaptiveFeedbackDetector().scan(ctx) == []


# ---------- Happy paths ---------------------------------------------


@pytest.mark.asyncio
async def test_dismiss_plus_automation_removed_emits_insight() -> None:
    """Classic case: user dismissed when X existed; X was removed."""
    from custom_components.ha_insights.lib.user_verdict_history import (
        EnvironmentalFingerprint,
    )

    insight_id = "ins1"
    long_ago = datetime.now(tz=UTC) - timedelta(days=120)
    old_fp = {
        "automation_ids": ["automation.competing"],
        "sensors_per_area": {},
        "active_integrations": [],
    }
    store = _FakeStore(
        histories={
            insight_id: [
                _verdict_row(
                    insight_id=insight_id,
                    kind="dismissed",
                    when=long_ago,
                    fp=old_fp,
                ),
            ],
        },
        insights={
            insight_id: _make_insight(insight_id=insight_id, title="Lights off when away"),
        },
    )
    current_fp = EnvironmentalFingerprint(
        automation_ids=frozenset(),  # automation gone
        sensors_per_area={},
        active_integrations=frozenset(),
    )
    ctx = _make_ctx(store=store, current_fp=current_fp)

    insights = await AdaptiveFeedbackDetector().scan(ctx)
    assert len(insights) == 1
    ins = insights[0]
    assert ins.detector == "adaptive_feedback"
    assert ins.kind == InsightKind.PATTERN_OBSERVATION
    assert ins.confidence == pytest.approx(0.70)
    assert "Lights off when away" in ins.title
    assert ins.payload["original_insight_id"] == insight_id
    assert ins.payload["negative_verdict_kind"] == "dismissed"
    assert ins.payload["what_changed"]["automations_removed"] == [
        "automation.competing"
    ]


@pytest.mark.asyncio
async def test_retire_plus_automation_removed_emits_insight() -> None:
    """Retire-bar is automation removal — should pass."""
    from custom_components.ha_insights.lib.user_verdict_history import (
        EnvironmentalFingerprint,
    )

    insight_id = "ins2"
    long_ago = datetime.now(tz=UTC) - timedelta(days=120)
    old_fp = {
        "automation_ids": ["automation.competing"],
        "sensors_per_area": {},
        "active_integrations": [],
    }
    store = _FakeStore(
        histories={
            insight_id: [
                _verdict_row(
                    insight_id=insight_id,
                    kind="retired",
                    when=long_ago,
                    fp=old_fp,
                ),
            ],
        },
        insights={insight_id: _make_insight(insight_id=insight_id)},
    )
    ctx = _make_ctx(
        store=store,
        current_fp=EnvironmentalFingerprint(),
    )
    insights = await AdaptiveFeedbackDetector().scan(ctx)
    assert len(insights) == 1
    assert insights[0].payload["negative_verdict_kind"] == "retired"


# ---------- Skip paths ----------------------------------------------


@pytest.mark.asyncio
async def test_retire_plus_only_sensor_added_skipped() -> None:
    """Retire bar is HIGHER — automation removal required. New sensor
    alone shouldn't trigger."""
    from custom_components.ha_insights.lib.user_verdict_history import (
        EnvironmentalFingerprint,
    )

    insight_id = "ins3"
    long_ago = datetime.now(tz=UTC) - timedelta(days=120)
    store = _FakeStore(
        histories={
            insight_id: [
                _verdict_row(insight_id=insight_id, kind="retired", when=long_ago),
            ],
        },
        insights={insight_id: _make_insight(insight_id=insight_id)},
    )
    ctx = _make_ctx(
        store=store,
        current_fp=EnvironmentalFingerprint(
            sensors_per_area={"bedroom": {"motion": 1}},
        ),
    )
    assert await AdaptiveFeedbackDetector().scan(ctx) == []


@pytest.mark.asyncio
async def test_applied_insight_skipped_even_if_history_says_yes() -> None:
    """User engaged — don't re-pester."""
    from custom_components.ha_insights.lib.user_verdict_history import (
        EnvironmentalFingerprint,
    )

    insight_id = "ins4"
    long_ago = datetime.now(tz=UTC) - timedelta(days=120)
    store = _FakeStore(
        histories={
            insight_id: [
                _verdict_row(
                    insight_id=insight_id,
                    kind="dismissed",
                    when=long_ago,
                    fp={
                        "automation_ids": ["automation.competing"],
                        "sensors_per_area": {},
                        "active_integrations": [],
                    },
                ),
            ],
        },
        insights={
            insight_id: _make_insight(
                insight_id=insight_id,
                applied_at=datetime.now(tz=UTC) - timedelta(days=1),
            ),
        },
    )
    ctx = _make_ctx(
        store=store,
        current_fp=EnvironmentalFingerprint(),
    )
    assert await AdaptiveFeedbackDetector().scan(ctx) == []


@pytest.mark.asyncio
async def test_active_snooze_skipped() -> None:
    from custom_components.ha_insights.lib.user_verdict_history import (
        EnvironmentalFingerprint,
    )

    insight_id = "ins5"
    long_ago = datetime.now(tz=UTC) - timedelta(days=120)
    store = _FakeStore(
        histories={
            insight_id: [
                _verdict_row(
                    insight_id=insight_id,
                    kind="dismissed",
                    when=long_ago,
                    fp={
                        "automation_ids": ["automation.competing"],
                        "sensors_per_area": {},
                        "active_integrations": [],
                    },
                ),
            ],
        },
        insights={
            insight_id: _make_insight(
                insight_id=insight_id,
                snoozed_until=datetime.now(tz=UTC) + timedelta(days=7),
            ),
        },
    )
    ctx = _make_ctx(store=store, current_fp=EnvironmentalFingerprint())
    assert await AdaptiveFeedbackDetector().scan(ctx) == []


@pytest.mark.asyncio
async def test_missing_original_skipped() -> None:
    """Original insight was purged from the store — skip (don't emit
    a meta-insight pointing at a row that doesn't exist)."""
    from custom_components.ha_insights.lib.user_verdict_history import (
        EnvironmentalFingerprint,
    )

    insight_id = "ins6"
    long_ago = datetime.now(tz=UTC) - timedelta(days=120)
    store = _FakeStore(
        histories={
            insight_id: [
                _verdict_row(
                    insight_id=insight_id,
                    kind="dismissed",
                    when=long_ago,
                    fp={
                        "automation_ids": ["automation.x"],
                        "sensors_per_area": {},
                        "active_integrations": [],
                    },
                ),
            ],
        },
        insights={},  # original NOT present
    )
    ctx = _make_ctx(store=store, current_fp=EnvironmentalFingerprint())
    assert await AdaptiveFeedbackDetector().scan(ctx) == []


@pytest.mark.asyncio
async def test_cooldown_blocks_recent_dismiss() -> None:
    """Recent dismiss + delta → still skipped by 30-day cooldown."""
    from custom_components.ha_insights.lib.user_verdict_history import (
        EnvironmentalFingerprint,
    )

    insight_id = "ins7"
    recent = datetime.now(tz=UTC) - timedelta(days=5)
    store = _FakeStore(
        histories={
            insight_id: [
                _verdict_row(
                    insight_id=insight_id,
                    kind="dismissed",
                    when=recent,
                    fp={
                        "automation_ids": ["automation.x"],
                        "sensors_per_area": {},
                        "active_integrations": [],
                    },
                ),
            ],
        },
        insights={insight_id: _make_insight(insight_id=insight_id)},
    )
    ctx = _make_ctx(store=store, current_fp=EnvironmentalFingerprint())
    assert await AdaptiveFeedbackDetector().scan(ctx) == []


# ---------- Hydration --------------------------------------------


@pytest.mark.asyncio
async def test_hydration_skips_malformed_rows() -> None:
    """Garbage rows in the store don't crash hydration."""
    from custom_components.ha_insights.lib.user_verdict_history import (
        EnvironmentalFingerprint,
    )

    insight_id = "ins8"
    long_ago = datetime.now(tz=UTC) - timedelta(days=120)
    store = _FakeStore(
        histories={
            insight_id: [
                {
                    "insight_id": insight_id,
                    "kind": "WAT_UNKNOWN",
                    "timestamp": 0.0,
                    "fingerprint": {},
                },
                {
                    "insight_id": insight_id,
                    "kind": "dismissed",
                    "timestamp": "not_a_number",
                    "fingerprint": {},
                },
                _verdict_row(
                    insight_id=insight_id,
                    kind="dismissed",
                    when=long_ago,
                    fp={
                        "automation_ids": ["automation.x"],
                        "sensors_per_area": {},
                        "active_integrations": [],
                    },
                ),
            ],
        },
        insights={insight_id: _make_insight(insight_id=insight_id)},
    )
    ctx = _make_ctx(store=store, current_fp=EnvironmentalFingerprint())
    insights = await AdaptiveFeedbackDetector().scan(ctx)
    # Bad rows skipped, real row processed → 1 insight emitted
    assert len(insights) == 1


# ---------- Payload structure ----------------------------------------


@pytest.mark.asyncio
async def test_payload_contains_what_changed_and_summary() -> None:
    from custom_components.ha_insights.lib.user_verdict_history import (
        EnvironmentalFingerprint,
    )

    insight_id = "ins9"
    long_ago = datetime.now(tz=UTC) - timedelta(days=120)
    store = _FakeStore(
        histories={
            insight_id: [
                _verdict_row(
                    insight_id=insight_id,
                    kind="dismissed",
                    when=long_ago,
                    fp={
                        "automation_ids": ["automation.morning_alert"],
                        "sensors_per_area": {},
                        "active_integrations": [],
                    },
                ),
            ],
        },
        insights={
            insight_id: _make_insight(
                insight_id=insight_id, title="Morning routine"
            )
        },
    )
    ctx = _make_ctx(store=store, current_fp=EnvironmentalFingerprint())
    insights = await AdaptiveFeedbackDetector().scan(ctx)
    p = insights[0].payload
    assert p["kind"] == "adaptive_feedback"
    assert p["original_insight_id"] == insight_id
    assert p["original_title"] == "Morning routine"
    assert p["original_detector"] == "schedule"
    assert "automation.morning_alert" in p["what_changed"]["automations_removed"]
    assert "Morning routine" in p["human_summary"]
    assert "automation.morning_alert" in p["human_summary"]
    assert "1 dismissed" in p["verdict_history_summary"]
    assert p["days_since_negative_verdict"] >= 119


@pytest.mark.asyncio
async def test_fingerprint_stable_across_rescans() -> None:
    """Re-scanning the same data → same id → store dedups."""
    from custom_components.ha_insights.lib.user_verdict_history import (
        EnvironmentalFingerprint,
    )

    insight_id = "ins10"
    long_ago = datetime.now(tz=UTC) - timedelta(days=120)
    store = _FakeStore(
        histories={
            insight_id: [
                _verdict_row(
                    insight_id=insight_id,
                    kind="dismissed",
                    when=long_ago,
                    fp={
                        "automation_ids": ["automation.x"],
                        "sensors_per_area": {},
                        "active_integrations": [],
                    },
                ),
            ],
        },
        insights={insight_id: _make_insight(insight_id=insight_id)},
    )
    ctx = _make_ctx(store=store, current_fp=EnvironmentalFingerprint())
    first = await AdaptiveFeedbackDetector().scan(ctx)
    second = await AdaptiveFeedbackDetector().scan(ctx)
    assert first[0].id == second[0].id
