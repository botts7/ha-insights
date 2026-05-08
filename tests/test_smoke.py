"""Smoke test — keeps pytest collection green until real tests land.

Replaced by detector / apply / privacy tests at critical-path steps 6, 13, 16.
"""
from __future__ import annotations


def test_smoke() -> None:
    """Trivial assertion to prevent pytest 'no tests collected' exit code 5."""
    assert True


def test_const_imports() -> None:
    """Confirm the const module imports and DOMAIN is set correctly."""
    from custom_components.ha_insights.const import DOMAIN

    assert DOMAIN == "ha_insights"
