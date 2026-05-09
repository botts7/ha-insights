# HA Insights — Architecture

> **Status:** Drafted 2026-05-08 as the v0.1 implementation charter. The architectural invariants below remain authoritative across releases; phase callouts ("v0.1 ships X", "deferred to v0.2") describe the original roadmap and don't always match what actually shipped. The [README](../README.md) and [CHANGELOG](../CHANGELOG.md) reflect the current state (currently **v0.7.0**); a release-history table at the bottom of this doc covers actual ship versus plan.

## Project frame

| | |
|---|---|
| **Name (long form)** | HA Insights for Home Assistant |
| **Name (short form)** | HA Insights |
| **Repos** | `ha-insights` (Python integration) + `ha-insights-card` (TS Lovelace card) |
| **Distribution** | HACS — custom repo at first, default after community trust |
| **License** | MIT |
| **HA version target** | 2025.4+ (stable Conversation Agents API) |
| **Sibling project** | ESP32-P4 tablet — separate, not coupled |

**Branding:** "HA Insights" (short) / "HA Insights for Home Assistant" (long). The `ha-` prefix follows established HACS community-integration naming convention. We don't claim Nabu Casa affiliation, don't use HA-branded logos/images (per HACS docs), and the "for Home Assistant" qualifier in the long-form name signals third-party status. "Home Assistant" remains a Nabu Casa trademark — Apache 2.0 doesn't grant trademark rights to the exact mark, but we don't use the exact mark either, so this is not a concern.

**Position vs HA's built-in LLM features:** HA's Assist (Conversation + LLM) is *reactive* — user asks, LLM answers and can act. HA Insights is *proactive* — observes patterns over time, surfaces suggestions. Same agents, complementary surfaces.

**Coupling rule:** card depends on integration's WebSocket API only. Integration ships zero JS. WS API is semver-stable from v0.1.

---

## Locked decisions

- **Two repos** — separate release cadence, HACS hygiene.
- **Hero (v0.1):** ScheduleDetector — *"you do X every weekday at ~T, automate this?"*
- **Privacy is the pillar:** three-mode UX (Off / Local / Cloud), advanced controls gated behind disclosure, trust badges everywhere, "what gets sent?" always one tap away.
- **Local LLMs treated differently:** real names, no preview-by-default, privacy domains unblocked (safety domains stay blocked).
- **Heuristic builds YAML; LLM writes prose only.** LLM never emits config that gets applied.
- **Apply via HA WS config API** + **HA Blueprints by default** (raw automations as advanced fallback).
- **Two-layer YAML validation** before apply — `cv` schema + WS `automation/validate`.
- **HA Conversation agents** wrap the LLM. No provider auth in our code.
- **No vector DB / RAG.** SQLite + Python statistics. `sqlite-vss` is the upgrade path if conversational queries land in v2.x.
- **Recorder optional.** ScheduleDetector works on in-memory ring buffer alone.
- **Default-blocked domains split:** privacy (camera/person/device_tracker — unblocked locally) vs safety (lock — always blocked).
- **Always-redacted attributes:** GPS, MAC, IP, password/token/key, BSSID, serial — regardless of mode.

---

## Architecture (7 layers)

```
L7  Surface       WS API · services · privacy_log sensor
L6  Apply         WS config-API client · snapshots · undo · drift detection
L5  LLM Gateway   redactor · agent_client · privacy log · context injection
L4  Insight Store SQLite · dedupe by fingerprint
L3  Detection    detector registry · scheduler · conflict detection
L2  Entity Graph in-memory: area→entities, fast lookups
L1  Ingest       event bus · ring buffer · recorder ro
```

L1–L4 are statistical / structural. L5 is opt-in and stateless — each Explain call is one-shot.

---

## Repo 1: `ha-insights` file tree

