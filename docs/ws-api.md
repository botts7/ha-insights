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
{"id": 1, "type": "home_insights/hello", "card_version": "0.1.0"}
```

**Response:**
```json
{
  "id": 1,
  "type": "result",
  "success": true,
  "result": {
    "integration_version": "0.1.0",
    "ws_protocol_version": 1,
    "supported_methods": ["hello", "list", "subscribe", "dismiss", "snooze", "apply", "scan_now", "purge_all"]
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

**Request:** `{"id": 6, "type": "home_insights/apply", "insight_id": "<id>"}`

**Response:** `{"automation_id": "ha_insights_<8-hex>"}`

**Errors:** `not_found`, `unsupported_format` (only `payload_format: "automation"` in v0.1), `invalid_payload` (Layer 1 schema rejected).

## `home_insights/scan_now`

Run all registered detectors immediately against the current state buffer. Useful for testing detectors and for forcing an out-of-band scan.

**Request:** `{"id": 7, "type": "home_insights/scan_now"}`

**Response:** `{"detectors_run": ["schedule", ...], "insights_emitted": <count>}`

## `home_insights/purge_all`

Privacy nuke — clears in-memory buffer, all insights, and outbound-call audit. Pseudonym map and applied-history snapshots are preserved.

**Request:** `{"id": 8, "type": "home_insights/purge_all"}`

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
