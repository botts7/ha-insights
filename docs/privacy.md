# HA Insights — Privacy

Privacy is the central invariant of this project. This document spells out exactly what gets observed, where it's stored, what does and doesn't cross your network boundary, and how to delete everything.

**If anything in this document differs from what you observe in practice, that's a bug — please open an issue.**

## v0.1 summary (TL;DR)

- **Zero outbound network calls.** v0.1 ships without the LLM gateway wired up. Nothing leaves your Home Assistant host.
- **All state lives locally** in a per-entry SQLite database (`<config>/ha_insights_<entry_id>.db`) and an in-memory rolling buffer (default 7 days).
- **One-shot escape hatch**: the `home_insights.purge_observations` service wipes observed state, insights, and the outbound-call audit log. Pseudonyms and applied-automation snapshots are preserved by design.

## What HA Insights observes

After install + setup, the integration subscribes to **two** HA event-bus events:

1. **`state_changed`** — every state transition for entities in your selected Areas. Default-blocked domains (`camera`, `person`, `device_tracker`, `lock`) are filtered before they ever enter the buffer.
2. **`entity_registry_updated`** — so a HA-side rename atomically migrates the buffer entries and pseudonym map. Avoids breaking detector history when you rename `light.kitchen` to `light.galley`.

Each accepted state change is appended to an in-memory rolling buffer. The buffer is dropped on HA restart in v0.1 (SQLite persistence is opt-in and lands in v0.2).

## Where data lives

| What | Where | Persists across restart? |
|---|---|---|
| State events | In-memory ring buffer | No (v0.1) |
| Insights | `<config>/ha_insights_<entry_id>.db` (SQLite) | Yes |
| Pseudonym map | Same SQLite | Yes |
| Applied-history snapshots | Same SQLite | Yes (used for Undo) |
| Outbound-call audit log | Same SQLite | Yes (empty in v0.1) |

The `.db` filename includes the config-entry id so removing and re-adding the integration creates a fresh database.

## Default-blocked domains

HA Insights ignores all events on:

- `camera` — privacy (image / motion data)
- `person` — privacy (presence / location)
- `device_tracker` — privacy (location)
- `lock` — safety (LLMs should never suggest unlock automations)

The privacy three (camera / person / device_tracker) become unblock-able in v0.2 once the LLM gateway lands and you're in **Local** mode (data stays on your network). The safety block on `lock` stays in every mode regardless — that's a hard rule, not a preference.

## What never leaves your network in v0.1

**Nothing.** v0.1 has no LLM call path wired up.

The `Local` and `Cloud` choices in the setup wizard are recorded as preferences but dormant — they activate when the LLM gateway lands in v0.2.

## How to wipe everything

Fastest path — call the service from Developer Tools → Services, or from any automation:

```yaml
service: home_insights.purge_observations
```

This deletes:

- All in-memory state events
- All insights in the SQLite store
- All outbound-call audit entries (empty in v0.1)

It **preserves**:

- The pseudonym map — so cross-restart references stay stable for the v0.2 LLM gateway
- Applied-history snapshots — so undo within the 7-day window still works for previously-applied automations

For a complete wipe including pseudonyms and applied-history, remove the integration entirely via **Settings → Devices & Services → HA Insights → Delete**. The next install creates a fresh per-entry SQLite database with no historical state at all.

## Inspecting what's stored

The SQLite database is plain text-readable from inside the HA container:

```bash
docker exec -it homeassistant sqlite3 /config/ha_insights_<entry_id>.db
sqlite> .tables
sqlite> SELECT * FROM insights;
sqlite> SELECT * FROM outbound_calls;  # empty in v0.1
```

Or copy the file out of the container (`docker cp ...`) for offline inspection.

## What HA Insights *cannot* do (hard guarantees)

- It registers exactly two event-bus listeners: `state_changed` and `entity_registry_updated`. No others.
- It does not write to entities outside of the automation it creates on Apply.
- It does not call HA services other than `automation.reload` after writing an automation file.
- It does not open any outbound network connection in v0.1. (Verified by absence of `aiohttp.ClientSession` usage outside `dev/probe.py`, which is a developer-only test harness, not part of the integration.)
- It does not include sensitive attributes — GPS coordinates, MAC addresses, tokens, passwords — in any insight payload. (Mostly moot in v0.1 since no payloads leave the host, but the redactor module is already in place for v0.2.)

## What changes in v0.2

When the LLM gateway lands:

- Three privacy modes (Off / Local / Cloud) become functional.
- Every outbound LLM call passes through a redactor that pseudonymizes entity IDs and strips sensitive attributes by default.
- Every call is recorded in the `outbound_calls` audit table.
- A `sensor.ha_insights_privacy_log` entity surfaces total bytes sent / received per day for at-a-glance audit.
- A "What gets sent?" modal in the card shows an example payload at the user's current settings.

The redactor module and audit-log table are already in the v0.1 schema, so adding the LLM gateway requires no schema migration.

## Reporting privacy concerns

If you find HA Insights doing something this document says it doesn't — please open a [GitHub issue](https://github.com/botts7/ha-insights/issues) with a reproduction. Privacy bugs are top priority.