```
ha-insights/
├── README.md, LICENSE, hacs.json, pyproject.toml
├── .github/workflows/{validate,tests,release}.yml
├── docs/
│   ├── installation.md
│   ├── privacy.md                          # THE document
│   ├── writing-a-detector.md               # community on-ramp
│   ├── ws-api.md                           # stable contract
│   ├── ARCHITECTURE.md                     # this file
│   └── data-flow-diagrams/
├── dev/                                    # autonomous dev + test harness
│   ├── docker-compose.yml                  # HA core image + integration mounted as volume
│   ├── up.sh, down.sh, reset.sh            # spin / tear down / wipe state
│   ├── seed.py                             # synthetic state history (backdated to recorder)
│   ├── probe.py                            # end-to-end pipeline assertion
│   └── README.md
├── tests/
│   ├── conftest.py
│   ├── test_schedule_detector.py
│   ├── test_apply_pipeline.py
│   ├── test_privacy_redactor.py
│   ├── test_drift_detection.py
│   ├── test_entity_rename.py
│   └── test_ws_api.py
└── custom_components/ha_insights/
    ├── __init__.py                         # async_setup_entry
    ├── manifest.json
    ├── const.py
    ├── config_flow.py                      # privacy-first wizard
    ├── options_flow.py
    ├── strings.json + translations/en.json
    ├── services.yaml
    ├── insight.py                          # Insight + InsightKind
    ├── detectors/
    │   ├── __init__.py                     # registry + auto-import
    │   ├── base.py                         # Detector ABC
    │   └── schedule_detector.py            # the hero
    ├── observers/state_event_buffer.py
    ├── store/{schema,store,migrations/}.py
    ├── llm/
    │   ├── redactor.py                     # entity-id pseudonyms + sensitive-attr blocklist
    │   ├── context.py                      # tiered context injection
    │   ├── agent_client.py                 # wraps conversation.process
    │   └── privacy_log.py                  # outbound-call ledger
    ├── apply/
    │   ├── automation_writer.py            # WS config API
    │   ├── blueprint_writer.py             # HA Blueprint emission (default)
    │   ├── validator.py                    # two-layer schema + live validate
    │   ├── drift_detector.py               # detect user edits before undo
    │   ├── conflict_scanner.py             # detect existing automations
    │   └── _ha_internals.py                # adapter for non-stable HA APIs
    ├── ws_api.py                           # subscribe/list/apply/dismiss/explain/hello
    ├── services.py
    └── entities/privacy_log_sensor.py
```

---

## Load-bearing contracts

### Insight (`insight.py`)

```python
class InsightKind(StrEnum):
    AUTOMATION_PROPOSAL = "automation_proposal"
    CARD_PROPOSAL       = "card_proposal"          # v0.2
    GROUP_PROPOSAL      = "group_proposal"         # v0.3
    ANOMALY             = "anomaly"                # v0.4
    DASHBOARD_CLEANUP   = "dashboard_cleanup"      # v0.3
    SCENE_PROPOSAL      = "scene_proposal"         # v0.3+

@dataclass(frozen=True)
class Insight:
    id: str                          # stable hash of (kind, fingerprint)
    kind: InsightKind
    detector: str
    area_id: str | None
    title: str                       # heuristic-generated, no LLM
    confidence: float                # 0.0-1.0
    fingerprint: dict                # detector-specific dedup key
    payload: dict                    # the YAML/blueprint to apply (heuristic-built)
    payload_format: str              # "blueprint" (default) or "automation"
    created_at: datetime
    snoozed_until: datetime | None = None
    explanation: str | None = None   # populated by LLM only on user request
    conflicts_with: list[str] = field(default_factory=list)  # existing automation_ids
```

### Detector ABC (`detectors/base.py`)

```python
class Detector(ABC):
    name: str
    kind: InsightKind
    requires_recorder: bool = False
    domains_default_blocked: ClassVar[set[str]] = {
        "camera", "person", "device_tracker", "lock"
    }

    @abstractmethod
    async def scan(self, ctx: DetectorContext) -> list[Insight]: ...

    def applies_to_event(self, event: Event) -> bool:
        return True
```

`DetectorContext` carries: HA instance, scoped event-buffer slice, recorder query helper, detector config, area filter, redactor.

### WebSocket API (semver-stable from v0.1)

