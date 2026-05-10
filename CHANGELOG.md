# Changelog

All notable changes to this project are documented in this file. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

v1.0 release-candidate work. Internal-testing track; HACS submission deferred until the user verifies stability on their dev install.

### Added

- **Refine cost confirmation (RC #1).** New `home_insights/refine_cost_estimate` WS endpoint redacts the payload, builds the same prompt `refine_insight` would, resolves the target agent, and returns a token + USD estimate without calling the LLM. Card pre-flights this before every Refine; if cost exceeds `CONF_REFINE_COST_THRESHOLD_USD` (default $0.05) and the agent is cloud, shows a confirm dialog. Local agents always cost $0 and never trigger the confirm.
- **Multi-turn Refine (RC #2).** Threads HA's `conversation_id` through `refine_insight` so consecutive Refines on the same insight maintain agent context. Card stores `_refineConversationById` per-insight, sends it on follow-up calls, captures the new id from each response. Failover safety: `conversation_id` is dropped on attempt 2+ to a different agent. Apply / Keep Original auto-clear the thread; new "🔁 Reset conversation" button clears manually.
- **Custom detector loading (RC #3).** Drop a `*.py` into `<config>/ha_insights_detectors/` and it autoloads at integration setup. Each module loads in isolation (per-module try/except), prefixed with `ha_insights_user.*` in `sys.modules` so a user `schedule.py` can't shadow our built-in `ScheduleDetector`. Underscore-prefixed files are skipped; helper modules without a `Detector` subclass are tolerated.
- **Preferred-agent dropdown polish (RC #4).** Each option now reads `[platform] Friendly name (entity_id)` so users with multiple Anthropic and OpenAI models can disambiguate at a glance.
- **i18n (RC #5).** German translations + expanded English baseline. Every OptionsFlow field now has both a label (`data`) and a help-text under it (`data_description`) explaining what the setting does. `strings.json`, `translations/en.json`, and `translations/de.json` ship the same key set.
- **mkdocs site (RC #6).** `mkdocs.yml` with mkdocs-material, navigation linking the existing `docs/*.md`. New `docs/index.md` landing page. `.github/workflows/docs.yml` builds with `--strict` (fails on broken links) and publishes to `gh-pages` on every push to main. Site goes live at `botts7.github.io/ha-insights` once the repo flips public + Pages is enabled.
- **Multi-config-entry support (RC #7).** Drops the unique_id-based abort so users can add a second entry — useful for separate area filters, different lookback windows, or pinning different LLM agents per scope. Each entry runs an independent store / buffer / sensor / digest. New `home_insights/list_entries` WS endpoint enumerates active entries. `_get_store` / `_get_buffer` accept an optional `entry_id`; default routes to the first entry for card backwards compatibility. Per-WS-call `entry_id` routing through every command + a card picker remains a v1.1 follow-up.

### Fixed

- **`hassfest` Validate workflow.** `manifest.json` now declares `recorder` (and `conversation`, `frontend`) in `after_dependencies`, fixing a long-standing hassfest error introduced when recorder backfill landed in v0.6.

### Internal

- Manifest version bumped from `0.8.2` to `0.9.0` to match the v0.9.0 release tag.
- `RefinementResult.conversation_id` and `ExplanationResult.chosen_agent_id` now ride through the WS surface so the audit log records the agent that actually responded after failover.

## [0.9.0] — 2026-05-10

Smart Features release. Tagged on both repos. See `git log` for the breakdown across the 9 phases (1A-1C, 2, 4-9).

## [0.8.2] — 2026-05-10

Refine + apply pipeline fixes from live testing, plus a comprehensive e2e harness.

### Fixed

- **`test_actions` unwraps the `data:` action key.** Actions like `{service: persistent_notification.create, data: {title, message}}` were being passed to `hass.services.async_call` with `service_data = {"data": {...}}`, producing the `extra keys not allowed @ data['data']` validator error. The handler now flattens `action["data"]` into `service_data` so both shapes work — flat (`{service, key1, key2}`) and wrapped (`{service, data: {key1, key2}}`).
- **Refiner distinguishes service names from entity_ids.** `_collect_entity_ids` now walks the payload structurally and only matches strings reached through `entity_id` / `entity_ids` keys. New service introductions like `light.turn_off` (when the original used `light.turn_on`) no longer false-positive as "hallucinated entities".
- **Refiner backfills the `description` field** when the LLM drops it (which they routinely do). Prefers the LLM's rationale (more useful than the detector-generated original — it explains what changed); falls through to the original when no rationale is available. The diff now reads `~ description` (changed) instead of `- description` (removed).

### Added

- **`dev/_e2e_smoke.py`** — comprehensive end-to-end smoke harness. Drives the live dev HA over WebSocket, runs 30 scenarios including all previously-debugged regressions (data: key unwrap, Layer 2 unknown platform, undo round-trip, refine round-trip, service-vs-entity distinction). LLM scenarios self-skip when privacy mode is OFF. UTF-8 stdout reconfigure so the ✓/✗ markers render on Windows cmd.

## [0.8.1] — 2026-05-10

Apply pipeline polish: bulk apply, payload editor, refine progress.

### Added (in companion card v0.8.1)

- **Inline payload editor** — `✎ Edit` button on the modal swaps the read-only `<pre>` for a `<textarea>` with the JSON payload. Edits flow through `home_insights/apply` via the existing `payload_override` plumbing — same Layer 1 + Layer 2 validators on the server. Parse errors surface inline; modal stays open for the fix.
- **Bulk apply in panel** — `✓ Apply all visible` button iterates the panel's currently-filtered list and applies each as a real HA automation. Confirms first; toast summarizes the result. Bulk applies use the original detected payload only (no per-insight refined / renamed / edited drafts).
- **LLM-busy pulse animation** — Refine + Explain buttons now pulse while in flight (1.4s ease-in-out opacity) and label `💭 thinking…` / `💭 refining…` instead of static text. Replaces "asking LLM…" with something visibly alive during the 5-15s LLM round-trip.

### Changed

- `INTEGRATION_VERSION` bumped to `0.8.1`.

## [0.8.0] — 2026-05-10

Apply pipeline gains undo + a second validation layer.

### Added

- **`home_insights/undo`** WS endpoint — reverses a previous apply: looks up `applied_history`, reads the current YAML via `AutomationWriter`, runs `detect_drift` against the snapshot, deletes the automation, and clears applied state. Refuses on drift unless `force=true` so user edits aren't silently lost.
- **`Insight.applied_at` / `applied_artifact_id` / `undo_window_expires_at`** fields — applied state now flows through the WS list/get response, so cards can show "applied 2h ago" + an Undo button without a separate lookup. `_row_to_insight` LEFT JOINs `applied_history` for the undo window.
- **`InsightStore.clear_applied(insight_id)`** — drops the applied_history row + clears the markers on the insights row + fires the new `undone` subscribe event.
- **Layer 2 online validator** (`apply/online_validator.py`) — wraps HA's automation config validator (services, entities, trigger/condition/action shapes) and runs after Layer 1 in `ws_apply`. Catches things like an unknown trigger platform before we write to `automations.yaml`. Returns `code: "ha_validation_failed"` with the actual reason when the validator rejects.

### Changed

- `subscribe` now emits `action: "undone"` events when an applied insight is reversed.

## [0.7.0] — 2026-05-09

Three new detectors. The library doubles in a single release.

### Added

- **`LongTailDetector`** — finds entities that stay active longer than expected (porch light all night, fan running 6hr). Walks the rolling buffer for active spans (`on` / `playing` / `open` / `unlocked` / `active` / `home`), filters by per-domain threshold (light 90min, switch/fan 120min, media_player 240min, input_boolean 120min), surfaces patterns of ≥3 long-tails as an `AUTOMATION_PROPOSAL` with an auto-off `state for: <threshold>` trigger.
- **`OrphanDeviceDetector`** — flags entities silent for >7 days. Requires ≥3 prior events in the lookback window so newly-added entities don't fire. Emits `ANOMALY` with a notify-when-back-online automation (apply-able if user wants the ping).
- **`StreakDetector`** — emerging-routine detector. Lower bar than `ScheduleDetector`: fires on ≥3 consecutive days of the same entity → state at roughly the same time-of-day (stddev ≤30 min, looser than Schedule's 8). Skips groups that already meet ScheduleDetector's bar so the stronger detector owns those.

### Changed

- `INTEGRATION_VERSION` bumped to `0.7.0` so cards on `0.6.x` see the version skew via the `home_insights/hello` handshake.

## [0.6.0] — 2026-05-09

Trust & visibility — privacy posture is now tangible, not just documented.

### Added

- **Per-entity LLM opt-out** — new `CONF_LLM_BLOCK_ENTITIES` config option. Listed entity_ids never reach an LLM in any form: real values become `[blocked]`, list entries are filtered, free-text mentions are masked. Privacy floor below the existing mode-driven redaction.
- **`home_insights/redaction_preview` WS endpoint** — runs the redactor pipeline on a given insight without calling any LLM. Returns the exact dict that would be embedded in the prompt, plus pseudonym map, attributes stripped, and entities blocked. Fuels the card's "What gets sent?" button.
- **`home_insights/audit_log` WS endpoint** — returns recent rows from the existing `outbound_calls` table joined to `insights` for titles. Default limit 50, clamped 1-500.
- **`InsightStore.get_outbound_calls(limit)`** helper — joins outbound_calls to insights so deleted-but-still-audited entries show as `[deleted <id>]` rather than disappearing.
- **`RedactionMap.entities_blocked: list[str]`** — tracks per-call which opt-out entities were actually stripped, so the card preview can show a count.

### Changed

- `Redactor` constructor accepts `blocked_entities: frozenset[str]`. Existing call sites in `ws_explain` and `ws_refine` resolve the union across active config entries before constructing the redactor.

### Deferred to v0.6.1
- Per-entity opt-out config UI in the OptionsFlow (today's release supports it via `data` / `options` only)
- HACS distribution prep (READMEs, brand assets, default-store PR)

## [0.5.1] — 2026-05-09

Refine pipeline polish — better error surfaces, follow-up feedback support, panel cache busting.

### Added

- **`INSUFFICIENT_BUDGET` self-signal** — refine prompt now instructs the LLM to output a single `INSUFFICIENT_BUDGET` line if it cannot produce a complete refinement within its token budget, instead of starting a YAML it can't finish. Refiner detects the marker and surfaces a friendly "increase max_output_tokens" message before any parsing.
- **`feedback` parameter on `home_insights/refine`** — optional string that becomes the highest-priority considerations block in the prompt. Lets users iterate ("also add a sun condition") without re-typing the whole context. Redacted before being sent to the LLM, just like the rest of the payload.
- **Panel `module_url` cache busting** — file mtime is appended as a `?v=…` query so HA's 31-day static-cache header doesn't hold a stale build forever. "Deploy new panel.js + restart HA" now reliably propagates without DevTools cache-disable.

### Changed

- **Tighter truncation detection** — `_looks_truncated` now also flags trailing colons (key opened, no value), bare indented identifiers (e.g. `    target` mid-emit), and missing `mode:` block (our prompt always asks for it as the final key). `_looks_structurally_incomplete` catches parse-success-validation-fail cases where action is missing while trigger is present (the canonical mid-emit cutoff for LLMs).
- **Refusal detection** — refiner detects model-side safety / policy refusals (`I cannot help`, `I'm unable`, `as an AI`, etc) and surfaces a clear "LLM declined to refine" error with provider-agnostic guidance, instead of "missing YAML section."
- **`refine_failed` errors include the raw LLM response** (truncated to 600 chars). Lets users see exactly where the LLM stopped, copy/paste into a different agent for testing, or report the issue cleanly.

## [0.5.0] — 2026-05-09

Sidebar panel ships. Surfaces a dedicated full-page insights view alongside the dashboard card.

### Added

- **Sidebar panel registration** — integration registers `frontend_url_path="ha-insights"` with `mdi:chart-arc` icon and title "Insights" via `frontend.async_register_built_in_panel`. Loads `/local/ha-insights-panel.js` (shipped by the companion card repo). Cleaned up on last config-entry unload.

### Changed

- `INTEGRATION_VERSION` bumped to `0.5.0` so cards on `0.4.x` see the version skew via the `home_insights/hello` handshake (no behavior change; cards stay backwards-compatible).

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
