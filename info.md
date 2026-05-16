# HA Insights

> ⚠️ **Early public release (v1.5.43).** This is the first public-facing
> version. The core pipeline (detectors, audit, redactor, store, WS API)
> is test-covered (75 lib + 157 smoke tests pass) but hasn't seen wide
> community use yet. The **panel UI is still hardening** — there's an
> in-flight blank-on-tab-return bug under active investigation. **Things
> will break; please report what you find.**
> [Open an issue](https://github.com/botts7/ha-insights/issues/new/choose)
> with your HA + integration versions, browser, and any console output.
> PRs welcome.

**Audits the automations you've already written + spots new ones — proactive pattern detection with AI-assisted refinement.**

> *"Your `TV Lights OFF` automation has 3 redundant target entries — drop them?"*
> *"On weekdays at ~06:47 AM you turn on `light.kitchen` — automate this?"*

Click **Apply** and either suggestion lands as a real HA automation. Optional LLM enrichment with strict privacy controls and a full audit log of every byte that leaves your network.

## What you get (v1.1)

### Audit your existing automations (NEW)
- **AutomationAuditDetector** reads every automation in `automations.yaml`, `configuration.yaml`, and package files
- Flags **entity unavailable / missing**, **long-stay durations**, **redundant action targets**, **trigger drift vs reality**, **conditions too strict**, **action errors**, **dormant automations** (no fires in 30d+)
- Findings with a **deterministic fix** (redundant_target, trigger_time_drift, long_on_duration) ship with a **📋 Preview** button — view + apply the fix in a side-by-side YAML diff, zero LLM tokens
- Findings without a clean algorithmic fix offer **🤖 Suggest** — LLM is given an explicit AUTHORIZED EDITS list so it can only act on what the findings actually justify, no hallucinated removals
- **Two-stage refinement** — algorithm first, then layer LLM iteration on top with extra user feedback
- Audit findings ALSO surface in **Settings → Repairs** so users discover them via HA's native UI

### Discover new patterns
- **Eight built-in detectors**: schedule, seasonality, cooccurrence, lagged_correlation, long_tail, streak, orphan_device, frequency_anomaly
- **Opt-in user-supplied detectors** loaded from `<config>/ha_insights_detectors/*.py` with AST-sandbox

### Pipeline
- **IDE-style side-by-side diff modal** with LCS line alignment, phone-responsive
- **Concise vs In-depth analysis toggle** — trade LLM cost vs reasoning depth
- **Token usage row** in every refine modal so you see what each call cost
- **Multi-turn refine** via conversation_id
- **Agent failover** — auto-walks preferred → Assist default → other agents
- **Per-month USD budget cap** for cloud LLM batch operations (local LLMs bypass)
- **Three-mode privacy wizard** — Off / Local / Cloud with pseudonymization on by default
- **Per-entity opt-out + redacted-payload preview before every call**
- **Sidebar panel + Lovelace card** — review, refine, apply, undo, drift-aware
- **Full audit log** of every outbound call (agent / bytes / cost / success)
- **Multi-config-entry** for independent insight scopes
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
