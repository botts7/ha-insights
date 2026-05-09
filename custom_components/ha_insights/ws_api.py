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
INTEGRATION_VERSION = "0.8.1"

SUPPORTED_METHODS = (
    "hello",
    "list",
    "subscribe",
    "dismiss",
    "snooze",
    "apply",
    "undo",
    "scan_now",
    "purge_all",
    "explain",
    "refine",
    "test_actions",
    "backfill_status",
    "redaction_preview",
    "audit_log",
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
    websocket_api.async_register_command(hass, ws_purge_all)
    websocket_api.async_register_command(hass, ws_explain)
    websocket_api.async_register_command(hass, ws_refine)
    websocket_api.async_register_command(hass, ws_test_actions)
    websocket_api.async_register_command(hass, ws_backfill_status)
    websocket_api.async_register_command(hass, ws_redaction_preview)
    websocket_api.async_register_command(hass, ws_audit_log)
    websocket_api.async_register_command(hass, ws_undo)
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


def _resolve_blocked_entities(hass: HomeAssistant, getter) -> frozenset[str]:
    """Aggregate the per-entity opt-out across active config entries.

    Single-entry common case returns that entry's set; future multi-entry
    setups are already supported by union.
    """
    blocked: set[str] = set()
    for entry in hass.config_entries.async_entries(DOMAIN):
        blocked |= getter(entry)
    return frozenset(blocked)


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
    """Handshake — return integration metadata + supported methods + privacy mode."""
    from .config_flow import get_active_mode

    privacy_mode = "off"
    for entry in hass.config_entries.async_entries(DOMAIN):
        privacy_mode = get_active_mode(entry)
        break
    connection.send_result(
        msg["id"],
        {
            "integration_version": INTEGRATION_VERSION,
            "ws_protocol_version": WS_PROTOCOL_VERSION,
            "supported_methods": list(SUPPORTED_METHODS),
            "privacy_mode": privacy_mode,
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/list",
        vol.Optional("include_dismissed", default=False): bool,
        vol.Optional("include_applied", default=False): bool,
        vol.Optional("include_snoozed", default=False): bool,
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
        include_snoozed=msg["include_snoozed"],
    )
    connection.send_result(
        msg["id"],
        {"insights": [i.to_dict() for i in insights]},
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/explain",
        vol.Required("insight_id"): str,
        vol.Optional("agent_id"): vol.Any(str, None),
    }
)
@websocket_api.async_response
async def ws_explain(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """User-initiated LLM explanation. Redactor + agent + dereference + audit."""
    from .config_flow import get_blocked_entities
    from .llm import RedactionMode, Redactor, explain_insight, record_call

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

    agent_id = msg.get("agent_id")
    blocked = _resolve_blocked_entities(hass, get_blocked_entities)
    redactor = Redactor(
        store, mode=RedactionMode.AGGRESSIVE, blocked_entities=blocked
    )
    result = await explain_insight(
        hass, agent_id=agent_id, insight=insight, redactor=redactor
    )

    await record_call(
        store,
        insight_id=insight.id,
        agent=str(agent_id) if agent_id else "default",
        # TODO: derive agent_locality from the chosen agent_id rather than
        # hard-coding "cloud" — local Conversation integrations (Ollama,
        # Piper) should record "local" so the audit log differentiates.
        agent_locality="cloud",
        redaction_mode=str(redactor.mode),
        bytes_sent=result.bytes_sent,
        bytes_received=result.bytes_received,
        success=result.success,
    )

    if not result.success:
        connection.send_error(
            msg["id"],
            "explain_failed",
            result.error or "Conversation agent returned no speech",
        )
        return

    # Persist the explanation onto the insight + notify subscribers
    await store._c.execute(
        "UPDATE insights SET explanation = ? WHERE id = ?",
        (result.explanation, insight.id),
    )
    await store._c.commit()
    refreshed = await store.get_insight(insight.id)
    store._notify("explained", refreshed)

    connection.send_result(
        msg["id"],
        {
            "explanation": result.explanation,
            "bytes_sent": result.bytes_sent,
            "bytes_received": result.bytes_received,
        },
    )


@websocket_api.websocket_command(
    {vol.Required("type"): "home_insights/purge_all"}
)
@websocket_api.async_response
async def ws_purge_all(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Privacy nuke: clear in-memory buffer + insights table + outbound-call log.

    Pseudonym map and applied-history snapshots are preserved by design.
    """
    store = _get_store(hass)
    buffer_ = _get_buffer(hass)
    if store is None or buffer_ is None:
        connection.send_error(msg["id"], "not_set_up", "Store/buffer not initialized")
        return
    events_dropped = buffer_.clear()
    counts = await store.purge_observations()
    connection.send_result(
        msg["id"],
        {"events_dropped": events_dropped, **counts},
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
        vol.Optional("payload_override"): dict,
    }
)
@websocket_api.async_response
async def ws_apply(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Apply an insight: validate, write the automation, record snapshot.

    `payload_override` (added v0.3) lets the card apply a refined automation
    in place of the original. The override is validated identically and
    stamped with `description: "Refined by HA Insights"` so the lineage is
    visible in HA's automation editor.

    Validation runs in two layers:
      L1 — offline schema check (required keys, types, mode enum)
      L2 — HA's own automation config validator (services exist,
           entities resolvable, trigger/condition/action shapes valid)
    Both must pass before we write. L2 catches "service light.turn_oN
    doesn't exist" (typo'd refinement) before it lands in
    automations.yaml as a broken automation.
    """
    from .apply import (
        AutomationWriter,
        hash_config,
        validate_automation,
        validate_automation_online,
    )

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

    override = msg.get("payload_override")
    if override is not None:
        # Stamp description so the user sees the lineage in HA's automation editor.
        # Don't mutate caller's dict.
        payload = {**override}
        payload.setdefault("description", "Refined by HA Insights")
    else:
        payload = insight.payload

    errors = validate_automation(payload)
    if errors:
        connection.send_error(msg["id"], "invalid_payload", "; ".join(errors))
        return

    online_errors = await validate_automation_online(hass, payload)
    if online_errors:
        connection.send_error(
            msg["id"],
            "ha_validation_failed",
            "; ".join(online_errors),
        )
        return

    writer = AutomationWriter(hass)
    auto_id = await writer.write(payload)
    snapshot = await writer.read(auto_id) or payload

    await store.record_applied(
        insight.id,
        artifact_kind="automation",
        artifact_id=auto_id,
        snapshot=snapshot,
        snapshot_hash=hash_config(snapshot),
    )
    connection.send_result(
        msg["id"],
        {"automation_id": auto_id, "refined": override is not None},
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/refine",
        vol.Required("insight_id"): str,
        vol.Optional("agent_id"): vol.Any(str, None),
        vol.Optional("feedback"): vol.Any(str, None),
    }
)
@websocket_api.async_response
async def ws_refine(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """User-initiated LLM refinement of an automation insight.

    Pseudonymizes the payload, calls the configured Conversation agent,
    parses + dereferences + validates the response. Does NOT mutate the
    insight — the refined payload is returned for the card to preview, then
    applied via `home_insights/apply` with `payload_override` if accepted.
    """
    from .llm import RedactionMode, Redactor, record_call, refine_insight

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
            f"refine only supports payload_format='automation' (got "
            f"{insight.payload_format!r})",
        )
        return

    from .config_flow import get_blocked_entities

    blocked = _resolve_blocked_entities(hass, get_blocked_entities)
    redactor = Redactor(
        store, mode=RedactionMode.AGGRESSIVE, blocked_entities=blocked
    )
    result = await refine_insight(
        hass,
        agent_id=msg.get("agent_id"),
        insight=insight,
        redactor=redactor,
        prior_explanation=insight.explanation,
        feedback=msg.get("feedback"),
    )

    await record_call(
        store,
        insight_id=insight.id,
        agent=str(msg.get("agent_id")) if msg.get("agent_id") else "default",
        agent_locality="cloud",
        redaction_mode=str(redactor.mode),
        bytes_sent=result.bytes_sent,
        bytes_received=result.bytes_received,
        success=result.success,
    )

    if not result.success:
        # Include a truncated raw_response so the user (and the card) can see
        # what the LLM actually returned when validation rejects the output.
        # Many LLMs produce shape-incomplete YAML even within token budget;
        # being able to inspect the raw text is essential for self-service
        # debugging.
        detail = result.error or "Refinement failed"
        if result.raw_response:
            snippet = result.raw_response.strip()
            if len(snippet) > 600:
                snippet = snippet[:600] + "…"
            detail = f"{detail}\n\nLLM said:\n{snippet}"
        connection.send_error(msg["id"], "refine_failed", detail)
        return

    connection.send_result(
        msg["id"],
        {
            "refined_payload": result.refined_payload,
            "rationale": result.rationale,
            "diff_summary": result.diff_summary,
            "bytes_sent": result.bytes_sent,
            "bytes_received": result.bytes_received,
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/test_actions",
        vol.Required("insight_id"): str,
        vol.Optional("payload_override"): dict,
    }
)
@websocket_api.async_response
async def ws_test_actions(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Fire the action block of an insight without saving the automation.

    Mirrors HA's "Run Actions" button on the automation editor. Iterates
    `payload['action']` (or the override) and calls each as a real service
    call. Triggers and conditions are skipped. Returns a per-action summary
    so the card can toast successes or surface specific errors.

    This is a privileged operation — it has real side effects on the user's
    home. The card surfaces a one-line warning before the first test.
    """
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

    payload = msg.get("payload_override") or insight.payload
    actions = payload.get("action")
    if not isinstance(actions, list) or not actions:
        connection.send_error(
            msg["id"], "no_actions", "Payload has no action list to test"
        )
        return

    results: list[dict[str, Any]] = []
    for index, action in enumerate(actions):
        if not isinstance(action, dict) or "service" not in action:
            results.append({
                "index": index,
                "ok": False,
                "error": "non-service actions (delay/choose/etc) skipped",
                "skipped": True,
            })
            continue

        service_str = action.get("service")
        if not isinstance(service_str, str) or "." not in service_str:
            results.append({
                "index": index,
                "ok": False,
                "error": f"invalid service: {service_str!r}",
            })
            continue

        domain, service = service_str.split(".", 1)
        target = action.get("target")
        # service_data = action minus the keys that aren't service params
        reserved = {"service", "target", "alias", "metadata"}
        service_data: dict[str, Any] = {
            k: v for k, v in action.items() if k not in reserved
        }
        # Some legacy actions put entity_id directly at the action level.
        # Move it into target if no target was set.
        if target is None and "entity_id" in service_data:
            target = {"entity_id": service_data.pop("entity_id")}

        try:
            await hass.services.async_call(
                domain,
                service,
                service_data or None,
                target=target,
                blocking=True,
            )
            results.append({"index": index, "ok": True, "service": service_str})
        except Exception as err:
            results.append({
                "index": index,
                "ok": False,
                "service": service_str,
                "error": str(err),
            })

    ran = sum(1 for r in results if r.get("ok"))
    errors = [r for r in results if not r.get("ok") and not r.get("skipped")]
    connection.send_result(
        msg["id"],
        {"ran": ran, "results": results, "error_count": len(errors)},
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/undo",
        vol.Required("insight_id"): str,
        vol.Optional("force", default=False): bool,
    }
)
@websocket_api.async_response
async def ws_undo(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Reverse a previous apply: delete the automation, clear applied history.

    Drift protection: if the user has edited the automation in HA's UI
    since we wrote it, we refuse the undo unless `force=true` so the
    user's manual edits aren't silently lost. The drift error returns
    `code: "drift"` plus a side-by-side hint so the card can prompt
    "you've edited this — undo anyway?".
    """
    from .apply import AutomationWriter, detect_drift

    store = _get_store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_set_up", "Store not initialized")
        return

    insight_id = msg["insight_id"]
    history = await store.get_applied_history(insight_id)
    if history is None:
        connection.send_error(
            msg["id"], "not_applied", f"Insight {insight_id!r} has no applied history"
        )
        return

    artifact_id = str(history["artifact_id"])
    snapshot = history["snapshot"]
    if not isinstance(snapshot, dict):
        connection.send_error(
            msg["id"], "corrupt_snapshot", "Stored snapshot is malformed"
        )
        return

    writer = AutomationWriter(hass)
    current = await writer.read(artifact_id)
    drift_detected = current is not None and detect_drift(snapshot, current)
    if drift_detected and not msg.get("force"):
        connection.send_error(
            msg["id"],
            "drift",
            (
                "Automation has been edited since it was applied. Pass "
                "force=true to undo anyway and lose those edits."
            ),
        )
        return

    deleted = await writer.delete(artifact_id) if current is not None else True
    if not deleted:
        connection.send_error(
            msg["id"],
            "delete_failed",
            f"Could not remove automation {artifact_id!r}",
        )
        return

    cleared = await store.clear_applied(insight_id)
    connection.send_result(
        msg["id"],
        {
            "automation_id": artifact_id,
            "drift_detected": drift_detected,
            "force_used": bool(msg.get("force")),
            "applied_cleared": cleared,
        },
    )


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
        vol.Required("type"): "home_insights/redaction_preview",
        vol.Required("insight_id"): str,
    }
)
@websocket_api.async_response
async def ws_redaction_preview(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Show the user exactly what would be sent to the LLM, no call made.

    Same redaction pipeline as `explain` and `refine` but stops before
    the conversation API. Returns:
      - redacted_payload: the dict that would be embedded in the prompt
      - entities_blocked: entity_ids stripped via per-entity opt-out
      - pseudonym_map: real-id -> pseudonym pairs (transparency)
      - attributes_stripped: attribute names dropped (gps, mac, secrets)
      - privacy_mode: which mode this preview reflects
    """
    from .config_flow import get_blocked_entities
    from .llm import RedactionMode, Redactor

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

    blocked = _resolve_blocked_entities(hass, get_blocked_entities)
    redactor = Redactor(
        store, mode=RedactionMode.AGGRESSIVE, blocked_entities=blocked
    )
    redacted_payload, redaction_map = await redactor.redact_insight_payload(
        insight.payload
    )
    redacted_title, _ = await redactor.redact_text(insight.title)

    connection.send_result(
        msg["id"],
        {
            "redacted_title": redacted_title,
            "redacted_payload": redacted_payload,
            "entities_blocked": list(redaction_map.entities_blocked),
            "pseudonym_map": dict(redaction_map.entity_to_pseudonym),
            "attributes_stripped": list(redaction_map.attributes_stripped),
            "privacy_mode": str(redactor.mode),
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/audit_log",
        vol.Optional("limit", default=50): vol.All(int, vol.Range(min=1, max=500)),
    }
)
@websocket_api.async_response
async def ws_audit_log(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return recent outbound LLM calls for the audit log viewer."""
    store = _get_store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_set_up", "Store not initialized")
        return
    rows = await store.get_outbound_calls(limit=msg["limit"])
    connection.send_result(msg["id"], {"calls": rows})


@websocket_api.websocket_command(
    {vol.Required("type"): "home_insights/backfill_status"}
)
@callback
def ws_backfill_status(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the current backfill status for the (single) config entry.

    Used by the card to surface a "Backfilled N events" toast on first
    connect after install. Returns {running, last}; `last` is the summary
    dict from the most recent run (or null if backfill has never run).
    """
    for entry_data in hass.data.get(DOMAIN, {}).values():
        if isinstance(entry_data, dict) and "buffer" in entry_data:
            connection.send_result(
                msg["id"],
                {
                    "running": bool(entry_data.get("backfill_running")),
                    "last": entry_data.get("last_backfill"),
                },
            )
            return
    connection.send_error(msg["id"], "not_set_up", "Integration not initialized")


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