```
ha_insights/hello           → handshake: returns { integration_version, ws_protocol_version, supported_methods }
ha_insights/list            → list of insights, filterable
ha_insights/subscribe       → live stream of new/updated/dismissed
ha_insights/explain         → triggers LLM enrichment (user-initiated only)
ha_insights/preview         → returns YAML diff that would apply
ha_insights/apply           → apply one insight (with conflict + validation pre-flight)
ha_insights/dismiss         → permanent dismiss + fingerprint blacklist
ha_insights/snooze          → snooze N days
ha_insights/purge_all       → privacy nuke button
ha_insights/whatgetssent    → returns example payload at current settings
```

**Version handshake:** card opens every connection with `ha_insights/hello { card_version }`. Integration replies with its version + supported methods. Card downgrades gracefully — disables UI for unsupported methods, shows "Update HA Insights integration to v0.X for {feature}." Same banner on inverse skew.

### Services

- `ha_insights.scan_now`
- `ha_insights.dismiss { id }`
- `ha_insights.apply { id }`
- `ha_insights.purge_observations`

---

## v0.1 hero: ScheduleDetector

Detects "user does X every weekday at ~T."

1. Pull state-change events for selected areas from recorder (≥7d) or buffer.
2. Group by `(entity_id, new_state)` for enum-like states.
3. Bucket by ISO weekday + time-of-day in 5-min slots.
4. Routine requires: ≥10 occurrences in 14d, time-of-day stddev ≤ 8 min, weekday consistency ≥ 80%.
5. `confidence = min(1, occurrences/14) × weekday_consistency × (1 − stddev_min/15)`.
6. Heuristic builds **HA Blueprint instance** (default) with parameters: `time`, `days`, `target_entity`, `action`. Or raw automation if user prefers (advanced).
7. Title: template ("On weekdays at 6:47 AM, light.kitchen turns on (12/12 days)").
8. Explanation: empty until user clicks Explain → LLM call with redaction.

**Edge cases:** manual override during routine (confidence decays), DST boundaries (clock-time grouping + DST notice), entities without friendly_name (fall back to entity_id), multi-state entities (any short non-dotted enum state is supported — `on`/`off`, `playing`/`paused`, `home`/`away`, `armed_home`, etc; only `unavailable`/`unknown`/`none` are excluded).

---

## Privacy model

### Three modes

| Mode | What it does | What leaves your network |
|---|---|---|
| **🚫 Off** | LLM disabled. Detectors still run, plain-English titles only, no Explain button. | **Nothing.** |
| **🟢 Local** | Auto-applied for Ollama or any agent declared local. Real names, real values, no friction. | **Nothing leaves the network.** |
| **🟡 Cloud** | Default for Anthropic/OpenAI/Google. Names + areas pseudonymized, numerics bucketed, sensitive domains blocked. | **Pseudonymized payloads only.** |

### Local vs Cloud — automatic behavior differences

| Behavior | Local 🟢 | Cloud 🟡 |
|---|---|---|
| Default redaction | None | Names + areas pseudonymized, numerics bucketed |
| Preview-before-send | Off by default | **On by default** (mandatory until user opts out) |
| Default-blocked **privacy** domains (camera, person, device_tracker) | Unblocked | Blocked — explicit opt-in per domain |
| Default-blocked **safety** domains (lock) | Still blocked | Still blocked |
| Auto-explain insights on detection | Allowed (free, fast) | Never — always user-initiated |
| Bandwidth/cost tracking | Off | On — daily budget cap configurable |
| UI badge | 🟢 LOCAL | 🟡 CLOUD |

**Local detection:** Ollama integration and HA's built-in intent agent are auto-trusted as local (hardcoded list, maintained per HA release). OpenAI-compatible (LocalAI, vllm, llama.cpp) is ambiguous — wizard asks once, editable later. Privacy log records the agent name and bytes regardless of declaration.

### Trust badges — visible everywhere

```
🟢  LOCAL — Ollama @ homeassistant.local
    Your data did not leave your network.

🟡  CLOUD — Anthropic — pseudonymized
    Real names replaced. Tap to see payload.

🔴  CLOUD — Anthropic — REAL NAMES (you opted in)
    Real names sent. Tap to see payload.
```

