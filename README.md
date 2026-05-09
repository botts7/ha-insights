# HA Insights for Home Assistant

Proactive routine detection and AI-assisted automation suggestions for Home Assistant. Watches your home over time, surfaces actionable suggestions ("On weekdays at ~6:47 AM you turn on `light.kitchen` — automate this?"), and applies the result as a real HA automation when you click Apply. Optional LLM enrichment for refinement and explanation, with strict privacy controls.

## Status

**v0.7.0** — five detectors, full LLM Refine pipeline, sidebar panel, recorder backfill, trust & visibility surfaces.

### Detectors
| Detector | What it finds |
|---|---|
| **Schedule** | "Every weekday at ~6:47 AM you turn on `light.kitchen`" — strong time-of-day routines |
| **Cooccurrence** | "Within 5s of the front door opening, the porch light turns on" — entity-follows-entity patterns |
| **LongTail** | "Bathroom fan stayed on for 4 hours, 12 times this fortnight" — auto-off proposals |
| **OrphanDevice** | "`sensor.battery_level_smoke` hasn't reported in 11 days" — battery / network alerts |
| **Streak** | "Light X turns on 3 days in a row at ~22:15" — emerging patterns (lower bar than Schedule) |

### Pipeline features
- **🔄 Recorder backfill** — on first install, ingests up to 30 days of HA recorder history so insights surface immediately, not after a 1-2 week buffer fill
- **✨ Refine with LLM** — let the LLM iterate on a proposed automation (add debounce, conditions, mode change). Side-by-side compare, follow-up feedback loop, refusal / token-limit detection
- **💬 Explain with LLM** — natural-language explanation of why this routine is a candidate for automation
- **🔥 Test actions** — run the proposed action block in real time (no automation save) so you can verify before applying
- **🛡️ "What gets sent?"** — exact-payload preview of what would leave your network, before any LLM call
- **🛡️ Audit log** — every outbound LLM call recorded with bytes / agent / mode / success
- **Apply pipeline** — writes a real HA automation to `automations.yaml`, calls `automation.reload`, supports refined / renamed payloads via override

### Privacy posture
- **OFF** mode: zero outbound network calls. Local pattern detection only.
- **LOCAL** mode: pseudonymized data goes to a local Conversation agent (Ollama, Piper). Stays on your network.
- **CLOUD** mode: pseudonymized data goes to a cloud Conversation agent (Anthropic, OpenAI, Google AI). Real entity_ids never leave your network — they're replaced with stable pseudonyms (`light.entity_a3f1b2`) before any LLM call. Per-entity opt-out is also available.

Every LLM call is logged. Mode switching is in-place via the OptionsFlow.

Full details: [`docs/privacy.md`](docs/privacy.md).

## Install

### Integration (this repo)

1. **HACS → Integrations → ⋮ → Custom repositories**
2. Add `https://github.com/botts7/ha-insights` as type **Integration**
3. Click **Install** on "HA Insights"
4. Restart Home Assistant
5. **Settings → Devices & Services → Add Integration → "HA Insights"**
6. Walk the wizard. Pick the privacy mode that fits — Off works fully without an LLM; Local / Cloud light up the Refine and Explain features.

### Card (separate repo)

[ha-insights-card](https://github.com/botts7/ha-insights-card) renders insights and exposes the Apply / Refine / Explain / Test surface. Required.

1. **HACS → Frontend → ⋮ → Custom repositories**
2. Add `https://github.com/botts7/ha-insights-card` as type **Lovelace**
3. Install
4. Add to a dashboard:
   ```yaml
   type: custom:ha-insights-card
   ```
5. The integration also registers a sidebar **Insights** panel (`/ha-insights`) for the full-page triage view.

### Companion LLM (optional)

For Refine + Explain, install one of these via HACS or the integrations registry, then choose it as the conversation agent:
- **Ollama** (local, free)
- **Anthropic Conversation** (Claude)
- **OpenAI Conversation** (GPT-4 / GPT-5)
- **Google Generative AI Conversation** (Gemini)
- **Nabu Casa Cloud** (with assist subscription)

The integration auto-picks the first installed LLM agent. Override per-call with the `agent_id` field in the Refine / Explain WS commands.

## Companion documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — full architectural charter (file trees, contracts, data model, validation pipeline, operational policies)
- [`docs/privacy.md`](docs/privacy.md) — what's stored, what isn't, how to wipe, redaction guarantees
- [`docs/ws-api.md`](docs/ws-api.md) — stable WebSocket API contract
- [`docs/writing-a-detector.md`](docs/writing-a-detector.md) — community detector contribution guide

## Position vs HA's built-in **Assist**

Home Assistant's [Assist](https://www.home-assistant.io/voice_control/) (Conversation + LLM) is **reactive** — user asks, LLM answers and can act. HA Insights is **proactive** — observes patterns over time, surfaces suggestions, optionally refines them with the same LLM agent you've configured for Assist. Same agents, complementary surfaces.

## Branding

"HA Insights" is a community project, not affiliated with or endorsed by Nabu Casa. "Home Assistant" is a Nabu Casa trademark; we follow the standard HACS-community pattern of `ha-` prefixed naming and don't use HA brand assets.

## License

MIT — see [`LICENSE`](LICENSE).
