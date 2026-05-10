# HA Insights

**Proactive routine detection and AI-assisted automation suggestions for Home Assistant.**

HA Insights observes your home state over time and surfaces actionable suggestions:

> *"On weekdays at ~06:47 AM you turn on `light.kitchen` — automate this?"*

Click **Apply** and the suggestion lands as a real HA automation. Optional LLM enrichment refines the YAML, explains the proposal in plain English, and proposes plausible causes for anomalies.

## Privacy first

- **No always-on cloud calls.** Every LLM call is opt-in and triggered by you.
- **Pseudonymization on by default.** Real entity names and area names never leave your network on cloud calls; sensitive attributes (GPS, MAC, tokens, passwords) are stripped server-side before the prompt is built.
- **Audit log.** Every outbound call is recorded — bytes sent / bytes received / agent / locality / estimated cost. Inspect any time from the panel.
- **Three-mode privacy wizard.** Off (no LLM), Local (Ollama / Wyoming — data stays on your network), Cloud (with explicit consent step).

[See the privacy charter →](privacy.md){ .md-button }

## Detectors

| Detector | What it finds |
|---|---|
| **Schedule** | "Every weekday morning at ~06:47 you turn on `light.kitchen`" |
| **Cooccurrence** | "Front door opens, porch light follows within 30 s" |
| **Lagged correlation** | "Garage opens, driveway light follows ~3 min later" |
| **Long tail** | Long-running states that probably want a timeout |
| **Streak** | Consecutive-day patterns (e.g. weekend morning routines) |
| **Seasonality** | "Every Friday at ~7 PM, movie lights go on" |
| **Frequency anomaly** | Entities firing far above their 14-day baseline |
| **Orphan device** | Entities that have gone silent (dead battery, network drop, removed) |

[Write your own →](writing-a-detector.md){ .md-button }

## LLM enrichment

- **Explain** — plain-prose rationale for any insight
- **Refine** — multi-turn iterative refinement of the YAML, with cost confirmation, agent failover, and full agent-level audit
- **Hypothesize** — for anomaly insights, ask the LLM for plausible causes ("battery dead", "stuck contact", "runaway automation")
- **Test actions** — fire the proposed action(s) for real, before committing
- **Apply with override** — edit the YAML in the card, then apply

## Architecture

[Read the architecture charter →](ARCHITECTURE.md){ .md-button }

[WebSocket API reference →](ws-api.md){ .md-button }
