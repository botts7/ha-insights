"""Regression tests for the admin gate on mutating + cost-incurring WS handlers.

A non-admin user must NOT be able to:
  - apply / undo / purge_all (mutating)
  - test_actions / dev_inject_event (mutating, fires services)
  - explain / refine / hypothesize (cost-incurring LLM calls)

A non-admin user MAY still:
  - list / dismiss / snooze / hello / list_entries / audit_log /
    redaction_preview / refine_cost_estimate / scan_now / subscribe /
    backfill_status

This test only exercises the gate — it doesn't assert the full handler
flow, since denied requests short-circuit before any business logic.
"""
from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_insights.config_flow import (
    CONF_LLM_MODE,
    CONF_LOOKBACK_DAYS,
    CONF_NOTIFY_ON_INSIGHT,
    LlmMode,
)
from custom_components.ha_insights.const import DOMAIN


@pytest.fixture
async def setup_integration(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_LLM_MODE: LlmMode.OFF.value,
            CONF_LOOKBACK_DAYS: 0,
            CONF_NOTIFY_ON_INSIGHT: False,
        },
        title="HA Insights",
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


_ADMIN_GATED_REQUESTS: list[tuple[str, dict]] = [
    ("home_insights/apply", {"insight_id": "fake"}),
    ("home_insights/undo", {"insight_id": "fake"}),
    ("home_insights/purge_all", {}),
    ("home_insights/test_actions", {"insight_id": "fake"}),
    ("home_insights/_dev/inject_event", {
        "entity_id": "light.x",
        "domain": "light",
        "timestamp": "2026-05-10T00:00:00+00:00",
        "new_state": "on",
    }),
    ("home_insights/explain", {"insight_id": "fake"}),
    ("home_insights/refine", {"insight_id": "fake"}),
    ("home_insights/hypothesize", {"insight_id": "fake"}),
]


_OPEN_REQUESTS: list[tuple[str, dict]] = [
    ("home_insights/hello", {}),
    ("home_insights/list_entries", {}),
    ("home_insights/audit_log", {}),
    ("home_insights/refine_cost_estimate", {"insight_id": "fake"}),
]


@pytest.mark.parametrize(("method", "payload"), _ADMIN_GATED_REQUESTS)
async def test_non_admin_blocked_on_destructive_handler(
    hass: HomeAssistant,
    hass_ws_client,
    hass_admin_user,
    setup_integration: MockConfigEntry,
    method: str,
    payload: dict,
) -> None:
    """Non-admin users get unauthorized on mutating + cost-incurring endpoints."""
    # Drop admin from the default test user
    hass_admin_user.groups = []

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": method, **payload})
    response = await client.receive_json()

    assert not response["success"]
    assert response["error"]["code"] == "unauthorized"


@pytest.mark.parametrize(("method", "payload"), _OPEN_REQUESTS)
async def test_non_admin_allowed_on_read_only_handler(
    hass: HomeAssistant,
    hass_ws_client,
    hass_admin_user,
    setup_integration: MockConfigEntry,
    method: str,
    payload: dict,
) -> None:
    """Non-admin users can still call read-only endpoints.

    The handler may return an error (e.g. not_found for a fake insight_id)
    but it must NOT be 'unauthorized' — that would block reading the
    panel for any non-admin frontend user, which is overly restrictive.
    """
    hass_admin_user.groups = []

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": method, **payload})
    response = await client.receive_json()

    if not response["success"]:
        assert response["error"]["code"] != "unauthorized", (
            f"{method} should not require admin; got {response['error']}"
        )
