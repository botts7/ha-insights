"""AutomationAudit subsystem.

Joins existing-automation YAML with the live state buffer, the
entity hierarchy, and recent detector findings into a structured
`AuditPacket` that the AutomationAuditDetector emits as an
AUTOMATION_IMPROVEMENT insight — and that the Phase C LLM layer
later sends through the existing `refine_insight` pipeline to
suggest concrete edits.

The packet primitives are intentionally reusable: the other
roadmap detectors (dormant, condition_too_strict, energy_hog,
weather_interaction, household_rhythm) all consume the same
observation vocabulary.
"""
from .packet import AuditPacket, Observation, build_audit_packet

__all__ = ["AuditPacket", "Observation", "build_audit_packet"]
