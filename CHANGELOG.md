# Changelog

All notable changes to this project are documented in this file. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.4.0] — 2026-05-09

Day-one onboarding shipped — the integration now backfills the StateEventBuffer from HA's recorder on install, so detectors find routines immediately instead of after a 1-2 week buffer fill.

### Added

- **`observers/history_backfill.py`** — async `backfill(hass, buffer, lookback_days, allowed_domains)` that pulls significant states from HA's recorder for the configured window and streams them into the rolling buffer. Domain allowlist (`light, switch, binary_sensor, fan, climate, cover, lock, media_player, input_boolean, input_select, input_number, scene, script`) excludes diagnostic/stats/weather entities that don't carry behavioral signal. Skips `unavailable` / `unknown` states; chains `old_state` across consecutive events for transition detection.
- **Auto-on-setup backfill** — `async_setup_entry` schedules the backfill as a background task so setup doesn't block. Buffer's `max_age` is widened to match `lookback_days` so backfilled events aren't immediately pruned.
- **`ha_insights.backfill` service** — manual re-run with optional `lookback_days` override. Surfaces in HA's UI with a slider selector (1-30).
- **`CONF_LOOKBACK_DAYS` config option** — 0-30 days, default 14. 0 disables backfill entirely. Configurable via initial flow + OptionsFlow. `get_lookback_days()` helper clamps invalid values.
- **`home_insights/backfill_status` WS endpoint** — returns `{running, last}` for the active config entry. Companion card uses this on connect to surface a one-shot toast (`"Backfilled N events from K entities (Dd)"`) only when a recent run actually ingested data.

### Changed

- `OptionsFlow` no longer sets `self.config_entry` explicitly (HA 2025.12 made it a read-only property; was previously deprecated, now hard error).

### Compatibility

- Requires HA recorder enabled (the default). Disabling the recorder makes backfill a no-op; live event capture still works.

## [0.3.0] — 2026-05-09

Refine + Co-occurrence detector + better Test actions feedback. Live-verified end-to-end against Google Gemini.

### Added

- **`CooccurrenceDetector`** — finds "entity B follows entity A within N seconds" patterns over the rolling state buffer. Common case: porch light comes on shortly after front door opens. 30s sliding window, requires ≥5 occurrences with timing stddev ≤12s and ≥60% leader-follower consistency. Emits an `AUTOMATION_PROPOSAL` with a state-trigger automation payload. Inherits the same default-blocked-domain rules (camera/person/tracker/lock) from the Detector ABC.
- **`home_insights/refine` WS endpoint** — user-initiated LLM refinement of an automation insight. Pseudonymizes the payload, calls the configured Conversation agent with a structured `RATIONALE: / YAML:` prompt, parses + dereferences pseudonyms, validates shape, and validates that the entity-id set is a subset of the original (rejects hallucinated entities). Returns refined_payload + rationale + diff_summary. Does NOT mutate the insight — the card holds the preview locally and applies via `home_insights/apply` with `payload_override` if the user accepts.
- **`payload_override` on `home_insights/apply`** — apply a refined automation in place of the original. The override is validated identically and stamped with `description: "Refined by HA Insights"` so the lineage shows in HA's automation editor.
- **`home_insights/test_actions` WS endpoint** — fires the action block of an insight without saving the automation. Mirrors HA's "Run Actions" button. Iterates `payload['action']`, skips non-service actions (delay/choose/etc), calls each via `hass.services.async_call`, returns per-action results with `ran` / `error_count` summary. Accepts `payload_override` so users can test a refined version before applying.
- **Truncation-aware refine error** — when the LLM hits its `max_output_tokens` mid-YAML, the refiner detects the unterminated quote/bracket pattern and surfaces a user-actionable error pointing to the LLM Conversation integration's max-tokens setting, instead of a raw YAML parser exception.

### Deferred to v0.4

- HA Blueprint emission (raw-automation apply path works end-to-end).
- Recorder backfill for day-one onboarding (insights immediately on install instead of after a 1-2 week buffer fill).
- Dedicated insights sidebar panel.

## [0.2.0] — 2026-05-09

LLM Explain feature shipped — privacy-first LLM enrichment via HA's Conversation API. Live-verified end-to-end against Google Gemini.

### Added

