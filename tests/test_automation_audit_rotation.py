"""Tests for AutomationAuditDetector round-robin target rotation (issue #12).

The detector caps each scan to _AUDIT_PER_SCAN_CAP = 25 automations.
The previous implementation always returned `eligible[:25]` — meaning
installs with N>25 automations had the same first 25 audited every
scan, and the rest never made it into audit insights.

v1.7.2 introduces a class-level offset that advances each scan. These
tests verify:
  - Small lists (N <= 25) return everything, no rotation needed.
  - Larger lists rotate through the full list across multiple scans.
  - Every eligible automation is hit within ceil(N/25) scans.
  - Wrap-around stitches tail + head so the cap is always honored.
  - Skip-labeled automations are filtered before rotation kicks in.
"""
from __future__ import annotations

import pytest

from custom_components.ha_insights.detectors.automation_audit import (
    _AUDIT_PER_SCAN_CAP,
    _SKIP_LABEL,
    AutomationAuditDetector,
)


@pytest.fixture(autouse=True)
def _reset_audit_offset() -> None:
    """Each test starts at offset 0 so they're independent."""
    AutomationAuditDetector._audit_offset = 0


def _automations(count: int) -> list[dict]:
    """Build N synthetic automation dicts with stable ids."""
    return [{"id": f"auto_{i:04d}", "alias": f"Automation {i}"} for i in range(count)]


def test_returns_all_when_under_cap() -> None:
    """N <= cap: no rotation, return everything in source order."""
    autos = _automations(10)
    detector = AutomationAuditDetector()
    result = detector._select_audit_targets(autos)
    assert len(result) == 10
    assert [a["id"] for a in result] == [a["id"] for a in autos]


def test_returns_exactly_cap_when_equal() -> None:
    """N == cap: return all, no rotation needed."""
    autos = _automations(_AUDIT_PER_SCAN_CAP)
    detector = AutomationAuditDetector()
    result = detector._select_audit_targets(autos)
    assert len(result) == _AUDIT_PER_SCAN_CAP


def test_first_scan_returns_first_cap() -> None:
    """N > cap, scan #1: starts at offset 0, returns first cap."""
    autos = _automations(100)
    detector = AutomationAuditDetector()
    result = detector._select_audit_targets(autos)
    assert len(result) == _AUDIT_PER_SCAN_CAP
    assert result[0]["id"] == "auto_0000"
    assert result[-1]["id"] == f"auto_{_AUDIT_PER_SCAN_CAP - 1:04d}"


def test_second_scan_advances_offset() -> None:
    """Scan #2: returns automations [cap : cap*2]."""
    autos = _automations(100)
    detector = AutomationAuditDetector()
    detector._select_audit_targets(autos)  # scan 1
    result = detector._select_audit_targets(autos)  # scan 2
    assert result[0]["id"] == f"auto_{_AUDIT_PER_SCAN_CAP:04d}"
    assert len(result) == _AUDIT_PER_SCAN_CAP


def test_full_cycle_covers_every_automation() -> None:
    """Across ceil(N/cap) scans, every automation must appear at least once."""
    n = 100  # 4 full batches + a wrap-around batch
    autos = _automations(n)
    detector = AutomationAuditDetector()
    seen: set[str] = set()
    scans_needed = -(-n // _AUDIT_PER_SCAN_CAP)  # ceil division
    for _ in range(scans_needed):
        batch = detector._select_audit_targets(autos)
        seen.update(a["id"] for a in batch)
    assert seen == {a["id"] for a in autos}, (
        f"Missing {len(autos) - len(seen)} automations after "
        f"{scans_needed} scans of {n} automations"
    )


def test_wrap_around_stitches_tail_and_head() -> None:
    """When offset + cap exceeds N, the batch stitches tail + head so
    the per-scan cap is still honored (no short final batch)."""
    n = _AUDIT_PER_SCAN_CAP + 5  # 30 with cap=25 → batch 2 should be
                                  # last-5 + first-20 = 25, not just 5
    autos = _automations(n)
    detector = AutomationAuditDetector()
    detector._select_audit_targets(autos)  # consumes 0..24
    batch_2 = detector._select_audit_targets(autos)  # 25..29 + 0..19
    assert len(batch_2) == _AUDIT_PER_SCAN_CAP
    # First 5 are the tail (auto_0025..auto_0029)
    assert batch_2[0]["id"] == f"auto_{_AUDIT_PER_SCAN_CAP:04d}"
    assert batch_2[4]["id"] == f"auto_{n - 1:04d}"
    # Next 20 wrap to the start
    assert batch_2[5]["id"] == "auto_0000"


def test_skip_labeled_automations_excluded_from_rotation() -> None:
    """Skip-labeled automations are filtered before rotation, so the
    user-facing cap applies to eligible automations only."""
    autos = _automations(50)
    skip_ids: set[str] = set()
    # Mark every other one as skip-labeled
    for i, a in enumerate(autos):
        if i % 2 == 0:
            a["description"] = f"important {_SKIP_LABEL} excluded"
            skip_ids.add(a["id"])
    detector = AutomationAuditDetector()
    # 25 eligible automations remain — should fit in one scan
    batch = detector._select_audit_targets(autos)
    seen = {a["id"] for a in batch}
    # No skip-labeled ID should be in the batch
    assert not (seen & skip_ids)
    # And all 25 eligible should be returned
    assert len(seen) == 25


def test_offset_resets_cleanly_for_grown_list() -> None:
    """If the user adds automations between scans, the offset modulo
    keeps everything bounded — no IndexError, just resumes from the
    current offset's modular position."""
    detector = AutomationAuditDetector()
    # First scan with 100 automations advances offset to 25
    detector._select_audit_targets(_automations(100))
    assert AutomationAuditDetector._audit_offset == _AUDIT_PER_SCAN_CAP
    # Now the user deletes most automations — list shrinks to 10
    # (under cap). Should return all 10, not crash on the stale offset.
    batch = detector._select_audit_targets(_automations(10))
    assert len(batch) == 10
