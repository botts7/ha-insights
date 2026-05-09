# HA Insights — WebSocket API

Stable from v0.1 with semver. Breaking changes require a major version bump and increment the `ws_protocol_version` returned by `home_insights/hello`.

All examples assume an authenticated WebSocket connection at `ws://<your-ha>/api/websocket`.

## Authenticate

Standard Home Assistant WebSocket auth flow first:

```json
// HA sends:
{"type": "auth_required", "ha_version": "..."}

// You send:
{"type": "auth", "access_token": "<long-lived token>"}

// HA replies:
{"type": "auth_ok", "ha_version": "..."}
```

After auth, all `home_insights/*` commands are available.

## `home_insights/hello`

Handshake. Returns integration metadata so cards can detect protocol skew and degrade gracefully.

**Request:**
```json
{"id": 1, "type": "home_insights/hello", "card_version": "0.7.0"}
```

**Response:**
```json
{
  "id": 1,
  "type": "result",
  "success": true,
  "result": {
    "integration_version": "0.7.0",
    "ws_protocol_version": 1,
    "supported_methods": [
      "hello", "list", "subscribe", "dismiss", "snooze", "apply",
      "scan_now", "purge_all", "explain", "refine", "test_actions",
      "backfill_status", "redaction_preview", "audit_log"
    ],
    "privacy_mode": "off"
  }
}
```

If a card's expected `ws_protocol_version` doesn't match the integration's, the card should disable any features that depend on incompatible methods and surface a banner.

## `home_insights/list`

List insights. Defaults exclude dismissed, applied, and currently-snoozed entries.

**Request:**
```json
{
  "id": 2,
  "type": "home_insights/list",
  "include_dismissed": false,
  "include_applied": false,
  "include_snoozed": false
}
```

**Response:** `{"insights": [Insight, ...]}` where each `Insight` has fields:

| Field | Type | Notes |
|---|---|---|
| `id` | string | Stable hash of (kind + fingerprint) |
| `kind` | enum | `automation_proposal`, `card_proposal`, `anomaly`, etc. |
| `detector` | string | Detector name (e.g., `schedule`) |
| `area_id` | string \| null | The HA area, if any |
| `title` | string | Heuristic-generated, no LLM |
| `confidence` | float | 0.0-1.0 |
| `fingerprint` | object | Detector-specific dedup key |
| `payload` | object | The YAML/blueprint to apply (heuristic-built) |
| `payload_format` | enum | `automation` (v0.1), `blueprint` (v0.2+), etc. |
| `created_at` | ISO timestamp | |
| `snoozed_until` | ISO timestamp \| null | |
| `explanation` | string \| null | Populated by LLM (v0.2+) |
| `conflicts_with` | string[] | Existing automation ids that overlap |

## `home_insights/subscribe`

Live stream of insight change events. Held open until the client unsubscribes or disconnects.

**Request:** `{"id": 3, "type": "home_insights/subscribe"}`

**Events** (delivered as `{"id": 3, "type": "event", "event": ...}`):
```json
{
  "action": "added" | "dismissed" | "snoozed" | "applied",
  "insight": {Insight} | null
}
```

The card removes the row on `dismissed` / `applied` / `snoozed` (matching the default `list` filter) and inserts/updates on `added`.

## `home_insights/dismiss`

Permanently dismiss an insight. The fingerprint goes into a blacklist so the same routine isn't re-suggested.

**Request:** `{"id": 4, "type": "home_insights/dismiss", "insight_id": "<id>"}`

**Errors:** `not_found` if no insight has that id.

## `home_insights/snooze`

Snooze until a future ISO timestamp.

**Request:** `{"id": 5, "type": "home_insights/snooze", "insight_id": "<id>", "until": "2026-06-01T00:00:00+00:00"}`

**Errors:** `invalid_time` (bad ISO format), `not_found`.

## `home_insights/apply`

Validate the payload, write it as a HA automation in `<config>/automations.yaml`, trigger `automation.reload`, record a snapshot for undo.

**Request:**
```json
{
  "id": 6,
  "type": "home_insights/apply",
  "insight_id": "<id>",
  "payload_override": {...}
}
```

`payload_override` (optional, v0.3+) — when provided, that dict is written instead of the stored payload. The integration stamps `description: "Refined by HA Insights"` on the override so the lineage is visible in HA's automation editor.

**Response:** `{"automation_id": "ha_insights_<8-hex>", "refined": <bool>}`

**Errors:** `not_found`, `unsupported_format` (only `payload_format: "automation"`), `invalid_payload` (Layer 1 schema rejected).

## `home_insights/explain` (v0.2+)

Call the configured Conversation agent for a natural-language explanation of an insight's payload. Pseudonymizes everything before sending; dereferences pseudonyms in the response.

**Request:** `{"id": 7, "type": "home_insights/explain", "insight_id": "<id>", "agent_id": null}`

`agent_id` (optional) — overrides the integration's auto-pick of the first installed LLM Conversation agent.

**Response:** `{"explanation": "...", "bytes_sent": N, "bytes_received": M}`

