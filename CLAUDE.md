# Project: HA Insights — Rules of Engagement

A Home Assistant custom integration + companion Lovelace card that
surfaces pattern-based automation suggestions. Two-repo HACS project:
`ha-insights` (Python integration, this repo) + `ha-insights-card`
(TS/Lit frontend).

This file is read by automated review agents AND human contributors.
**Architectural invariants only — narrative and dev workflow notes
live elsewhere** (private to each contributor's checkout).

## Read this first

- `docs/ARCHITECTURE.md` — file tree, contracts, data model
- `docs/writing-a-detector.md` — how to add a new detector
- `docs/privacy.md` — pseudonymization + redaction guarantees
- `docs/ws-api.md` — stable WebSocket API contract
- `docs/HA_EVENT_SEMANTICS.md` — HA state-change gotchas every detector author must know

---

## Hard rules — DO NOT violate

### 1. Detector fan-out only via `run_all_detectors()`

`detectors/__init__.py::run_all_detectors()` is the **single chokepoint**
for fanning out a scan. It yields to the event loop between detectors
AND between insight inserts, and refuses to run before
`CoreState.running`. Heavy inline detector loops in setup hooks have
historically starved the WS API and frozen the HA frontend on large
installs (~340 K events × 8 detectors). Never grep `DETECTORS.values()`
and loop manually. Trigger setup-time scans from
`EVENT_HOMEASSISTANT_STARTED`, not from `async_setup_entry`.

### 2. Yield in CPU loops over user-scale data

Any loop that iterates user-scale data (event buffer, entity registry,
recorder history) MUST call `await asyncio.sleep(0)` periodically.
The event loop is single-threaded; starving it freezes HA. Small/bounded
work (a few entity lookups, a single SQLite insert) is fine inline.
The trigger is "this iterates over user-scale data."

### 3. No hardcoded credentials, IPs, or tokens

Cloud LLM keys come from the user's configured Conversation agent
integration — never hardcode. Never log a redacted-but-recognizable
form. The redactor is the one place that knows real names.

### 4. Privacy controls are mandatory

- Pseudonymization is **on by default** and only switched OFF after an
  explicit cloud-consent flow.
- The audit log records every outbound call.
- Sensitive attributes (GPS, MAC, tokens, passwords) are stripped
  BEFORE pseudonymization, not after — defense-in-depth ordering.
- Per-entity opt-out blocks specific entities from EVER being sent,
  not even pseudonymized.

### 5. Surgical diffs only

Every changed line traces to the requested change. No drive-by
refactors, no comment rewrites in unrelated files. If you spot
adjacent dead code, mention it; don't delete it unless asked.

### 6. Extend composites; don't duplicate apply-chains

When ≥2 detectors apply the same chain of grader libs, that chain
belongs in a composite (the `HumanLikelihoodFeatures` pattern at
`lib/human_likelihood.py`). Adding a new grader is a ~10-line
extension to the composite — detectors don't change. An
`equivalence test` pins byte-for-byte output against the
pre-refactor chain whenever a composite gains a new optional grader.

### 7. State a verify-step plan before risky work

For multi-step changes that touch setup paths, scheduling, the
`run_all_detectors` pipeline, or anything that runs at boot: emit a
numbered plan listing how each step will be verified (test, log line,
HA check) BEFORE deploying. Production-scale buffers turn small bugs
into frontend hangs.

---

## Architecture invariant

```
View (Lovelace card / panel — TS/Lit)
    ↓ WS
ws_api.py  (single source of all WS endpoints; admin-gated where destructive)
    ↓
Detectors  (run via run_all_detectors only) → Store (aiosqlite, apply_lock-serialized)
    ↓
LLM agents (Conversation API; failover-capable; per-attempt audit)
    ↓
Redactor   (pseudonymization-aware; the only outbound-payload assembler)
```

Pure-math libraries under `custom_components/ha_insights/lib/` have
**no HA imports** so they remain HA-core-adoptable.

---

## Pinned versions

- HA core: 2024.12+ (Conversation API multi-turn requires it)
- Python: 3.13 (HA's pinned)
- Lit: 3.x
- TypeScript: 5.x
- aiosqlite, voluptuous: as pinned by HA core
