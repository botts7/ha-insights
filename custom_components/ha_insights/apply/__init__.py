"""Apply pipeline — validation, conflict detection, write to HA, drift handling.

Public surfaces:
  - validate_automation: Layer 1 schema check (offline shape validation)
  - find_conflicts: pre-flight overlap detection vs existing automations
  - AutomationWriter: writes automations.yaml + triggers automation.reload
  - hash_config / detect_drift: snapshot + comparison for the (planned) undo flow

Layer 2 (online HA WS validate / template-evaluate) is on the roadmap.
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