Every Explain click, every insight detail, every privacy-log row carries the same badge. Same colors, same sentence pattern.

### "What gets sent?" — one tap from anywhere

Any badge → tap → opens a modal showing: current mode, list of fields sent (pseudonymized), list of fields never sent, **example payload at current settings**, and a "Change settings" link. Source of truth for "what will I expose?"

### Always-redacted attributes (built-in, not user-editable)

Regardless of mode, these attributes are stripped from any LLM payload:
- `gps_lat`, `gps_lon`, `gps_accuracy`, `latitude`, `longitude`, `altitude`
- `mac`, `ip`, `ip_address`, `bssid`, `ssid`
- `password`, `token`, `access_token`, `auth`, `api_key`
- `serial_number`, `device_id` (when not the primary identifier)

User-editable sensitive list on top via advanced regex blocklist.

### Setup wizard — single page

```
LLM Enrichment

⦿ Off — I just want pattern detection
○ Use a local LLM (recommended for privacy)
    🟢 Ollama detected at homeassistant.local
○ Use a cloud LLM
    ○ Anthropic   ○ OpenAI   ○ Google

▸ Advanced privacy options                        ← collapsed
```

### Advanced controls (gated behind disclosure)

For power users only:
- 4 redaction levels (Paranoid / Balanced / Permissive / Custom)
- Per-entity allow/block/never-send
- Per-attribute toggles (`temperature` yes, `battery_level` no)
- Regex blocklist (additive to always-redacted)
- Numeric bucket fine-tuning (energy / temp / time granularity)
- Preview-on-send override per level
- Daily/monthly token budget caps

---

## LLM context injection

The LLM gets a small structured context per Explain call. **What it sees depends on the privacy mode** — same gradient as redaction:

| Context field | 🟢 Local | 🟡 Cloud (default) | 🔴 Cloud permissive |
|---|---|---|---|
| HA version (major.minor) | ✅ full (`2025.4.2`) | ✅ truncated (`2025.4`) | ✅ full |
| Installation type (OS / Container / Core) | ✅ | ❌ | ✅ |
| Conversation agent + model | ✅ | ❌ | ✅ |
| Insight-relevant domains | ✅ | ✅ | ✅ |
| Specific integrations installed | ✅ | ❌ | ✅ |
| Total entity / area counts | ✅ | ❌ | ✅ |
| Specific area / entity names | ✅ | ❌ (pseudonyms) | ✅ |

HA version (major.minor) is **always sent** — public on release day, low sensitivity, lets the LLM phrase against the right feature set. Specific integrations/counts/names are gated.

The same redactor handles both insight payload and context fields → **one privacy boundary, not two.**

Cloud-default system prompt:
```
You are explaining a detected routine to a Home Assistant user.
Home Assistant version: 2025.4
Insight involves: domain `light`
Use only documented HA core features that exist in 2025.4+.
Do not reference specific integrations not present in the payload below.
```

---

## YAML validation pipeline

**Reminder:** the LLM doesn't produce YAML — the heuristic does. So validation is about heuristic output and resilience against HA upgrades.

```
Heuristic generates dict (Blueprint instance or raw automation)
        ↓
Layer 1: cv.AUTOMATION_SCHEMA / cv.BLUEPRINT_SCHEMA  (offline, same validator HA uses)
        ↓
Layer 2: WS automation/validate or blueprints/validate  (online — entities exist? services exist? valid for this HA version?)
        ↓
Layer 3 (v0.2+): WS check_config / template-evaluate for complex flows
        ↓
WS automation/config POST or blueprints/import  (apply)
```

Nothing reaches apply without passing both Layers 1 and 2.

### Failure UX

Three named states surfaced in the card:
- **Schema rejection**: *"Couldn't apply — automation schema rejected. [Show details]"*
- **Live validation failure**: *"`light.kitchen_old` no longer exists. [Update to current entity] [Dismiss]"*
- **HA reload failure**: *"Applied but reload failed. [Manual reload] [Undo]"*
- **LLM timeout (Explain)**: *"LLM didn't respond. [Retry] [Send to a different agent]"*