**Errors:** `not_found`, `explain_failed` (with the LLM agent's error or "rule-based fallback" guidance).

## `home_insights/refine` (v0.3+)

Ask the LLM to propose a refined version of an automation insight. Returns the refined payload + rationale + diff summary; does NOT mutate the insight. Apply via `home_insights/apply` with `payload_override`.

**Request:**
```json
{
  "id": 8,
  "type": "home_insights/refine",
  "insight_id": "<id>",
  "agent_id": null,
  "feedback": "Add a sun.below_horizon condition"
}
```

`feedback` (optional, v0.5.1+) — user instructions prepended as the highest-priority considerations in the LLM prompt.

**Response:**
```json
{
  "refined_payload": {...},
  "rationale": "Added a 5s debounce so flapping doesn't re-trigger.",
  "diff_summary": ["+ for", "~ mode"],
  "bytes_sent": N,
  "bytes_received": M
}
```

**Errors:** `not_found`, `unsupported_format` (only `automation` payloads), `refine_failed` (with the actual reason: truncation / refusal / hallucinated entity / etc, plus a `LLM said:` snippet of the raw response when applicable).

## `home_insights/test_actions` (v0.3+)

Fires the action block of an insight without saving the automation. Mirrors HA's "Run Actions" button. Optional `payload_override` to test a refined version.

**Request:** `{"id": 9, "type": "home_insights/test_actions", "insight_id": "<id>", "payload_override": null}`

**Response:**
```json
{
  "ran": 2,
  "error_count": 0,
  "results": [
    {"index": 0, "ok": true, "service": "light.turn_on"},
    {"index": 1, "ok": false, "service": "switch.turn_on", "error": "..."}
  ]
}
```

Non-service actions (delay, choose, repeat, etc) are skipped (`{"skipped": true}`).

## `home_insights/backfill_status` (v0.4+)

Returns the current backfill status — used by cards to surface a "Backfilled N events" toast on connect.

**Request:** `{"id": 10, "type": "home_insights/backfill_status"}`

**Response:** `{"running": false, "last": {"events_added": N, "entities_seen": K, "lookback_days": D, "duration_seconds": S, "completed_at": "..."}}`

## `home_insights/redaction_preview` (v0.6+)

Runs the redactor pipeline on an insight WITHOUT calling any LLM. Returns the exact dict that would be embedded in the prompt — fuels the card's 🛡️ "What gets sent?" button.

**Request:** `{"id": 11, "type": "home_insights/redaction_preview", "insight_id": "<id>"}`

**Response:**
```json
{
  "redacted_title": "...",
  "redacted_payload": {...},
  "entities_blocked": ["lock.front_door"],
  "pseudonym_map": {"light.kitchen": "light.entity_a3f1b2"},
  "attributes_stripped": ["gps_lat"],
  "privacy_mode": "RedactionMode.AGGRESSIVE"
}
```

## `home_insights/audit_log` (v0.6+)

Returns the most recent rows from the `outbound_calls` audit table, joined to insights for titles.

**Request:** `{"id": 12, "type": "home_insights/audit_log", "limit": 50}`

**Response:**
```json
{
  "calls": [
    {
      "id": 42,
      "timestamp": "2026-05-09T...",
      "insight_id": "...",
      "insight_title": "...",
      "agent": "conversation.gemini",
      "agent_locality": "cloud",
      "redaction_mode": "RedactionMode.AGGRESSIVE",
      "bytes_sent": 1486,
      "bytes_received": 442,
      "success": true
    }
  ]
}
```

## `home_insights/scan_now`

Run all registered detectors immediately against the current state buffer. Useful for testing detectors and for forcing an out-of-band scan.

**Request:** `{"id": 13, "type": "home_insights/scan_now"}`

**Response:** `{"detectors_run": ["schedule", "cooccurrence", "long_tail", "orphan_device", "streak"], "insights_emitted": <count>}`

## `home_insights/purge_all`

Privacy nuke — clears in-memory buffer, all insights, and outbound-call audit. Pseudonym map and applied-history snapshots are preserved.

**Request:** `{"id": 14, "type": "home_insights/purge_all"}`

**Response:** `{"events_dropped": N, "insights_deleted": M, "outbound_calls_deleted": K}`

## Stability guarantees

- The WS contract is semver-stable from v0.1.
- New methods may be added in minor releases.
- Removing methods, renaming fields, or changing field semantics requires a major version bump and a `ws_protocol_version` increment.
- Cards using this API should send `home_insights/hello` first and gracefully degrade on protocol skew.

## Errors

All commands respond with the standard HA WS error envelope on failure:

```json
{
  "id": <request_id>,
  "type": "result",
  "success": false,
  "error": {"code": "<error_code>", "message": "<details>"}
}
```

Common codes used by HA Insights:

| Code | Meaning |
|---|---|
| `not_set_up` | Integration's store/buffer isn't initialized |
| `not_found` | The referenced insight id doesn't exist |
| `unsupported_format` | The insight's `payload_format` isn't supported by this command |
| `invalid_payload` | Layer 1 schema validation failed |
| `invalid_time` | A timestamp argument couldn't be parsed |

Cards should map these to specific UX states rather than dumping raw error text.
