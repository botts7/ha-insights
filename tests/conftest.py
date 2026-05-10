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
def _force_utc_default_timezone(
    enable_custom_integrations: None,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Pin dt_util.DEFAULT_TIME_ZONE to UTC for the duration of each test.

    Detectors and the digest now convert ev.timestamp to local time before
    bucketing by weekday / minute-of-day (v1.0 review timezone fix).
    Tests that seed events at hour=19 UTC and expect an "evening" bucket
    only behave correctly when the test runtime's local tz IS UTC.
    pytest-homeassistant-custom-component otherwise sets US/Pacific via
    its hass fixture's `hass.config.set_time_zone`, which leaves
    DEFAULT_TIME_ZONE as Pacific even after the hass fixture tears down.

    We depend on `enable_custom_integrations` so this fixture runs AFTER
    pytest-homeassistant-custom-component's own setup, then use
    monkeypatch.setattr (not set_default_time_zone) to bypass anything
    that re-reads the module global from a cached import.
    """
    monkeypatch.setattr(dt_util, "DEFAULT_TIME_ZONE", dt_util.UTC)
    yield
