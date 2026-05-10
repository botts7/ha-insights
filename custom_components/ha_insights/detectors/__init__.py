"""Detector registry. Auto-imports sibling modules so they self-register.

The discovery + import side effects are sync I/O (`pkgutil.iter_modules`
does `os.listdir`; `importlib.import_module` does file I/O), so they
must NOT run on the event loop. v1.0 review caught this — HA logs
"blocking call to listdir" warnings on every cold start. Moved off
the import path so callers explicitly run discovery via the executor.
"""
from __future__ import annotations

import importlib
import pkgutil

from .base import DETECTORS, Detector, DetectorContext, register_detector


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


__all__ = [
    "DETECTORS",
    "Detector",
    "DetectorContext",
    "load_builtin_detectors",
    "register_detector",
]