- **LLM Explain feature** — `home_insights/explain` WS command redacts the insight payload, calls a configured Conversation agent (Anthropic / OpenAI / Google AI / Ollama), dereferences pseudonyms in the response back to real entity_ids, persists the explanation onto the insight, fires `explained` subscribe event.
- **Privacy redactor** (`llm/redactor.py`) with mode-aware behavior. Always-redacted attributes — GPS / MAC / IP / tokens / passwords / serial — stripped regardless of mode. Stable pseudonyms via `pseudonym_map` so the LLM sees consistent identifiers across calls.
- **Auto-pick LLM agent** — scans the entity registry on every Explain call, finds any installed LLM Conversation integration, falls back to HA's default agent only if no LLM is installed.
- **Privacy log sensor** — `sensor.ha_insights_privacy_log` exposes trailing-24h call count, bytes-sent/received, last-call timestamp, last-agent name. Diagnostic category, mdi:shield-eye icon.
- **OptionsFlow** for in-place mode switching (Off ↔ Local ↔ Cloud) without removing + re-adding the integration. Switching INTO Cloud re-prompts the data-flow consent dialog.
- **`home_insights/hello` returns `privacy_mode`** so cards can render the active mode.
- **Differentiated error surfaces**: LLM agent errors show the agent's actual response (rate limit, deprecated model, invalid key); rule-based fallback shows install instructions for an LLM Conversation integration.

### Changed

- `home_insights/list` defaults: now excludes applied insights too (`include_applied=false`). Snoozed insights filtered when `snoozed_until > now`.

### Fixed

- `AutomationWriter` writes to `<config>/automations.yaml` (the canonical user-editable file HA's `automation.reload` re-reads), not `.storage/automations` which the automation domain doesn't read for runtime registration.

## [0.1.0] — 2026-05-08

First public release.

### Added

- **`ScheduleDetector` hero feature** — finds time-of-day routines from observed HA state events (e.g., "weekday mornings ~6:47 AM you turn on `light.kitchen`"), emits an `AUTOMATION_PROPOSAL` insight with a ready-to-apply automation YAML payload.
- **WebSocket API** (semver-stable from v0.1) — `home_insights/hello`, `list`, `subscribe`, `dismiss`, `snooze`, `apply`, `scan_now`, `purge_all`. Cards use the handshake to detect protocol skew and degrade gracefully.
- **`Insight` + `Detector` ABC + registry** — load-bearing community contract. Drop a file in `custom_components/ha_insights/detectors/`, decorate with `@register_detector`, and your detector is auto-loaded.
- **Three-mode privacy wizard config flow** — Off / Local / Cloud. Cloud requires explicit consent. v0.1 ships only **Off** functionally (Local + Cloud activate when v0.2 lands the LLM gateway).
- **SQLite-backed `InsightStore`** — per-config-entry database with idempotent migrations, listener bus for live event subscribe.
- **In-memory `StateEventBuffer`** — rolling 7-day window, area-filtered at insertion. Subscribed to HA's `state_changed` event bus.
- **Entity-rename handler** — `entity_registry_updated` triggers atomic migration of buffer entries + pseudonym map so renames don't sever detector history.
- **Conflict scanner + Layer 1 validator** — pre-flight checks before any apply: overlap detection vs existing automations, schema-shape validation.
- **Apply pipeline** — writes to `<config>/automations.yaml` (the canonical user-editable file HA's `automation.reload` re-reads), records snapshot for undo, marks insight applied. Configurable conflict detection.
- **Drift detector** — blake2b hash comparison so future undo flows can warn on user edits before reverting.
- **`home_insights.purge_observations` service** — privacy escape hatch. Wipes observed state + insights + outbound-call audit log. Preserves pseudonym map and applied-history snapshots by design.
- **`home_insights.scan_now` service** — runs all registered detectors immediately.
- **Companion Lovelace card** — [ha-insights-card](https://github.com/botts7/ha-insights-card). Lit + TypeScript. Live-updates via subscribe. Apply / Snooze / Dismiss with optimistic UX and toast confirmations.
- **`dev/` harness** — docker-compose with HA 2025.4, `seed.py`, `probe.py` for end-to-end verification.
- **Documentation** — `docs/ARCHITECTURE.md`, `docs/privacy.md`, `docs/ws-api.md`, `docs/writing-a-detector.md`.

### Privacy posture

**v0.1 makes zero outbound network calls.** All detection and storage happens locally on the HA host. The Local + Cloud modes in the wizard are stored as preferences but dormant until v0.2 wires the LLM gateway. The `purge_observations` service is the user-facing escape hatch.

### Deferred to v0.2

- LLM gateway (Local + Cloud modes become functional)
- Trust badges + "What gets sent?" modal in the card
- Detail modal with payload preview + Explain button
- HA Blueprint emission (v0.1 emits raw automations)
- Co-occurrence detector
- Privacy-log sensor entity
- HACS-default-store inclusion (requires public repo + brand assets)

### Compatibility

- Home Assistant 2025.4+
- Python 3.13+
- Companion card requires modern browsers (last two versions of Chrome / Firefox / Safari)

[Unreleased]: https://github.com/botts7/ha-insights/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/botts7/ha-insights/releases/tag/v0.1.0
