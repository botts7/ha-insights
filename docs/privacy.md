# HA Insights — Privacy

Privacy is the central invariant of this project. This document spells out exactly what gets observed, where it's stored, what does and doesn't cross your network boundary, and how to delete everything.

**If anything in this document differs from what you observe in practice, that's a bug — please open an issue.**

## TL;DR

- **Three privacy modes** (Off / Local / Cloud) selected at install + switchable in-place via the OptionsFlow.
- **Off** ships zero outbound network calls. All detection is local.
- **Local** + **Cloud** both run all data through a redactor before any LLM call: entity_ids become stable pseudonyms (`light.entity_a3f1b2`), sensitive attributes (GPS / MAC / tokens / passwords / serial) are stripped, per-entity opt-out lets you blocklist specific entities entirely.
- **Audit log + previewer**: the panel surfaces every outbound LLM call, and a 🛡️ "What gets sent?" button shows the exact redacted payload before any LLM call.
- **One-shot escape hatch**: the `ha_insights.purge_observations` service wipes observed state, insights, and the outbound-call audit log.

## Privacy modes

| Mode | LLM enabled? | What leaves the host? |
|---|---|---|
| **Off** | No | Nothing. Pattern detection is local-only. |
| **Local** | Yes — local Conversation agent (Ollama, Piper) | Pseudonymized payload + redacted text. Stays on your network. |
| **Cloud** | Yes — cloud Conversation agent (Anthropic, OpenAI, Google AI, Nabu Casa) | Same pseudonymized payload + redacted text. Real entity_ids never leave. Requires explicit consent in the wizard. |

Mode is changeable in-place via **Settings → Devices & Services → HA Insights → Configure**. Switching INTO Cloud re-prompts the consent dialog.

## What HA Insights observes

After install + setup, the integration subscribes to **two** HA event-bus events:

1. **`state_changed`** — every state transition for entities in your selected Areas. Default-blocked domains (`camera`, `person`, `device_tracker`, `lock`) are filtered before they ever enter the buffer.
2. **`entity_registry_updated`** — so a HA-side rename atomically migrates the buffer entries and pseudonym map. Avoids breaking detector history when you rename `light.kitchen` to `light.galley`.

Each accepted state change is appended to an in-memory rolling buffer (default 14-day window, matching the configured `lookback_days`). On first install, HA's recorder is queried to backfill historical events into the buffer (configurable 0-30 days — 0 disables backfill entirely).

## Where data lives

| What | Where | Persists across restart? |
|---|---|---|
| State events (live + backfilled) | In-memory rolling buffer | No (recorder backfill repopulates on next setup) |
| Insights | `<config>/ha_insights_<entry_id>.db` (SQLite) | Yes |
| Pseudonym map | Same SQLite | Yes (so the LLM sees stable identifiers across calls) |
| Applied-history snapshots | Same SQLite | Yes (used for future undo) |
| Outbound-call audit log | Same SQLite | Yes |

The `.db` filename includes the config-entry id so removing and re-adding the integration creates a fresh database.

## Default-blocked domains

HA Insights ignores all events on:

- `camera` — privacy (image / motion data)
- `person` — privacy (presence / location)
- `device_tracker` — privacy (location)
- `lock` — safety (LLMs never suggest unlock automations, even with explicit user prompting)

The privacy three (camera / person / device_tracker) are recoverable via custom config in future releases. The safety block on `lock` stays in every mode regardless — that's a hard rule, not a preference.

## Per-entity opt-out (v0.6)

Beyond mode-driven redaction, you can blocklist specific entity_ids that should NEVER reach an LLM in any form. The `llm_block_entities` config option (set via `data` or `options` on the config entry):

```yaml
llm_block_entities:
  - lock.front_door
  - device_tracker.kids_phone
  - sensor.specific_secret_metric
```

Behaviour at the redactor layer:
- Listed entity_ids in payload values become `[blocked]`
- Listed entity_ids inside list values are filtered out
- Free-text mentions of listed entity_ids are masked to `[blocked]`
- The `🛡️ What gets sent?` modal shows a "blocked" count when any opt-out hit

## Redactor (Cloud + Local mode)

Every LLM-bound payload runs through:

1. **Always-redact attribute floor** — these keys are stripped regardless of mode:
   - `gps_lat`, `gps_lon`, `latitude`, `longitude`, `altitude`
   - `mac`, `ip`, `bssid`, `ssid`
   - `password`, `token`, `access_token`, `auth`, `api_key`, `secret`
   - `serial_number`, `device_id`
2. **Per-entity opt-out** (above)
3. **Pseudonymization** — entity_ids replaced with stable per-call pseudonyms via the local `pseudonym_map` table. The LLM sees `light.entity_a3f1b2`; the response is dereferenced back to `light.kitchen` before display.
4. **Title + payload deep-walk** — every string value is scanned for entity-id-shaped substrings; matches are replaced.

