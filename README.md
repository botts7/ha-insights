# HA Insights for Home Assistant

> **Automation suggestions from what your home actually does — not what it could do.**
>
> HA Insights mines the last 14 days of your event history and surfaces patterns
> worth automating: routines you keep doing manually, schedules that match real
> behaviour, anomalies that mean something just broke, and automations that
> have started silently failing.
>
> Every suggestion is grounded in **observed events**, not a guess from your entity
> list. The 10+ deterministic detectors run locally with zero tokens spent.
> LLM is the **fallback for polish** — never the foundation.

![status: v1.5](https://img.shields.io/badge/status-v1.5-green)
![python: 3.13](https://img.shields.io/badge/python-3.13-blue)
![home assistant: 2025.6+](https://img.shields.io/badge/home%20assistant-2025.6+-blue)
![license: MIT](https://img.shields.io/badge/license-MIT-lightgrey)

---

## What HA Insights finds

| If your home shows... | HA Insights surfaces |
|---|---|
| `light.kitchen` ON 11/14 days clustering at ~17:27 (±8 min spread) | **Streak**: "Build automation? 11 days at ~17:27" — windowed match, not exact-minute |
| Door sensor that fired 38× its 14-day baseline today | **Frequency anomaly**: stuck loop, manual override, or genuine event burst |
| 3 entities in an automation are currently `unavailable` | **Audit**: "automation will silently fail until X comes back" |
| Inverter switch ON ~10 hrs/day, 11/14 days | **Long-tail**: "Auto-off after 120 min?" |
| Tuya entity + ESPHome entity in one automation | **Reliability**: "cloud outage will fire local side silently" |
| Phone charging that never finishes before bedtime | **Predictive**: "you'll be at 9% by your usual bedtime" |
| Light schedule that drifts with sunset across the year | **Seasonality**: "tracks sunset within ~8 min" |

Detectors emit **windowed** matches, not exact-minute claims — a streak at "~17:27"
means a cluster within a tolerance band, and the title shows the cluster spread
on hover. The integration is honest about uncertainty.

## Privacy floor — table stakes, not features

- **Local-first**: every detector runs on-device. No internet required for the core experience.
- **LLM is opt-in and optional**: pick local (Ollama, HA Assist) or cloud (Anthropic, OpenAI). Off by default.
- **"What gets sent?" modal**: see the exact redacted payload before any cloud call. Entity IDs, area names, and your custom labels are redacted by default.
- **Audit log viewer**: every LLM call recorded with prompt + token cost + redacted payload. Reviewable in the panel any time.
- **Entity-level blocklist**: opt-out specific entities from any analysis.
- **Three-tier maturity**: STABLE / BETA / EXPERIMENTAL detectors; experimental gated off by default.
- **Opt-in community analytics**: off by default; aggregated detector performance only, never per-event data.

---

## What it does (full)

**Two modes**, both work without any LLM:

### 1. Audit your existing automations (NEW in v1.1)

Reads every automation you've written and tells you what's wrong with it. Findings come from HA's own data — entity registry, automation execution traces, and 90 days of state history:

- **Entity unavailable / missing** — your automation references entities HA can't find anymore (renamed, removed, integration gone)
- **Long-stay duration** — light stays on 271 min on average; your `for: 60` is too tight
- **Redundant target** — action targets both `light.living_group` AND `light.living_lamp_1` (member). Drop one
- **Trigger drift** — `at: '07:00'` but observed transition averages 07:08 across 14 days. Shift the trigger
- **Condition too strict** — the automation triggered 184× but a condition blocked 142 of them. Maybe relax it
- **Action errors** — actions are throwing exceptions on N% of runs
- **Dormant** — hasn't fired in 60+ days; possibly broken or unneeded
- **Seasonal patterns** — only fires Nov-Mar (90-day rollup); add a `month:` condition if trigger is time-based

Each finding either:
- Ships with a **📋 Preview** button that shows the deterministic YAML fix in a side-by-side diff (no LLM, no tokens) — Apply commits it
- Ships with a **🤖 Suggest** button when there's no algorithmic fix — the LLM is given an explicit AUTHORIZED EDITS list of what the findings actually justify
- Both: **🤖 Refine further with LLM** layers LLM ideas on top of the deterministic stage

### 2. Discover patterns in your home

Eight built-in detectors watch state history and surface routines you might want to automate:

| Detector | What it finds |
|---|---|
| **Schedule** | "Every weekday at ~6:47 AM you turn on `light.kitchen`" |
| **Seasonality** | "Every Friday at ~7 PM, movie lights go on" (weekly cycles) |
| **Cooccurrence** | "Within 5s of the front door opening, the porch light turns on" |
| **LaggedCorrelation** | "Garage opens, driveway light follows ~3 min later" |
| **LongTail** | "Bathroom fan stayed on 4h, 12 times this fortnight" |
| **Streak** | "Light X turns on 3 days in a row at ~22:15" |
| **OrphanDevice** | "`binary_sensor.front_door` hasn't reported in 11 days" |
| **FrequencyAnomaly** | "Front door fired 50× today (~2/day baseline)" |

Cohort detection collapses 35 NVR cameras silent for 8 days into a single row, not 35 separate insights.

Click **Apply** and it writes a real `automation:` block to `automations.yaml`. **Undo** within 7 days reverses cleanly with drift detection.

---

## Device-vs-human classification (v1.5.35+)

A 36-day daily pattern at exactly `08:54:00.000` with zero variance is almost
certainly a device's internal timer — not a habit you'd want to "automate".
HA Insights demotes these so you don't see them at default confidence.

Four pure-math libraries each grade one signal; their multipliers compose
into a single confidence demotion:

| Library | Signal | Device fingerprint |
|---|---|---|
| `lib/timing_likelihood.py` | stddev + range of fire times | sub-second precision on a daily pattern |
| `lib/cooccurrence_likelihood.py` | median nearby events in ±5 s | isolated (no other entities reacting) |
| `lib/persistence_likelihood.py` | CV of duration-in-state, both directions | FIXED_CYCLE (CV < 5 %) — e.g. 2-minute toothbrush |
| `lib/transition_entropy.py` | distinct preceding entities | NOVEL_CONTEXT — every fire follows a different lead-in |

Each is HA-core-adoptable (no HA imports, pure-Python, fully unit-tested),
bundled behind a `HumanLikelihoodFeatures` composite. Adding a fifth grader
is a ~10-line addition to the composite — detectors don't change. Threshold
tables are iot_class-aware (local push/polling tightens to < 2 s; cloud
push/polling relaxes to < 10 s).

The card pairs render a **🤖 device-managed** or **🤖 tight-pattern** pill
with a tooltip explaining which signal demoted the row.

---

## Screenshots

> _Captured on a 1000-entity HA install running v1.2.0._

| | |
|---|---|
| ![panel overview](screenshots/01-panel.png) | **Main panel.** Detector count chips, filter dropdowns, per-row context (🔌 integration, 🏷️ external-app, 🔁 already-automated, age). Audit and discovery insights mixed on one surface. |
| ![preview diff](screenshots/02-preview-diff.png) | **📋 Preview deterministic fix.** Side-by-side IDE-style diff (LCS line alignment). Zero LLM tokens — algorithm computed the fix from the redundant_target observation. |
| ![LLM refine diff](screenshots/03-llm-refine-diff.png) | **🤖 Algorithm + LLM Refine.** Stage 2 layers LLM iteration on top of the algorithm output. The "Refine again with more guidance" textarea drives multi-turn refinement. |
| ![repairs page](screenshots/04-repairs.png) | **Standard HA Repairs page.** v1.2 dual-emits audit findings into HA's official issue registry, so users discover them via native UI without needing the panel open. |
| ![config flow](screenshots/05-options-flow.png) | **OptionsFlow.** Privacy mode, daily digest, audit window, audit verbosity, monthly cloud-LLM budget, auto-rollup scheduler. Everything configurable from Settings → Devices & Services. |

---

## Architecture in one diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          HA Insights Pipeline                            │
└─────────────────────────────────────────────────────────────────────────┘

       HA event bus + recorder + automation registry
                          │
                          ▼
     ┌──────────────────────────────────────────────┐
     │  Detectors run on a buffer snapshot           │
     │  • schedule, streak, cooccurrence, etc.      │
     │  • automation_audit (NEW — reads existing    │
     │    YAMLs + traces + rollups)                  │
     │  Pure-Python; thread-safe; no I/O on loop    │
     └────────────────────┬─────────────────────────┘
                          │ Insight objects
                          ▼
     ┌──────────────────────────────────────────────┐
     │  SQLite store + display-time dedup (cohorts)  │
     │  + Repairs registry sync (dual-emit)         │
     └────────────────────┬─────────────────────────┘
                          │ ws_list / subscribe events
                          ▼
     ┌──────────────────────────────────────────────┐
     │  ha-insights-card (Lit element)              │
     │  • Panel + Lovelace card                     │
     │  • Filter chips, group-by, expand cohorts    │
     │  • Side-by-side diff modal                   │
     │  • Apply / Refine / Suggest buttons          │
     └──────────────────────────────────────────────┘

   LLM only fires on user action — not in the scan loop.
   When it fires, goes through:
     Redactor (pseudonymize) → Conversation API → audit log
     → reverse-dereference → validator → apply pipeline
```

---

## Privacy posture

- **OFF mode** — zero outbound network. Pattern detection runs locally.
- **LOCAL mode** — pseudonymized data goes to a local Conversation agent (Ollama, Piper). Stays on your network.
- **CLOUD mode** — pseudonymized data goes to a cloud agent (Claude, GPT, Gemini). Real entity_ids never leave — they're replaced with stable pseudonyms (`light.entity_a3f1b2`) before any LLM call. Reverse-mapped on response.

Per-entity opt-out blocks specific entities from EVER being sent (not even pseudonymized). Every outbound call is logged with bytes / agent / cost / success. The **"What gets sent?"** modal previews the exact payload before any LLM action.

Full details: [`docs/privacy.md`](docs/privacy.md).

---

## v1.5 highlights

- **Four signal-grader libraries** (v1.5.35–v1.5.40) classify events as
  device- vs. human-driven from timing / co-occurrence / persistence /
  transition-entropy. Pure-math, HA-core-adoptable, bundled via the
  `HumanLikelihoodFeatures` composite — adding a fifth grader is a
  ~10-line extension, detectors don't change.
- **iot_class-aware thresholds** — cloud-integrated devices add network
  jitter, so the same algorithm uses different sub-second bands for
  `local_*` vs `cloud_*` integrations.
- **HA semantics filters** (v1.5.x) — context.id batch correlator,
  unavailable-transition filter, template-source pair drop, long-silence
  filter — all pulled into `lib/event_filters.py` so they're liftable
  into HA core without integration scaffolding.
- **Cohort dedup hardening** (v1.5.23) — entities with `device_id=None`
  no longer get falsely absorbed into other cohorts.
- **iot_class deadlock fix** (v1.5.22) — `_load_iot_classes` now reads
  the manifest cache off-loop.
- **HACS-path panel resolver** (v1.5.32) — eliminates the post-update
  "hard-refresh required" loop for HACS users.
- **Versioned cache-bust** (v1.5.41) — panel URL now includes integration
  version so HACS updates always serve the new bundle.

## Research inspiration

Detector design draws on published work in habit detection, anomaly
attribution, and human-vs-device routine classification. None of these
papers is reimplemented verbatim — each maps to a concrete library plus
a deliberate simplification suited to running on-device against HA's
14-day buffer:

- **Houzé 2022** — *Algorithmic Information Theory (AIT) memorability*
  for anomaly scoring. `transition_entropy.py` approximates the AIT
  score via a 2nd-order Markov proxy (entropy of distinct preceding
  entities). Full AIT would require building a generative model of the
  house; the proxy needs O(N) over the cluster window and catches the
  same novelty signal in practice.
- **Gad 2026** — multimodal context features (co-occurrence, persistence)
  as device-vs-human signal. Direct inspiration for the second + third
  grader libraries.
- **Fu 2021 (HAWatcher)** — shadow-execution + correlation rules; 97 %
  precision claim. Reserved as v1.6 roadmap: detect rules that should
  be firing but aren't, by maintaining a parallel state model and
  comparing against actuals.
- **PELT (Killick 2012)** — change-point detection. Used in the
  seasonality + frequency-anomaly detectors for "behavior shifted on
  date X" findings.

What we deliberately don't ship: vector embeddings of entity history
(memory cost grows with the install — see `docs/ARCHITECTURE.md` for
why the no-vector-DB decision was load-bearing); Cox proportional-hazards
survival models (researched, found to fail proportionality assumptions
on HA data — AFT models are the queued replacement).

---

## v1.1 highlights

- **AutomationAuditDetector** — audits every automation you've written. Eight kinds of findings, deterministic fixes available for half, LLM refinement for the rest.
- **Side-by-side LCS diff modal** — IDE-style aligned rows with red `-` / green `+` gutters. Phone-responsive (panes stack vertically below 720px).
- **Two-stage refinement** — deterministic fix first (free, instant), then optionally layer LLM iteration on top with an extra user-feedback box.
- **Repairs registry dual-emit** — audit findings appear in HA's standard `Settings → Repairs` page alongside HA's own issue notifications. Users discover the integration even when they forget the panel exists.
- **Concise vs In-depth toggle** — top-of-panel switch trades LLM cost vs reasoning depth. Concise (~700 token prompts) is the default; In-depth (~1200 token prompts) for tricky automations.
- **AUTHORIZED EDITS per-call** — instead of universal rules the LLM must obey, each refine ships an explicit list of changes the findings or user request authorise. LLM can't invent removals the audit didn't justify.
- **Token usage row** — every refine modal shows approximate in/out token counts so you know exactly what each call cost.
- **24 unit tests** covering dedup, audit packet builders, deterministic fix builders. Run via `pytest tests/test_lib_dedup.py tests/test_audit_packet.py tests/test_audit_fixes.py`.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full audit pipeline design.

---

## Install

### Integration

1. **HACS → Integrations → ⋮ → Custom repositories**
2. Add `https://github.com/botts7/ha-insights` as type **Integration**
3. Click **Install** on "HA Insights"
4. Restart Home Assistant
5. **Settings → Devices & Services → Add Integration → "HA Insights"**
6. Walk the wizard — pick the privacy mode that fits. Off works fully without an LLM; Local / Cloud light up Refine + Suggest + Explain.

### Card

The card repo is [ha-insights-card](https://github.com/botts7/ha-insights-card) — render insights as a Lovelace card AND mount the sidebar panel.

1. **HACS → Frontend → ⋮ → Custom repositories**
2. Add `https://github.com/botts7/ha-insights-card` as type **Lovelace**
3. Install
4. The integration auto-registers a sidebar **Insights** panel at `/ha-insights` once the card resource loads
5. For a dashboard tile too:
   ```yaml
   type: custom:ha-insights-card
   compact: true
   ```

### Optional: LLM Conversation agent

Refine + Suggest + Explain need a Conversation integration. Pick from HA's standard options:
- **Ollama** (local, free)
- **Anthropic Conversation** (Claude — best output quality for YAML)
- **OpenAI Conversation** (GPT-4 / GPT-5)
- **Google Generative AI Conversation** (Gemini — make sure `max_output_tokens` is set high enough; default 150 is too low)
- **Nabu Casa Cloud** (Assist subscription)

The integration auto-picks the first installed LLM agent. Override per-call via the UI's preferred-agent dropdown.

---

## How the audit works end-to-end

1. Every scan, the **AutomationAuditDetector** walks every automation it can find (`automations.yaml`, `configuration.yaml`, packages, runtime registry).
2. For each automation, it builds an **AuditPacket**:
   - Live state-machine snapshot (HA `states`) — for entity_silent
   - 14-day event buffer aggregates — for long_on_duration, trigger_time_drift
   - HA's own **automation traces** (last N runs) — for trace_dormant, trace_condition_blocks, trace_action_errors
   - 90-day recorder rollups (day-of-week / day-of-month / month-of-year) — for seasonal patterns
   - Cross-reference to other detector findings touching the same entities
3. Each observation feeds into a per-kind hint that gets shown alongside the finding.
4. **Findings that have a deterministic fix** (redundant_target, long_on_duration, trigger_time_drift) ship with `payload_format="automation"` + a 📋 Preview button. No LLM tokens spent.
5. **Findings without a deterministic fix** (entity_silent, trace_*, rollup_*) ship as `payload_format="report"` with a 🤖 Suggest button.
6. Clicking 🤖 sends through HA's Conversation API with: the YAML, the observations, and an `AUTHORIZED EDITS:` block explicitly listing which changes the findings justify.
7. The card renders the LLM's refined YAML as a side-by-side aligned diff. Apply commits via the existing validator + writer.

---

## Cost economics

For a typical 30-automation home with the v1.1 prompt:

| Action | Tokens (approx) | Notes |
|---|---|---|
| Scan + emit audit insights | 0 | Pure-Python detectors, no LLM |
| 📋 Preview deterministic fix | 0 | Algorithm runs offline |
| 🤖 Suggest, Concise depth | ~700 in / ~150-400 out | ~$0.0008-0.002 on Sonnet |
| 🤖 Suggest, In-depth | ~1200 in / ~150-400 out | 4× input for tricky automations |
| 🤖 Refine further (stage 2) | ~700 in / ~150-300 out | Concise enforced regardless of setting |
| Local LLM (Ollama, etc.) | n/a | $0; no budget gate fires |

A per-month USD budget can be set in OptionsFlow for cloud agents; the background batch suggest service stops queuing once the cap is hit.

---

## Companion docs

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — full architectural charter
- [`docs/HA_EVENT_SEMANTICS.md`](docs/HA_EVENT_SEMANTICS.md) — HA state-change event gotchas detector authors must know
- [`docs/privacy.md`](docs/privacy.md) — what's stored / what isn't / how to wipe
- [`docs/ws-api.md`](docs/ws-api.md) — stable WebSocket API contract
- [`docs/writing-a-detector.md`](docs/writing-a-detector.md) — community detector contribution guide

---

## Position vs HA's built-in Assist

[Assist](https://www.home-assistant.io/voice_control/) is **reactive** — user asks, LLM answers and can act. HA Insights is **proactive** — observes patterns + audits existing automations + surfaces actionable suggestions, optionally refined with the same LLM agent you've configured for Assist. Same agents, complementary surfaces.

---

## Branding

"HA Insights" is a community project, not affiliated with or endorsed by Nabu Casa. "Home Assistant" is a Nabu Casa trademark; we follow the standard HACS-community pattern of `ha-` prefixed naming and don't use HA brand assets.

## Status & contributing

**v1.5.43** — first public release. What that means in practice:

| Area | Status |
|---|---|
| Integration core (detectors, audit, redactor, store, WS API) | **Test-covered** — 75 lib + 157 smoke tests passing. Hasn't seen wide community use yet. |
| Privacy controls (opt-in LLM, pseudonymization, audit log, "what gets sent?") | **Test-covered** — privacy contract is a hard rule, not a feature flag |
| Panel UI | **Under active investigation** — in-flight blank-on-tab-return bug. v1.2.24/v1.2.25 in the card chased part of the cause; a second root cause is still being tracked. |
| Mobile push throttling, daily-digest cadence | **Untested at scale** — anti-spam logic exists; defaults will likely need tuning based on community feedback |
| HAWatcher shadow-execution (v1.6 roadmap) | **Not started** — research direction; contributors welcome |

### How to report something broken

[Open a bug](https://github.com/botts7/ha-insights/issues/new?template=bug.yml) — the template asks for HA version, integration version, browser, repro steps, relevant `homeassistant.log` lines. Detailed reports get triaged same-day; "it broke" reports queue.

### How to contribute

- **Bugs**: fork, branch off `main`, add a test that reproduces (use `tests/test_lib_*.py` for pure logic or `tests/_smoke_v1_4_x.py` for integration-shape checks), open a PR. The PR template walks you through the surgical-diff conventions.
- **New detector**: see [`docs/writing-a-detector.md`](docs/writing-a-detector.md) — the existing 10+ detectors follow a stable contract; your detector is one folder + one entry in `detectors/__init__.py`.
- **Discussion / ideas**: [GitHub Discussions](https://github.com/botts7/ha-insights/discussions) for shape-of-the-feature talks; issues are for bugs and concrete proposals.

### Conventions (CLAUDE.md captures these)

- Surgical diffs only — every changed line traces to the request, no drive-by refactors
- Yield in CPU loops over user-scale data (HA event loop is single-threaded)
- No hardcoded credentials, IPs, tokens
- Test-first when feasible; smoke tests catch architectural regressions cheaply

## License

MIT — see [`LICENSE`](LICENSE).
