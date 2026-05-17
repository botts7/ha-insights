# Changelog

All notable changes to this project are documented in this file. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.7.6] — 2026-05-17

### Fixed

- **Bundled panel.js bumped to card v1.3.4** — fixes the 🔗 coupling
  badge never rendering on the side panel. Root cause was a
  custom-element registration collision: when HACS had an older
  `ha-insights-card.js` (pre-v1.3.0) loaded BEFORE the integration's
  bundled panel.js ran, the `customElements.define("ha-insights-card",
  ...)` guard in the bundled card source saw the name already taken
  and silently discarded the freshly-built class. The panel embedded
  the stale HACS class — which lacked the badge code.

  Card v1.3.4 registers an `ha-insights-card-bundled` alias (trivial
  subclass of the freshly-built `HaInsightsCard`) and embeds that
  inside the panel. The bundled class always wins, regardless of
  HACS card state.

  No integration code change — just a fresh panel.js artifact baked
  in. After updating + hard refresh, the 🔗 badge should render on
  any TIGHT-coupled insight.

## [1.7.5] — 2026-05-17

### Fixed

- **Panel rendering twice** — bumps the bundled panel.js to card
  v1.3.3 which fixes a race in the v1.3.1 recovery code. v1.3.1's
  IIFE called `tryRecover()` synchronously at module load AND
  started a polling burst immediately. On first `/ha-insights`
  visit, our force-mount ran before HA's normal panel resolver
  finished → HA then mounted a second `ha-insights-panel` on top
  of ours.

  v1.3.3 adds (a) a dedupe pass that removes extra panels at the
  start of every recovery attempt, (b) a 500ms first-probe delay
  so HA's normal mount completes first, (c) drops the synchronous
  module-load attempt entirely.

  No integration code change — just a fresh panel.js artifact
  baked in.

## [1.7.4] — 2026-05-17

### Fixed

- **v1.7.3 panel-bundle URL never registered.** Real-install
  reported "Unable to load custom panel from
  `/api/ha_insights/static/panel.js?v=1.7.3-...`" immediately after
  updating. Two bugs compounded:

  1. **`hass.http.register_static_path` has been removed** in
     recent HA versions (replaced by
     `async_register_static_paths`, plural+async). My v1.7.3 call
     to the removed API silently `AttributeError`'d → URL never
     registered → 404 → "Unable to load custom panel."
  2. The URL prefix `/api/*` is reserved by HA. Even if the old
     API had worked, this would have been blocked by HA's API
     router.

  v1.7.4 fixes both:
  - Use the modern `async_register_static_paths([StaticPathConfig(...)])`
    API.
  - Serve from `/ha_insights_static/panel.js` (no `/api/` prefix).
  - Wider exception handling — only `RuntimeError` (the
    already-registered case) is silently swallowed; other failures
    log a warning and fall back to the legacy HACS-card URL so the
    panel still loads.

  No manual cleanup required; v1.7.4 will simply register the new
  URL and the panel will load.

## [1.7.3] — 2026-05-17

### Fixed

- **panel.js now bundled INTO the integration and served via
  `register_static_path`.** Pre-v1.7.3 the panel JS was loaded from
  `/local/community/ha-insights-card/ha-insights-panel.js` — a HACS
  card-managed path. But the companion card's release workflow only
  attached `ha-insights-card.js` (not `ha-insights-panel.js`) until
  v1.3.2, meaning `panel.js` was frozen at whatever was last
  manually committed to the card's `dist/`. Real-install diagnostic
  on 2026-05-17 caught a user serving a 73KB pre-v1.2.26 bundle
  despite ten subsequent card releases — every `src/ha-insights-
  panel.ts` change since then, including v1.2.26's blank-panel
  recovery and v1.3.1's shadow-DOM observer fix, was dead code.

  v1.7.3 ships `panel.js` as a static asset inside
  `custom_components/ha_insights/static/panel.js`, served at
  `/api/ha_insights/static/panel.js`. Panel JS now tracks
  integration version exactly — same lifecycle as the Python code.

  Resolution order kept as fallback for users mid-migration:
  bundled path first, then card-HACS path, then legacy `/www/`.
  Future major version drops the fallbacks.

  This change is invisible to users running healthy installs — the
  cache-bust query string + register_static_path path are different
  but the rendered UI is identical. Users who were stuck on the
  stale 73KB panel get the actual current bundle without needing
  to manually copy files.

### Notes

The bundled `panel.js` is built from the companion `ha-insights-card`
repository's `src/ha-insights-panel.ts`. Future updates require:
1. Card repo: src change → tag → release workflow builds and attaches
   `ha-insights-panel.js` to the GitHub release.
2. Integration repo: pull the built artifact, replace
   `static/panel.js`, bump version, release.

The release pipeline could automate step 2 in a future iteration.

## [1.7.2] — 2026-05-17

### Fixed

- **Closes #12 — AutomationAuditDetector now actually rotates through
  every automation.** The previous `eligible[:_AUDIT_PER_SCAN_CAP]`
  slice always audited the same first 25 automations alphabetically.
  An install with N>25 automations had the later ones permanently
  invisible to the audit detector — the docstring claimed "rotation
  across scans is implicit" but the code didn't implement it.

  Replaced with a class-level offset that advances each scan, with
  two-segment slicing for clean wrap-around (final batch of each
  cycle stitches the tail-end with a slice from the start so the
  per-scan cap is always honored). Full list completes in
  `ceil(N / _AUDIT_PER_SCAN_CAP)` scans regardless of automation
  count.

  Modulo handling means adding or removing automations between scans
  doesn't crash on a stale offset — list shrink/grow resumes from
  the current modular position.

  Resets to 0 on HA restart (acceptable — worst case one extra
  rotation cycle). Tests cover small lists, equal-to-cap lists,
  multi-scan walks, wrap-around stitching, skip-label filtering,
  and shrunken-list robustness.

## [1.7.1] — 2026-05-17

### Added

- **TIGHT-coupled example fixture** — `inject_examples` now produces a
  Z-Wave-scene-controller cooccurrence insight whose payload carries
  `_coupling: {tier: "TIGHT", median_lag_ms: 180, consistency: 0.94}`,
  so users (and developers) can see the 🔗 badge render without
  waiting for organic device-binding patterns to surface on their
  install. Also retrofitted the existing minute-scale example with a
  NONE-tier stamp so its payload is honest about why no badge appears.

  Closes the verification gap reported on real install: v1.7.0
  shipped the badge code but the example fixtures predated v1.7
  and didn't include `_coupling`, so `inject_examples` couldn't
  demonstrate the feature.

### Removed

- Leading 🔗 emoji from the office-monitor example's title text —
  that was decorative pre-v1.7 chrome; the actual coupling badge
  is now a separate visual element, so the title-emoji was
  ambiguous ("is this the badge or just text?").

## [1.7.0] — 2026-05-17

### Added

- **Coupling-strength badge for pair-based insights.** Cooccurrence,
  lagged-correlation, and button-press detectors now compute a
  `CouplingScore` for every emitted pair (median lag in ms,
  consistency, tier ∈ TIGHT / LOOSE / NONE) and stamp it onto the
  payload as `_coupling`. Card v1.3.0+ reads this and renders a 🔗
  badge for TIGHT-tier pairs.

  Rationale (see `docs/HA_EVENT_SEMANTICS.md` and the upstream
  agent memory `reference_device_internal_logic_problem`): HA event
  metadata can't distinguish ESPHome on_press / Z-Wave binding /
  Zigbee binding from user-driven action — both produce
  `user_id=None, parent_id=None`. The latency signature CAN: device-
  internal logic fires the consequent within ~500ms at near-zero
  stddev; user habits don't. We surface the signature on the insight
  so the user judges whether the pair is "already handled, ignore"
  or "good automation candidate."

  - **TIGHT** (median ≤ 500ms AND consistency ≥ 90%): almost
    certainly device-internal logic or a pre-existing HA automation
    handling the same flow. Confidence demoted ×0.85 so these rank
    below uncoupled suggestions. Card renders 🔗 badge.
  - **LOOSE** (median ≤ 2s AND consistency ≥ 70%): could be an HA
    automation, could be a fast user habit — ambiguous. No
    demotion, no badge. (Phase 2 may surface a different mark.)
  - **NONE**: looks like real user habit. Insight emits normally.

  Tunable thresholds in `lib/coupling_strength.py` constants.

- **NEW** `custom_components/ha_insights/lib/coupling_strength.py` —
  pure function `compute_coupling(deltas_seconds, leader_count)`
  returning `CouplingScore`. Zero HA imports; unit-tested in
  `tests/test_lib_coupling_strength.py`.

### Changed

- `CooccurrenceDetector._evaluate_pair` calls `compute_coupling`
  and `apply_tier_demotion`; payload now includes `_coupling`.
- `LaggedCorrelationDetector._evaluate_pair` propagates the
  parent's coupling stamp into its rebuilt payload (at lagged
  windows tier is essentially always NONE, but stamping
  consistently lets the card make uniform rendering decisions).
- `ButtonPressHabitDetector._build_insight` computes coupling
  over `delays` × `total_firings` and demotes accordingly.

### Notes

- No schema migration; `_coupling` is additive in the free-form
  payload dict. Older card versions ignore the field; older
  integration versions don't stamp it.

## [1.5.51] — 2026-05-17

### Fixed

