"""Apply pipeline — validation, conflict detection, write to HA, drift handling.

v0.1 surfaces:
  - validate_automation: Layer 1 schema check (offline)
  - find_conflicts: pre-flight overlap detection vs existing automations

Layer 2 WS validate + automation_writer + drift detector land at step 13.
"""
from __future__ import annotations

from .automation_writer import AutomationWriter
from .conflict_scanner import find_conflicts
from .drift_detector import detect_drift, hash_config
from .validator import validate_automation

__all__ = [
    "AutomationWriter",
    "detect_drift",
    "find_conflicts",
    "hash_config",
    "validate_automation",
]
