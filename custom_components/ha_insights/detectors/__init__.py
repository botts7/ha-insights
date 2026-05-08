"""Detector registry. Auto-imports sibling modules so they self-register."""
from __future__ import annotations

import importlib
import pkgutil

from .base import DETECTORS, Detector, DetectorContext, register_detector


def _autoload_detectors() -> None:
    """Import every sibling module so it can self-register via decorator."""
    for module_info in pkgutil.iter_modules(__path__):
        if module_info.name.startswith("_") or module_info.name == "base":
            continue
        importlib.import_module(f"{__name__}.{module_info.name}")


_autoload_detectors()


__all__ = ["DETECTORS", "Detector", "DetectorContext", "register_detector"]
