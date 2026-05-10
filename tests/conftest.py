"""Shared pytest fixtures for HA Insights tests."""
from __future__ import annotations

from collections.abc import Iterator

import pytest
from homeassistant.util import dt as dt_util

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> Iterator[None]:
    """Make HA Insights discoverable in all tests that touch hass."""
    yield


@pytest.fixture(autouse=True)
def _force_utc_default_timezone() -> Iterator[None]:
    """Pin dt_util.DEFAULT_TIME_ZONE to UTC for the duration of each test.

    Detectors and the digest now convert ev.timestamp to local time before
    bucketing by weekday / minute-of-day (v1.0 review timezone fix).
    Tests that seed events at hour=19 UTC and expect an "evening" bucket
    only behave correctly when the test runtime's local tz IS UTC.
    pytest-homeassistant-custom-component otherwise inherits whatever
    DEFAULT_TIME_ZONE was set by an earlier test or by HA bootstrap, so
    we pin explicitly. Restored after each test.
    """
    original = dt_util.DEFAULT_TIME_ZONE
    dt_util.set_default_time_zone(dt_util.UTC)
    try:
        yield
    finally:
        dt_util.set_default_time_zone(original)