The redactor is the same module called by Refine, Explain, and the `home_insights/redaction_preview` WS endpoint, so the previewer shows the *actual* output of the same pipeline that gets sent to the LLM.

## Audit log

Every LLM call (Refine + Explain) writes one row to `outbound_calls`:
- Timestamp + insight_id + agent + agent_locality (local / cloud) + redaction_mode
- Bytes sent + bytes received
- Success / failure
- Optional: full redacted payload JSON (off by default; toggle for forensics only)

The panel's **🛡️ LLM activity** section displays the most recent 25 calls. The full table is queryable via the existing `home_insights/audit_log` WS command (limit configurable 1-500).

## How to wipe everything

Fastest path — call the service from Developer Tools → Services, or from any automation:

```yaml
service: ha_insights.purge_observations
```

This deletes:

- All in-memory state events
- All insights in the SQLite store
- All outbound-call audit entries

It **preserves**:

- The pseudonym map — so cross-restart references stay stable
- Applied-history snapshots — so future undo still works for previously-applied automations

For a complete wipe including pseudonyms and applied-history, remove the integration entirely via **Settings → Devices & Services → HA Insights → Delete**. The next install creates a fresh per-entry SQLite database with no historical state at all.

## Inspecting what's stored

The SQLite database is plain text-readable from inside the HA container:

```bash
docker exec -it homeassistant sqlite3 /config/ha_insights_<entry_id>.db
sqlite> .tables
sqlite> SELECT * FROM insights;
sqlite> SELECT * FROM outbound_calls;
sqlite> SELECT * FROM pseudonym_map;
```

Or copy the file out of the container (`docker cp ...`) for offline inspection.

## What HA Insights *cannot* do (hard guarantees)

- Two event-bus listeners only: `state_changed` and `entity_registry_updated`. No others.
- Does not write to entities outside the automation it creates on Apply.
- Does not call HA services other than `automation.reload` after writing the automation file (and the action you click Test on, which is by definition explicit).
- In **Off** mode: makes no outbound network connection. (Verified by absence of `aiohttp.ClientSession` usage in non-LLM code paths.)
- In **Local / Cloud** modes: every outbound call passes through the redactor; the audit log captures the final sent payload size; the previewer can show the exact JSON before sending.
- Sensitive attributes (GPS / MAC / tokens / passwords / serials) are stripped from every insight payload regardless of mode — they never reach the redactor's pseudonymization pass to begin with.

## Authorization on the WebSocket surface

Mutating + cost-incurring WS endpoints require `connection.user.is_admin`:

- `home_insights/apply` (writes `automations.yaml`)
- `home_insights/undo`
- `home_insights/purge_all` (wipes audit log)
- `home_insights/test_actions` (fires arbitrary services)
- `home_insights/explain`, `home_insights/refine`, `home_insights/hypothesize` (cost-incurring LLM calls against the admin's API key)
- `home_insights/_dev/inject_event` (debug-only state injection)

Read-only and per-user-state endpoints stay open: `list`, `dismiss`, `snooze`, `scan_now`, `subscribe`, `audit_log`, `redaction_preview`, `refine_cost_estimate`, `hello`, `list_entries`, `backfill_status`. A non-admin frontend user can review insights and dismiss/snooze them, but can't mutate shared state or burn LLM tokens.

## Per-attempt audit log

When LLM agent failover walks more than one candidate (e.g. Anthropic times out, integration falls over to Ollama), each round-trip lands in `outbound_calls` as its own row — not just the successful attempt. The privacy-log sensor's `bytes_sent_today` reflects total cumulative network egress including failed attempts.

Each row records the actual responding agent (`agent`), the locality classification (`local` / `cloud` / `unknown`), the redaction mode at the time, and the byte counts. The `est_cost_usd` per row uses our pricing table (Anthropic Opus/Sonnet/Haiku, OpenAI 4o/4o-mini, Google Gemini 2.5 Pro/Flash, vendor fallback). Local agents always cost $0.

## User-supplied detectors (sandbox)

Off by default. When a user opts in via OptionsFlow (`allow_user_detectors=True`), `<config>/ha_insights_detectors/*.py` files are AST-scanned and rejected if they import network modules (`socket`, `urllib`, `requests`, `httpx`, `aiohttp`, `ssl`, `http`, `ftplib`, `smtplib`, etc.), filesystem-write modules (`os`, `shutil`, `tempfile`, `subprocess`), code-execution helpers (`pickle`, `marshal`, `code`, `ctypes`), or use `__import__`, `__builtins__`, `eval`, `exec`, `compile`. Modules clearing the scan run with full HA process privileges; the AST check is a best-effort sandbox, not actual subprocess isolation.

## Reporting privacy concerns

If you find HA Insights doing something this document says it doesn't — please open a [GitHub issue](https://github.com/botts7/ha-insights/issues) with a reproduction. Privacy bugs are top priority.
