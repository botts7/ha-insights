"""Regression: SUPPORTED_METHODS tuple matches the actual register calls.

Cards using `home_insights/hello` to feature-detect rely on the tuple
being correct. v1.0 review found three live endpoints (hypothesize,
refine_cost_estimate, list_entries) missing from the tuple, so cards
silently wouldn't render those features. This test parses the
async_register source to keep the two in lockstep.
"""
from __future__ import annotations

import re
from pathlib import Path

from custom_components.ha_insights.ws_api import SUPPORTED_METHODS


def test_supported_methods_matches_async_register() -> None:
    ws_api_src = (
        Path(__file__).parent.parent
        / "custom_components"
        / "ha_insights"
        / "ws_api.py"
    ).read_text(encoding="utf-8")
    # Find every `websocket_api.async_register_command(hass, ws_<name>)` call
    handlers = set(
        re.findall(
            r"websocket_api\.async_register_command\(hass,\s*ws_(\w+)\)",
            ws_api_src,
        )
    )
    # `_dev/inject_event` is intentionally excluded (debug-only); skip it.
    handlers.discard("dev_inject_event")

    declared = set(SUPPORTED_METHODS)
    missing_from_tuple = handlers - declared
    extra_in_tuple = declared - handlers

    assert not missing_from_tuple, (
        f"SUPPORTED_METHODS missing handlers actually registered: "
        f"{sorted(missing_from_tuple)}"
    )
    assert not extra_in_tuple, (
        f"SUPPORTED_METHODS lists handlers no longer registered: "
        f"{sorted(extra_in_tuple)}"
    )
