"""Tests for lib/title_cleanup.py — pure-string CTA stripping.

Runs without HA. Verifies the cohort-suffix interaction surfaced by
the v1.5.42 review batch.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from custom_components.ha_insights.lib.title_cleanup import (
    strip_already_automated_cta,
)


def test_strip_end_anchored_build_automation():
    assert (
        strip_already_automated_cta("at ~17:27 — Build automation?")
        == "at ~17:27 —"
    )


def test_strip_end_anchored_automate_this():
    assert (
        strip_already_automated_cta("Every weekday at 6:47 AM — Automate this?")
        == "Every weekday at 6:47 AM —"
    )


def test_strip_end_anchored_automate_it():
    assert (
        strip_already_automated_cta("Garage open → driveway light — Automate it")
        == "Garage open → driveway light —"
    )


def test_strip_with_cohort_suffix_keeps_suffix():
    """The bug v1.5.42 fixes: CTA followed by cohort suffix was a no-op
    under the end-anchored regex. Now strips the CTA from the prefix
    portion and rejoins with the preserved suffix.

    Real-world title shape — cohort merge appends `(+N similar...)` to
    the end of the rep insight, whose own title ends with the CTA."""
    title = (
        "Every weekday at ~6:47 AM. Automate this? "
        "(+5 similar entities: light.living_room_*)"
    )
    assert strip_already_automated_cta(title) == (
        "Every weekday at ~6:47 AM. "
        "(+5 similar entities: light.living_room_*)"
    )


def test_strip_with_cohort_members_suffix():
    """Group-member cohort uses `members` not `entities`."""
    title = "11 days at ~22:15. Build automation? (+3 similar members: light.kitchen_*)"
    assert strip_already_automated_cta(title) == (
        "11 days at ~22:15. (+3 similar members: light.kitchen_*)"
    )


def test_strip_no_cta_passes_through():
    title = "12-hour anomaly: door fired 38× today"
    assert strip_already_automated_cta(title) == title


def test_strip_idempotent():
    title = "at ~17:27. Build automation? (+5 similar entities: light.*)"
    pass1 = strip_already_automated_cta(title)
    pass2 = strip_already_automated_cta(pass1)
    assert pass1 == pass2


def test_empty_input():
    assert strip_already_automated_cta("") == ""


def test_strip_with_only_cta_returns_empty():
    """Edge case: title is literally just the CTA, nothing else."""
    assert strip_already_automated_cta("Build automation?") == ""


def test_cta_alone_with_cohort_suffix():
    """Edge: prefix is just the CTA, suffix is the cohort tail. Result is
    just the suffix without leading whitespace."""
    title = "Automate this? (+12 similar entities: switch.nvr_profile_*)"
    assert strip_already_automated_cta(title) == (
        "(+12 similar entities: switch.nvr_profile_*)"
    )


def test_does_not_chew_earlier_automate_mention():
    """An `Automate this?` mid-string isn't end-of-prefix-CTA; must not
    be stripped. Only the trailing CTA goes."""
    title = "Automate this? You already did. Build automation?"
    assert strip_already_automated_cta(title) == (
        "Automate this? You already did."
    )
