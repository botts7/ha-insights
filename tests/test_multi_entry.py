"""Tests for multi-config-entry support (v1.0 RC #7).

Covers:
  - Two entries can be created side-by-side (no unique_id abort)
  - Each entry runs an independent store / buffer
  - _get_store routes by entry_id when given one; first-entry default otherwise
  - home_insights/list_entries enumerates both
"""
from __future__ import annotations

from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_insights import async_setup_entry
from custom_components.ha_insights.config_flow import CONF_LLM_MODE, LlmMode
from custom_components.ha_insights.const import DOMAIN
from custom_components.ha_insights.ws_api import _get_buffer, _get_store


async def _add_entry(hass: Any, title: str) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_LLM_MODE: LlmMode.OFF.value},
        title=title,
    )
    entry.add_to_hass(hass)
    assert await async_setup_entry(hass, entry)
    await hass.async_block_till_done()
    return entry


# --- Setup ---


@pytest.mark.asyncio
async def test_two_entries_set_up_independently(hass: Any) -> None:
    """Each entry creates its own store + buffer."""
    a = await _add_entry(hass, "First")
    b = await _add_entry(hass, "Second")

    store_a = _get_store(hass, a.entry_id)
    store_b = _get_store(hass, b.entry_id)
    buffer_a = _get_buffer(hass, a.entry_id)
    buffer_b = _get_buffer(hass, b.entry_id)

    assert store_a is not None
    assert store_b is not None
    assert store_a is not store_b
    assert buffer_a is not None
    assert buffer_b is not None
    assert buffer_a is not buffer_b


@pytest.mark.asyncio
async def test_default_get_store_returns_first_entry(hass: Any) -> None:
    """No entry_id => first entry's store. Card backwards compat."""
    a = await _add_entry(hass, "First")
    await _add_entry(hass, "Second")

    default_store = _get_store(hass)
    a_store = _get_store(hass, a.entry_id)
    assert default_store is a_store


@pytest.mark.asyncio
async def test_get_store_with_unknown_entry_returns_none(hass: Any) -> None:
    """A made-up entry_id resolves to None, not a wrong entry."""
    await _add_entry(hass, "First")
    assert _get_store(hass, "not-a-real-id") is None


# --- WS list_entries ---


@pytest.mark.asyncio
async def test_list_entries_enumerates_all(hass_ws_client: Any, hass: Any) -> None:
    """home_insights/list_entries returns one row per active config entry."""
    a = await _add_entry(hass, "Personal")
    b = await _add_entry(hass, "Guest house")

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "home_insights/list_entries"})
    response = await client.receive_json()

    assert response["success"]
    entries = response["result"]["entries"]
    by_id = {e["entry_id"]: e["title"] for e in entries}
    assert by_id[a.entry_id] == "Personal"
    assert by_id[b.entry_id] == "Guest house"
