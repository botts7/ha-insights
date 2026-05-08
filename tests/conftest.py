"""Shared pytest fixtures for HA Insights tests."""
from __future__ import annotations

from collections.abc import Iterator

# Pre-import homeassistant.components.conversation so unittest.mock.patch can
# resolve the dotted attribute path in test_agent_client. homeassistant.components
# is a namespace package; submodules aren't attributes until imported somewhere.
import homeassistant.components.conversation  # noqa: F401
import pytest

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> Iterator[None]:
    """Make HA Insights discoverable in all tests that touch hass."""
    yield
