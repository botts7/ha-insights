"""Snapshot tests for the v1.5.44 refiner prompt extension.

Locks two invariants:
  1. When `candidate_block=None` (default), `build_refine_prompt` produces
     byte-identical output to v1.5.43. Backward compat.
  2. When `candidate_block` is provided, the prompt contains the
     REQUIRED-vs-OPTIONAL two-tier constraint language + the action-
     consistency instruction.

These run under PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 with --noconftest to
bypass the HA pytest plugin (which can't load on Windows without fcntl).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from custom_components.ha_insights.llm.refiner import build_refine_prompt

_SAMPLE_PAYLOAD = {
    "alias": "Hallway motion → light",
    "trigger": [
        {"platform": "state", "entity_id": "binary_sensor.hallway_motion", "to": "on"}
    ],
    "action": [
        {
            "service": "light.turn_on",
            "target": {"entity_id": "light.hallway"},
        }
    ],
    "mode": "single",
}


def test_no_candidates_path_unchanged_constraint_text():
    """Backward compat: no candidate_block → 'Use ONLY these entity_ids:' line.

    We don't byte-snapshot (YAML serializer may shift trivially with
    Python versions) but we lock the constraint phrasing.
    """
    prompt = build_refine_prompt(
        _SAMPLE_PAYLOAD,
        prior_explanation=None,
        feedback=None,
    )
    assert "Use ONLY these entity_ids:" in prompt
    assert "light.hallway" in prompt
    assert "binary_sensor.hallway_motion" in prompt
    # The new two-tier text must NOT appear when no candidates
    assert "REQUIRED entity_ids" not in prompt
    assert "OPTIONAL candidates" not in prompt


def test_candidates_path_uses_two_tier_constraint():
    candidate_block = (
        "  light.hallway_lamp  (HIGH: same area as light.hallway)\n"
        "  switch.hallway_outlet  (MEDIUM: same area as light.hallway)"
    )
    prompt = build_refine_prompt(
        _SAMPLE_PAYLOAD,
        prior_explanation=None,
        feedback="add more lights",
        candidate_block=candidate_block,
    )
    # Two-tier constraint phrasing
    assert "REQUIRED entity_ids" in prompt
    assert "OPTIONAL candidates" in prompt
    # Candidates section is present verbatim
    assert "light.hallway_lamp" in prompt
    assert "(HIGH: same area as light.hallway)" in prompt
    # Action-consistency instruction is present (anti-TV-with-lights guard)
    assert "Action-type consistency" in prompt
    assert "cross-domain" in prompt
    # Required entities still listed
    assert "light.hallway" in prompt
    # User feedback still threaded
    assert "add more lights" in prompt
    # The legacy "Use ONLY these entity_ids" line is NOT in the candidates path
    assert "Use ONLY these entity_ids:" not in prompt


def test_empty_candidate_block_falls_back_to_legacy_path():
    """`candidate_block=""` (empty string) is falsy — should behave as None."""
    prompt = build_refine_prompt(
        _SAMPLE_PAYLOAD,
        prior_explanation=None,
        feedback=None,
        candidate_block="",
    )
    assert "Use ONLY these entity_ids:" in prompt
    assert "REQUIRED entity_ids" not in prompt
