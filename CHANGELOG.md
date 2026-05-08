# Changelog

All notable changes to this project are documented in this file. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
