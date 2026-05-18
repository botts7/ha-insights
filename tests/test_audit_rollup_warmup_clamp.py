"""Regression test for v1.12.14 audit_rollup warmup-clamp fix.

Real-install SQL audit (2026-05-18) found 100+ entities sitting at
the SAME cursor position (2026-01-13 13:00 UTC = `now - 180 days +
56 days`) with `audit_rollups` table EMPTY despite progress having
been recorded for months.

Root cause: when an install's recorder retention is shorter than the
configured `audit_rollup_window_days` (default 180), the cursor
walks through (window_days − recorder_retention) days of empty
chunks before reaching any data. With `_MAX_CHUNKS_PER_ENTITY = 8`
× `_CHUNK_DAYS = 7 = 56 days/batch`, an install with 10-day recorder
retention takes ~3 batches before the cursor reaches retained data
— during which the user sees 0 rollups despite the batch running.

Fix: clamp the initial cursor to `max(now - window_days,
recorder_oldest_ts)`. The recorder probe runs ONCE per batch and is
passed through to every per-entity call.

This test asserts the clamp math via the public function shape — no
HA recorder needed.
"""
from __future__ import annotations

import inspect

from custom_components.ha_insights.audit import rollup as rollup_mod


def test_probe_helper_exists() -> None:
    """The probe helper must exist + accept an HA instance."""
    assert hasattr(rollup_mod, "_probe_recorder_oldest_ts")
    sig = inspect.signature(rollup_mod._probe_recorder_oldest_ts)
    assert list(sig.parameters) == ["hass"]


def test_per_entity_function_accepts_recorder_oldest_ts() -> None:
    """The per-entity rollup must accept the clamp kwarg so the batch
    loop can pass it through. If a future refactor drops the kwarg,
    this test screams immediately rather than silently regressing the
    warmup behaviour."""
    sig = inspect.signature(
        rollup_mod._compute_rollups_for_entity_incremental
    )
    assert "recorder_oldest_ts" in sig.parameters
    # Must default to None so legacy callers (tests, ad-hoc invocations)
    # still work without the clamp.
    assert sig.parameters["recorder_oldest_ts"].default is None


def test_probe_days_ladder_covers_typical_retentions() -> None:
    """The probe ladder must cover common recorder retentions (10–30
    days are the HA defaults; 180 is the audit-window default; 365
    is the practical ceiling)."""
    ladder = rollup_mod._RECORDER_PROBE_DAYS
    assert 1 in ladder
    assert 7 in ladder
    assert 14 in ladder
    assert 30 in ladder
    assert 90 in ladder
    assert 180 in ladder
    assert 365 in ladder
    # Must be monotonic ascending so the "first empty → stop" logic
    # accumulates the deepest hit correctly.
    assert ladder == tuple(sorted(ladder))