Each is a defined state, not a silent exception.

---

## Apply pipeline

For `automation_proposal`:
1. Heuristic builds **Blueprint instance** (default) or raw automation config.
2. Conflict scanner: check existing automations for trigger overlap → suppress or label.
3. Layer 1+2 validation (above).
4. WS POST to `automation/config/{auto-id}` or `blueprints/import`.
5. HA reloads automatically.
6. Insight marked `applied`; artifact_id + snapshot stored for undo.

### Drift detection on applied automations

Before any undo:
1. Fetch current automation, compare hash to `applied_history` snapshot.
2. Three states:
   - **Unchanged**: undo silently
   - **User-edited**: confirm dialog: *"You've modified this automation since we created it. Undo will revert your edits. [Show diff] [Undo anyway] [Cancel]"*
   - **Deleted**: clean up our record, no-op the undo button

Same drift check before re-running upgrade-resilience re-validation.

### Upgrade resilience (v0.2+)

Subscribe to `automation_reloaded`, re-validate our applied automations on HA upgrade. If any now fail validation, surface as a special insight: *"Your auto-generated automation no longer validates after HA upgrade — review."*

### Conflict detection with existing automations

At insight-generation time:
- Scan existing automations for trigger overlap on the same entity/time window
- If overlap: either suppress the insight or attach `conflicts_with: [automation_id]` and label *"You already have an automation covering this — review?"*

### Entity-id rename handling

Subscribe to `entity_registry_updated`. On rename:
- Migrate pseudonym map atomically
- Recompute affected fingerprints
- Update `applied_history` snapshots so drift detection doesn't false-positive

---

## Repo 2: `ha-insights-card` file tree

```
ha-insights-card/
├── README.md, LICENSE, hacs.json
├── package.json, rollup.config.mjs, tsconfig.json
├── .github/workflows/release.yml          # publishes built JS to release
├── src/
│   ├── ha-insights-card.ts              # main custom element
│   ├── insight-row.ts
│   ├── insight-detail-modal.ts            # explain/preview/apply
│   ├── what-gets-sent-modal.ts            # the trust modal
│   ├── editor.ts                          # GUI card editor
│   ├── ws/{client,types,handshake}.ts
│   └── styles.ts
└── dist/ha-insights-card.js             # built artifact, committed for HACS
```

Stack: Lit 3 + TypeScript strict + Rollup. Mirrors HA's official card stack.

---

## Data model (SQLite)

```sql
CREATE TABLE state_events (
    id INTEGER PRIMARY KEY,
    timestamp REAL NOT NULL,
    entity_id TEXT NOT NULL,
    domain TEXT NOT NULL,
    area_id TEXT,
    old_state TEXT,
    new_state TEXT
);
CREATE INDEX ix_state_events_ts ON state_events(timestamp);
CREATE INDEX ix_state_events_eid ON state_events(entity_id);

CREATE TABLE insights (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    detector TEXT NOT NULL,
    area_id TEXT,
    title TEXT NOT NULL,
    confidence REAL NOT NULL,
    fingerprint_json TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_format TEXT NOT NULL DEFAULT 'blueprint',
    explanation TEXT,
    conflicts_with_json TEXT,
    created_at REAL NOT NULL,
    snoozed_until REAL,
    dismissed_at REAL,
    applied_at REAL,
    applied_artifact_id TEXT
);

CREATE TABLE outbound_calls (
    id INTEGER PRIMARY KEY,
    timestamp REAL NOT NULL,
    insight_id TEXT,
    agent TEXT NOT NULL,
    agent_locality TEXT NOT NULL,           -- 'local' | 'cloud'
    redaction_mode TEXT NOT NULL,
    bytes_sent INTEGER NOT NULL,
    bytes_received INTEGER,
    success BOOLEAN,
    redacted_payload_json TEXT              -- audit trail, retention-bound
);

CREATE TABLE applied_history (
    insight_id TEXT PRIMARY KEY,
    artifact_kind TEXT NOT NULL,            -- automation, blueprint, card, group
    artifact_id TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,            -- prior state for undo
    snapshot_hash TEXT NOT NULL,            -- for drift detection
    applied_at REAL NOT NULL,
    undo_window_expires_at REAL NOT NULL
);

CREATE TABLE pseudonym_map (
    entity_id TEXT PRIMARY KEY,
    pseudonym TEXT NOT NULL UNIQUE,
    area_id TEXT,
    created_at REAL NOT NULL
);
```

