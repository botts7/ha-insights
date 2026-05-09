"""Apply pipeline — validation, conflict detection, write to HA, drift handling.

Public surfaces:
  - validate_automation: Layer 1 offline shape validator (required keys,
    correct types, mode in valid enum)
  - validate_automation_online: Layer 2 validator using HA's own
    automation config validator — catches missing services, missing
    entities, bad trigger/condition/action shapes
  - find_conflicts: pre-flight overlap detection vs existing automations
  - AutomationWriter: writes automations.yaml + triggers automation.reload
  - hash_config / detect_drift: snapshot + comparison for the undo flow
"""
from __future__ import annotations

from .automation_writer import AutomationWriter
from .conflict_scanner import find_conflicts
from .drift_detector import detect_drift, hash_config
from .online_validator import validate_automation_online
from .validator import validate_automation

__all__ = [
    "AutomationWriter",
    "detect_drift",
    "find_conflicts",
    "hash_config",
    "validate_automation",
    "validate_automation_online",
]
