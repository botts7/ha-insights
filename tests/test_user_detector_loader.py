"""Tests for the user-detector loader (v1.0 RC #3).

The loader scans <config>/ha_insights_detectors/*.py and imports each in
isolation. We verify:
  - A valid module gets imported and its detector lands in DETECTORS
  - A module with a syntax error is logged and skipped (others still load)
  - A module with no Detector subclass is silently no-op (helper modules ok)
  - A missing directory is a no-op (returns 0)
  - Underscore-prefixed files are skipped (matches our _user_loader convention)
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from custom_components.ha_insights.detectors.base import DETECTORS
from custom_components.ha_insights.detectors._user_loader import (
    discover_user_detector_files,
    load_user_detectors,
)


@pytest.fixture(autouse=True)
def _restore_detectors():
    """Snapshot + restore DETECTORS so tests don't leak between each other."""
    snapshot = dict(DETECTORS)
    yield
    DETECTORS.clear()
    DETECTORS.update(snapshot)


_VALID_DETECTOR_BODY = """
from custom_components.ha_insights.detectors.base import (
    Detector, DetectorContext, register_detector,
)
from custom_components.ha_insights.insight import InsightKind


@register_detector
class _TestUserDetector(Detector):
    name = "user_test_alpha"
    kind = InsightKind.AUTOMATION_PROPOSAL

    async def scan(self, ctx: DetectorContext) -> list:
        return []
"""


def _write(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


# --- Discovery ---


def test_discover_returns_empty_when_dir_missing(tmp_path: Path) -> None:
    """No directory => no files => no error."""
    assert discover_user_detector_files(tmp_path / "does_not_exist") == []


def test_discover_skips_underscore_prefixed(tmp_path: Path) -> None:
    """Underscore files are loader internals, not user detectors."""
    _write(tmp_path / "_helper.py", "")
    _write(tmp_path / "ok.py", "")
    found = discover_user_detector_files(tmp_path)
    assert [p.name for p in found] == ["ok.py"]


def test_discover_only_returns_py_files(tmp_path: Path) -> None:
    _write(tmp_path / "ok.py", "")
    _write(tmp_path / "README.md", "")
    _write(tmp_path / "data.json", "{}")
    found = discover_user_detector_files(tmp_path)
    assert [p.name for p in found] == ["ok.py"]


def test_discover_orders_alphabetically(tmp_path: Path) -> None:
    """Predictable order so error messages reproduce."""
    _write(tmp_path / "z.py", "")
    _write(tmp_path / "a.py", "")
    _write(tmp_path / "m.py", "")
    found = discover_user_detector_files(tmp_path)
    assert [p.name for p in found] == ["a.py", "m.py", "z.py"]


# --- Load ---


def test_missing_directory_no_op(tmp_path: Path) -> None:
    """Missing dir => count 0, no exception."""
    assert load_user_detectors(tmp_path / "nope") == 0


def test_loads_valid_detector_into_registry(tmp_path: Path) -> None:
    _write(tmp_path / "alpha.py", _VALID_DETECTOR_BODY)
    count = load_user_detectors(tmp_path)
    assert count == 1
    assert "user_test_alpha" in DETECTORS


def test_syntax_error_does_not_break_loader(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A broken module is logged and skipped — others still load."""
    _write(tmp_path / "broken.py", "this is not valid python ::: !!\n")
    _write(tmp_path / "good.py", _VALID_DETECTOR_BODY)
    with caplog.at_level(logging.ERROR):
        count = load_user_detectors(tmp_path)
    assert count == 1
    assert "user_test_alpha" in DETECTORS
    # The broken module gets logged at exception level (covers ERROR + traceback)
    assert any("broken.py" in record.message for record in caplog.records)


def test_module_with_no_detector_is_silently_loaded(tmp_path: Path) -> None:
    """A helper module without a Detector subclass is fine.

    Some users may want to drop shared helpers that get imported by
    sibling detector files. We don't enforce one-detector-per-file.
    """
    helper = "VALUE = 42\n"
    _write(tmp_path / "helper.py", helper)
    count = load_user_detectors(tmp_path)
    assert count == 1
    # No new detector showed up — the module loaded but didn't register
    assert all(name != "helper" for name in DETECTORS)


def test_two_modules_with_detectors_both_register(tmp_path: Path) -> None:
    body_b = _VALID_DETECTOR_BODY.replace(
        "user_test_alpha", "user_test_beta"
    ).replace("_TestUserDetector", "_TestUserDetectorB")
    _write(tmp_path / "alpha.py", _VALID_DETECTOR_BODY)
    _write(tmp_path / "beta.py", body_b)
    count = load_user_detectors(tmp_path)
    assert count == 2
    assert "user_test_alpha" in DETECTORS
    assert "user_test_beta" in DETECTORS


def test_module_namespace_isolation(tmp_path: Path) -> None:
    """User module name like `schedule.py` doesn't shadow built-in.

    Our loader prefixes module names with `ha_insights_user.` so the
    built-in `custom_components.ha_insights.detectors.schedule` module
    keeps its identity in sys.modules.
    """
    import sys

    schedule_module_before = sys.modules.get(
        "custom_components.ha_insights.detectors.schedule"
    )
    body = _VALID_DETECTOR_BODY.replace(
        "user_test_alpha", "user_schedule_clone"
    )
    _write(tmp_path / "schedule.py", body)
    load_user_detectors(tmp_path)
    schedule_module_after = sys.modules.get(
        "custom_components.ha_insights.detectors.schedule"
    )
    # Built-in module reference is unchanged
    assert schedule_module_before is schedule_module_after
