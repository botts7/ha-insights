# HA Insights

**Proactive routine detection and AI-assisted automation suggestions for Home Assistant.**

> *"On weekdays at ~06:47 AM you turn on `light.kitchen` — automate this?"*

Click **Apply** and the suggestion lands as a real HA automation. Optional LLM enrichment refines the YAML, explains the proposal, and proposes plausible causes for anomalies — with strict privacy controls and a full audit log of every byte that leaves your network.

## What you get

- **Eight built-in detectors** covering daily schedules, weekly patterns, entity-follows-entity correlations (with lag), long-running states, anomalies, orphan devices, streaks
- **Opt-in user-supplied detectors** loaded from `<config>/ha_insights_detectors/*.py` with AST-sandbox
- **Multi-turn LLM Refine** — iterate the proposed automation through natural conversation
- **Agent failover** — auto-pick walks preferred → Assist default → other agents on failure
- **Per-call cost estimator + threshold confirm** — prevents surprise Opus-tier bills
- **Three-mode privacy wizard** — Off (no LLM) / Local (Ollama / Wyoming) / Cloud (Anthropic, OpenAI, Google) with explicit consent
- **Pseudonymization on by default** — real entity_ids never leave your network on cloud calls
- **Sidebar panel + Lovelace card** — review, refine, apply, undo, drift-aware
- **Full audit log** — every outbound call recorded with agent / locality / bytes / cost / success
- **Daily digest + high-confidence notifications**
- **Multi-config-entry** — independent insight scopes
- **English + German translations**

## Companion card

This integration ships with a companion Lovelace card available at [`botts7/ha-insights-card`](https://github.com/botts7/ha-insights-card). Install it from HACS as a Frontend (Lovelace) custom repository.

## Documentation

- [Architecture](https://github.com/botts7/ha-insights/blob/main/docs/ARCHITECTURE.md)
- [Privacy charter](https://github.com/botts7/ha-insights/blob/main/docs/privacy.md)
- [Writing a detector](https://github.com/botts7/ha-insights/blob/main/docs/writing-a-detector.md)
- [WebSocket API](https://github.com/botts7/ha-insights/blob/main/docs/ws-api.md)

## Privacy posture

- **OFF** mode: zero outbound network calls. Local pattern detection only.
- **LOCAL** mode: pseudonymized data goes to a local Conversation agent (Ollama, Wyoming). Stays on your network.
- **CLOUD** mode: pseudonymized data goes to a cloud agent (Anthropic, OpenAI, Google). Real entity_ids replaced with stable pseudonyms (`light.entity_a3f1b2`) before any LLM call. Per-entity opt-out is also available.

Mode switching is in-place via Configure. Cloud mode requires explicit re-confirmation.

## Mutating endpoints require admin

`apply`, `undo`, `purge_all`, `test_actions`, `explain`, `refine`, `hypothesize`, and the dev `inject_event` endpoint all require `connection.user.is_admin`. Read-only and per-user-state actions (list, dismiss, snooze, scan_now, audit_log, etc.) remain open so non-admin frontend users can still review insights.
