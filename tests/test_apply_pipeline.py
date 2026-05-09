"""Tests for the WS apply pipeline (apply command + AutomationWriter + applied_history)."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_insights.config_flow import (
    CONF_LLM_MODE,
    CONF_NOTIFY_ON_INSIGHT,
    LlmMode,
)
from custom_components.ha_insights.const import DOMAIN
from custom_components.ha_insights.insight import Insight, InsightKind


def _make_insight(insight_id: str = "abc123", **overrides: Any) -> Insight:
    base: dict[str, Any] = {
        "id": insight_id,
        "kind": InsightKind.AUTOMATION_PROPOSAL,
        "detector": "schedule",
        "area_id": "kitchen",
        "title": "Weekday morning routine",
        "confidence": 0.9,
        "fingerprint": {"entity": "light.kitchen"},
        "payload": {
            "alias": "HA Insights: weekday kitchen on",
            "trigger": [{"platform": "time", "at": "06:47:00"}],
            "condition": [{"condition": "time", "weekday": ["mon", "tue"]}],
            "action": [
                {"service": "light.turn_on", "target": {"entity_id": "light.kitchen"}}
            ],
            "mode": "single",
        },
        "payload_format": "automation",
        "created_at": datetime(2026, 5, 8, 12, 0, tzinfo=UTC),
    }
    base.update(overrides)
    return Insight(**base)


@pytest.fixture
async def setup_integration(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_LLM_MODE: LlmMode.OFF.value,
            # Disable insight-add notifications so the assertion targets
            # in apply / undo tests aren't polluted by background
            # persistent_notification.create calls.
            CONF_NOTIFY_ON_INSIGHT: False,
        },
        unique_id=DOMAIN,
        title="HA Insights",
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    # Set up automation component for the storage helper + reload service.
    from homeassistant.setup import async_setup_component

    await async_setup_component(hass, "automation", {})
    await hass.async_block_till_done()
    # The real automation.reload service re-reads configuration.yaml; the
    # pytest-homeassistant testing_config doesn't ship one, so swap in a
    # no-op for tests. In production reload happens normally.
    from homeassistant.core import ServiceCall

    async def _noop_reload(_call: ServiceCall) -> None:
        return None

    hass.services.async_remove("automation", "reload")
    hass.services.async_register("automation", "reload", _noop_reload)
    return entry


async def test_apply_unknown_insight_returns_not_found(
    hass: HomeAssistant, hass_ws_client, setup_integration
) -> None:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "home_insights/apply", "insight_id": "nope"}
    )
    msg = await client.receive_json()
    assert msg["success"] is False
    assert msg["error"]["code"] == "not_found"


async def test_apply_unsupported_format_rejected(
    hass: HomeAssistant, hass_ws_client, setup_integration
) -> None:
    store = hass.data[DOMAIN][setup_integration.entry_id]["store"]
    bad = _make_insight(insight_id="card1", payload_format="card")
    await store.add_insight(bad)

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "home_insights/apply", "insight_id": "card1"}
    )
    msg = await client.receive_json()
    assert msg["success"] is False
    assert msg["error"]["code"] == "unsupported_format"


async def test_apply_invalid_payload_rejected(
    hass: HomeAssistant, hass_ws_client, setup_integration
) -> None:
    store = hass.data[DOMAIN][setup_integration.entry_id]["store"]
    # Payload missing required 'action' field
    bad_payload = {"alias": "broken", "trigger": [{"platform": "time", "at": "06:47"}]}
    bad = _make_insight(insight_id="bad1", payload=bad_payload)
    await store.add_insight(bad)

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "home_insights/apply", "insight_id": "bad1"}
    )
    msg = await client.receive_json()
    assert msg["success"] is False
    assert msg["error"]["code"] == "invalid_payload"


async def test_apply_records_history(
    hass: HomeAssistant, hass_ws_client, setup_integration
) -> None:
    """Successful apply: returns automation_id, records applied_history, marks insight applied."""
    store = hass.data[DOMAIN][setup_integration.entry_id]["store"]
    insight = _make_insight()
    await store.add_insight(insight)

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "home_insights/apply", "insight_id": insight.id}
    )
    msg = await client.receive_json()
    assert msg["success"] is True
    auto_id = msg["result"]["automation_id"]
    assert auto_id.startswith("ha_insights_")

    history = await store.get_applied_history(insight.id)
    assert history is not None
    assert history["artifact_kind"] == "automation"
    assert history["artifact_id"] == auto_id
    assert history["snapshot"]["alias"] == "HA Insights: weekday kitchen on"
    assert isinstance(history["snapshot_hash"], str)
    assert len(history["snapshot_hash"]) == 32

    refreshed = await store.get_insight(insight.id)
    assert refreshed is not None
    # applied_at field is stored separately; check via the list filter
    applied_only = await store.list_insights(include_applied=True)
    assert any(i.id == insight.id for i in applied_only)


# --- v0.3: apply with payload_override (refine pipeline) ---


def _valid_automation_payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "alias": "Override test",
        "trigger": [{"platform": "state", "entity_id": "binary_sensor.x", "to": "on"}],
        "action": [
            {"service": "light.turn_on", "target": {"entity_id": "light.y"}}
        ],
        "mode": "single",
    }
    base.update(overrides)
    return base


async def test_apply_with_payload_override_stamps_description(
    hass: HomeAssistant, hass_ws_client, setup_integration, tmp_path
) -> None:
    hass.config.config_dir = str(tmp_path)
    store = hass.data[DOMAIN][setup_integration.entry_id]["store"]
    await store.add_insight(
        _make_insight(payload=_valid_automation_payload())
    )

    refined = _valid_automation_payload(mode="queued")
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "home_insights/apply",
            "insight_id": "abc123",
            "payload_override": refined,
        }
    )
    msg = await client.receive_json()
    assert msg["success"] is True, msg
    assert msg["result"]["refined"] is True

    yaml_path = tmp_path / "automations.yaml"
    assert yaml_path.exists()
    content = yaml_path.read_text(encoding="utf-8")
    assert "Refined by HA Insights" in content
    assert "queued" in content


async def test_apply_without_override_uses_original(
    hass: HomeAssistant, hass_ws_client, setup_integration, tmp_path
) -> None:
    hass.config.config_dir = str(tmp_path)
    store = hass.data[DOMAIN][setup_integration.entry_id]["store"]
    await store.add_insight(
        _make_insight(payload=_valid_automation_payload(mode="single"))
    )

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "home_insights/apply", "insight_id": "abc123"}
    )
    msg = await client.receive_json()
    assert msg["success"] is True
    assert msg["result"].get("refined") is False


async def test_apply_with_invalid_override_returns_error(
    hass: HomeAssistant, hass_ws_client, setup_integration
) -> None:
    store = hass.data[DOMAIN][setup_integration.entry_id]["store"]
    await store.add_insight(
        _make_insight(payload=_valid_automation_payload())
    )

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "home_insights/apply",
            "insight_id": "abc123",
            "payload_override": {"alias": "broken — no trigger"},
        }
    )
    msg = await client.receive_json()
    assert msg["success"] is False
    assert msg["error"]["code"] == "invalid_payload"


# --- v0.8: Layer 2 online validator ---


async def test_apply_rejects_unknown_trigger_platform(
    hass: HomeAssistant, hass_ws_client, setup_integration, tmp_path
) -> None:
    """Layer 2 (HA's automation validator) catches an unknown trigger platform.

    HA's validator doesn't check service-name typos at config-validate
    time (services can load later), but it DOES check trigger platforms
    against the registered set. A typo'd platform like
    'nonexistent_xyz123' should fail Layer 2 before we write to yaml.
    """
    hass.config.config_dir = str(tmp_path)
    store = hass.data[DOMAIN][setup_integration.entry_id]["store"]
    bad_payload = _valid_automation_payload(
        trigger=[{"platform": "nonexistent_platform_xyz123"}]
    )
    await store.add_insight(_make_insight(payload=bad_payload))

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "home_insights/apply", "insight_id": "abc123"}
    )
    msg = await client.receive_json()
    assert msg["success"] is False
    assert msg["error"]["code"] in (
        "ha_validation_failed",
        "invalid_payload",
    )
    yaml_path = tmp_path / "automations.yaml"
    if yaml_path.exists():
        assert (
            "nonexistent_platform_xyz123" not in yaml_path.read_text(
                encoding="utf-8"
            )
        )


# --- v0.8: undo applied (round-trip + drift detection) ---


async def test_undo_unknown_insight(
    hass: HomeAssistant, hass_ws_client, setup_integration
) -> None:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "home_insights/undo", "insight_id": "never_applied"}
    )
    msg = await client.receive_json()
    assert msg["success"] is False
    assert msg["error"]["code"] == "not_applied"


async def test_apply_then_undo_round_trip(
    hass: HomeAssistant, hass_ws_client, setup_integration, tmp_path
) -> None:
    """Happy path: apply then undo removes the automation and clears state."""
    hass.config.config_dir = str(tmp_path)
    store = hass.data[DOMAIN][setup_integration.entry_id]["store"]
    await store.add_insight(_make_insight(payload=_valid_automation_payload()))

    client = await hass_ws_client(hass)

    # Apply
    await client.send_json_auto_id(
        {"type": "home_insights/apply", "insight_id": "abc123"}
    )
    apply_msg = await client.receive_json()
    assert apply_msg["success"] is True
    auto_id = apply_msg["result"]["automation_id"]

    yaml_path = tmp_path / "automations.yaml"
    assert yaml_path.exists()
    content_before = yaml_path.read_text(encoding="utf-8")
    assert auto_id in content_before

    # Undo
    await client.send_json_auto_id(
        {"type": "home_insights/undo", "insight_id": "abc123"}
    )
    undo_msg = await client.receive_json()
    assert undo_msg["success"] is True, undo_msg
    assert undo_msg["result"]["automation_id"] == auto_id
    assert undo_msg["result"]["drift_detected"] is False
    assert undo_msg["result"]["applied_cleared"] is True

    # Automation removed from yaml
    content_after = yaml_path.read_text(encoding="utf-8")
    assert auto_id not in content_after

    # Insight no longer marked applied
    refreshed = await store.get_insight("abc123")
    assert refreshed is not None
    assert refreshed.applied_at is None


async def test_undo_refuses_on_drift_unless_forced(
    hass: HomeAssistant, hass_ws_client, setup_integration, tmp_path
) -> None:
    hass.config.config_dir = str(tmp_path)
    store = hass.data[DOMAIN][setup_integration.entry_id]["store"]
    await store.add_insight(_make_insight(payload=_valid_automation_payload()))

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "home_insights/apply", "insight_id": "abc123"}
    )
    apply_msg = await client.receive_json()
    auto_id = apply_msg["result"]["automation_id"]

    # Simulate user editing the automation: rewrite the yaml file with
    # a different alias for the same id
    import yaml as _yaml

    yaml_path = tmp_path / "automations.yaml"
    parsed = _yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or []
    for item in parsed:
        if item.get("id") == auto_id:
            item["alias"] = "User edited this manually"
    yaml_path.write_text(_yaml.safe_dump(parsed, sort_keys=False), encoding="utf-8")

    # Undo without force should refuse
    await client.send_json_auto_id(
        {"type": "home_insights/undo", "insight_id": "abc123"}
    )
    msg = await client.receive_json()
    assert msg["success"] is False
    assert msg["error"]["code"] == "drift"

    # Automation still in yaml
    assert auto_id in yaml_path.read_text(encoding="utf-8")
    refreshed = await store.get_insight("abc123")
    assert refreshed is not None and refreshed.applied_at is not None

    # Force=true should remove it anyway
    await client.send_json_auto_id(
        {"type": "home_insights/undo", "insight_id": "abc123", "force": True}
    )
    forced = await client.receive_json()
    assert forced["success"] is True
    assert forced["result"]["drift_detected"] is True
    assert forced["result"]["force_used"] is True
    assert auto_id not in yaml_path.read_text(encoding="utf-8")