State-event buffer is in-memory by default; SQLite persistence is opt-in.

---

## Operational policies

### Data lifecycle & retention (defaults; user-tunable)

| Table | Retention | Notes |
|---|---|---|
| `state_events` | 7d, in-memory only | Persistence opt-in |
| `insights` | until applied / dismissed / purged | No auto-expiry |
| `outbound_calls` | 30d | Redacted payloads bound by same window |
| `applied_history` | 7d hard / 90d soft | Snapshot dropped at 90d, record retained |
| `pseudonym_map` | persistent | Never auto-purged (used for stable references) |

All wiped by `ha_insights.purge_observations` (except pseudonym_map and applied_history — those stay so undo and references work).

### Rate limiting & cost circuit-breakers

- **Cloud agent token budget:** 50k tokens/day default per agent (configurable)
- **Local agent:** unlimited
- **Explain calls:** 60/hour ceiling per user
- **Detector scan:** 500ms p95 wall-clock budget per detector per scan
- **Daily nightly scan job:** ≤ 30s wall-clock total across all detectors
- **Failure mode:** when budget exhausted, badge shows "*budget exhausted, resets at HH:MM*"

### Performance budget (Raspberry Pi 4 reality)

- Event-bus subscription pre-filtered to selected areas (don't fan out 1500-entity firehose)
- Memory ceiling: 50 MB resident
- Documented in `docs/writing-a-detector.md` as non-negotiable

### Behavior on uninstall

- **Applied automations / blueprints**: stay (now native HA assets, not ours)
- **Insights queue, state-event buffer, privacy log, applied-history, pseudonym-map**: wiped
- Documented in `privacy.md`

### HA-internals dependency policy

- Wrap every non-public HA import in `apply/_ha_internals.py` (single point of contact)
- CI matrix: integration-test against **last 3 HA minor versions**
- Graceful import error: log + show "*HA Insights doesn't yet support HA {version}. Upgrade HA Insights or downgrade HA.*" — never crash boot

### HA version maintenance window

- Support **HA 2025.4** + **last 12 months of major.minor releases** (rolling)
- Deprecation cycle: warn one release, error the next
- Stated in README as a contract

---

## Testing harness & autonomous dev loop

### Why this exists at v0.1

HA Insights claims to detect routines from observed state — that claim must be *demonstrable end-to-end* before any insight code is trusted. The `dev/` harness lets a developer (or an autonomous agent like `/ultraplan`) seed a fresh HA, run the full pipeline, and assert the result in under 2 minutes.

### `dev/docker-compose.yml`

Boots `ghcr.io/home-assistant/home-assistant:2025.4` with our integration mounted at `/config/custom_components/ha_insights`. Exposes WS at `localhost:8125 (default; override via `HA_PORT` env var)`. Long-lived access token pre-created via `configuration.yaml` + token file injection. Tear-down wipes state cleanly.

### `dev/seed.py`

Generates synthetic state history. Example:
```
python dev/seed.py --days 14 --pattern weekday-routine \
    --entity light.kitchen --action turn_on --time 06:47
```
Connects via WS, backdates entries to recorder. Produces a HA instance that *looks like* it observed N days of usage.

### `dev/probe.py`

End-to-end assertion script:
1. Reset HA state
2. Install integration via WS config entry
3. Run `seed.py` for a known pattern
4. Trigger `ha_insights.scan_now`
5. Assert insight appeared with expected fingerprint + confidence
6. Call `ha_insights.apply`
7. Assert automation now exists in HA
8. Print pass/fail report

This is the autonomous agent's success criterion at every step: code change → probe pass → commit.

### Autonomy gates for `/ultraplan`

`/ultraplan` runs autonomously between gates, pauses at each for human review:

| Gate | When | What human reviews |
|---|---|---|
| **G0 — Pre-bootstrap** | Before creating repos | Trademark + name availability, license confirmed |
| **G1 — Post-bootstrap** | Repos init + dev harness up | Manifest, hacs.json, CI green, harness reachable |
| **G2 — Post-demo-path** | End of critical-path step 13 | End-to-end probe passes; manual Explain click |
| **G3 — Pre-tag** | Before v0.1.0 release | All tests pass, privacy doc reviewed, success criteria met |

Between gates: agent codes a step → runs `dev/probe.py` (or unit tests) → on pass commits → next step. On fail: reads error, attempts one fix, retries; if still fails, surfaces to human and pauses.

### What the agent cannot do autonomously

- Create GitHub repos (needs auth — human runs `gh repo create`)
- Push to remotes (needs auth)
- Trademark / branding decisions
- Subjective UX (color, copy beyond functional defaults)
- Touch the user's *actual* HA install — **only the Dockerized one**
- Modify the charter without explicit approval

### Tooling preconditions

- Docker Desktop running (user has it for ESP-IDF)
- Python 3.13+ locally
- Node 20+ for card builds
- `gh` CLI authenticated (for repo create + push, when human approves)

---

## Critical path (v0.1)

Each step's "verify" is the gate that must pass before commit. Agent advances autonomously; human reviews at G0–G3.

1. **G0** ← human: trademark + name availability + license confirmed
2. **Repo bootstrap × 2** (manifests, hacs.json, CI skeletons) → *verify:* hassfest + HACS validate green
3. **`dev/` harness up** (docker-compose, seed/probe stubs) → *verify:* HA reachable at `localhost:8125 (default; override via `HA_PORT` env var)`, probe.py runs
4. **G1** ← human: harness review
5. **`Insight` + `InsightKind` + `Detector` ABC + registry** — **freezes community shape** → *verify:* import + ABC unit tests
6. **`state_event_buffer`** + entity-rename handler → *verify:* synthetic event stream test, rename doesn't break fingerprints
7. **`store` (SQLite + migrations)** + `pseudonym_map` → *verify:* roundtrip + migration tests
8. **`config_flow`** (three-mode wizard) → *verify:* config-flow pytest
9. **`ScheduleDetector` MVP** + Blueprint emission → *verify:* `probe.py` with 14-day synthetic routine produces expected insight + Blueprint
10. **Conflict scanner + two-layer validator** → *verify:* `probe.py` with pre-existing automation suppresses duplicate
11. **WS API** (hello/list/subscribe + handshake) → *verify:* `probe.py` asserts handshake response shape
12. **Card MVP** (list + handshake + downgrade banner) → *verify:* vitest + manual smoke at `localhost:8125 (default; override via `HA_PORT` env var)`
13. **`apply/automation_writer` + `blueprint_writer` + drift detector** → *verify:* `probe.py` applies, asserts automation exists, edits, asserts drift detected
14. **Card detail modal** (preview + apply) → *verify:* manual click-through against probe-seeded HA
15. **G2** ← human: full demo path works end-to-end
16. **`llm/redactor` + `llm/context` + `llm/agent_client` + `llm/privacy_log`** → *verify:* redactor unit tests, no-network test, privacy-log sensor test
17. **Trust badges + "what gets sent?" modal** → *verify:* vitest snapshot tests
18. **Card detail modal** (explain + redaction preview) → *verify:* mock LLM round-trip, payload matches expected redaction
19. **Snooze + dismiss + purge + budget breaker** → *verify:* pytest + `probe.py` budget-exhaustion test
20. **Docs** (privacy.md, writing-a-detector.md, ws-api.md) → *verify:* links resolve, examples run
21. **Test coverage ≥80%** on detector + apply + privacy + drift → *verify:* coverage report
22. **G3** ← human: pre-tag review
23. **Tag v0.1.0** → *verify:* HACS validate green, release artifact built

---

## Release history (actual)

| Version | Theme | Highlights |
|---|---|---|
| v0.1.0 | Foundation | ScheduleDetector, inbox card, three-mode privacy wizard, apply pipeline |
| v0.2.0 | LLM Explain | Conversation API integration, Redactor, privacy log sensor, OptionsFlow |
| v0.3.0 | Refine + co-occur | CooccurrenceDetector, LLM Refine, Test actions, modal UI, TTS, inline rename |
| v0.4.0 | Day-one onboarding | Recorder backfill (auto on setup + manual service + lookback config) |
| v0.5.0 | Surface expansion | Sidebar panel, visual editor, adaptive sizing, compact tile, search |
| v0.5.1 | Refine polish | INSUFFICIENT_BUDGET self-signal, refusal detection, side-by-side compare, follow-up feedback |
| v0.6.0 | Trust & visibility | Per-entity LLM opt-out, "What gets sent?" preview, audit log viewer, trust pills |
| v0.7.0 | Detector library doubles | LongTailDetector, OrphanDeviceDetector, StreakDetector, confidence colors, age, sort/group |

## Future roadmap (planned)

| Target | Theme | Candidate items |
|---|---|---|
| v0.8 | Apply pipeline polish | Undo applied, online (Layer 2) validator, edit YAML before apply, bulk apply |
| v0.9 | Smart features | Notifications, LLM cost estimator, agent failover, AnomalyDetector, SeasonalityDetector, CorrelationDetector |
| v1.0 | Release candidate | Multi-config-entry, custom detector loading, multi-turn refine, i18n, docs site, HACS default-store PR |

> The original v0.1 charter envisioned a different shape (vision-LLM, anomaly, cleanup as separate releases). Actual cadence has prioritized refining the hero loop and the privacy story before broadening detector kinds. See git tags for the canonical record.

---

## Risks

| Risk | Mitigation |
|---|---|
| HA WS config API changes between minor versions | Pin to documented endpoints; CI matrix against last 3 HA versions |
| Recorder unavailable | Heuristic works on rolling buffer; recorder is enhancement |
| User has no Conversation agent set up | Wizard detects, links to docs, falls back to LLM-disabled |
| Detector false positives erode trust | Confidence threshold + dismiss → fingerprint blacklist; never re-suggest |
| YAML-mode Lovelace can't apply card-proposals | Detect mode, degrade to copy-YAML UX |
| Big installs (1500+ entities) overwhelm scan | Area-scoped, scan budget, pre-filtered subscription |
| Community detectors do unsafe things | Detector ABC restricts file/network; in-tree contributions get code review |
| WS protocol drift between card and integration | Handshake on every connect; UI downgrades; banner prompts |
| User edits applied automation, then undoes | Drift detection → confirm dialog with diff |
| Sensitive attributes leak via LLM context | Always-redacted attribute list, enforced at redactor; CI tests |

---

## Success criteria for v0.1

- HACS custom-repo install in <5 min
- First insight within 24h on a typical home
- **Zero outbound network calls** until user opts in to LLM and clicks Explain
- "Apply" produces a Blueprint instance indistinguishable from hand-written
- `docs/privacy.md` survives a hostile read by an HA-community privacy advocate
- ≥3 community detector contributions within 60 days

---

## Why no vector DB / RAG (recorded for posterity)

- Data is **structured** (state events, entity metadata, YAML configs); SQL handles it.
- "Search" is **structural** (by entity, by area, by pattern fingerprint), not semantic.
- The LLM is a **narrow translator** ("turn this candidate into prose"), not a brain that needs retrieval. The heuristic detector already picked the context.
- Embeddings cost cloud API calls (privacy hit) or local sentence-transformers (heavy CPU/RAM); zero retrieval benefit at v0.1–v1.0 scope.
- User-feedback loop ("stop suggesting dismissed things") is a fingerprint blacklist + confidence weights, not vector similarity.
- Upgrade path if conversational queries land in v2.x: `sqlite-vss` extension on the SQLite we already use. No separate DB process.

**Don't relitigate this without a feature that genuinely needs semantic distance.**
