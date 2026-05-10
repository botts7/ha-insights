"""User-supplied detector loader.

Scans `<config>/ha_insights_detectors/` for *.py files and imports each in
isolation. The module's `@register_detector` decorator handles real
registration; we just provide the import path.

Design notes:
  - Underscore prefix on the filename so the auto-loader in
    `detectors/__init__.py` doesn't try to load THIS file as a detector.
  - Per-module try/except so one broken file can't take the rest of the
    integration with it. Errors land in the HA logs at WARNING level so
    the user sees them.
  - We don't add the user dir to sys.path; we use `spec_from_file_location`
    so the user's module names live in their own namespace and can't
    shadow our built-in detector modules.
  - No hot reload. Users restart HA / reload the integration to pick up
    changes. Live reload during a scan would risk torn state in the
    rolling buffer.
"""
from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

_LOGGER = logging.getLogger(__name__)


def discover_user_detector_files(directory: Path) -> list[Path]:
    """Return *.py files in `directory` (non-recursive), excluding dunders.

    Returns empty list if the directory doesn't exist — that's the common
    case and a no-op is the right behavior. Sorting keeps the load order
    predictable (and so error messages are reproducible).
    """
    if not directory.is_dir():
        return []
    return sorted(
        p
        for p in directory.iterdir()
        if p.is_file()
        and p.suffix == ".py"
        and not p.name.startswith("_")
    )


def load_user_detectors(directory: Path) -> int:
    """Import every *.py in `directory`. Returns count successfully loaded.

    Each module's @register_detector decorator runs as part of import,
    so by the time this returns the global DETECTORS registry already
    contains anything the user supplied. Failures are logged but never
    raised — a syntax error in one user file shouldn't prevent the
    integration from setting up.
    """
    files = discover_user_detector_files(directory)
    if not files:
        return 0

    loaded = 0
    for path in files:
        # Module name must be unique enough to avoid colliding with
        # built-in detector names in sys.modules. Prefix with our own
        # namespace marker so a user's `schedule.py` doesn't shadow
        # our built-in ScheduleDetector module.
        mod_name = f"ha_insights_user.{path.stem}"
        spec = importlib.util.spec_from_file_location(mod_name, path)
        if spec is None or spec.loader is None:
            _LOGGER.warning(
                "HA Insights: could not build import spec for %s", path
            )
            continue
        try:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception:
            # Log with traceback so the user can see what broke. We don't
            # propagate — one busted user detector mustn't take the
            # integration down.
            _LOGGER.exception(
                "HA Insights: failed to load user detector %s", path
            )
            continue
        loaded += 1
        _LOGGER.info("HA Insights: loaded user detector %s", path.name)
    return loaded


__all__ = ["discover_user_detector_files", "load_user_detectors"]
