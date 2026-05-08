# HA Insights for Home Assistant

Proactive routine detection and automation suggestions for Home Assistant. Watches your home over time, surfaces actionable suggestions ("On weekdays at ~6:47 AM you turn on `light.kitchen` — automate this?"), and applies the result as a real HA automation when you click Apply.

## Status

**v0.1.0** — first release.

What works in v0.1:

- **`ScheduleDetector` hero** finds time-of-day routines from observed state
- Insights surface in a Lovelace card via a stable WebSocket API
- Apply writes a real HA automation to your `automations.yaml`; HA picks it up via `automation.reload`
- Snooze + Dismiss work with optimistic UI updates and live event streams
- Conflict scanner skips routines that overlap an existing automation
- Drift detection records a snapshot at apply-time so future undo flows can warn before reverting your manual edits

What's deferred to v0.2:

- LLM-based explanations (the wizard's Off / Local / Cloud privacy modes are stored but dormant in v0.1 — the gateway lands in v0.2)
- Trust badges + "What gets sent?" modal
- Co-occurrence, anomaly, and dashboard-cleanup detectors
- HA Blueprint emission as an apply target (v0.1 emits raw automations)

**Privacy in v0.1: zero outbound network calls.** All detection and storage happens locally on your HA host. Full details: [`docs/privacy.md`](docs/privacy.md).

## Install

### Integration (this repo)

1. **HACS → Integrations → ⋮ → Custom repositories**
2. Add `https://github.com/botts7/ha-insights` as type **Integration**
3. Click **Install** on "HA Insights"
4. Restart Home Assistant
5. **Settings → Devices & Services → Add Integration → "HA Insights"**
6. Walk the wizard. Pick **Off** in v0.1 (Local / Cloud need v0.2's LLM gateway)

### Card (separate repo)

[ha-insights-card](https://github.com/botts7/ha-insights-card) renders insights and exposes Apply / Snooze / Dismiss. Required for the visual surface.

1. **HACS → Frontend → ⋮ → Custom repositories**
2. Add `https://github.com/botts7/ha-insights-card` as type **Lovelace**
3. Install
4. Add to a dashboard:
   ```yaml
   type: custom:ha-insights-card
   ```

## Companion documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — full architectural charter (file trees, contracts, data model, validation pipeline, operational policies, critical path)
- [`docs/privacy.md`](docs/privacy.md) — what's stored, what isn't, how to wipe
- [`docs/ws-api.md`](docs/ws-api.md) — stable WebSocket API contract
- [`docs/writing-a-detector.md`](docs/writing-a-detector.md) — community detector contribution guide

## Position vs HA's built-in `hassist`

Home Assistant's Conversation + LLM (`hassist`) is **reactive** — user asks, LLM answers and can act. HA Insights is **proactive** — observes patterns over time, surfaces suggestions. Same agents (when v0.2 lands), complementary surfaces.

## Branding

"HA Insights" is a community project, not affiliated with or endorsed by Nabu Casa. "Home Assistant" is a Nabu Casa trademark; we follow the standard HACS-community pattern of `ha-` prefixed naming and don't use HA brand assets.

## License

MIT — see [`LICENSE`](LICENSE).
