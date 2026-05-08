"""WebSocket API for HA Insights.

Stable contract from v0.1 (per docs/ARCHITECTURE.md). Cards consume:
  - home_insights/hello       -> handshake (version + supported methods)
  - home_insights/list        -> list insights (filterable)
  - home_insights/subscribe   -> live stream of change events
  - home_insights/dismiss     -> dismiss an insight
  - home_insights/snooze      -> snooze an insight
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN

if TYPE_CHECKING:
    from .insight import Insight
    from .store import InsightStore


WS_PROTOCOL_VERSION = 1
INTEGRATION_VERSION = "0.1.0-dev"

SUPPORTED_METHODS = (
    "hello",
    "list",
    "subscribe",
    "dismiss",
    "snooze",
    "apply",
    "scan_now",
)


@callback
def async_register(hass: HomeAssistant) -> None:
    """Register all WS handlers. Idempotent via the WS framework."""
    websocket_api.async_register_command(hass, ws_hello)
    websocket_api.async_register_command(hass, ws_list)
    websocket_api.async_register_command(hass, ws_subscribe)
    websocket_api.async_register_command(hass, ws_dismiss)
    websocket_api.async_register_command(hass, ws_snooze)
    websocket_api.async_register_command(hass, ws_apply)
    websocket_api.async_register_command(hass, ws_scan_now)
    websocket_api.async_register_command(hass, ws_dev_inject_event)


def _get_store(hass: HomeAssistant) -> InsightStore | None:
    """Resolve the active store from hass.data; None if integration not set up."""
    data = hass.data.get(DOMAIN, {})
    for value in data.values():
        if isinstance(value, dict) and "store" in value:
            return value["store"]
    return None


def _get_buffer(hass: HomeAssistant):
    """Resolve the active StateEventBuffer; None if integration not set up."""
    data = hass.data.get(DOMAIN, {})
    for value in data.values():
        if isinstance(value, dict) and "buffer" in value:
            return value["buffer"]
    return None


# --- Handlers ---


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/hello",
        vol.Optional("card_version"): str,
    }
)
@callback
def ws_hello(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Handshake — return integration metadata + supported methods."""
    connection.send_result(
        msg["id"],
        {
            "integration_version": INTEGRATION_VERSION,
            "ws_protocol_version": WS_PROTOCOL_VERSION,
            "supported_methods": list(SUPPORTED_METHODS),
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/list",
        vol.Optional("include_dismissed", default=False): bool,
        vol.Optional("include_applied", default=True): bool,
    }
)
@websocket_api.async_response
async def ws_list(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """List insights from the store."""
    store = _get_store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_set_up", "Store not initialized")
        return
    insights = await store.list_insights(
        include_dismissed=msg["include_dismissed"],
        include_applied=msg["include_applied"],
    )
    connection.send_result(
        msg["id"],
        {"insights": [i.to_dict() for i in insights]},
    )


@websocket_api.websocket_command(
    {vol.Required("type"): "home_insights/subscribe"}
)
@callback
def ws_subscribe(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Subscribe to insight change events (added / dismissed / snoozed)."""
    store = _get_store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_set_up", "Store not initialized")
        return

    sub_id = msg["id"]

    @callback
    def on_event(event_type: str, insight: Insight | None) -> None:
        connection.send_event(
            sub_id,
            {
                "action": event_type,
                "insight": insight.to_dict() if insight else None,
            },
        )

    unsub = store.add_listener(on_event)
    connection.subscriptions[sub_id] = unsub
    connection.send_result(sub_id)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/dismiss",
        vol.Required("insight_id"): str,
    }
)
@websocket_api.async_response
async def ws_dismiss(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Permanently dismiss an insight."""
    store = _get_store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_set_up", "Store not initialized")
        return
    success = await store.dismiss_insight(msg["insight_id"])
    if not success:
        connection.send_error(
            msg["id"], "not_found", f"No insight {msg['insight_id']!r}"
        )
        return
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/apply",
        vol.Required("insight_id"): str,
    }
)
@websocket_api.async_response
async def ws_apply(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Apply an insight: validate, write the automation, record snapshot."""
    from .apply import AutomationWriter, hash_config, validate_automation

    store = _get_store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_set_up", "Store not initialized")
        return
    insight = await store.get_insight(msg["insight_id"])
    if insight is None:
        connection.send_error(
            msg["id"], "not_found", f"No insight {msg['insight_id']!r}"
        )
        return
    if insight.payload_format != "automation":
        connection.send_error(
            msg["id"],
            "unsupported_format",
            f"payload_format {insight.payload_format!r} not yet supported",
        )
        return

    errors = validate_automation(insight.payload)
    if errors:
        connection.send_error(msg["id"], "invalid_payload", "; ".join(errors))
        return

    writer = AutomationWriter(hass)
    auto_id = await writer.write(insight.payload)
    snapshot = await writer.read(auto_id) or insight.payload

    await store.record_applied(
        insight.id,
        artifact_kind="automation",
        artifact_id=auto_id,
        snapshot=snapshot,
        snapshot_hash=hash_config(snapshot),
    )
    connection.send_result(msg["id"], {"automation_id": auto_id})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/snooze",
        vol.Required("insight_id"): str,
        vol.Required("until"): str,
    }
)
@websocket_api.async_response
async def ws_snooze(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Snooze an insight until the given ISO timestamp."""
    store = _get_store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_set_up", "Store not initialized")
        return
    try:
        until = datetime.fromisoformat(msg["until"])
    except ValueError:
        connection.send_error(
            msg["id"], "invalid_time", "until must be ISO 8601 format"
        )
        return
    success = await store.snooze_insight(msg["insight_id"], until=until)
    if not success:
        connection.send_error(
            msg["id"], "not_found", f"No insight {msg['insight_id']!r}"
        )
        return
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {vol.Required("type"): "home_insights/scan_now"}
)
@websocket_api.async_response
async def ws_scan_now(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Run all registered detectors immediately. Returns count of new insights."""
    from .detectors import DETECTORS, DetectorContext

    store = _get_store(hass)
    buffer_ = _get_buffer(hass)
    if store is None or buffer_ is None:
        connection.send_error(msg["id"], "not_set_up", "Store/buffer not initialized")
        return

    ctx = DetectorContext(hass=hass, event_buffer=buffer_)
    new_count = 0
    detector_names: list[str] = []
    for name, detector_cls in DETECTORS.items():
        detector = detector_cls()
        insights = await detector.scan(ctx)
        for insight in insights:
            await store.add_insight(insight)
            new_count += 1
        detector_names.append(name)

    connection.send_result(
        msg["id"],
        {
            "detectors_run": detector_names,
            "insights_emitted": new_count,
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/_dev/inject_event",
        vol.Required("entity_id"): str,
        vol.Required("domain"): str,
        vol.Optional("area_id"): vol.Any(str, None),
        vol.Required("timestamp"): str,
        vol.Optional("old_state"): vol.Any(str, None),
        vol.Required("new_state"): str,
    }
)
@callback
def ws_dev_inject_event(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """DEV ONLY — push a synthetic state event into the buffer with a chosen timestamp.

    Used by dev/seed.py to backfill the rolling buffer for ScheduleDetector
    testing without needing access to HA's recorder. Not part of the stable
    public API; the underscore prefix marks it as dev-only.
    """
    from .observers.state_event_buffer import StateEvent

    buffer_ = _get_buffer(hass)
    if buffer_ is None:
        connection.send_error(msg["id"], "not_set_up", "Buffer not initialized")
        return

    try:
        ts = datetime.fromisoformat(msg["timestamp"])
    except ValueError:
        connection.send_error(
            msg["id"], "invalid_time", "timestamp must be ISO 8601 format"
        )
        return

    event = StateEvent(
        timestamp=ts,
        entity_id=msg["entity_id"],
        domain=msg["domain"],
        area_id=msg.get("area_id"),
        old_state=msg.get("old_state"),
        new_state=msg["new_state"],
    )
    accepted = buffer_.add(event)
    connection.send_result(msg["id"], {"accepted": accepted})
