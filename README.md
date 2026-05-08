# HA Insights for Home Assistant

Proactive routine detection and automation suggestions for Home Assistant. Observes state changes over time, surfaces actionable insights (automation proposals, anomalies, dashboard improvements), and applies them as HA Blueprints.

## Status

Pre-alpha — v0.1 in development. Not ready for use.

## Companion card

[`ha-insights-card`](https://github.com/botts7/ha-insights-card) — Lovelace card that surfaces insights.

## Privacy

Privacy is the pillar of this project. Three modes (Off / Local / Cloud), zero outbound calls until the user opts in to LLM enrichment AND clicks Explain, sensitive attributes (GPS / MAC / IP / tokens / passwords) always redacted regardless of mode. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) §Privacy model.

## Position vs HA's built-in LLM features

HA's hassist (Conversation + LLM) is *reactive* — user asks, LLM answers and can act. HA Insights is *proactive* — observes patterns over time, surfaces suggestions. Same agents, complementary surfaces.

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — full architectural charter (file trees, contracts, data model, validation pipeline, operational policies, critical path)

## License

MIT — see [`LICENSE`](LICENSE).