- **Second wave of pre-existing test failures (issue #11).** After
  the first batch fixes landed, pytest collection progressed further
  and surfaced 7 more failures with the same root cause: stale seed
  counts vs raised thresholds. All fixed:
  - `test_long_tail_detector.py`: 4 tests needed ≥5 spans (confidence
    formula is `count/10`, MIN_CONFIDENCE_TO_EMIT=0.5).
  - `test_lagged_correlation_detector.py`: needed ≥6 pairs (inherited
    cooccurrence floor of 0.55).
  - `test_frequency_anomaly_detector.py`: renamed
    `test_three_x_ratio_is_threshold` → `test_eight_x_ratio_is_threshold`
    after v0.9 bumped RATIO_THRESHOLD from 3 to 8.
  - `test_schedule_detector.py`: loosened a confidence-value assertion
    that synthetic single-entity seeds can no longer satisfy now that
    `assess_human_likelihood` shapes confidence.
  - `test_streak_detector.py`: fixed UTC-vs-local-time mismatch in the
    seed helper — `dt_util.as_local` in the detector was reading
    timezone-shifted hours on non-UTC test runners.
  - `ws_api.py`: dropped `dev_inject_event` from `SUPPORTED_METHODS`
    (test already enforced it's debug-only).

- **BETA-detector audit (issue #11 follow-up).**
  `ButtonPressHabitDetector._already_automated` only matched scalar
  `entity_id` on existing triggers. HA state triggers accept either a
  string or a list of strings; the list form (`entity_id: [a, b, c]`)
  silently fell through, so the detector could propose a "press X →
  do Y" automation even when an existing automation triggered on `[X,
  other]`. Fix iterates list-form entity_ids.

- **Pre-existing test failures surfaced by v1.5.50.** v1.5.50 cleared the
  ruff backlog and pytest collection started running — which immediately
  exposed ~10 tests that had been broken across multiple versions but
  hidden because ruff was failing the `pytest` step. Resolved here as
  [#11](https://github.com/botts7/ha-insights/issues/11). All test
  failures are now green:

  - **`conflict_scanner.py`**: real production bug. The schedule-like
    fallback added in 2026-05-10 (ea61c3936) over-fired on
    same-`platform: time` pairs that the time-window check had already
    decided were not in conflict. Added an `_all_platform_time(a) and
    _all_platform_time(b)` short-circuit before the fallback — when both
    sides have only directly-comparable time triggers, the
    `_times_close` check is authoritative. Catches the same edge case
    where a malformed `at: not-a-time` would get flagged purely from
    the fallback. The schedule-like fallback still does its intended
    job for cross-platform cases (time vs sun, calendar, etc.).
  - **`test_conflict_scanner.py`**: 3 state-trigger tests assumed
    overlap on the source entity alone was a conflict, but the scanner
    has required overlap on BOTH source entity AND action target since
    earlier. The tests' action targets differed by name; updated to
    overlap so the tests test what their names claim.
  - **`test_config_flow.py`**: the OptionsFlow init step is now a menu
    (Quick wizard / per-user overrides / Advanced); lookback_days lives
    inside Advanced. The test was written when init was a single form.
    Rewrote to walk init-menu → Advanced → submit.
  - **`test_cooccurrence_detector.py`**: 3 tests seeded 8 pairs but the
    v0.5+ busy-entity prefilter requires per-entity count ≥
    `MIN_OCCURRENCES = 15`. Bumped seeds to 16 pairs to clear the
    threshold. (The "StopIteration" failure in
    `test_payload_has_state_trigger_and_service_action` was the same
    root cause — `next()` on an empty insights list.)

## [1.5.50] — 2026-05-17

### Fixed

- **Ruff lint debt — `Tests` CI is now green.** The repo had accumulated
  **393** ruff violations across the codebase, which kept the `Tests`
  workflow failing on every push since the lint check was added. Not
  HACS-blocking (only `Validate` matters there) but a constant red
  signal that masked real failures. v1.5.50 ships zero.

  Breakdown of what changed:

  - **290 auto-fixes** via `ruff check --fix`: unused `# noqa` directives
    dropped, `__future__` quoted-annotation strings unquoted, imports
    sorted, `datetime.timezone.utc` → `UTC`, etc. Mechanical.
  - **4 real bugs / authoring artifacts fixed**:
    - `__init__.py` had an unused `get_analytics_settings` import.
    - `hierarchy.py` had two unused loop variables (`container`, `device`).
    - `manual_habit.py` had an unused unpack (`svc_call`).
    - `test_lib_persistence_likelihood.py` had a dead test path with an
      orphaned assignment + a TODO comment ("Let me check more carefully")
      that had been left in. Cleaned up.
  - **4 `(str, Enum)` → `StrEnum`** modernizations: cooccurrence,
    persistence, timing, transition_entropy likelihood classes.
  - **27 long lines wrapped** with implicit string concatenation in
    `setup_quality.py` tier descriptions and a few other spots.
  - **5 semicolon-separated statements** in test files split onto
    separate lines.
  - **Config additions** in `pyproject.toml`:
    - Ignore RUF001/002/003 globally — we use Unicode arrows / ±
      / em-dashes intentionally for readability.
    - Ignore RUF046 globally — defensive `int(x)` casts where the
      analyzer thinks `x` is already int (it isn't always at runtime).
    - Per-file `E501` ignore on `lib/event_filters.py` because the
      module docstring contains a markdown table that would lose
      grid alignment if wrapped at 100 chars.

All 107 lib unit tests + all 175 smoke tests pass.

## [1.5.49] — 2026-05-17

### Fixed

- **Hassfest CI failure: missing `after_dependencies` entries.**
  v1.5.46 added `from homeassistant.components import logbook` and the
  audit module has long used `homeassistant.components.trace`, but
  neither was declared in `manifest.json`. Hassfest fails the build
  with `[ERROR] [DEPENDENCIES] Using component <name> but it's not in
  'dependencies' or 'after_dependencies'`. Both added to
  `after_dependencies` (we don't HARD-require them — the logbook
  emission falls back gracefully when logbook isn't loaded, and the
  audit detector skips its trace observations when trace isn't
  available — so `after_dependencies` is the right severity).
- **HACS validation failure: extra `description` key.** `hacs.json`
  doesn't accept `description` — the field is intended for
  `manifest.json` only on integrations. Dropped from the HACS manifest;
  the same copy lives in the README which HACS renders inline thanks
  to `render_readme: true`.

These two failures kept the integration's CI red for every release
since v1.5.46. The HACS catalog PR ([hacs/default#7682](https://github.com/hacs/default/pull/7682))
needs a green CI run on the latest release, so v1.5.49 unblocks
resubmission.

## [1.5.48] — 2026-05-17

### Added

- **`HabitualOverrideDetector` — surface automations the user keeps
  correcting.** When an automation sets `light.hallway` to `on` and
  within two minutes you manually flip it `off`, ONCE is noise.
  THREE TIMES across 14 days, on different days, is a habit — the
  automation likely needs revising.

  Surfaces a `PATTERN_OBSERVATION` insight per detected (entity,
  automation_state, manual_state) tuple where the user reverses an
  automation's effect within 120 s on at least 3 distinct days. NOT
  one-click applicable — the user owns their own automation and may
  want to remove the action, add a condition, or flip the target
  state. We surface the observation; they choose the fix.

  - New pure lib `lib/habitual_override.py` exposing
    `find_habitual_overrides(events, …) -> list[OverrideStat]`. Forward-
    only window, same-entity reversal detection, only-first-reversal-
    counts logic so later "corrections of own corrections" don't
    inflate sample size. Zero HA imports. 15 unit tests covering
    window boundaries, equal-state non-reversals, cross-entity
    isolation, bootstrap exclusion, automation-vs-automation handoff,
    and physical-switch-as-manual classification.
  - New detector `detectors/habitual_override.py` wrapping the lib.
    Maturity `BETA`. Auto-registered via the sibling-module discovery
    pattern. Honors per-entity opt-out via `blocked_entities`.
  - Re-uses the v1.5.45 manual/automation classification (`_is_manual`,
    `_is_automation_driven`) — the same unifying-signal foundation
    that drives Suggested Additions in the other direction.

## [1.5.47] — 2026-05-17

### Added

- **Brand icons ship inside the integration.** The
  `home-assistant/brands` repo no longer accepts new custom-
  integration assets — Home Assistant 2026.3.0+ reads brand
  icons directly from each integration's directory. See
  [brands-proxy-api announcement](https://developers.home-assistant.io/blog/2026/02/24/brands-proxy-api).

  v1.5.47 ships `custom_components/ha_insights/brand/`:
  - `icon.png` (256×256)
  - `icon@2x.png` (512×512)
  - `dark_icon.png` (256×256)
  - `dark_icon@2x.png` (512×512)

  No manifest change required — HA's frontend resolves the local
  path automatically when present. On HA 2026.2 and earlier the
  icons fall back to the brands CDN (which never picked them up
  because the upstream PR was closed) — those versions will see
  the default placeholder, which is fine: they're out of support
  before the next public-release window anyway.

## [1.5.46] — 2026-05-17

### Added

- **Retire lifecycle alongside Dismiss / Snooze.** The card and panel
  already had Dismiss (one-off "not relevant") and Snooze (temporary
  suppression). Retire is the third option: *"I have consciously
  decided NOT to automate this pattern, even though the detector
  keeps seeing it."* Future re-detections of the same fingerprint
  stay suppressed until the user explicitly un-retires.

  New surface:
  - DB schema migration v5 — `retired_at REAL` column on `insights`.
  - `InsightStore.retire_insight(id)` / `clear_retired(id)` methods,
    mirroring the existing `dismiss_insight` / `snooze_insight`
    shape. Notify "retired" / "unretired" events stream through the
    existing subscribe channel.
  - `home_insights/retire` + `home_insights/unretire` WS endpoints
    (admin-gated through the same path as snooze).
  - `home_insights/list` now accepts `include_retired: bool`
    (defaults `False`). The default list view stays clean; the
    history / management view opts in.
  - Existing UPSERT path's "DELIBERATELY NOT TOUCHED" list now
    includes `retired_at`, so a re-detection of the same insight
    doesn't wipe the user's retire decision.

- **Logbook entry emitted on every Apply.** When `home_insights/apply`
  succeeds, the integration fires a `logbook.async_log_entry` with
  `entity_id=automation.<id>`. The apply now shows up in HA's
  standard activity timeline alongside the `automation_reloaded`
  events the writer already triggers. Message tags Apply vs
  Apply-Refined vs Extended (the three apply variants) so the user
  can scan their Logbook history and see at a glance which insights
  they applied as-is versus refined-via-LLM versus extended via the
  Suggested-Additions modal.

  Best-effort: a logbook-not-loaded environment falls through
  silently — the apply itself never fails because the activity log
  couldn't write.

### Fixed

- `ws_suggest_additions` was defined in v1.5.44 but never registered
  via `async_register_command`. The smoke harness only checked the
  handler existed, not that it was wired into the WS router — the
  bug shipped silently. v1.5.46 adds the missing registration plus
  a smoke test that verifies registration alongside definition.

## [1.5.45] — 2026-05-16

### Added

- **Coactivation signal wiring for Suggested Additions.** v1.5.44 shipped
  the candidate-entities pipeline with a `coactivation_days` parameter
  but stubbed it to `None` — the three weaker signals (area-mates,
  device-mates, domain-siblings) carried the load. v1.5.45 lights up the
  fourth, strongest signal.

  New pure-Python lib `lib/coactivation.py` exposes
  `compute_coactivation_days(events, anchor_entity_ids, …)`. It walks
  the 14-day state-event buffer, finds candidates that fire within
  ±5 seconds of any required ("anchor") entity, and returns
  `entity_id → distinct_days_count`. The Suggested-Additions WS
  handler calls it with `anchor_entity_ids=required` and passes the
  result through to `build_candidate_entities`, which promotes
  `days >= 3` entities into the HIGH-tier "coactivator" bucket — they
  appear pre-selected in the card modal with the reason
  *"fired within ±5 s of trigger on N of 14 days"*.

  Defaults match the existing reason-string contract:
  `window_seconds=5`, `lookback_days=14`, `min_coactivation_days=3`.
  The lib also applies a `manual_only` filter (default on) that drops
  chain-automation noise — only events tagged with a `context_user_id`
  (UI / mobile / voice) or with NO HA-side context at all (physical
  switch / external) count as candidates. `from_bootstrap=True`
  events are always excluded (HA startup fan-out — Gotcha 5).

  Best-effort wiring: a buffer snapshot failure or counter exception
  falls back to `None`, leaving the three structural signals
  (area / device / domain) to produce candidates without the
  observed-behavior signal.

  Zero HA imports in the lib — duck-typed `_EventLike` Protocol means
  the function tests cleanly from a plain Python env and is
  HA-core-adoptable.

## [1.5.44] — 2026-05-16

### Added

- **Suggested Additions — local-first candidate-entity discovery.**
  When you're looking at an automation insight, HA Insights can now
  surface entities you might want to extend the automation's action
  block with — picked from observed evidence and topology, not
  hallucinated by an LLM. Pairs with companion card v1.2.27+ for the
  visible checkbox-modal surface; the WS contracts are in place in
  v1.5.44 so the card update unlocks the UX cleanly.

  Four signal categories, each tier-classified (HIGH / MEDIUM / LOW):

  - **Coactivator** (HIGH): observed to fire within ±5 s of the
    trigger across multiple days. Strongest evidence; rationalises
    cross-domain candidates (e.g. *"you manually flip the coffee
    switch within 2 min of the motion trigger 12 of 14 days"*).
    The `coactivation_days` input wires through `EventBuffer` and
    `ManualHabitDetector` signals. *Engine accepts the input; the
    WS handler populates it in v1.5.45.*
  - **Device-mate** (HIGH / MEDIUM): same device as an existing
    target. RGB strips with sub-entities, multi-channel switches.
  - **Area-mate** (MEDIUM / LOW): same `area_id` as an existing
    target. Lights in the same room.
  - **Domain-sibling** (MEDIUM): same domain as existing targets,
    anywhere on the install. Capped tightest to avoid prompt bloat.

  Cross-domain candidates are tagged with explicit reason strings
  (`"different domain (media_player.*)"`) and sorted last within each
  category. Without coactivation evidence, cross-domain candidates
  land in the LOW tier — collapsed under "Show more" in the card.
  The TV-on-with-lights case is filtered out by default.

  **Action-target compatibility filter**: candidates suggested for
  an automation's action block must be in actionable domains
  (`light`, `switch`, `fan`, `media_player`, `climate`, `cover`,
  `lock`, `vacuum`, `automation`, `scene`, `script`, `input_boolean`,
  `input_button`, `notify`, `remote`, `humidifier`, `water_heater`,
  `siren`, `valve`, `lawn_mower`, `button`). Sensors / binary_sensors
  / device_trackers / persons / zones / sun / weather are silently
  dropped — you can't `turn_on` a binary_sensor.

  Per-entity opt-out (`blocked_entities` in OptionsFlow) is honored
  by the engine — blocked entities never appear as candidates.

- **New WS endpoint `home_insights/suggest_additions`** — returns the
  flat candidate list with `tier`, `reasons`, `category` per candidate.
  Deterministic, local-only, no LLM tokens. Companion card opens
  a checkbox modal populated from this endpoint.

- **`home_insights/apply` extended with `additional_entity_ids`** —
  optional list of entity_ids the user picked from Suggested Additions.
  Server runs `lib/automation_yaml.append_entities_to_action_block` on
  the payload BEFORE the existing L1/L2 validators + AutomationWriter
  pipeline. Same validation, same writer, same undo flow. Cross-domain
  candidates not in a known turn_on/off domain return as
  `unhandled_entity_ids` in the response so the card can offer
  escalation to LLM Refine for the right service call.

- **`build_refine_prompt` extended with `candidate_block` kwarg** —
  when present, the LLM Refine prompt switches from the legacy
  *"Use ONLY these entity_ids"* single-tier constraint to a two-tier
  REQUIRED / OPTIONAL phrasing with explicit action-type consistency
  instructions. When absent, the prompt is byte-identical to v1.5.43.
  Backward-compat preserved for any caller that hasn't migrated.

- **`lib/candidate_entities.py`** — new pure-Python (HA-core-adoptable,
  no HA imports) module with `build_candidate_entities()` and the
  `CandidateEntities` / `CandidateEntity` dataclasses. 22 unit tests
  covering priority logic, action-target filter, tier classification,
  cross-domain handling, blocked-entity opt-out, deterministic
  ordering, prompt formatting.

- **`lib/automation_yaml.py`** — new pure-Python (no HA imports) YAML
  transform helper. `append_entities_to_action_block(payload, eids)`
  finds the matching action item by service-domain match, promotes
  scalar `entity_id` to list, appends, dedupes. Handles all three
  legacy field shapes (`target.entity_id`, top-level `entity_id`,
  `data.entity_id`). Creates a new action item with
  `<domain>.turn_on` service for cross-domain additions in 21 known
  turn-on/off domains. 14 unit tests.

### Notes

The card-side UX (pill, checkbox modal, deterministic apply button,
LLM Refine escalation for cross-domain) ships in **ha-insights-card
v1.2.27** as a follow-up. The integration-side contracts in v1.5.44
are stable; the card can opt in when it's built.

This release is **purely additive** — every existing WS endpoint,
detector, and lifecycle path behaves identically to v1.5.43 unless
a caller explicitly opts into the new fields. Backward-compat
verified via snapshot tests in `tests/test_refiner_prompt_candidates.py`.

## [1.5.43] — 2026-05-16

### Changed

- **Opt-in community analytics removed from OptionsFlow pending the v1.6
  receiver deployment.** The default endpoint
  (`https://analytics.ha-insights.io/v1/report`) isn't live yet, so
  firing the weekly POST would silently fail and confuse early users.
  `analytics.py` library + the `analytics_install_uuid` stable
  identifier + the `home_insights/analytics_preview` WS endpoint stay
  in the codebase, ready to re-wire when the receiver lands.
  Existing options entries with `analytics_enabled: true` from v1.4 /
  v1.5 remain in storage but are dormant — no scheduler runs.
  Constants `CONF_ANALYTICS_*` and `get_analytics_settings()` keep
  for backwards compat.

## [1.5.42] — 2026-05-16

### Fixed

- **`Automate this?` CTA stripped at storage time, canonical for every
  consumer.** Pre-v1.5.42 the strip ran only in the WS list pipeline
  AFTER cohort dedup appended `(+N similar entities: …)` to titles —
  the end-anchored regex no-op'd and the CTA leaked through to the
  persistent_notification toast, mobile push, and daily digest on
  shadowed insights. Strip now runs in the detector emission loop
  right after `conflicts_with` is set, before `store.add_insight`.
  Shared `lib/title_cleanup.py` is suffix-aware (splits off the
  cohort tail, strips the prefix CTA, rejoins).
- **`_resolve_panel` defaults to HACS path when neither file exists.**
  Brand-new HACS install where the card tarball hasn't finished
  extracting → both panel files momentarily missing → resolver was
  returning the legacy `/local/ha-insights-panel.js` URL, which 404s
  until the user reloads the UI. Now defaults to the HACS URL so the
  panel registration stays stable across the extraction window.
- **Docstring drift in grader libs.**
  - `lib/persistence_likelihood.py::FIXED_CYCLE` said "≥ 4 sessions";
    `_MIN_SAMPLES` has been 3 since v1.5.39.
  - `lib/cooccurrence_likelihood.py` class docstrings said "on
    average" (mean); code classifies on the median, and ISOLATED
    now reads "< 1" not "< 0.5".
  - Matters because these libs are explicitly marked HA-core-adoptable.

## [1.5.41] — 2026-05-16

### Fixed

- **Panel cache-bust string includes integration version.** Pre-v1.5.41
  the query was `?v={mtime}-{size}`; HACS tarball extraction preserves
  mtimes from the release tarball, so byte-similar bundles landed
  cache-identical and the browser kept the cached panel after an
  update. Now `?v={version}-{mtime}-{size}` — a version bump alone
  forces a refetch on the next integration reload.

## [1.5.40] — 2026-05-16

### Added

- **`lib/transition_entropy.py`** — fourth signal-grader (sibling to
  timing / cooccurrence / persistence). Approximates Houzé 2022's AIT
  memorability via a 2nd-order Markov proxy: counts distinct preceding
  entities per cluster event. High diversity at unstable timing →
  `NOVEL_CONTEXT` → 25 % confidence demotion. Stable few-entity
  contexts agree with `HUMAN_CONTEXT`. Toothbrush vs. solar inverter
  separate cleanly on this axis where co-occurrence alone misclassified
  them. Wired into schedule + streak as an `Optional` grader on the
  v1.5.38 composite; legacy callers get byte-identical scores.

## [1.5.39] — 2026-05-16

### Fixed

- **3-day streaks now graded.** All four grader libs lowered
  `_MIN_SAMPLES` from 4 → 3 so StreakDetector's 3-day-floor patterns
  no longer fall through ungraded. stddev/CV is still computable at
  n=3 (df=2); accuracy is lower than n≥10 but matches the downstream
  consumer's floor. Closes the live-validation gap where 3-day
  device patterns (solar inverter, BYD windows) stayed at 39–42 %
  with no device pill.
- **Persistence checks the previous state's duration too.** Toothbrush
  OFF events previously saw only forward duration (24 h until next
  brushing → HUMAN_VARIABLE, no penalty). `assess_persistence` now
  accepts `previous_state_durations_seconds`; picks the direction
  with the lower CV. The 2-minute brushing cycle now fingerprints as
  FIXED_CYCLE in the backward direction.

## [1.5.38] — 2026-05-16

### Changed

- **Three-lib apply-chain collapsed into a `HumanLikelihoodFeatures`
  composite.** schedule + streak previously inlined 18 lines of
  identical `lib.apply_to()` + `payload[_*_assessment] = ...` plumbing.
  Composite owns one `.apply_to(base)` + one `.payload_keys()`; future
  graders extend it without touching detectors. Equivalence test
  (`tests/test_lib_human_likelihood.py`, 7 cases × human/device/cloud/
  unknown iot_class) pins byte-for-byte identical output against the
  pre-refactor chain.

## [1.5.37] — 2026-05-15

### Added

- **`lib/persistence_likelihood.py`** — third signal-grader. CV of
  duration-in-state classifies sessions as FIXED_CYCLE (CV < 5 %,
  0.25× multiplier), TIGHT_DURATION (CV < 30 %, 0.85×), or
  HUMAN_VARIABLE (1.0×). Scale-invariant so 2-minute toothbrush
  cycles and 4-hour TV sessions compare cleanly. Open-ended sessions
  at buffer edges are omitted to avoid short-bias. Pure-math,
  HA-core-adoptable.

## [1.5.36] — 2026-05-15

### Added

- **`lib/cooccurrence_likelihood.py`** — second signal-grader.
  Median nearby-event count classifies events as HUMAN_CONTEXT,
  AMBIGUOUS, or ISOLATED in the ±5 s window. Wired into schedule +
  streak alongside timing_likelihood; combined demotion lands an
  isolated device-timer pattern around ~7 % confidence so users
  don't see it unless they explicitly browse low-confidence rows.

## [1.5.35] — 2026-05-15

### Added

- **`lib/timing_likelihood.py`** — first signal-grader. Classifies
  recurring events as DEVICE_LIKELY / TIGHT_PATTERN / HUMAN_LIKELY
  / INSUFFICIENT_DATA from stddev + range, with iot_class-aware
  thresholds: local push/polling at < 2 s range, cloud push/polling
  at < 10 s, unknown at < 5 s (conservative). Sub-second precision
  on a daily pattern is a fingerprint no human can produce.
- **Card** (v1.2.17) renders a 🤖 *device-managed* / *tight-pattern*
  pill on graded rows so users see WHY confidence was demoted.

## [1.5.34] — 2026-05-15

### Fixed

- **Underscore-prefixed detector metadata stripped before writing
  automations.yaml.** `_manual_habit`, `_audit`, `_streak`, and the
  v1.5.35+ `_*_assessment` keys are detector bookkeeping, not part
  of the applied automation. HA's automation loader was lenient
  enough to accept the extras but they polluted every applied
  entry's YAML. `AutomationWriter.write()` now calls
  `_strip_private_keys()` first.

## [1.5.33] — 2026-05-15

### Added

- **Per-check signal details surfaced in setup_quality.** Each
  recipe check's detail string ("1 GPS device_tracker(s)", "12 areas
  with ≥1 entity") now lands in `setup_steps[i]['signals']` instead
  of being dropped. Card (v1.2.15) renders them under the GREAT-tier
  badge so users can verify *which* sensors / trackers were matched.
  Setup-URL link now shows at every tier with a verb-swapped label
  ("Manage" at GREAT vs. "Set this up" below).

## [1.5.32] — 2026-05-15

### Fixed

- **Panel resolver prefers HACS path over legacy `/www/`.** The
  integration was registering the sidebar panel from
  `/local/ha-insights-panel.js` (= `/config/www/...`). HACS lands
  the bundle at `/config/www/community/ha-insights-card/...`. Two
  files on disk; integration kept serving the legacy one even when
  it was stale. Resolver now picks the HACS path when present;
  falls back to legacy for manual installs. Cache-buster computes
  off the file actually being served, so HACS users no longer need
  to "Reload UI" / hard-refresh after every plugin update.

## [1.5.31] — 2026-05-15

### Fixed

- **`Automate this?` CTA stripped server-side on shadowed insights.**
  Card v1.2.11 had a client-side strip when `conflicts_with` was
  non-empty, but users reported still seeing the CTA in incognito —
  likely HA service-worker / Lovelace resource-registry caching of
  the compiled template. Server-side strip in `ws_api.py` bypasses
  all client caching; notifications, persistent-notification, mobile
  push, and daily digest all benefit. Card-side strip kept as
  defense in depth (regex no-ops when already stripped).

## [1.5.30] — 2026-05-15

### Fixed

- **Goal-tracking setup-step deeplink** now lands on the HA Insights tile
  (`/config/integrations/integration/ha_insights`) instead of the
  integrations dashboard. The v1.5.17 detour was defensive against a
  reported blank-page issue that no longer reproduces on HA 2023.1+.

## [1.5.29] — 2026-05-15

### Added

- **Goal Tracker targets exposed in OptionsFlow** (Advanced step) as five
  Optional HH:MM string fields: bedtime by, wake up by, leave home by,
  get to work by, home by. The detector has been reading `goals_json`
  since v1.4 but the field was never surfaced — users couldn't actually
  configure goals. Serializes back into the same `goals_json` string the
  detector consumes; manual goals_json setters keep working unchanged.

## [1.5.28] — 2026-05-15

### Added

- **HA 2024.4+ label support.** `ws_api` emits `labels[]` per insight
  from `hierarchy.labels_of` (primary entity's labels, cascading from
  device + area). Pair with companion card v1.2.10 for a Label filter
  chip and `group_by: "label"`. Empty array when no labels OR HA < 2024.4.

## [1.5.27] — 2026-05-14

### Fixed

- **Conflict scanner factors `for:` duration** into state-trigger signatures.
  Two triggers with the same entity + to_state but different `for:` durations
  fire at different times — pre-1.5.27 we matched them as the same signature
  and silently flagged false-positive 🔁 already-automated conflicts.
  Signature is now `set[tuple[entity, to_state, for_seconds]]`.

## [1.5.26] — 2026-05-14

### Added

- **Sun-relative trigger emission** in `streak` + `schedule` detectors.
  When a daily pattern's wall-clock fingerprint tracks sunset / sunrise
  within ±10 min more closely than a fixed time, the proposed automation
  emits `platform: sun` with the correct event + offset instead of
  `platform: time`. Stops the integration from generating clock-time
  YAML for patterns that are clearly photo-period driven.

## [1.5.25] — 2026-05-13

### Fixed

- **Long-silence filter** drops state transitions that follow a > 8h gap
  with no other activity for the same entity. Implicit poll-cycle wake-ups
  (e.g. BYD car virtual-unavailable transitions every 8h) were escaping
  the unavailable-transition filter and polluting daily-pattern detectors.

## [1.5.24] — 2026-05-13

### Fixed

- **Group/scene-aware conflict matching.** Pre-1.5.24 the conflict scanner
  did a literal `set.intersection` of action `entity_id`s, which missed
  the case where an insight targets `light.backyard_garden_lights` (a group)
  and the existing automation targets the individual member lights. The
  scanner now expands both sides via `hierarchy.members_of` before
  intersecting — same intent, different surface form, now matched.

## [1.5.23] — 2026-05-12

### Fixed

- **Cohort dedup bug**: pet feeder entity with no device_id was being
  merged into HA group-light cohorts. `_find_common_container` was
  calling `device_ids.discard(None)` **before** the `len == 1` shared-
  device check, so any set containing `{None, device_A}` collapsed to
  `{device_A}` and incorrectly assigned the orphan to that device.
  Fixed to require `None not in device_ids`.

## [1.5.22] — 2026-05-12

### Fixed

- **URGENT deadlock**: `automation_audit` detector was hanging on
  `/config/integrations/dashboard` (frontend stuck on spinner). Cause:
  `_load_iot_classes` called `async_get_integration` from inside a
  worker thread — HA's loader requires the main event loop. Moved
  iot_class enumeration to `run_all_detectors` on the main loop and
  threaded the map through `DetectorContext`.

## [1.5.18 – 1.5.21] — 2026-05-11

### Added

- **ButtonPressHabitDetector** (v1.5.21, Phase 3 of v1.6 button-press work).
  Pairs `event.*` firings (HA's native button-press abstraction) with
  consequent state changes within a 5s window; emits AUTOMATION_PROPOSAL
  insights with `platform: state` trigger + template condition.
- **Event-type capture** for HA `event.*` entities (v1.5.19–20). The
  state-event buffer records `event_type` so detectors can group button
  presses by which press (`single_press`, `double_press`, etc.) the user
  is actually correlating against.
- **Manual habit detection accepts physical switches** (v1.5.18) when the
  entity belongs to a local integration (Zigbee, Z-Wave, ESPHome, MQTT,
  Hue local bridge). A relay-style smart-switch controlling smart lights
  via button-press is "manual" behavior worth surfacing.

## [1.5.13 – 1.5.17] — 2026-05-10

### Added

- **Cross-integration coupling finding** in automation_audit. Flags
  automations that pair a cloud-polling source with a local-push action
  (Tuya → ZHA, etc.) so users see "this one cloud round-trip is the
  reason your light feels slow".
- **Per-member cohort metadata** (`cohort_member_info` on every insight).
  Each cohort member now carries its own `integration` + `external_source`,
  so the expand/collapse dropdown shows accurate 🔌 / 🏷️ badges per row.

### Fixed

- **Setup-quality reframe** — "Setup health" → "Setup completeness".
  Health framed unset features as failure; completeness frames them
  as steps. Structured `setup_steps` payload + per-step deeplinks.
- **Daily-pattern detectors** (streak, schedule, cooccurrence, seasonality)
  now drop `FROM-unavailable` state transitions across the board, not
  just the recorder rollup path. Centralizes the filter via the new
  `lib/event_filters.py` module (v1.5.16).

## [1.5.0 – 1.5.12] — 2026-05-07 → 2026-05-10

### Added

- **HA event-semantics gotcha filters.** Five subtle classes of HA event
  noise that detectors were treating as signal — all now filtered
  centrally:
  - Gotchas 1–3: `context.id` batch correlation (one user action fans
    out to N entities via groups/scenes; previously counted as N habits)
  - Gotcha 4: template / derived-platform pair drop (state of
    `sensor.derived` mirrors `sensor.source`; both stored, only one
    is the real signal)
  - Gotcha 6: unavailable-transition filter (entity going `unavailable`
    on integration reload is not a user action)
  - Gotcha 8: recorder-vs-live event distinction (long-window detectors
    consume recorder rollups; short-window detectors consume the live
    state-event buffer)
- **`code review` audit fix batches** (v1.5.8–10) — 16 confirmed bugs
  across three batches, ranging from data-loss in option migration to
  broken filter chips to example-data leaking into prod insights.
- **Maturity tier rendering** — every insight now carries a
  `maturity: "stable" | "beta" | "experimental"` field. Card renders
  🟡 BETA / 🧪 EXPERIMENTAL pills accordingly. Pre-HACS demotion of
  four risky detectors (`phone_charge_reminder`, `weather_correlation`,
  `presence_inference`, `routine`) to BETA.

### Fixed

- Bootstrap fan-out filter — HA's startup event burst (every entity
  emits one `state_changed`) was being read as user activity.
- HA group fan-out + slaved-member false positives.
- Explain prompt is now insight-kind-aware (diagnostic framing for
  anomalies, vs proposal framing for patterns).
- Dismiss survives re-scans — re-emitted insights inherit dismissal
  state instead of re-notifying.
- 4 audit-cache staleness bugs (compute_cache_key call-site mismatches).

## [1.4.0] — 2026-05-03

### Added

- **Multi-step OptionsFlow wizard** with refinement-aware intro. New
  users get a guided preset → mobile targets → experimental opt-in
  flow; returning users land on the Advanced form directly.
- **Three-tier detector maturity flag** (`stable` / `beta` / `experimental`)
  with config-time gating via `allow_experimental_detectors`.
- **Try with example data** — fixture-driven insight preview so users
  can see what the integration produces before granting recorder access.
- **PhoneChargeReminderDetector** (BETA) — predicts low-battery wake-up
  windows from charging history; emits a daily mobile notification when
  the user is on track to wake up with < 30%.
- **WeatherCorrelationDetector** (BETA) — pairs OpenWeatherMap (or any
  HA `weather.*` entity) state transitions with downstream actions.
- **Opt-in community analytics** — weekly aggregate counts (detector
  fire/apply/dismiss per maturity tier) to `analytics_endpoint`.
  Off by default; payload contract documented in `analytics.py`.
- **Notify modes** — Basic (Quiet / Balanced / Chatty) + Adaptive +
  Advanced presets. Four anti-spam knobs (confidence floor, daily cap,
  quiet hours, attribution-confidence floor) auto-derived from preset
  unless mode is Advanced.
- **Multi-user notification routing**: `notify.mobile_app_*` multi-select
  picker + per-user policy overrides (Dad gets balanced, Mum gets
  adaptive). Resolved at notification time.
- **Sun-relative triggers** in `ManualHabit` + `Routine` detectors.
- **GoalTrackerDetector** — compare user-defined target times against
  observed phone activity, report adherence over 14 days.
- **SetupQualityDetector** — per-feature setup-completeness scoring
  ("3 things would unlock high-impact detectors").
- **PresenceInferenceDetector** (BETA) — infer per-room occupancy from
  activity concentration when no PIR sensor is wired.
- **RoutineDetector** — bundle multi-entity morning / evening flows
  into one insight ("you turn off 4 things between 22:45 and 23:00").

### Changed

- **OptionsFlow** consolidated to one Advanced form that merges instead
  of replacing options (fixes silent option-drop regression when fields
  not in the form get cleared).

## [1.2.0] — 2026-04-26

### Added

- **Incremental chunked backfill** for large datasets — historical state
  events are paged in 25-entity batches with 60s per-entity timeout and
  120s per-batch budget. Single-flight lock prevents pile-up.
- **Repairs dual-emit** — high-confidence audit findings surface in
  `Settings → Repairs` alongside HA's native issues. HACS feature +
  core-merge bridge: dropping the integration into HA core would lose
  no functionality.
- **v1.2.x smoke suite** — 21 regression guards covering dedup, audit
  packet emission, fix builder, fingerprint stability, store schema
  migration, recorder-window detection.

### Fixed

- **Audit fingerprint stability** — re-scans were duplicating insights
  instead of updating in place; the fingerprint included a timestamp
  field that should have been omitted.
- **Repairs persistence across HA restarts**. Sweep only on uninstall.
- **Dedup bucket signature** now lowercased (`light.MAIN_ROOM` and
  `light.main_room` no longer split into separate cohorts).

## [1.1.0] — 2026-05-12

The audit release. v1.0 was pattern detection on what your home does;
v1.1 is auditing what your automations already say they do.

### Added

- **AutomationAuditDetector** — reads every automation in `automations.yaml`,
  `configuration.yaml`, and package files. Emits an AUTOMATION_IMPROVEMENT
  insight per automation that has anything worth saying. Filtered to high-
  confidence + actionable observation kinds; silent on automations with
  zero findings.
- **Eight observation primitives** (`audit/packet.py`):
  - `long_on_duration` — entity stays on past sensible `for:` thresholds
  - `trigger_time_drift` — `at:` differs from observed transition by >= 5min
  - `entity_silent` — referenced entity is unavailable / missing from state machine
  - `redundant_target` — action targets both a container and members
  - `trace_dormant` — HA traces show no fires in 30d+
  - `trace_condition_blocks` — condition step blocks > 50% of fires
  - `trace_action_errors` — actions throw exceptions in N% of runs
  - `rollup_*` — day-of-week / day-of-month / seasonal patterns
- **HA Automation Traces integration** (`audit/traces.py`) — pulls from
  `hass.data[DATA_TRACE]` directly via the documented internal API
- **Recorder rollup cache** (`audit/rollup.py`) — 90-day day-of-week /
  day-of-month / month-of-year transition counts materialized into a
  new `audit_rollups` SQLite table off the scan loop. Single-flight
  lock, 20s per-entity timeout, 120s batch budget, 7-day TTL. Service:
  `ha_insights.run_audit_rollup`.
- **Deterministic YAML fix builder** (`audit/fixes.py`) — when an
  observation has an obvious safe fix (redundant_target, long_on_duration,
  trigger_time_drift), emit the audit insight with `payload_format="automation"`
  + a pre-computed refined YAML. Apply works without ever calling the LLM.
- **`home_insights/audit_suggest` WS endpoint** — for findings without a
  deterministic fix, route through the existing refine_insight pipeline
  with an AUTHORIZED EDITS block derived from the observations. Content-
  hash cache (30d TTL, 500-entry LRU). Two-stage refinement: pass
  `seed_config` to layer LLM ideas on top of the algorithm's output.
- **Repairs registry dual-emit** (`audit/repairs.py`) — high-confidence
  actionable findings surface in `Settings → Repairs` alongside HA's
  standard issue notifications. Auto-clears on dismiss / apply / purge.
  Translation key `audit_finding` with `{automation}` + `{summary}`
  placeholders.
- **Side-by-side IDE-style diff modal** (card) — LCS line alignment,
  red `-` / green `+` gutters, stage-aware titles + pane labels
  (`Current YAML (live)` → `Algorithm Fix (no LLM)` → `LLM Refinement (stage 2)`),
  phone-responsive (stacked at ≤720px).
- **📋 Preview button** on deterministic-fix audit rows — opens the
  diff modal pre-populated with the algorithm's edit. Zero LLM tokens.
- **🤖 Refine further with LLM** button inside Preview modal —
  layered refinement: algorithm fix as the starting point, optional
  user follow-up text, LLM iterates.
- **Concise / In-depth analysis depth toggle** (panel header) —
  switches the LLM prompt between ~150-token rules and ~600-token
  rules with examples. Persisted in localStorage; per-call override
  via `analysis_depth` field in audit_suggest WS message.
- **OptionsFlow `audit_monthly_budget_usd`** — per-month USD cap on
  background batch suggest. Default $5, range 0..50. Local LLM agents
  bypass the budget gate automatically.
- **Token usage row** in refine modals — shows `≈ X in / Y out tokens`
  estimated via bytes/4.
- **24 unit tests** for the pure dedup + audit packet + fix-builder logic
  in `tests/test_lib_dedup.py`, `tests/test_audit_packet.py`,
  `tests/test_audit_fixes.py`.

### Changed

- **Display-time dedup bucket key** now includes domain — collapses 51
  mixed-domain NVR rows into per-domain cohorts (35 binary_sensors +
  11 switches → 2 cohort rows).
- **Scan-time dedup** no longer short-circuits when `entity_dependencies`
  is empty (regression introduced during v1.2 hierarchy migration).
- **Display-time dedup extracted to `lib/dedup.py`** as pure functions
  with no HA imports. ws_api wraps with a thin registry walker.
- **Refine prompts** rebuilt with per-use-case framing + AUTHORIZED
  EDITS list derived from observations or user request, replacing
  the universal "never remove entities" rule. LLM gets a specific
  list of authorized changes per call.
- **Refiner post-processing** preserves `id:`, `mode:`, `max:`,
  `initial_state:`, `trace:`, `variables:` from the original (LLMs
  drop them). Normalises `action:` vs `service:` key style.
- **Rationale dereferences pseudonyms** before display — prior bug
  surfaced `light.entity_1y3s70` to users instead of the real entity.
- **Sidebar panel re-registers** on every config-entry setup so the
  cache-bust URL refreshes (previous bug locked it to first-startup
  mtime, requiring a full HA restart to deploy new bundles).
- **`ha_insights.reload_ui` service + 🔄 Reload UI button** — bumps
  the panel URL + force-reloads the tab so a deploy-and-test cycle
  takes seconds, not an HA restart.

### Fixed

- 51 NVR cameras silent for 8 days now collapse to 2 cohort rows
  (one per domain) instead of 51 individual insights.
- `_eids_for_dedup` internal field stripped from every outbound dict.
- PyYAML can no longer raise `RepresenterError("cannot represent an
  object", "id")` on automation raw_configs — every site sanitises
  through `json.dumps(..., default=str)` first.
- `home_insights/audit_suggest` no longer crashes with
  `AttributeError: 'AttemptAudit' object has no attribute 'to_dict'`.
- `home_insights/get_automation` walks packages + `configuration.yaml`,
  not just `automations.yaml`, so package-defined automations are
  reachable.
- Stage-two refines force concise depth so Gemini's `max_output_tokens`
  budget covers the YAML rewrite.

### Security

- Repairs registry entries respect blocked_entities (per-automation
  audits skipped entirely when all entities are blocked).
- Audit suggest cache key includes content hashes; no raw payloads stored.
- LLM response rationale dereferenced before storage in the audit log.

## [1.0.0] — 2026-04-26

Initial public release. Pattern detection, multi-turn LLM Refine, multi-
config-entry, full privacy posture. Detail below.

### Security & resilience hardening (v1.0 review)

A multi-agent code review surfaced 22 findings across privacy, security, concurrency, resource management, and code quality. The following landed before v1.0 tagging:

- **Admin gate on destructive WS handlers** (review #1). `apply`, `undo`, `purge_all`, `test_actions`, `_dev/inject_event`, `explain`, `refine`, `hypothesize` now require `connection.user.is_admin`. Read-only endpoints stay open so non-admin frontend users can still view + dismiss/snooze. Regression test parametrizes both buckets.
- **Per-attempt audit logging** (#2). Failover walks multiple agents; each round-trip MUST hit the privacy log. `ExplanationResult.attempts` and `RefinementResult.attempts` accumulate `AttemptAudit` rows, WS handlers iterate via new `_audit_attempts` helper. Closes a privacy hole where earlier failed attempts disappeared from `outbound_calls`.
- **Custom-detector sandbox** (#3). `CONF_ALLOW_USER_DETECTORS` defaults to False (opt-in gate); even when on, the loader AST-scans every file and rejects modules importing `os/subprocess/socket/urllib/urllib3/http/requests/httpx/aiohttp/websocket(s)/ftplib/smtplib/telnetlib/imaplib/poplib/shutil/tempfile/fcntl/termios/pwd/grp/spwd/ctypes/cffi/pickle/marshal/shelve/code/codeop` or using `__import__/__builtins__/eval/exec/compile`. 15 parametrized rejection tests. Unsandboxed `exec_module` was an RCE-on-config-write.
- **Blocking imports off the event loop** (#4). `pkgutil.iter_modules` + `importlib.import_module` in `_autoload_detectors` now run via `hass.async_add_executor_job` once per HA boot. HA's blocking-call detector no longer fires on every cold start.
- **Backfill task cancellation on entry unload** (#5). Captured as `entry_data["backfill_task"]`; `async_unload_entry` cancels + awaits before closing the store. A reload mid-backfill no longer leaks a coroutine writing to a popped buffer.
- **Store leak guard on partial setup failure** (#6). `async_setup_entry` body wrapped in try/except → `store.close()` + reraise. Multi-entry reload-on-error otherwise stacked open SQLite handles.
- **`SUPPORTED_METHODS` matches actual `async_register_command` calls** (#7). Three live endpoints (`hypothesize`, `refine_cost_estimate`, `list_entries`) were missing from the feature-detection tuple. New regression test parses ws_api.py source and asserts the two stay in lockstep.
- **PII deref in agent error messages** (#8). When an LLM returns an error and echoes the prompt, real entity_ids round-trip through `redaction_map.dereference` so the user sees their real names in the WS reply, not `light.entity_xxx`. Same for `raw_response` debug output.
- **Pseudonym map invalidated on entity remove** (#9). New `entity_registry "remove"` action handler calls `store.delete_entity_pseudonym(entity_id)` so a re-created entity_id doesn't inherit a deleted entity's pseudonym.
- **Per-store apply lock** (#10). `InsightStore.apply_lock` (asyncio.Lock) wraps `validate → write → record_applied` in `ws_apply` and `get_history → drift → delete → clear_applied` in `ws_undo`. Two near-simultaneous applies on overlapping entities can no longer race in `automations.yaml`.
- **Panel registration off the event loop** (#11). `_async_register_panel` is now async; `os.path.getmtime` runs via `hass.async_add_executor_job`.
- **Entry-bound background tasks** (#12). The notify, rename-pseudonym, and delete-pseudonym tasks now use `entry.async_create_background_task` so HA auto-cancels them on unload.
- **State event buffer count cap** (#13). `DEFAULT_MAX_EVENTS = 500_000` (~50 MB of `StateEvent` objects); deque(maxlen) gives silent oldest-drop, one-shot WARNING when the cap engages so the user knows their effective lookback is being trimmed by volume.
- **Refiner / agent_client failure factory** (#14). `RefinementResult.failure(...)` and `ExplanationResult.failure(...)` classmethods collapse 12 nearly-identical failure-branch constructors into named-arg call sites. Each site now shows only the fields that actually differ per failure path.
- **Multi-entry strings drift** (#16). `preferred_agent_id` and `refine_cost_threshold_usd` descriptions in `strings.json` + EN + DE now note the cross-entry combination semantics (first non-empty preference wins; lowest threshold wins).
- **Documentation: preferred-agent first-wins** (#17). Same description update covers the surprising semantics; real entry_id-aware routing through every WS command remains a v1.1 follow-up.
- **Dropped dead `_pick_llm_agent_id`** (#18). 33 LOC, no callers, superseded by `_list_agent_candidates` in v0.9 phase 7.
- **Drift detection regression tests** (#19). 6 cases asserting volatile-field stripping (anything `_`-prefixed) and dict-iteration-order independence.

### Deferred to v1.1

- **`ws_api.py` extraction** (#15). 1,245 LOC, 19 handlers — natural splits along CRUD / LLM proxy / diagnostics already visible. Pure structural refactor; no correctness/security implications. Tracked for v1.1 alongside per-WS-call `entry_id` routing.
- **Digest cross-restart catch-up** (#20). Today's digest is missed if HA is down at the trigger hour. Persistent state (`last_digest_at`) tracking + startup catch-up logic deferred — workaround is to lower `digest_hour` to before HA's typical restart window.

### Added

- **Refine cost confirmation (RC #1).** New `home_insights/refine_cost_estimate` WS endpoint redacts the payload, builds the same prompt `refine_insight` would, resolves the target agent, and returns a token + USD estimate without calling the LLM. Card pre-flights this before every Refine; if cost exceeds `CONF_REFINE_COST_THRESHOLD_USD` (default $0.05) and the agent is cloud, shows a confirm dialog. Local agents always cost $0 and never trigger the confirm.
- **Multi-turn Refine (RC #2).** Threads HA's `conversation_id` through `refine_insight` so consecutive Refines on the same insight maintain agent context. Card stores `_refineConversationById` per-insight, sends it on follow-up calls, captures the new id from each response. Failover safety: `conversation_id` is dropped on attempt 2+ to a different agent. Apply / Keep Original auto-clear the thread; new "🔁 Reset conversation" button clears manually.
- **Custom detector loading (RC #3).** Drop a `*.py` into `<config>/ha_insights_detectors/` and it autoloads at integration setup. Each module loads in isolation (per-module try/except), prefixed with `ha_insights_user.*` in `sys.modules` so a user `schedule.py` can't shadow our built-in `ScheduleDetector`. Underscore-prefixed files are skipped; helper modules without a `Detector` subclass are tolerated.
- **Preferred-agent dropdown polish (RC #4).** Each option now reads `[platform] Friendly name (entity_id)` so users with multiple Anthropic and OpenAI models can disambiguate at a glance.
- **i18n (RC #5).** German translations + expanded English baseline. Every OptionsFlow field now has both a label (`data`) and a help-text under it (`data_description`) explaining what the setting does. `strings.json`, `translations/en.json`, and `translations/de.json` ship the same key set.
- **mkdocs site (RC #6).** `mkdocs.yml` with mkdocs-material, navigation linking the existing `docs/*.md`. New `docs/index.md` landing page. `.github/workflows/docs.yml` builds with `--strict` (fails on broken links) and publishes to `gh-pages` on every push to main. Site goes live at `botts7.github.io/ha-insights` once the repo flips public + Pages is enabled.
- **Multi-config-entry support (RC #7).** Drops the unique_id-based abort so users can add a second entry — useful for separate area filters, different lookback windows, or pinning different LLM agents per scope. Each entry runs an independent store / buffer / sensor / digest. New `home_insights/list_entries` WS endpoint enumerates active entries. `_get_store` / `_get_buffer` accept an optional `entry_id`; default routes to the first entry for card backwards compatibility. Per-WS-call `entry_id` routing through every command + a card picker remains a v1.1 follow-up.

### Fixed

- **`hassfest` Validate workflow.** `manifest.json` now declares `recorder` (and `conversation`, `frontend`) in `after_dependencies`, fixing a long-standing hassfest error introduced when recorder backfill landed in v0.6.

### Internal

- Manifest version bumped from `0.8.2` to `0.9.0` to match the v0.9.0 release tag.
- `RefinementResult.conversation_id` and `ExplanationResult.chosen_agent_id` now ride through the WS surface so the audit log records the agent that actually responded after failover.

## [0.9.0] — 2026-05-10

Smart Features release. Tagged on both repos. See `git log` for the breakdown across the 9 phases (1A-1C, 2, 4-9).

## [0.8.2] — 2026-05-10

Refine + apply pipeline fixes from live testing, plus a comprehensive e2e harness.

### Fixed

- **`test_actions` unwraps the `data:` action key.** Actions like `{service: persistent_notification.create, data: {title, message}}` were being passed to `hass.services.async_call` with `service_data = {"data": {...}}`, producing the `extra keys not allowed @ data['data']` validator error. The handler now flattens `action["data"]` into `service_data` so both shapes work — flat (`{service, key1, key2}`) and wrapped (`{service, data: {key1, key2}}`).
- **Refiner distinguishes service names from entity_ids.** `_collect_entity_ids` now walks the payload structurally and only matches strings reached through `entity_id` / `entity_ids` keys. New service introductions like `light.turn_off` (when the original used `light.turn_on`) no longer false-positive as "hallucinated entities".
- **Refiner backfills the `description` field** when the LLM drops it (which they routinely do). Prefers the LLM's rationale (more useful than the detector-generated original — it explains what changed); falls through to the original when no rationale is available. The diff now reads `~ description` (changed) instead of `- description` (removed).

### Added

- **`dev/_e2e_smoke.py`** — comprehensive end-to-end smoke harness. Drives the live dev HA over WebSocket, runs 30 scenarios including all previously-debugged regressions (data: key unwrap, Layer 2 unknown platform, undo round-trip, refine round-trip, service-vs-entity distinction). LLM scenarios self-skip when privacy mode is OFF. UTF-8 stdout reconfigure so the ✓/✗ markers render on Windows cmd.

## [0.8.1] — 2026-05-10

Apply pipeline polish: bulk apply, payload editor, refine progress.

### Added (in companion card v0.8.1)

- **Inline payload editor** — `✎ Edit` button on the modal swaps the read-only `<pre>` for a `<textarea>` with the JSON payload. Edits flow through `home_insights/apply` via the existing `payload_override` plumbing — same Layer 1 + Layer 2 validators on the server. Parse errors surface inline; modal stays open for the fix.
- **Bulk apply in panel** — `✓ Apply all visible` button iterates the panel's currently-filtered list and applies each as a real HA automation. Confirms first; toast summarizes the result. Bulk applies use the original detected payload only (no per-insight refined / renamed / edited drafts).
- **LLM-busy pulse animation** — Refine + Explain buttons now pulse while in flight (1.4s ease-in-out opacity) and label `💭 thinking…` / `💭 refining…` instead of static text. Replaces "asking LLM…" with something visibly alive during the 5-15s LLM round-trip.

### Changed

- `INTEGRATION_VERSION` bumped to `0.8.1`.

## [0.8.0] — 2026-05-10

Apply pipeline gains undo + a second validation layer.

### Added

- **`home_insights/undo`** WS endpoint — reverses a previous apply: looks up `applied_history`, reads the current YAML via `AutomationWriter`, runs `detect_drift` against the snapshot, deletes the automation, and clears applied state. Refuses on drift unless `force=true` so user edits aren't silently lost.
- **`Insight.applied_at` / `applied_artifact_id` / `undo_window_expires_at`** fields — applied state now flows through the WS list/get response, so cards can show "applied 2h ago" + an Undo button without a separate lookup. `_row_to_insight` LEFT JOINs `applied_history` for the undo window.
- **`InsightStore.clear_applied(insight_id)`** — drops the applied_history row + clears the markers on the insights row + fires the new `undone` subscribe event.
- **Layer 2 online validator** (`apply/online_validator.py`) — wraps HA's automation config validator (services, entities, trigger/condition/action shapes) and runs after Layer 1 in `ws_apply`. Catches things like an unknown trigger platform before we write to `automations.yaml`. Returns `code: "ha_validation_failed"` with the actual reason when the validator rejects.

### Changed

- `subscribe` now emits `action: "undone"` events when an applied insight is reversed.

## [0.7.0] — 2026-05-09

Three new detectors. The library doubles in a single release.

### Added

- **`LongTailDetector`** — finds entities that stay active longer than expected (porch light all night, fan running 6hr). Walks the rolling buffer for active spans (`on` / `playing` / `open` / `unlocked` / `active` / `home`), filters by per-domain threshold (light 90min, switch/fan 120min, media_player 240min, input_boolean 120min), surfaces patterns of ≥3 long-tails as an `AUTOMATION_PROPOSAL` with an auto-off `state for: <threshold>` trigger.
- **`OrphanDeviceDetector`** — flags entities silent for >7 days. Requires ≥3 prior events in the lookback window so newly-added entities don't fire. Emits `ANOMALY` with a notify-when-back-online automation (apply-able if user wants the ping).
- **`StreakDetector`** — emerging-routine detector. Lower bar than `ScheduleDetector`: fires on ≥3 consecutive days of the same entity → state at roughly the same time-of-day (stddev ≤30 min, looser than Schedule's 8). Skips groups that already meet ScheduleDetector's bar so the stronger detector owns those.

### Changed

- `INTEGRATION_VERSION` bumped to `0.7.0` so cards on `0.6.x` see the version skew via the `home_insights/hello` handshake.

## [0.6.0] — 2026-05-09

Trust & visibility — privacy posture is now tangible, not just documented.

### Added

- **Per-entity LLM opt-out** — new `CONF_LLM_BLOCK_ENTITIES` config option. Listed entity_ids never reach an LLM in any form: real values become `[blocked]`, list entries are filtered, free-text mentions are masked. Privacy floor below the existing mode-driven redaction.
- **`home_insights/redaction_preview` WS endpoint** — runs the redactor pipeline on a given insight without calling any LLM. Returns the exact dict that would be embedded in the prompt, plus pseudonym map, attributes stripped, and entities blocked. Fuels the card's "What gets sent?" button.
- **`home_insights/audit_log` WS endpoint** — returns recent rows from the existing `outbound_calls` table joined to `insights` for titles. Default limit 50, clamped 1-500.
- **`InsightStore.get_outbound_calls(limit)`** helper — joins outbound_calls to insights so deleted-but-still-audited entries show as `[deleted <id>]` rather than disappearing.
- **`RedactionMap.entities_blocked: list[str]`** — tracks per-call which opt-out entities were actually stripped, so the card preview can show a count.

### Changed

- `Redactor` constructor accepts `blocked_entities: frozenset[str]`. Existing call sites in `ws_explain` and `ws_refine` resolve the union across active config entries before constructing the redactor.

### Deferred to v0.6.1
- Per-entity opt-out config UI in the OptionsFlow (today's release supports it via `data` / `options` only)
- HACS distribution prep (READMEs, brand assets, default-store PR)

## [0.5.1] — 2026-05-09

Refine pipeline polish — better error surfaces, follow-up feedback support, panel cache busting.

### Added

- **`INSUFFICIENT_BUDGET` self-signal** — refine prompt now instructs the LLM to output a single `INSUFFICIENT_BUDGET` line if it cannot produce a complete refinement within its token budget, instead of starting a YAML it can't finish. Refiner detects the marker and surfaces a friendly "increase max_output_tokens" message before any parsing.
- **`feedback` parameter on `home_insights/refine`** — optional string that becomes the highest-priority considerations block in the prompt. Lets users iterate ("also add a sun condition") without re-typing the whole context. Redacted before being sent to the LLM, just like the rest of the payload.
- **Panel `module_url` cache busting** — file mtime is appended as a `?v=…` query so HA's 31-day static-cache header doesn't hold a stale build forever. "Deploy new panel.js + restart HA" now reliably propagates without DevTools cache-disable.

### Changed

- **Tighter truncation detection** — `_looks_truncated` now also flags trailing colons (key opened, no value), bare indented identifiers (e.g. `    target` mid-emit), and missing `mode:` block (our prompt always asks for it as the final key). `_looks_structurally_incomplete` catches parse-success-validation-fail cases where action is missing while trigger is present (the canonical mid-emit cutoff for LLMs).
- **Refusal detection** — refiner detects model-side safety / policy refusals (`I cannot help`, `I'm unable`, `as an AI`, etc) and surfaces a clear "LLM declined to refine" error with provider-agnostic guidance, instead of "missing YAML section."
- **`refine_failed` errors include the raw LLM response** (truncated to 600 chars). Lets users see exactly where the LLM stopped, copy/paste into a different agent for testing, or report the issue cleanly.

## [0.5.0] — 2026-05-09

Sidebar panel ships. Surfaces a dedicated full-page insights view alongside the dashboard card.

### Added

- **Sidebar panel registration** — integration registers `frontend_url_path="ha-insights"` with `mdi:chart-arc` icon and title "Insights" via `frontend.async_register_built_in_panel`. Loads `/local/ha-insights-panel.js` (shipped by the companion card repo). Cleaned up on last config-entry unload.

### Changed

- `INTEGRATION_VERSION` bumped to `0.5.0` so cards on `0.4.x` see the version skew via the `home_insights/hello` handshake (no behavior change; cards stay backwards-compatible).

## [0.4.0] — 2026-05-09

Day-one onboarding shipped — the integration now backfills the StateEventBuffer from HA's recorder on install, so detectors find routines immediately instead of after a 1-2 week buffer fill.

### Added

- **`observers/history_backfill.py`** — async `backfill(hass, buffer, lookback_days, allowed_domains)` that pulls significant states from HA's recorder for the configured window and streams them into the rolling buffer. Domain allowlist (`light, switch, binary_sensor, fan, climate, cover, lock, media_player, input_boolean, input_select, input_number, scene, script`) excludes diagnostic/stats/weather entities that don't carry behavioral signal. Skips `unavailable` / `unknown` states; chains `old_state` across consecutive events for transition detection.
- **Auto-on-setup backfill** — `async_setup_entry` schedules the backfill as a background task so setup doesn't block. Buffer's `max_age` is widened to match `lookback_days` so backfilled events aren't immediately pruned.
- **`ha_insights.backfill` service** — manual re-run with optional `lookback_days` override. Surfaces in HA's UI with a slider selector (1-30).
- **`CONF_LOOKBACK_DAYS` config option** — 0-30 days, default 14. 0 disables backfill entirely. Configurable via initial flow + OptionsFlow. `get_lookback_days()` helper clamps invalid values.
- **`home_insights/backfill_status` WS endpoint** — returns `{running, last}` for the active config entry. Companion card uses this on connect to surface a one-shot toast (`"Backfilled N events from K entities (Dd)"`) only when a recent run actually ingested data.

### Changed

- `OptionsFlow` no longer sets `self.config_entry` explicitly (HA 2025.12 made it a read-only property; was previously deprecated, now hard error).

### Compatibility

- Requires HA recorder enabled (the default). Disabling the recorder makes backfill a no-op; live event capture still works.

## [0.3.0] — 2026-05-09

Refine + Co-occurrence detector + better Test actions feedback. Live-verified end-to-end against Google Gemini.

### Added

- **`CooccurrenceDetector`** — finds "entity B follows entity A within N seconds" patterns over the rolling state buffer. Common case: porch light comes on shortly after front door opens. 30s sliding window, requires ≥5 occurrences with timing stddev ≤12s and ≥60% leader-follower consistency. Emits an `AUTOMATION_PROPOSAL` with a state-trigger automation payload. Inherits the same default-blocked-domain rules (camera/person/tracker/lock) from the Detector ABC.
- **`home_insights/refine` WS endpoint** — user-initiated LLM refinement of an automation insight. Pseudonymizes the payload, calls the configured Conversation agent with a structured `RATIONALE: / YAML:` prompt, parses + dereferences pseudonyms, validates shape, and validates that the entity-id set is a subset of the original (rejects hallucinated entities). Returns refined_payload + rationale + diff_summary. Does NOT mutate the insight — the card holds the preview locally and applies via `home_insights/apply` with `payload_override` if the user accepts.
- **`payload_override` on `home_insights/apply`** — apply a refined automation in place of the original. The override is validated identically and stamped with `description: "Refined by HA Insights"` so the lineage shows in HA's automation editor.
- **`home_insights/test_actions` WS endpoint** — fires the action block of an insight without saving the automation. Mirrors HA's "Run Actions" button. Iterates `payload['action']`, skips non-service actions (delay/choose/etc), calls each via `hass.services.async_call`, returns per-action results with `ran` / `error_count` summary. Accepts `payload_override` so users can test a refined version before applying.
- **Truncation-aware refine error** — when the LLM hits its `max_output_tokens` mid-YAML, the refiner detects the unterminated quote/bracket pattern and surfaces a user-actionable error pointing to the LLM Conversation integration's max-tokens setting, instead of a raw YAML parser exception.

### Deferred to v0.4

- HA Blueprint emission (raw-automation apply path works end-to-end).
- Recorder backfill for day-one onboarding (insights immediately on install instead of after a 1-2 week buffer fill).
- Dedicated insights sidebar panel.

## [0.2.0] — 2026-05-09

LLM Explain feature shipped — privacy-first LLM enrichment via HA's Conversation API. Live-verified end-to-end against Google Gemini.

### Added

- **LLM Explain feature** — `home_insights/explain` WS command redacts the insight payload, calls a configured Conversation agent (Anthropic / OpenAI / Google AI / Ollama), dereferences pseudonyms in the response back to real entity_ids, persists the explanation onto the insight, fires `explained` subscribe event.
- **Privacy redactor** (`llm/redactor.py`) with mode-aware behavior. Always-redacted attributes — GPS / MAC / IP / tokens / passwords / serial — stripped regardless of mode. Stable pseudonyms via `pseudonym_map` so the LLM sees consistent identifiers across calls.
- **Auto-pick LLM agent** — scans the entity registry on every Explain call, finds any installed LLM Conversation integration, falls back to HA's default agent only if no LLM is installed.
- **Privacy log sensor** — `sensor.ha_insights_privacy_log` exposes trailing-24h call count, bytes-sent/received, last-call timestamp, last-agent name. Diagnostic category, mdi:shield-eye icon.
- **OptionsFlow** for in-place mode switching (Off ↔ Local ↔ Cloud) without removing + re-adding the integration. Switching INTO Cloud re-prompts the data-flow consent dialog.
- **`home_insights/hello` returns `privacy_mode`** so cards can render the active mode.
- **Differentiated error surfaces**: LLM agent errors show the agent's actual response (rate limit, deprecated model, invalid key); rule-based fallback shows install instructions for an LLM Conversation integration.

### Changed

- `home_insights/list` defaults: now excludes applied insights too (`include_applied=false`). Snoozed insights filtered when `snoozed_until > now`.

### Fixed

- `AutomationWriter` writes to `<config>/automations.yaml` (the canonical user-editable file HA's `automation.reload` re-reads), not `.storage/automations` which the automation domain doesn't read for runtime registration.

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
