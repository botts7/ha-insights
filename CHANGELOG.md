# Changelog

All notable changes to this project are documented in this file. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.24.0] — 2026-07-09

### Added — `critical_device_offline` detector (BETA)

Fast-path ANOMALY insight when a *load-bearing* device goes fully
offline (every eligible entity `unavailable`) for 1+ hour — devices
with entities referenced by automations (confidence 0.90, clears the
mobile-push floor) or exposing actuator entities (0.80, panel +
persistent notification).

Field-motivated: a Shelly 2.5 wall switch in decoupled mode wedged
overnight (2026-07-09). Its relay stayed latched so the lights kept
working from HA, but the wall button — forwarded via the HA API —
silently died. `unavailable_device_fixit` would have flagged it 47
hours later; its 48 h gate is right for "long-broken junk" triage
and wrong for "something you rely on is down NOW".

Device-level (fingerprint = device_id), one insight per device;
`cohort_dedup = False` — each offline device is its own incident.
Pure sensors nobody automates on stay with the 48 h slow path.

## [1.23.4] — 2026-05-23

### Added — Per-group collapse/expand (bundled card v1.10.20)

Re-bundles `static/panel.js` from card v1.10.20. Closes Task #242
from the original "Showing 200 of 788" conversation.

With **Group by** set to anything other than "None" (Detector,
Area, Floor, Integration, Label), any section with >5 items now
starts collapsed showing only the top 5, with a clickable header
chevron + a "Show all N ▾" footer button.

To get the triage view, set Group by → Detector. Each detector
becomes a collapsed top-5 stack; click into the noisy ones, leave
the rest alone.

No backend changes — pure card-side UX.

## [1.23.3] — 2026-05-23

### Fixed — Extend already-automated check to remaining auto-emitting detectors

v1.22.4 added the `ctx.entities_already_automated` check to
`ManualHabitDetector` + `LongTailDetector`. The other detectors
that emit `payload_format="automation"` still didn't check.
Preemptive sweep before another field report surfaces it.

| Detector | Rule |
|---|---|
| `StreakDetector` | skip if `entity_id` is already automated (single-entity) |
| `ScheduleDetector` | skip if `entity_id` is already automated (single-entity) |
| `CooccurrenceDetector` | skip if **follower** entity is already automated (pair → automation acts on follower) |
| `ButtonPressHabitDetector` | skip if **consequent** entity is already automated (event → action on consequent) |
| `RoutineDetector` | drop already-automated pairs from the routine bundle; skip the whole routine if too few remain |

`LaggedCorrelationDetector` stays unchanged — its existing
`MIN_OCCURRENCES` + `MIN_CONFIDENCE_TO_EMIT` already filter
sparse signals.

Same rationale as v1.22.4: when a user already has an automation
acting on an entity, the duplicate suggestion is noise — they've
thought about it.

## [1.23.2] — 2026-05-23

### Fixed — Day-1 noise: warmup clamp on rolling-baseline detectors

From Discussion #104 (dziban303). Rolling-baseline detectors
(FrequencyAnomaly, Seasonality, StateShift, LaggedCorrelation)
compare today's behaviour to a multi-day baseline. On a fresh
install with <1 day of data, every event looks "anomalous"
because there's no baseline to compare against — the user sees
hundreds of insights that quiet down once data accumulates.

### What lands

New `data_span_days()` on `StateEventBuffer` + `_FrozenBufferView`
returns the gap between the earliest buffered event and now. Each
of the four rolling-baseline detectors now has a
`MIN_DATA_DAYS_FOR_EMIT` class attribute and gates its `scan()`:

| Detector | Min days |
|---|---|
| `FrequencyAnomalyDetector` | 7 |
| `StateShiftDetector` | 7 |
| `SeasonalityDetector` | 14 (needs ≥2 weekly cycles) |

`LaggedCorrelationDetector` doesn't get a day-span gate — its
existing `MIN_OCCURRENCES` per-pair + `MIN_CONFIDENCE_TO_EMIT`
already filter sparse signals out, so day-1 flood doesn't reach
it regardless.

When the buffer's data span is below the gate, the detector
returns `[]` silently (no insights, no log spam). Once the buffer
matures past the threshold, normal scanning resumes.

`isinstance(span, (int, float))` guard protects tests passing
MagicMock buffers from spurious comparison results.

### Added — Verdict-action tooltips (bundled card v1.10.19)

Tooltips on Dismiss / Snooze / Retire / Suppress Device
explaining the three-tier lifecycle. From the same Discussion
#104 — actions were visually indistinguishable buttons; only
Retire had a tooltip.

## [1.23.1] — 2026-05-23

### Fixed — "Load 200 more" button truly works now

The fix shipped in card v1.10.17 (cache-key split so pagination
bumps don't trigger the filter-reset branch) only reached users
who installed the standalone ha-insights-card via HACS. **Panel
users got their `panel.js` bundled inside the integration** — and
the integration was still shipping v1.10.16's buggy `panel.js`
(last refreshed in v1.21.4).

v1.23.1 re-bundles `static/panel.js` from card v1.10.18, which
contains:

- The v1.10.17 pagination-cache fix (so Load-more actually loads
  more)
- The v1.10.18 "Dismiss all visible" / "Retire all visible"
  toolbar buttons (paired with the v1.23.0 WS handlers)

### Lesson learned

Adding to the pre-flight checklist: **whenever a card-side fix
lands, the integration also needs a re-bundle release**. Currently
this is manual (no CI step pulls the latest card release into the
integration). Tracking as a backlog item to automate.

## [1.23.0] — 2026-05-23

### Added — bulk dismiss / retire WS handlers

Discussion #104 (dziban303): user had 105 Uptime-Kuma noise items
to clear one click at a time. Mirror of the existing per-id
`home_insights/dismiss` and `home_insights/retire` operations as a
batch.

#### `home_insights/bulk_dismiss`
- Body: `{insight_ids: list[str]}`
- Returns: `{dismissed: int, not_found: list[str]}`
- Admin-gated (destructive). Each successful dismiss writes a
  `dismissed` verdict to user-verdict-history AND clears the
  mirrored HA Repairs issue if one existed. Single bad id doesn't
  abort the batch — surfaces as a `not_found` entry instead.

#### `home_insights/bulk_retire`
- Body: `{insight_ids: list[str]}`
- Returns: `{retired: int, not_found: list[str]}`
- Admin-gated. Each successful retire writes a `retired` verdict.
  Retire is the harder of the two (permanent "don't auto-suggest"
  per fingerprint), so the card should confirm intent before
  invoking this for a large batch.

Each handler validates input via voluptuous, swallows per-id
exceptions to keep the batch moving, and reports the full summary
in the single result so the card can show "97 dismissed, 8 not
found" without a second round-trip.

Card-side "Dismiss all visible" / "Retire all visible" toolbar
buttons land in card v1.10.18.

## [1.22.4] — 2026-05-23

### Fixed — Quietude pass from Discussion #104 field report

Two unrelated sources of noise reported by @dziban303 after a few
days of real-install use:

#### 1. Buttons stuck at "unknown" treated as unavailable

`button.*`, `event.*`, `input_button.*`, `tag.*` entities have
`"unknown"` as their NORMAL pre-activation state — a never-pressed
button is fine, not broken. v1.14.0's UnavailableDeviceFixIt
treated `state in {"unavailable", "unknown"}` uniformly and emitted
"unavailable for 8 days — diagnose connection" for every untouched
button on the install.

Fix: new `_DOMAINS_UNKNOWN_IS_NORMAL` frozenset in
`unavailable_device_fixit.py`. For these domains we still flag
genuine `"unavailable"` (the integration is broken), but skip
`"unknown"` (the entity just hasn't been activated yet).

#### 2. Already-automated entities still being suggested

Field report: `manual_habit` and `long_tail` were suggesting "add
an automation for this light" for lights the user already had
automations for. The user takes their existing automation as a
sign they've already thought about how the entity should be
controlled — a new auto-generated automation feels redundant.

Fix: pre-compute `entities_already_automated: frozenset[str]`
once per scan (in `detectors/__init__.py`'s `run_all_detectors`
helper) by walking every existing automation's `action` block.
Wire into `DetectorContext` so any detector emitting
`payload_format="automation"` can consult it before emit.

Applied to:
- `LongTailDetector`: skip outright when entity is already
  automated.
- `ManualHabitDetector`: skip outright (in addition to the
  existing time-bucket signature check, which only caught matches
  at the same time-of-day).

Other automation-emitting detectors (`cooccurrence`,
`button_press_habit`, `lagged_correlation`, `streak`) remain
unchanged for now — those produce pairwise / cross-entity rules
where "already automated" is fuzzier. Will revisit case-by-case
if real-install reports show similar noise.

## [1.22.3] — 2026-05-20

### Fixed — Companion-app Wi-Fi signal sensors invisible to find

Real-install diagnostic from user 2026-05-20 (continuation of
v1.22.2): the user has the HA Companion app installed on their
phone, with the "WiFi Signal Strength" auto-sensor enabled. That
sensor is named `sensor.<device>_wifi_signal_strength` and reports
a working dBm value (unlike the Omada path which is stuck at
"unknown").

**The bug:** v1.21.2 / v1.22.2 used `rsplit("_", 1)[-1]` to
extract the last segment of the entity name and checked it against
a set of single-word suffixes (`signal`, `rssi`, `bssid`, ...).
For `sensor.dans_s23_wifi_signal_strength`, the last single
segment is `"strength"` — which wasn't in any recognised set, so
the Companion app's signal sensor was **completely invisible** to
the sister-merge logic. Even after the v1.22.2 trackable-pending
fix, picking the Companion-app device_tracker would still show
"not trackable" because no signal sensor matched.

### The fix

Introduced `_match_name_suffix` — a pure module-level helper that
matches multi-word entity-name suffix patterns, longest-first.

Recognised signal suffixes (mapped to canonical capability keys):
- `wifi_signal_strength_dbm` → `signal_strength`
- `wifi_signal_strength` → `signal_strength`   ← Companion app
- `signal_strength` → `signal_strength`
- `wifi_signal` → `signal_strength`
- `rx_signal` → `rx_rssi`
- `tx_signal` → `signal_strength`
- `rssi` → `rssi`
- `signal` → `signal`

Recognised AP suffixes:
- `wifi_bssid` → `bssid`   ← Companion app (when enabled)
- `wifi_connection` → `ap_name`   ← Companion app
- `access_point` → `access_point`
- `bssid` → `bssid`
- `ap` → `access_point`

Ordering matters — listed longest-first so `wifi_signal_strength`
matches before a hypothetical bare `_strength` rule would. The
"strength" single-word suffix is intentionally NOT in the list
(too generic — would false-positive on user custom sensors).

### What the user should do

If they enable the **WiFi BSSID** auto-sensor in the Companion app
(Settings → Companion app → Manage Sensors), the Companion-app
device_tracker will become a fully trackable Wi-Fi find candidate
on its own — completely independent of the Omada controller's
per-client-stats polling state. This is actually the more reliable
path for walking-find: phone-resident readings, no controller
config dependency, faster update cadence.

### Tests

New `tests/test_wifi_find_name_matcher.py` (16 cases):
- Companion-app naming variants (signal_strength, _dbm, bssid,
  connection)
- UniFi / Omada naming (`rx_signal`, `rssi`, `access_point`)
- Longest-first ordering verification
- Exact-match edge cases (`sensor.rssi` etc.)
- Non-match cases (battery, temperature, lone `strength`)

## [1.22.2] — 2026-05-20

### Fixed — Wi-Fi mode hidden when RSSI sensor exists but has unknown state

Real-install diagnostic: user has zachcheatham/ha-omada installed,
`device_tracker.<phone>` has `ap_mac` + `ap_name` populated, sister
`sensor.<phone>_rssi` exists — but the RSSI sensor's current state
is `"unknown"` because the Omada controller's per-client statistics
poll hasn't fired yet. v1.21.2's heuristic correctly skips "unknown"
states (so we don't promote garbage to a numeric attribute), but
that caused the trackability check to return False overall,
hiding the Wi-Fi mode button.

### The fix

`_collect_device_state_attrs` now also returns a third boolean —
`signal_sensor_exists` — that's True whenever a sister entity is
structurally tagged as a Wi-Fi signal sensor (by `device_class` or
name suffix), regardless of its current state value.

The WS handler uses this to apply a **trackable-pending-first-
reading override**: if the device has both AP info AND a
structurally-recognised signal sensor (even if currently unknown),
we mark `is_trackable: True` with a reason explaining the
controller hasn't polled yet. The v0.7.1 PWA already has a 45 s
no-sample-yet warning UX, so the subscription handles the wait
gracefully.

New `pending_first_reading: bool` field in the capability response
lets the PWA (future v0.7.5) show a "data pending" badge instead
of treating these like fully-confirmed trackable entities.

### What the user should still do

Even with this fix shipped, the deeper "your Omada controller
isn't polling per-client stats" issue means the RSSI sensors stay
at `"unknown"` forever — there's no data for the subscription to
deliver. The user-side fix is to enable per-client statistics
polling in the Omada controller settings (Settings → Site →
Services → Statistics, or Controller Settings → Data Retention).

## [1.22.1] — 2026-05-20

### Fixed — Wi-Fi mode hidden on HACS Omada installs

Real-install validation 2026-05-20: user installed a HACS Omada
integration, enabled per-client RSSI sensors, confirmed they were
working — but the find-my-ha PWA still hid the Wi-Fi mode button.

Root cause: v1.21.3's `_CONTROLLER_SIDE_PLATFORMS` whitelist only
included `tplink_omada` (the official HA core integration). HACS
community Omada packages register under different platform names
(`omada`, `omada_open_api`, `omada_controller`, etc.) which the
gate rejected as if they were stationary IoT self-reports.

### Fix

Expanded the whitelist to cover every plausible HACS Omada
package's platform identifier:
- `omada` (zachcheatham/ha-omada)
- `ha_omada` (alternative naming)
- `omada_open_api` (bullitt186/ha-omada-open-api)
- `omada_controller` (community fork variant)
- `tplink_omada_open_api` (belt-and-suspenders)

All are controller integrations and safe to allow — controller-side
RSSI is direction-correct for walking find regardless of which
package registers the sensors.

PWA-side: no change required. After HACS picks this up and the
user reloads, `wifi_find_capability` returns `is_trackable: true`
for the Omada-tracked clients, the count goes non-zero, and v0.7.4
unhides the 📶 Wi-Fi mode button automatically.

## [1.22.0] — 2026-05-20

### Added — AdaptiveFeedback detector-level rejection signal

The long-tail extension to the v1.14 AdaptiveFeedbackDetector
lineage. Closes the second insight kind from the original
memory-note design: **detector-level meta-insights** that ask the
user to consider disabling a detector whose suggestions they keep
rejecting.

### What's new

- **`lib/detector_quality.find_rejection_signals()`** — pure
  function that scans `{detector → [verdict_kinds]}` and returns
  detectors with `apply_rate < 0.10` AND `n_decisive >= 20` in the
  input window. Higher bar than the v1.14.7 confidence penalty
  (which kicks in at `< 0.20` with `n >= 5`) because the action
  proposed here is louder.

- **`store.get_decisive_verdict_kinds_by_detector_since(since_ts)`**
  — time-windowed variant of the existing all-time aggregator. The
  detector-level signal uses last-30-days data so the prompt
  tracks current sentiment, not lifetime rejections.

- **`AdaptiveFeedbackDetector.scan()` extension** — after the
  pattern-level re-suggestion pass (unchanged), runs the new
  detector-level signal pass. For each flagged detector, emits a
  `PATTERN_OBSERVATION` insight:

  > Consider disabling **schedule** — 21/22 suggestions rejected
  > in the last 30 days (4.5% apply rate)

  Payload includes `n_decisive`, `n_applies`, `n_rejections`,
  `apply_rate_pct`, deeplink to Devices & Services, and suggested
  actions (disable / wait / Refine). Skips emitting against itself
  (no tail-eating ouroboros).

### Hard rules retained

- Never auto-disables a detector. ALWAYS surfaces as an insight
  the user actions.
- Dedupes via `{kind: "adaptive_feedback_detector_disable",
  detector: <name>}` so the same flag doesn't multi-emit per scan.
- Maturity stays EXPERIMENTAL — thresholds need real-install
  calibration before promotion.

### Tests

10 cases covering: empty input, below-min sample, threshold
boundaries, snooze/undo exclusion, retire-as-rejection, multi-
detector sorting, healthy-detector filter, custom thresholds.

## [1.21.4] — 2026-05-20

### Changed — bundle card v1.10.16 panel.js (modal renderers + layout + Load-more)

Picks up the v1.10.16 panel rebuild:

- **Subject-specific modal bodies for v1.14.x detectors.** Modals
  for `unavailable_device_fixit`, `reboot_loop`, `hardware_suggestion`,
  `stale_automation`, and `wifi_find` now render with friendly fields
  + suggested-actions lists + deeplinks instead of raw JSON.
- **Panel header layout.** Detector filter chips move out of the
  titles column into a full-width row below; action buttons get
  `flex-wrap` so they stop clipping at the viewport's right edge.
  Eliminates the dead-space gap above insights on busy installs.
- **Load-more pagination.** The "Showing 200 of 788 — +588 more →"
  truncation footer is now a working button. Panel listens for
  `ha-insights-card-load-more` and bumps its cap by 200 each click.

Bundle-only change. No backend code touched. panel.js +15 kB.

## [1.21.3] — 2026-05-20

### Fixed — controller-platform whitelist excludes stationary self-reports

Real-install validation 2026-05-20: with v1.21.2's sister-entity
merge live, a user with 326 device-trackers reported the picker
showing ONE candidate — "Main Room Light 4," an ESPHome smart
light. The light is tracked by the router (presence), AND it
exposes its own ESPHome wifi_signal sensor (default ESPHome
component). v1.21.2 happily merged the two and flagged the device
Wi-Fi-findable. But the light is stationary — its self-reported
RSSI doesn't change a single dB as the user walks. False positive
that wastes a tap.

### Fix

`_CONTROLLER_SIDE_PLATFORMS` whitelist gates the sister-entity
merge:
- **Allowed**: unifi, asuswrt, tplink_omada, mikrotik, ubus,
  ddwrt, fritz, keenetic_ndms2, luci, huawei_lte (controllers
  that measure the client's signal from the AP's perspective —
  signal varies as the client walks), plus mobile_app (HA
  Companion app — self-reported but the device IS mobile).
- **Excluded**: esphome, shelly, tasmota, mqtt-platform IoT
  devices, ZHA, zwave_js (self-reported by stationary devices —
  signal doesn't change with user movement).

Two gates:
1. The picked entity's own `platform` must be in the whitelist,
   otherwise the merge short-circuits and returns only the
   picked-entity's attributes (so the v1.18 capability check
   rejects it cleanly).
2. Each sister entity's `platform` is checked the same way,
   preventing an ESPHome wifi_signal sister from being merged
   into a UniFi-tracked device.

The capability response now also includes `platform` so the PWA
can hide the Wi-Fi mode button entirely on installs with zero
controller-side trackable entities (find-my-ha v0.7.4 pairing).

### Companion-app upstream context

Real Wi-Fi find for installs without UniFi/Omada needs the HA
Companion app to expose Wi-Fi RSSI at higher cadence than the
current default (and ideally as a foreground-streaming sensor
during an active "find" session). New draft issue at
`docs/drafts/companion_app_wifi_rssi_streaming.md` mirrors the
v1.21.x architecture as prior art for the upstream proposal.
Sister to the BLE active-scan draft from earlier in the
find-my-device roadmap.

## [1.21.2] — 2026-05-20

### Fixed — Wi-Fi capability merges sister-entity attributes

User report: "no devices found that this Wi-Fi method can be used."
Real fault was architectural — most HA Wi-Fi integrations split
signal + AP info across multiple entities on the same device:

  - UniFi: `device_tracker.alice_phone` carries home/not_home state,
    but RSSI is on `sensor.alice_phone_rx_signal` and AP name is on
    `sensor.alice_phone_access_point`. All same device, three
    different entities.
  - Asuswrt/Omada: similar split.

v1.21.0–v1.21.1 only checked the picked entity's own attributes,
so essentially every real install rejected every candidate.

### The fix

New helper `_collect_device_state_attrs(hass, entity_id)` walks
the entity registry for every sister entity sharing the picked
entity's `device_id`, then merges their state + attributes into
one dict (the picked entity's own attrs win on key collision).
Two promotion heuristics catch the common cases where the value
is on `state.state` rather than `state.attributes`:

  - `device_class == "signal_strength"` → synthetic
    `signal_strength` attribute pulled from `state.state`
  - Entity name segment ending in `signal` / `rssi` / `rx_signal`
    / `access_point` / `ap` / `bssid` → synthetic attribute under
    the canonical capability-lib key

Wired into both:
  - `ws_wifi_find_capability` — batch check now uses merged attrs
    so device-trackers with sensor-side signal sisters report
    `is_trackable: true`. Response also includes
    `consulted_entities` so the PWA can show "found data on
    sensor.alice_phone_rx_signal" diagnostics.
  - `ws_wifi_find_self` — subscribes to state-change events on
    EVERY consulted entity (not just the tracker), so RSSI sensor
    ticks at their own cadence drive the warmer/colder updates.

Pure capability lib (`lib/wifi_find_capability.py`) unchanged —
all the registry-walking logic lives in the WS-handler shim.

## [1.21.1] — 2026-05-20

### Added — `home_insights/wifi_find_capability` batch trackability query

Mirrors `ws_ble_capability`. Read-only, not admin-gated. Pairs with
find-my-ha v0.7.2 PWA pre-filter so users don't pick a mobile_app
GPS-only device-tracker and only find out after hitting Start.

**Handler:** `home_insights/wifi_find_capability`
- Args: `entity_ids: [str]`
- Response: per-entity `{is_trackable, signal_attribute,
  signal_dbm, ap_attribute, ap_identifier, reason}`
- Missing / unknown entities still get a row with
  `is_trackable: false` so the PWA can show "N of M trackable"
  for the full input set.

Reuses the v1.18 `lib/wifi_find_capability.py` function so the
detector + streaming subscription + batch query all share the same
"is this entity Wi-Fi-trackable?" semantics.

## [1.21.0] — 2026-05-19

### Added — `home_insights/wifi_find_self` WS handler (Wi-Fi walking find)

The backend half of inverse-multilateration walking-find for
Wi-Fi devices. Pairs with find-my-ha v0.6.x for the PWA-side UX.

**The flip.** `lib/ble_capability.py` correctly notes Wi-Fi RSSI
is device→AP, not phone→device — browsers can't read the target
device's signal directly. So we flip the problem: the **APs**
measure the **phone** as it walks, and v1.18's `device→AP`
inference tells us which AP the target device lives near. The
phone's RSSI to THAT AP is the warmer/colder signal.

**Handler:** `home_insights/wifi_find_self`
- Admin-gated (phone-location data is sensitive).
- Args: `entity_id` (phone tracker), optional `target_ap_device_id`
  (from v1.18 WifiFindDetector inference).
- Subscribes to state changes for the phone entity. Each change
  carries new AP attribute + RSSI value. Forwards as `event` msgs
  with raw + EMA-smoothed RSSI, AP device_id, friendly name, plus
  an `ap_matches_target` flag the PWA uses for warmer/colder copy.
- Reuses `apply_rssi_ema` from `ws_api/ble_find.py` so card-side
  smoothing is consistent across BLE and Wi-Fi find paths.
- Sends an initial result with the phone's CURRENT readings so the
  PWA has data immediately (UniFi's ~30 s poll cadence would
  otherwise leave the UI blank on first subscribe).

**Cadence trade-off.** UniFi controllers poll per-client signal
every ~30 s by default (configurable to ~10 s on UDM); Asuswrt
fires state-changed events from the router. That's slower than
BLE's ~1 Hz advertisement rate, so the warmer/colder arrow
updates every 10-30 s rather than continuously. EMA smoothing
hides the worst of the noise; the PWA renders a freshness pill
("last update 12 s ago") so users don't think it's broken.

**Coverage.** Same as v1.18.0 capability lib — UniFi, Asuswrt,
Omada, generic 802.11, ESPHome Wi-Fi quality.

Tests: 6 cases covering subscribe-with-trackable / not-trackable /
missing / malformed entity_ids, state-change event forwarding,
target-AP match flag.

## [1.18.0] — 2026-05-19

### Added — WifiFindDetector (passive location inference)

The v1.18 entry in the "find my device" series. Sibling to v1.11.5
LocationProposalDetector (spatial-correlation area inference) and
v1.12.0 BLE live-find (walking warmer/colder).

**What it does.** For each `device_tracker.*` entity with a
recognised Wi-Fi signal-strength attribute (`rx_rssi`,
`signal_strength`, `signal`, …) and an AP-identifier attribute
(`ap_mac`, `bssid`, `host`, …), the detector cross-references the
AP it's currently associated with against that AP's `area_id` in
the device registry. When the device's current area doesn't match
the AP's area (or the device has no area assigned), the detector
emits a PATTERN_OBSERVATION proposing the AP's area as a likely
location.

**What it does NOT do.** Wi-Fi RSSI is device→AP, so this isn't
walking-around find — that lives in BLE land. Think of it as
"where was this last seen" / "where does it usually live" rather
than the metal-detector UX.

**Confidence curve** (single-snapshot, capped at 0.80):
- ≥ -50 dBm → 0.80 (very close — same room)
- ≥ -65 dBm → 0.60 (probably same area)
- ≥ -75 dBm → 0.45 (could be adjacent area)
- < -75 dBm → skip (too weak to act on)

**Safety guards:**
- Single-AP installs skipped (would propose same area for everything).
- Already-correctly-assigned entities silent (no "confirmed" noise).
- Hard cap: 10 insights per scan.
- Never auto-applies — advisory only, opens bulk-area-assign on tap.

**Integration coverage.** UniFi (`rx_rssi` + `ap_mac`), Asuswrt
(`signal` + `host`), generic 802.11 (`rssi` + `bssid`), TP-Link
Omada, ESPHome Wi-Fi quality.

**Maturity: BETA.** Real-install calibration needed for the
signal→confidence curve; recorder-based "consistent for ≥ 24 h"
upgrade slated for v1.18.x.

Companion lib `lib/wifi_find_capability.py` provides the pure
capability function the WS layer will consume in v1.18.x for the
card-side "Find via Wi-Fi" button.

## [1.15.2] — 2026-05-19

### Changed — bundle card v1.10.15 panel.js (a11y polish)

Picks up the focus-visible ring on all `.action` buttons in the
card + panel surface. Desktop keyboard-nav users now see a 2 px
primary-color outline when tabbing through dialog footers and
insight rows. CSS-only change; no integration code touched.

## [1.15.1] — 2026-05-19

### Fixed — streak + weather_correlation 30 s timeouts on large installs

User report on a 3,378-entity install:
`HA Insights detector 'streak' exceeded 30s budget; skipping` +
same for `weather_correlation`. Three occurrences across two
detector cycles.

Root cause: both detectors called
`ctx.event_buffer.query(entity_id=X)` inside a per-group /
per-entity loop. `StateEventBuffer.query` is a linear walk over the
entire event deque, so the asymptotic cost was `O(groups × buffer)`
or `O(habits × buffer)`. On a 3,378-entity install the buffer holds
tens of thousands of events; multiply by hundreds of pattern groups
or habit entities and the detector trips its 30-second budget.

### The fix

Pre-index the buffer **once** per detector run, then do dict
lookups per group/entity instead of full re-scans.

- `streak`: `scan()` now builds `events_by_entity` (per-entity
  timelines) AND `all_events_sorted` / `all_ts_sorted` (time-sorted
  index for the nearby-window co-occurrence calc) during the same
  pass that discovers pattern groups. `_evaluate_group` accepts
  these as kwargs and does `O(log N)` `bisect` lookups instead of
  full buffer scans for the nearby-window and per-entity duration
  passes. Falls back to the old `buffer.query` path when the indices
  aren't passed in (preserves existing test interfaces).
- `weather_correlation`: same pattern. `scan()` builds
  `events_by_entity` once; `_build_daily_weather_context` and
  `_evaluate_entity` take the prebuilt index instead of issuing
  fresh `buffer.query(entity_id=...)` calls per call.

Net effect on real installs: both detectors' inner loops drop from
O(N × B) to O(N) where B = full buffer size. The user's reported
30 s+ timeouts should disappear; on smaller installs the change is
invisible.

No behaviour change — same insights produced, same fingerprints,
same payload shapes. The fallback path in `streak._evaluate_group`
ensures existing unit tests that construct a detector + buffer
directly (rather than going through `scan()`) keep working.

### Files

- `custom_components/ha_insights/detectors/streak.py`
- `custom_components/ha_insights/detectors/weather_correlation.py`
- `custom_components/ha_insights/manifest.json` (1.15.0 → 1.15.1)

### Deferred — work parked at 2026-05-19 session end

These tasks are scoped but not yet started. Pick up in this order:

1. **v1.15.1 — streak + weather_correlation 30s timeout fix.** User
   reported on real install (3,378-entity, 78 integrations):
   `HA Insights detector 'streak' exceeded 30s budget; skipping` +
   same for `weather_correlation`. Same class as the v1.14.8/v1.14.10
   `unavailable_device_fixit` recorder fix — unbounded loop or query
   too big for the 30s detector budget. Fix pattern: chunk the
   recorder query, add the worker-loop → main-loop bridge via
   `asyncio.run_coroutine_threadsafe` + `asyncio.wrap_future`. Read
   `detectors/streak.py` + `detectors/weather_correlation.py`; reference
   commit `af62aaf` (v1.14.10) for the bridge pattern.
2. **v1.18 — WifiFindDetector.** Server-side Wi-Fi RSSI find via
   UniFi `device.rx_rssi` / Asuswrt / OPNsense / OpenWrt integration
   data. Multilateral against known AP positions to infer device
   area. No PWA changes — phones can't read client Wi-Fi RSSI.
3. **v1.19 — ZigbeeFindDetector.** Server-side Zigbee LQI find from
   Z2M MQTT `lqi` attr or ZHA `last_seen_lqi`. Router with highest
   LQI = closest scanner. Infer device area from that router's area.
4. **v1.20 — ZWaveFindDetector.** Z-Wave JS exposes `rssi` for
   last-talked-to controller. Same shape as Wi-Fi/Zigbee variants.

Roadmap context in memory:
`ha_insights_multi_radio_find_roadmap.md` — why these are all
server-side (phone radios can't reach Wi-Fi/Zigbee/Z-Wave). Each
defers until BLE find (v1.10–v1.15) proves valuable on real installs.

### Cross-cutting — find-my-ha PWA integration

v1.15.0's `companion_scan_stream` WS handler is shipped. Future PWA
work that will need server-side awareness:

- **PWA v0.6 capability-based filter + identify endpoint reuse**:
  PWA will call `home_insights/identify` (v1.10.12 vendor-aware)
  when present, fall back to `light.toggle` otherwise. No HA-side
  changes needed — endpoint already exists. PWA work tracked in
  `find-my-ha` repo, not here.
- **PWA v0.6 Touch-test for sensors**: PWA subscribes to entity
  state changes for sensors via `subscribe_trigger`. HA core
  feature; no integration-side changes needed.

## [1.15.0] — 2026-05-19

### Added — `companion_scan_stream` WS handler family (experimental)

A new server-side WebSocket protocol that lets the companion PWA
(`find-my-ha`, separate repo) stream BLE RSSI samples from the
user's phone into HA Insights' live-find machinery. Until now, BLE
live-find could only use stationary scanners — proxies, APs, and
ESPHome BLE proxies. Stationary scanners give *room-level* find
because the geometry is fixed; a moving phone gives the "warmer /
colder" UX the v1.10–v1.12 Find-My-Device feature was designed
around. This release ships the integration side of the contract;
the PWA itself is at v0.2 / early-access.

Three new WS messages, namespaced under `home_insights/`:

  - **`companion_scan_subscribe`** — admin-gated. Names the target
    entity (and optionally the BLE MAC the PWA is filtering on).
    Replies with `{subscription_id, max_sample_rate_hz: 4}`. A new
    subscribe for the same `(user, entity_id)` replaces the
    previous one (per spec); the displaced subscription gets its
    own unsubscribe audit row for honesty.
  - **`companion_scan_sample`** — fire-and-forget RSSI reading
    `{subscription_id, rssi, ts_ms, device_name?}`. Server-side
    rate-limited to 4 Hz (drop-silent), stale-dropped at > 60 s
    `ts_ms` skew, and threaded through the same EMA smoothing that
    stationary proxies feed (extracted as
    `ws_api.ble_find.apply_rssi_ema` for shared use). Emits a
    `companion`-source live event on the original subscribe msg id
    so card-side renderers can use one handler for both phone and
    proxy streams.
  - **`companion_scan_unsubscribe`** — idempotent teardown.
    Connection close also implicitly unsubscribes via the standard
    HA `connection.subscriptions` cleanup hook.

### Privacy / audit

Subscribe and unsubscribe each write one row to `outbound_calls`
via `record_call` (agent=`companion-scan`,
agent_locality=`local`, redaction_mode=`local`). The unsubscribe
row carries an aggregate summary (samples accepted / dropped /
duration / reason). Individual samples are NOT logged — at 4 Hz
× 10 min that'd be 2400 rows per session.

### Maturity

`experimental`. The PWA itself is at v0.2 / early-access. The
contract is documented at `find-my-ha/docs/WS_PROTOCOL.md`
(`schema_version: 1`). Behaviour, message names, and the
sample-rate cap may evolve before v1.16 — forward-incompatible
changes will bump `schema_version`.

### Files

  - `custom_components/ha_insights/ws_api/companion_scan.py` (new)
  - `custom_components/ha_insights/ws_api/ble_find.py` (extracted
    `apply_rssi_ema` from inline EMA, no behaviour change for
    `ws_ble_live_find`)
  - `custom_components/ha_insights/ws_api/__init__.py` (register +
    `SUPPORTED_METHODS`)
  - `tests/test_ws_companion_scan.py` (new)

## [1.14.12] — 2026-05-19

### Fixed — schedule_detector test flake (day-of-week sensitive)

`test_consistent_weekday_routine_produces_insight` and
`test_insight_payload_is_valid_automation_shape` were red on
unfriendly weekdays AND when CI's `dt_util.DEFAULT_TIME_ZONE` was
US/Pacific (the pytest-homeassistant-custom-component default).
Two compounding root causes:

1. The seed built `local_when` in UTC; the detector's
   `dt_util.as_local()` then shifted events to 22:47/23:47 the
   previous local day, flipping weekday<->weekend.
2. A hard-coded `_FIXED_NOW` anchor went stale once it drifted
   outside the detector's `LOOKBACK_DAYS=14` cutoff — every
   seeded event then filtered out.

Fix: localise `end` into HA's configured timezone before walking
back the day offsets, and compute `_FIXED_NOW` dynamically as the
most-recent Monday at 10:00 UTC (fresh AND day-of-week-stable).
No production code touched.

### Fixed — dev_audit event-buffer counter always reported 0

Hardware validation showed `events_24h: 0`, `events_7d: 0`,
`unique_entities: 0` across multiple dev_audits on a 3,378-entity
install (with 78 integrations producing thousands of events/hour).
The buffer wasn't empty — the *counter* was broken.

`_build_event_buffer_signature` called `buffer.iter_events()`,
which doesn't exist on `StateEventBuffer`. The resulting
`AttributeError` was caught at DEBUG level and the counts silently
stayed at zero.

### The fix

Use `buffer.snapshot()` (the canonical "give me every event" method
that's been there since v0.1) and bump the exception logging from
DEBUG to WARNING so future bugs are visible in HA's standard log
view.

### Impact

This bug suppressed visibility into how busy the buffer actually is.
With the counter fixed, the dev_audit will finally show real numbers
and we can answer "is this detector silent because of no signal, or
because of a bug?" accurately for buffer-dependent detectors
(cooccurrence, schedule, frequency_anomaly, streak, seasonality,
manual_habit, lagged_correlation, button_press_habit, long_tail,
routine, presence_inference, ...).

## [1.14.11] — 2026-05-19

### Fixed — three dormant detector bugs surfaced by hardware validation

The verbose logging from v1.14.9 exposed multiple silently-failing
detectors on a 3,378-entity install. Three are HA-API drift bugs;
all three result in zero output from the affected detector
(swallowed by `run_all_detectors`'s per-detector exception handler).

  - **`setup_quality`**: `AreaEntry.area_id` → `AreaEntry.id` (HA
    renamed). Now uses `getattr(a, "id", None) or getattr(a,
    "area_id", None)` so installs on either side of the rename
    keep working.
  - **`physical_device_link`**: `device.identifiers` /
    `device.connections` tuples are no longer guaranteed to be
    2-element. Some integrations now emit 3+ element tuples with
    extra metadata. Replaced `for ct, cv in (...)` with explicit
    `len(conn) < 2` skip + index access — tolerant of any length
    ≥ 2.
  - **`habitual_override`**: detector called `.snapshot()` on
    `ctx.event_buffer`, but `_FrozenBufferView` (the production
    wrapper used in worker threads) only exposes `.query()`.
    Replaced with `tuple(ctx.event_buffer.query())`.

### Known issue (not fixed in this release)

`streak` detector exceeded the 30s per-detector budget on the same
install. Needs profiling data before optimization; the per-detector
timeout already prevents it from blocking the scan. Tracked for
v1.14.12.

## [1.14.10] — 2026-05-19

### Fixed — UnavailableDeviceFixIt recorder query cross-loop bug

**Hardware-validation finding from v1.14.9 logs.** With visible
logging in place, the actual error finally surfaced:

```
RuntimeError: Task got Future attached to a different loop
```

Detectors run inside `asyncio.run()` on a worker thread (per
`detectors/__init__.py:_run_detector_in_thread`), which gives each
detector its own event loop. But
`recorder.async_add_executor_job(...)` schedules onto the
recorder's executor and returns a `Future` bound to HA's **main**
loop. Awaiting that Future from the worker's loop raises
RuntimeError.

This is the same architectural pattern as the v1.5.22
`_load_iot_classes` deadlock fix.

### The fix

Standard HA cross-loop bridge:

```python
async def _on_main_loop():
    return await recorder.async_add_executor_job(_query)

cf_future = asyncio.run_coroutine_threadsafe(
    _on_main_loop(), hass.loop
)
result = await asyncio.wrap_future(cf_future)
```

- Detects we're on a worker loop (via `asyncio.get_running_loop()`
  vs `hass.loop`).
- If we are: schedule the coroutine onto the main loop, await
  via `asyncio.wrap_future` to convert the
  `concurrent.futures.Future` back to an awaitable on our worker
  loop.
- If we're already on the main loop (tests, direct invocation):
  just `await` directly.

### Diagnostic logging stays

The v1.14.9 INFO/WARNING lines remain — if anything still fails
after the bridge, the user can see the new failure mode in HA
logs without flipping debug flags.

## [1.14.9] — 2026-05-19

### Fixed — UnavailableDeviceFixIt recorder fallback was silently failing

**Hardware-validation follow-up.** v1.14.8 added a recorder fallback,
but on the 3,378-entity install with 1,603 unavailable entities the
detector still emitted **zero** insights. The single bulk
`get_significant_states` call was failing silently (caught
exception at DEBUG level → invisible).

### Two-part fix

**1. Chunked recorder query.** Suspect entity_ids are split into
batches of **200** per `get_significant_states` call rather than
one giant call. Each batch stays under ~1-2 seconds on a typical
install; up to ~15 batches fit in the 30-second per-detector budget.
Avoids both SQLite parameter-limit risk and recorder-query-timeout
on big installs.

**2. Verbose, visible logging.** The recorder helper now logs at
**INFO/WARNING** rather than DEBUG, so future failures are
diagnosable from HA's standard log view without flipping per-
component debug flags:

  - `INFO` — "querying recorder for N suspect entities in M batch(es)"
  - `INFO` — "query complete — A/B batches successful, R rows
    scanned, E entities resolved (F will fall back to live)"
  - `WARNING` — per-batch query failures with batch index +
    entity count + error message
  - `WARNING` — "X/N recorder batches FAILED" summary
  - `INFO` — "recorder component unavailable; skipping recorder
    fallback" (when integration loaded without recorder)
  - `WARNING` — "could not acquire recorder instance"

### Defensive

  - Ruff B023 fix: inner `_query` closure binds `batch_eids` and
    `idx_label` as default args rather than capturing the loop
    variable.
  - Failed batches don't abort the scan; the helper still returns
    whatever successful batches produced.
  - Partial success: 9 of 10 batches working still yields the
    resolved 9 batches' worth of insights.

### How to read the new logs (for hardware re-validation)

After v1.14.9 + restart + one scan, search HA logs for
`unavailable_device_fixit`. Expected pattern:

```
INFO  unavailable_device_fixit: querying recorder for 1603 suspect
      entities in 9 batch(es), window=14d
INFO  unavailable_device_fixit: recorder query complete — 9/9 batches
      successful, 12000 total rows scanned, 1200 entities resolved
      (403 will fall back to live last_changed)
INFO  UnavailableDeviceFixItDetector emitted 1200 insights
      (1603 suspect entities resolved via recorder)
```

If you see `WARNING ... query failed for batch N/M: <error>`, that's
the next diagnostic — paste the error and we'll fix the underlying
recorder issue.

## [1.14.8] — 2026-05-19

### Fixed — UnavailableDeviceFixIt missed post-restart entities

**Hardware-validation finding.** A 3,378-entity install reported
**1,603 unavailable entities, all with `last_changed < 1 hour`** —
detector emitted zero. Root cause: HA restart resets `last_changed`
for many integrations (cloud APIs, Tuya, polling-only platforms),
making genuinely-dead-for-weeks entities look fresh to the live
state machine.

### The fix

Recorder fallback. For each currently-unavailable entity whose live
`last_changed` is suspiciously recent (within the 48h cutoff), bulk-
query the recorder for the **most recent non-unavailable state** in
the last 14 days. That timestamp is the true "unavailable since" —
entity has been continuously unavailable ever since.

  - One recorder query per scan (bulk across all suspect entities),
    routed through `recorder.get_instance(hass).async_add_executor_job`
    per HA core review guidelines.
  - `min(live_last_changed, recorder_ts)` — prefer the older timestamp
    so we don't pretend an entity is fresher than evidence allows.
  - If recorder has rows but ALL are unavailable in the window →
    use start-of-window as a conservative lower bound (still trips
    the 48-hour gate correctly).
  - If recorder has no rows / fails / unavailable → silently fall
    back to live `last_changed` (no regression from v1.14.0 behavior).

### Defensive notes

  - `requires_recorder` stays `False`. Installs without recorder
    keep the old behavior; the fallback is opportunistic.
  - Recorder failures are caught per-entity; one bad entity doesn't
    poison the whole scan.
  - Handles both modern `State` objects and `minimal_response=True`
    dict format (same tolerance pattern as `audit/rollup.py`).

### Tests

5 new unit tests covering: recorder rescue of post-restart entity,
recorder called only with suspect entities, recorder-empty falls
back to live, recorder-says-recently-alive doesn't emit, min(live,
recorder) when both disagree. Existing 17 tests stay green.

Smoke-verified locally: live `last_changed` 30 min ago + recorder
says 10 days ago → emits correctly with 240 h / 0.88 confidence.

## [1.14.7] — 2026-05-19

### Added — apply-rate detector-quality penalty (closes v1.14 batch)

Detectors whose suggestions users consistently reject now get their
emitted insights' confidence demoted. New emissions from a
"chronic rejection" detector show up less prominently in the panel
and trip the existing low-confidence filler floor sooner.

### The rule

Per detector, computed from the v1.14.3+ verdict timeline:

| Apply-rate | Penalty factor | Effect |
|---|---|---|
| ≥ 0.50 | 1.0× | Neutral — user finds the detector useful |
| 0.20–0.50 | 0.85× | Light demotion |
| < 0.20 | 0.60× | Heavy demotion (visibly less prominent) |

Below `MIN_DECISIVE_VERDICTS = 5` the factor stays at **1.0** — too
little signal to penalize. New installs see no penalty until
enough verdict history accumulates.

Snoozes / undos / clear_applied are filtered out: they don't
reflect a user's opinion about the *value* of the suggestion. Only
APPLY / DISMISS / RETIRE count. (Same set as the lib's
`apply_rate` from v1.14.3a.)

### Why penalty-only

Confidence is a per-insight signal the detector set based on its
own evidence. Inflating it post-hoc would lie to the rest of the
pipeline (notification thresholds, repairs dual-emit, audit hooks
all gate on confidence). Penalty-only stays honest.

### New module — `lib/detector_quality.py`

Pure stdlib, same architecture as the other v1.x libs:

  - `apply_rate_from_kinds(kinds)` — `(rate, decisive_count)`.
  - `compute_penalty_factor(rate, count)` — applies the rule above.
  - `compute_penalties_by_detector(kinds_by_detector)` — bulk variant.

### New store method

`InsightStore.get_decisive_verdict_kinds_by_detector()` — SQL JOIN
of `verdict_history` × `insights`, filtered to decisive kinds at
the SQL level. Returns `{detector_name: [kind, ...]}`. Lighter
than `get_all_verdict_histories` (no fingerprint deserialization)
because we only need the kind sequence for the apply-rate math.

### Wiring

In `run_all_detectors`:

  1. **Before** the per-detector scan loop: compute
     `detector_quality_penalties` once via store JOIN + lib bulk
     variant.
  2. **Inside** the per-insight processing loop: `replace(insight,
     confidence=insight.confidence * penalty)` if the lookup yields
     anything ≠ 1.0. Happens BEFORE the existing low-confidence
     filler check, so demoted insights legitimately get filtered
     when they fall below the floor.

Exception-safe: if the JOIN fails for any reason, falls back to an
empty penalty dict (every detector defaults to 1.0).

### Smoke output (local)

```
Detectors with verdicts: ['cooccurrence', 'schedule', 'state_shift']
  cooccurrence: count=8,  apply_rate=0.00 → penalty=0.60
  schedule:     count=10, apply_rate=0.20 → penalty=0.85
  state_shift:  count=3,  apply_rate=0.00 → penalty=1.0  (<5 → neutral)

Demotion examples (original confidence=0.85):
  schedule (light):     0.85 * 0.85 = 0.722
  cooccurrence (heavy): 0.85 * 0.60 = 0.510
  state_shift (neutral): 0.85 * 1.0 = 0.850
```

### Tests

  - 13 unit tests for the lib (empty, all-applies, mixed, retire-
    counts-negative, snooze-ignored, unknown-kind-tolerated,
    bucket boundaries, bulk variant, threshold exactness)
  - 3 store-join tests (groups by detector, orphan verdicts
    dropped via INNER JOIN, empty DB)

### v1.14 batch complete

Eight PRs, all CI-green, all tagged + released:

| Version | What | PR |
|---|---|---|
| v1.14.0 | UnavailableDeviceFixItDetector | #75 |
| v1.14.1 | RebootLoopDetector | #76 |
| v1.14.2 | HardwareSuggestionDetector | #77 |
| v1.14.3 | `lib/user_verdict_history.py` | #78 |
| v1.14.4 | SQLite `verdict_history` + store methods | #79 |
| v1.14.5 | `lib/environmental_fingerprint.py` + WS hooks | #80 |
| v1.14.6 | AdaptiveFeedbackDetector | #81 |
| **v1.14.7** | **apply-rate penalty** | this |

## [1.14.6] — 2026-05-19

### Added — AdaptiveFeedbackDetector (Step C-2 of v1.14.3)

The headline consumer of the v1.14.3 verdict-history pipeline.
For every insight the user has previously dismissed or retired,
this detector compares the environmental fingerprint captured at
verdict time against the current fingerprint. If
`should_re_suggest` returns True, the detector emits a fresh
`PATTERN_OBSERVATION` "Revisit" insight nudging the user to take
another look.

The most common trigger:

  - User dismissed "lights off when away" because they already had
    `automation.competing` covering it.
  - User later deleted that automation.
  - Fingerprint diff: `automations_removed = {'automation.competing'}`.
  - AdaptiveFeedback fires:
    *"Revisit: `Lights off when away` — `automation.competing` was removed"*

### Skip rules

  - Original insight purged from store → skip
  - Original currently applied → skip (user engaged)
  - Active snooze → skip (let it run)
  - 30-day cooldown after each verdict (enforced by lib)
  - Retire bar higher than dismiss: only `automations_removed`
    overrides a retire; new sensors alone aren't enough.

### Payload structure

```python
{
    "kind": "adaptive_feedback",
    "original_insight_id": "abc123",
    "original_title": "Lights off when away",
    "original_detector": "schedule",
    "negative_verdict_kind": "dismissed",
    "days_since_negative_verdict": 120,
    "what_changed": {
        "automations_added": [...],
        "automations_removed": ["automation.competing"],
        "sensors_added_per_area": {...},
        "sensors_removed_per_area": {...},
        "integrations_added": [...],
        "integrations_removed": [...],
    },
    "human_summary": "You dismissed ... because ... was removed — ...",
    "verdict_history_summary": "1 dismissed",
}
```

### Behaviour notes

  - Never re-emits the original insight; emits a META-insight that
    points at the original via `original_insight_id`.
  - Original stays in its dismissed/retired state; the meta-insight
    is a separate row the user can act on independently.
  - Fingerprint dedupes across scans (one re-surface per original
    insight), so re-running doesn't spam the panel.

### Defensive

  - Store-fetch failures are caught (detector returns `[]`).
  - Hydration of verdict rows is per-row tolerant: malformed kind /
    timestamp / fingerprint values skip the row without crashing.

### Tests

13 unit tests:

  - Empty / null cases (no store, no history, store raises)
  - Dismiss + automation_removed → emits
  - Retire + automation_removed → emits (high bar met)
  - Retire + sensor_added → skips (high bar not met)
  - Applied insight → skips
  - Active snooze → skips
  - Missing original → skips
  - Recent dismiss (cooldown) → skips
  - Malformed verdict rows → skipped but real rows still processed
  - Payload structure (all keys + human_summary content)
  - Fingerprint stable across re-scans

Smoke-verified end-to-end: 1 dismiss + competing automation removed
→ correctly emits "Revisit: ..." with the right summary and
auto-registers in DETECTORS.

### Up next (optional)

**v1.14.7:** wire `apply_rate` from the lib into detector-quality
scoring so detectors with chronically-rejected suggestions get
demoted in the panel.

## [1.14.5] — 2026-05-19

### Added — fingerprint capture + WS hook wiring (Step C-1 of v1.14.3)

Connects the v1.14.3a verdict-history lib + v1.14.4 SQLite layer
to the real WS verdict handlers. Every dismiss / retire / unretire /
apply / undo / snooze now appends a row to `verdict_history` with
the `EnvironmentalFingerprint` captured at verdict time.

### New module `lib/environmental_fingerprint.py`

Pulled the HA-aware capture out of the pure-stdlib lib so the
verdict-history lib stays portable.

  - `capture_environmental_fingerprint(hass)` — snapshot the three
    fields the lib defines: enabled automation entity_ids, per-area
    device_class counts, active integration domains. Defensive
    against broken hass/registry — always returns a valid (possibly
    empty) `EnvironmentalFingerprint`.
  - `fingerprint_to_dict(fp)` / `dict_to_fingerprint(d)` — JSON-safe
    round-trip pair. Frozensets become sorted lists so the store's
    `sort_keys=True` JSON dump stays deterministic.
  - `hash_user_id(user_id)` — 12-byte blake2b hash so HA user_ids
    don't appear raw in the long-lived verdict timeline.

### WS handler hooks

Each handler appends a row to `verdict_history` after the existing
state mutation succeeds. Helper `_record_verdict_safely` swallows
any exception so a failed timeline write never breaks the user-
visible action.

| Handler | Verdict kind |
|---|---|
| `ws_dismiss` | `dismissed` |
| `ws_snooze` | `snoozed` |
| `ws_retire` | `retired` |
| `ws_unretire` | `unretired` |
| `ws_apply` | `applied` |
| `ws_undo` | `undone` |

### Privacy notes

The fingerprint deliberately excludes:

  - Individual entity_ids (except for automations, which are
    coarse-grained pattern identifiers).
  - State values.
  - Friendly names.
  - Raw user_ids — those are hashed before storage.

Any future expansion must preserve this contract — the verdict
fingerprint is meant to detect environmental DELTAS, not to log
home contents.

### Tests

19 unit tests for the fingerprint module (hash, round-trip,
capture happy-path, capture edge cases — disabled / hidden /
excluded domains / no area / missing device_class). Smoke-verified
end-to-end locally: 3 entries → fingerprint correctly captured 1
enabled automation, kitchen had {motion:1, temperature:1, light:1},
{mqtt, zha} integrations, user hash deterministic + privacy-safe.

### Up next

**v1.14.5b:** `detectors/adaptive_feedback.py` reading
`get_all_verdict_histories` + applying `should_re_suggest`.
**v1.14.5c (maybe):** `apply_rate` penalty in detector-quality
scoring.

## [1.14.4] — 2026-05-19

### Added — verdict-history persistence (Step B of v1.14.3)

Persistence layer for the v1.14.3 verdict timeline. Adds the
SQLite `verdict_history` table + three new `InsightStore` methods:

  - `record_verdict(insight_id, kind, fingerprint, *, when, user_id_hash)`
    — append one verdict event. `kind` is a `VerdictKind` value;
    `fingerprint` is the JSON-serializable dict form of an
    `EnvironmentalFingerprint` (the store stays JSON-free of the
    lib so the lib stays import-free of the store).
  - `get_verdict_history(insight_id)` — read a single insight's
    timeline, ascending by timestamp. Returns plain dicts so the
    store keeps no dependency on the lib types; consumers hydrate
    into `Verdict` / `VerdictHistory` as needed.
  - `get_all_verdict_histories()` — bulk read for the detector
    pass, keyed by insight_id.

### Schema migration 6

```sql
CREATE TABLE verdict_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  insight_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  timestamp REAL NOT NULL,
  fingerprint_json TEXT NOT NULL,
  user_id_hash TEXT,
  FOREIGN KEY (insight_id) REFERENCES insights(id) ON DELETE CASCADE
);
CREATE INDEX ix_verdict_history_insight ON verdict_history(insight_id);
CREATE INDEX ix_verdict_history_ts ON verdict_history(timestamp);
```

`fingerprint_json` is written with `sort_keys=True` so two
semantically-equal fingerprints serialize identically (useful for
diff-by-text in dumps).

FK CASCADE is declared but not enforced — the existing store
doesn't enable `PRAGMA foreign_keys=ON`. v1.14.4c can revisit if
orphan rows become a concern; for now the test documents the
behaviour.

### Why a separate table

The existing verdict columns on `insights` (`dismissed_at`,
`retired_at`, `applied_at`, `snoozed_until`) track only the
*current* state. They get overwritten on each verdict transition.
The append-only `verdict_history` table is the timeline — required
for the [[ha_insights_v2_presence_and_adaptive]] AdaptiveFeedback
re-suggest logic and v2.0 per-person apply-rate stats.

### Tests

11 unit tests covering migration application, schema version,
record + read round-trip, ordering, user_id_hash, nested-dict
fingerprint serialization, bulk read grouping, append-only
semantics, idempotent re-open, deterministic JSON serialization.

Smoke-tested locally against a real SQLite file: schema version
6 applied cleanly, 3 verdicts out-of-order insertion → read back
in ascending order, bulk-read groups correctly, idempotent
re-open preserves data.

### Up next

**Step C (v1.14.5):** the consumers.
  - Hook `ws_dismiss` / `ws_retire` / `ws_apply` / `ws_undo` to
    capture an `EnvironmentalFingerprint` and call `record_verdict`.
  - Build `detectors/adaptive_feedback.py` consuming
    `get_all_verdict_histories` + the lib's `should_re_suggest`.
  - Wire `apply_rate` penalty into detector-quality scoring so
    detectors with chronically-rejected suggestions get demoted.

## [1.14.3] — 2026-05-19

### Added — `lib/user_verdict_history.py` (Step A of v1.14.3)

New pure-function lib providing the **timeline** abstraction over
user verdicts (apply / dismiss / retire / snooze / undo). Today's
`InsightStore` tracks only the *current* verdict state — each
verdict overwrites its predecessor. This lib defines the data model
+ comparison primitives for a verdict timeline plus an
**environmental fingerprint** captured at the moment of each verdict.

#### Why

Foundation for:

  - **v1.14.4 AdaptiveFeedbackDetector** — re-suggest patterns the
    user previously dismissed when the environmental context changes
    (deleted automation, new sensor, new integration).
  - **v2.0 per-person presence** — needs verdict history per pattern
    so each resident's apply-rate can tracked.

#### What's in it

  - `VerdictKind` enum — `APPLY` / `DISMISS` / `RETIRE` / `UNRETIRE` /
    `SNOOZE` / `UNDO` / `CLEAR_APPLIED`. Matches the existing
    `InsightStore` event names so callers pass them through.
  - `EnvironmentalFingerprint` — frozen dataclass with
    `automation_ids` / `sensors_per_area` / `active_integrations`.
    Hashable (custom `__hash__` because dict fields make it
    non-hashable by default). ~200 bytes after JSON serialization.
  - `Verdict` / `VerdictHistory` — frozen dataclasses representing
    one verdict and a per-insight timeline of verdicts respectively.
    `VerdictHistory.__post_init__` enforces ascending-timestamp
    invariant.
  - `diff_fingerprints(old, new)` — pure `(old → new)` delta
    computation. Returns `FingerprintDelta` with `automations_added` /
    `automations_removed` / `sensors_added_per_area` /
    `sensors_removed_per_area` / `integrations_added` /
    `integrations_removed`.
  - `FingerprintDelta.is_substantial` — heuristic: any automation
    change, any new sensor, or any new integration. Removed sensors
    and removed integrations alone don't qualify.
  - `should_re_suggest(history, current, *, now)` — the
    AdaptiveFeedback decision. Rules:
      1. There must be a negative verdict (DISMISS or RETIRE).
      2. The MOST RECENT verdict must still be negative.
      3. Fingerprint delta must be substantial.
      4. 30-day cooldown since the last verdict.
      5. RETIRE has a higher bar: only `automation_removed` can
         override (user explicitly took action suggesting their
         original reasoning changed).
  - `apply_rate` / `dismiss_rate` — for detector-quality penalty
    system. `dismiss_rate` excludes retires from the denominator
    (retire = permanent no, distinct signal from "not now").

#### Architecture

  - Pure stdlib + dataclasses; **no HA imports, no DB imports**.
  - Same pattern as `lib/changepoint_detection.py`,
    `lib/transfer_entropy.py`, `lib/coupling_strength.py`.
  - 31 unit tests covering edge cases (timestamp ordering, cooldown,
    retire-vs-dismiss bar, mixed verdict timelines).

#### Roadmap

Step B (v1.14.4) wires it up: SQLite migration for a `verdict_history`
table, hook into the existing `ws_dismiss` / `ws_retire` / `ws_apply`
handlers to capture the fingerprint, build the
`AdaptiveFeedbackDetector` that reads histories and decides which
dismissed patterns are worth re-surfacing.

## [1.14.2] — 2026-05-19

### Added — HardwareSuggestionDetector

New EXPERIMENTAL detector emits **per-area** sensor-gap suggestions.
Complements `setup_quality` (which reports home-wide coverage
percentages) by saying "*this specific* kitchen has 4 lights and no
motion sensor — consider adding one." One PATTERN_OBSERVATION
insight per (area, recipe) gap.

### Non-commercial commitment

Hard rules from [[ha_insights_hardware_gap_detector]] memory:

  - **No brand names** (no Aqara / Hue / Shelly / IKEA / etc.)
  - **No affiliate links**
  - **No buy URLs**
  - **No specific product recommendations**

Each payload includes an explicit `non_commercial_disclaimer` string
reiterating the policy. Tests assert the absence of common brand
names from every emitted insight.

### Recipes

1. **motion_sensor_for_active_area** — area has ≥3 light/switch/
   media_player/climate/cover entities AND no motion/occupancy/
   presence sensor.
2. **illuminance_sensor_for_lit_area** — area has ≥2 light entities
   AND no illuminance sensor.
3. **temperature_sensor_for_climate_area** — area has a climate
   entity AND no standalone temperature sensor.
4. **contact_sensor_for_entry_area** — area name matches an entry
   pattern (entry/foyer/garage/front/back/mudroom/hallway/porch)
   AND no door/window/opening contact sensor.

Each insight payload surfaces the hardware category, a rationale,
and 3+ "unlocks" — scenarios the missing sensor would enable.

Confidence is a flat 0.70 — these are suggestions, not anomalies.

### Forward-look

v1.15+ can extend with more recipes (smart-button gap, weather
integration gap, BLE-proxy gap for Find My Device, etc.).

## [1.14.1] — 2026-05-19

### Added — RebootLoopDetector

New EXPERIMENTAL detector pairs with v1.14.0 `UnavailableDeviceFixIt`
on the connectivity-health side. Flags entities whose `→ unavailable`
transitions over the last 7 days form a **regular** cadence —
small coefficient of variation in inter-arrival times — which
signals a **config-driven reboot loop** (power-cycle schedule,
watchdog timer, weak-mesh re-routing) rather than random outages.

### The statistical test

Coefficient of variation (CV = stddev / mean) of gaps between
consecutive `→ unavailable` transitions:

  - CV ≥ 0.30: too random → skip
  - CV 0.20–0.30: moderately regular → 0.65
  - CV 0.10–0.20: clearly regular → 0.80
  - CV  < 0.10: tightly regular → 0.92

Two sanity gates:
  - **≥5 transitions** in the 7-day window (CV unreliable below this)
  - **Median gap <48 h** (>48 h is intentional weekly maintenance, not a loop)

### Suggested actions

Loop-specific (distinct from v1.14.0's stuck-device guidance):
power-cycle schedule check, watchdog/keepalive inspection,
Zigbee/Z-Wave mesh signal-strength check, integration-log grep,
ESPHome/Shelly/Tasmota firmware update.

### Forward-look

v1.15+ can run [[lib/changepoint_detection]] on the rolling CV to
detect *when* a reboot loop began (config-change attribution, not
just current-state).

### Notes

Defensive `isinstance(..., str)` guards on `entity_entry.disabled_by` /
`hidden_by` to reject MagicMock proxies in tests while still
correctly skipping real user-disabled entities (HA's
`RegistryEntryDisabler` is a StrEnum). Same defensive pattern as
`physical_device_link.py`.

## [1.14.0] — 2026-05-19

### Added — UnavailableDeviceFixItDetector

New EXPERIMENTAL detector flags entities stuck in `unavailable` or
`unknown` for **48+ hours** and emits a diagnostic-style ANOMALY
insight with structured fix guidance.

HA already shows you that an entity is unavailable, but does not
surface *how long* prominently. A motion sensor dead for 6 weeks
looks identical in the UI to one that flickered offline this
afternoon. This detector turns "you have 47 unavailable entities"
into "8 of them have been broken for >1 month — start here."

Each insight surfaces:

  - Entity friendly name + current state
  - Hours stuck (and a confidence tier that scales with duration)
  - Owning integration + deeplink to its Settings page
  - Tiered suggested actions: physical-device check → cloud/local
    integration class hints → domain-specific hints (Companion app
    for device_tracker / person; HVAC hub for climate) → restart-
    integration walkthrough → "remove if abandoned"

Confidence tiers:

  - 48-72 h: 0.65 (might still be transient)
  - 72-168 h (3-7 d): 0.78
  - 168-720 h (1-4 w): 0.88
  - 720+ h (4+ w): 0.95 (abandoned/broken)

Excluded domains: `automation`, `script`, `scene`, `zone`, `sun`,
`persistent_notification` (where unavailable/unknown is either
impossible or expected noise). Registry-disabled and registry-
hidden entities are skipped (user already knows). Privacy
blocklist honoured.

Marked `Maturity.EXPERIMENTAL`; threshold and excluded-domain list
will tune from real-install feedback.

## [1.13.9] — 2026-05-19

### Internal — ws_api LLM-handler family extraction (v1.13 step 7)

Final big extraction. The three LLM-driven handlers that still
lived in the monolith each move to their own file:

  - `ws_api/audit_suggest.py` (~508 lines) — `ws_audit_suggest`
    plus its two prompt-building helpers
    (`_build_audit_feedback` + `_authorized_edits_from_observations`)
  - `ws_api/chat.py` (~196 lines) — `ws_chat_create_automation`
    (the blank-canvas chat handler)
  - `ws_api/hypothesize.py` (~112 lines) — `ws_hypothesize`
    (LLM anomaly hypothesis generator)

Re-imported back into `__init__.py` for backward-compat. No
behavior change. Ruff clean.

Also drops the now-dead `_REFINE_PRINCIPLES` backwards-compat
alias from `__init__.py` (no callers left after step 6).

### Monolith trajectory

`ws_api/__init__.py` now **2,837 lines**, down from **5,259** at
the start of the v1.13 refactor — a **46% reduction** across
seven incremental, reviewable steps:

  - step 0: rename `ws_api.py` → `ws_api/__init__.py`
  - step 1: `_helpers.py` (universal helpers)
  - step 2: `identify.py` (Find My Device handlers)
  - step 3: `ble_find.py` (BLE live-find handlers)
  - step 4: `managed_devices.py` (ManagedDevices handlers)
  - step 5: `_refine_helpers.py` (pure REFINE helpers)
  - step 6: `refine.py` (REFINE handlers + prompt cluster)
  - step 7: `audit_suggest.py` + `chat.py` + `hypothesize.py`

## [1.13.8] — 2026-05-19

### Internal — ws_api/refine.py extraction (v1.13 step 6)

Second sub-step of the REFINE handler-family extraction. The four
REFINE handlers and their tightly-coupled prompt-template cluster
moved out of `ws_api/__init__.py` into `ws_api/refine.py` (~662
lines):

Handlers extracted:

  - `ws_refine` — the original refine WS endpoint
  - `ws_refine_cost_estimate` — pre-call token/cost preview
  - `ws_refine_automation` — full-automation refinement with
    side-by-side YAML diff
  - `ws_apply_automation_refinement` — write the refined YAML back
    to `automations.yaml`

Prompt-template cluster (kept together because they only make
sense as a group):

  - `_REFINE_PRINCIPLES_CONCISE` / `_REFINE_PRINCIPLES_INDEPTH`
    — depth-aware system-prompt rules
  - `_principles_for(depth)` — picker
  - `_OBS_KIND_HINTS` — per-observation-kind LLM hint table
  - `_authorized_from_user_text` — gate the model from rewriting
    automation IDs / aliases unless the user explicitly asked
  - `_wrap_user_feedback` — compose the final LLM prompt string
  - `_resolve_refine_cost_threshold` — read the per-entry cost cap

Plus the BLE handlers' previously-extracted re-exports continue
to work; `ws_chat_create_automation` and `ws_audit_suggest`
remain in `__init__.py` for now (they import the extracted
helpers via the package). No behavior change. Monolith now
~3,553 lines, down from ~5,259 at the start of the v1.13
refactor.

## [1.13.7] — 2026-05-19

### Internal — ws_api/_refine_helpers.py extraction (v1.13 step 5)

First sub-step of the REFINE handler-family extraction. Six pure
helpers moved out of `ws_api/__init__.py` into their own module:

  - `_resolve_audit_depth` — pick LLM verbosity (concise/indepth)
  - `_humanize_llm_error` — translate provider errors (Gemini
    MAX_TOKENS, OpenAI context_length, Anthropic max_tokens,
    rate-limit) into actionable user guidance
  - `_attempt_to_dict` — serialize LLM AttemptAudit to JSON-safe
    dict
  - `_sanitize_yaml_safe` — round-trip through JSON so PyYAML's
    safe_dump can represent HA Templates / Selectors / etc.
  - `_find_automation_by_id` — look up an automation's raw_config
    by id or alias (runtime state + automations.yaml + packages)
  - `_build_chat_feedback` — compose the LLM feedback string for
    the v1.13.2 chat handler

Plus the `_CHAT_AUTOMATION_SKELETON` constant (only used by
`_build_chat_feedback`).

Re-imported back into `__init__.py` so existing handler call
sites unchanged. AST verified: every helper relocated, none
duplicated.

`ws_api/__init__.py` shrinks from 4,369 → 4,122 lines (-247
net). New `ws_api/_refine_helpers.py` is 321 lines.

**Cumulative refactor progress** vs 5,259-line pre-refactor
baseline: 5 modules extracted (-1,317 lines total).

The prompt-building cluster (`_wrap_user_feedback` +
`_authorized_from_user_text` + `_principles_for` +
`_REFINE_PRINCIPLES_*` + `_OBS_KIND_HINTS`) is intentionally
NOT extracted in this step — those form a tight prompt-template
subsystem better moved alongside `ws_refine` itself in v1.13.8.

Next: v1.13.8 will move `ws_refine` + `ws_refine_automation` +
`ws_apply_automation_refinement` + the prompt-template cluster
into `ws_api/refine.py`. v1.13.9 will move
`ws_chat_create_automation` + `ws_audit_suggest` +
`ws_hypothesize` into a `chat.py` / `audit_suggest.py` split
(TBD based on dependency analysis).

## [1.13.6] — 2026-05-19

### Internal — ws_api/managed_devices.py extraction (v1.13 step 4)

Step 4 of the v1.13 ws_api refactor. Two ManagedDevices handlers
+ one helper extracted from `ws_api/__init__.py`:

  - `ws_list_managed_devices`
  - `ws_set_device_managed`
  - `_managed_devices_set` (helper, also used by one other handler
    in `__init__` so it's imported back via the same path)

Re-imported back into `ws_api/__init__.py` and added to `__all__`.

`ws_api/__init__.py` shrinks from 4,474 → 4,369 lines (-105 net).
New `ws_api/managed_devices.py` is 171 lines.

**Cumulative refactor progress** vs 5,259-line pre-refactor
baseline:
- v1.12.25 helpers: -180 lines
- v1.13.4 identify: -567 lines
- v1.13.5 ble_find: -218 lines
- v1.13.6 managed_devices: -105 lines
- **Total: -1,070 lines extracted; monolith now 4,369 lines.**

That completes the three isolated handler groups flagged by the
dependency-map memory (BLE + IDENTIFY + MANAGED_DEVICES). The
remaining big extraction is the REFINE handler family (8 handlers
+ 6 helpers, higher coupling) — planned for v1.13.7+ as a
multi-step refactor: helpers first, then handler groups.

## [1.13.5] — 2026-05-19

### Internal — ws_api/ble_find.py extraction (v1.13 step 3)

Step 3 of the v1.13 ws_api refactor. Two BLE live-find handlers
+ two helpers extracted from `ws_api/__init__.py` into their own
file:

  - `ws_ble_capability` (batch trackability lookup)
  - `ws_ble_live_find` (streaming RSSI subscription)
  - `_ble_proxy_label` (helper)
  - `_seen_proxies_for` (helper)

Re-imported back into `ws_api/__init__.py` and added to `__all__`
for backward compat. No behaviour change.

`ws_api/__init__.py` shrinks from 4,692 → 4,474 lines (-218
net). New `ws_api/ble_find.py` is 280 lines.

Cumulative progress against the 5,259-line baseline (pre-refactor):
v1.12.25 _helpers (180 lines) + v1.13.4 identify (866 lines) +
v1.13.5 ble_find (280 lines) = 1,326 lines moved out, with the
monolith down to 4,474 lines. Next: ManagedDevices (similar
isolated profile), then the larger Refine handler family.

## [1.13.4] — 2026-05-19

### Internal — ws_api/identify.py extraction (v1.13 step 2)

Step 2 of the v1.13 ws_api refactor (step 1 in v1.12.25 moved
universal helpers to `_helpers.py`). Find My Device handlers
extracted into their own file:

  - `ws_identify_capability`
  - `ws_identify_entity`
  - `ws_perturbation_guide`
  - `ws_perturbation_test`
  - `_collect_ip_attrs_for_candidates` (helper used only by
    `ws_identify_capability`)

All four handlers re-imported into `ws_api/__init__.py` and added
to `__all__` so external consumers + the `async_register` call
keep working unchanged. No behaviour change.

`ws_api/__init__.py` shrinks from 5,259 lines → 4,692 lines
(-567 lines moved out; the rest is the new import block + helper
imports). New `ws_api/identify.py` is 866 lines (handler bodies
+ docstrings + module-level comment).

Per the dependency-map memory: BLE / IDENTIFY / MANAGED_DEVICES
were flagged as the most-isolated handler groups (no
cross-handler coupling beyond the universal helpers). Identify
is moved first; BLE + Managed Devices come in subsequent steps.

## [1.13.3] — 2026-05-19

### Bundled card v1.10.13 — 💬 Ask AI to write an automation

Pure panel.js bundle of card v1.10.13. No backend code changes.

Card v1.10.13 adds the 💬 button in the panel header → modal with
textarea → calls the v1.13.2 \`home_insights/chat_create_automation\`
endpoint → YAML preview → Apply via existing \`home_insights/apply\`
flow with payload_override.

This completes the competitive-analysis sweep: three gaps closed
across v1.13.0 (StaleAutomationDetector), v1.13.1 (Repairs proposal
dual-emit), and v1.13.2 + v1.13.3 (chat-create-automation
backend + card).

## [1.13.2] — 2026-05-19

### Added — Blank-canvas automation chat WS endpoint (backend MVP)

Third competitive-gap closure. Closes the AI Agent HA flagship demo
("type a sentence, get an automation") using the existing Refine
plumbing.

New WS endpoint `home_insights/chat_create_automation` takes a
free-form user prompt + optional `related_insight_ids` for context.
Wraps the prompt in a virtual `Insight` skeleton, runs it through
the same `refine_insight` pipeline as `ws_refine` and
`ws_refine_automation` — same redactor, same Conversation-agent
failover chain, same audit log.

**Differentiator vs AI Agent HA**: callers can pass
`related_insight_ids` so the LLM is grounded in the user's actual
observed habits. Card UX will surface "I noticed you do X every
evening — make an automation for that?" inline (card UI lands in
v1.13.3 — backend MVP only this release).

**Privacy parity**: full audit row per LLM attempt via
`_audit_attempts`. Failover round-trips appear in the privacy log
identically to ws_refine.

**Validation**: prompt length capped at 2000 chars (Voluptuous
schema). Bad related_insight_ids tolerated silently — dropped from
context rather than failing the call.

Response payload mirrors ws_refine_automation: `refined_payload`
(automation YAML), `rationale`, `diff_summary`, `bytes_sent`,
`bytes_received`, `conversation_id` for multi-turn refinement,
plus `related_insights_used` so the card can show which
observations were factored in.

Card UI ships in v1.13.3.

## [1.13.1] — 2026-05-19

### Added — Dual-emit high-confidence proposals into HA Repairs

Second competitive-gap closure. Extends the existing setup_quality →
HA Repairs bridge (v1.2) to also surface high-confidence proposal-
style insights — schedule, cooccurrence, streak, long_tail,
state_shift, stale_automation, etc. — in **Settings → Repairs**.

Closes the discoverability gap vs Spook: users who don't open the
HA Insights panel still see the insights as standard HA issue
notifications.

**Opt-in via OptionsFlow** (default OFF — `CONF_EMIT_PROPOSALS_TO_REPAIRS`).
Busy installs can produce dozens of high-confidence proposals per
scan; defaulting OFF preserves Repairs as a high-signal surface
until the user explicitly opts in.

**Strict confidence floor: 0.85.** Audit findings keep their existing
0.7 floor (deterministic) but proposals need a higher bar because
they're inferential — a 0.7 schedule could still be coincidence from
a short observation window.

**Lifecycle:**
- Per-scan reconciliation: create new, refresh existing, delete
  obsolete. Idempotent — no-op when nothing changed.
- Flipping the OptionsFlow toggle OFF triggers a sweep on the next
  scan; previously-emitted proposal rows clear out.
- Dismissing / applying an insight in our panel ALSO clears the
  matching Repairs row (existing `clear_issue_for_insight` extended
  to try both prefixes).

Separate issue-id prefixes (`audit:` and `proposal:`) so the two
streams don't collide and either can be swept independently.

## [1.13.0] — 2026-05-19

### Added — StaleAutomationDetector

Competitive-analysis-driven (May 2026) new detector. Closes the gap
vs Danm72/home-assistant-automation-suggestions, whose 30-day stale
list is their most-praised feature.

Walks every `automation.*` entity in the state machine and emits an
`AUTOMATION_IMPROVEMENT` insight when `last_triggered` is older than
30 days (or `None` on a sufficiently-aged automation).

**Confidence tiers** scale with staleness:
- 30–60 days: 0.65
- 60–120 days: 0.80
- 120+ days: 0.92
- Never fired (on an old automation): 0.75

**Skip rules** match the existing AutomationAuditDetector contract:
- `ha_insights:no-audit` label → skip
- Entity in `blocked_entities` → skip
- Disabled automation (state == "off") → skip (user intent)
- Automation younger than threshold → skip (no signal yet)

Each insight payload includes the entity_id, days_stale, and an
`automation.remove_automation` action so the card can render a
delete button. `payload_format="report"` because the action is to
remove, not propose a new automation.

15 tests cover the four staleness buckets, all skip rules, payload
shape, fingerprint stability across re-scans, and the
`last_triggered` parser's defensive paths (None, naive datetime,
ISO string, datetime object, garbage).

## [1.12.25] — 2026-05-19

### Internal — ws_api/_helpers.py extraction (v1.13 step 1)

Step 1 of the v1.13 ws_api refactor. Five universal helpers
(`_get_store`, `_get_buffer`, `_audit_attempts`,
`_resolve_blocked_entities`, `_resolve_preferred_agent_id`,
`_require_admin`) moved from `ws_api/__init__.py` into
`ws_api/_helpers.py`. Re-exported from `__init__` via `__all__`
for backward compat — handler call sites unchanged.

This unblocks the per-feature handler-file moves (refine / audit /
find_my_device / managed_devices / identify, etc.) that have been
parked on a 5,400-line monolith. Each future move can now pull in
the helpers it needs without dragging definitions around.

No behaviour change. Internal-only.

## [1.12.24] — 2026-05-19

### Added — Live power-consumption critical-load gate

New `lib/critical_load_power.py` extends the v1.10.9 keyword-based
critical-load deny-list with a runtime power check. When a `switch`
or `siren` entity has a linked power sensor on the same device
(`device_class: power` or `*_power` name), the WS handler reads the
current draw before firing identify. Above **50 W** → refused with
the reading + sensor entity_id in the error.

Catches the cases the keyword list misses:

- `switch.0x00158d000a1b2c3d` powering a 200 W kitchen refrigerator
- `switch.outlet_4` on a TP-Link strip driving a 90 W home server
- `switch.zigbee_relay_kc` running an aquarium pump + heater
- Any unlabelled EV charger reporting 7.4 kW

Unit normalisation handles `W` / `kW` / `mW`. Missing or
non-numeric state (`unknown`, `unavailable`) treated as "no info"
— doesn't block when the sensor is broken. Lights and media
players bypass entirely (their identify paths don't power-cycle).

Refusal message tells the user exactly which sensor triggered:
"Refused: switch.outlet_4 is currently drawing 92 W (sensor
sensor.outlet_4_power). Above the 50 W safety gate."

## [1.12.23] — 2026-05-18

### Added — Vendor-native identify primitives

New `lib/vendor_identify_strategy.py` maps an entity's integration
platform (from the entity registry) onto the canonical vendor
identify primitive. WS handler now consults it first, falling
back to the generic capability pipeline only when no vendor
mapping exists.

| Integration | Service                                            | Method                         |
|-------------|----------------------------------------------------|--------------------------------|
| ZHA         | `zha.issue_zigbee_cluster_command` cluster=0x0003 cmd=0x00 | Zigbee Identify (3 s breathe)  |
| Zigbee2MQTT | `light.turn_on effect: blink`                      | Z2M Identify effect            |
| Z-Wave JS   | `zwave_js.invoke_cc_api` cc=Indicator (0x87)       | Z-Wave Identify indicator LED  |
| LIFX        | `lifx.effect_pulse mode: blink power_on: false`    | LIFX native HSBK pulse         |
| Yeelight    | `yeelight.start_flow action: recover`              | Yeelight native flow           |

ZHA requires the device's IEEE address; the handler resolves it
from the device registry's `identifiers` field.

Response includes `vendor_native: true` and the method label;
card v1.10.12 surfaces it inline as "⚡ Vendor primitive:
{description}".

Real-install impact: Zigbee bulbs no longer brightness-wiggle —
they trigger the canonical Identify cluster which is what every
Zigbee certification test exercises. Z-Wave devices flash an
indicator LED without cycling the load. LIFX uses its native
pulse instead of brightness changes.

Bundles card v1.10.12.

## [1.12.22] — 2026-05-18

### Added — Device-graph alternative identifier (use LED, not relay)

New `lib/device_alternative_identifier.py` pure-function lib:
takes a list of sibling entities on the same device and picks the
safest identify target.

Priority order:
1. Sibling with `entity_category: diagnostic` AND domain in
   {light, switch} — intentional indicator entities exposed by
   the integration.
2. Sibling with domain `light` — brightness-wiggle is safer than
   switch toggle.
3. Sibling whose entity_id / name contains `led`, `status`,
   `indicator`, `led_ring`, `signal_light`, `mode_light`,
   `activity_led`, etc.

WS handler `home_insights/identify_entity` now performs a
device-registry lookup before firing on switch / siren targets,
substitutes when a safer sibling exists, and surfaces the
substitution in the response (`substitution: {from, to, reason, rule}`).
The card renders the hint inline.

Real-install benefits:
- **Tesla Wall Connector**: pulses the status LED instead of
  cycling the contactor (won't interrupt an active charge session).
- **Shelly Plus 1**: blinks `light.shelly_plus_1_led` instead of
  toggling `switch.shelly_plus_1` (won't cut power to downstream
  load).
- **Sonoff with custom config**: prefers `light.foo_led` over the
  main relay.

Lights and media players pass through unchanged. Critical-load
gate re-runs on the substitute as a defensive check.

Bundles card v1.10.11 with the inline-hint UI.

## [1.12.21] — 2026-05-18

### Bundled card v1.10.10 — Find Device touch-test + watch mode for sensors

Bundles the new card panel.js. No integration-side code changes
— v1.10.10 is purely a card-side enhancement that uses HA's
existing `state_changed` event subscription.

Two new modes in the panel-level Find Device modal:

- **👆 Touch-test** for perturbable sensors (temperature, humidity,
  CO₂, illuminance, sound_pressure, moisture). Baseline + state
  subscription + per-class delta detection.
- **👀 Watch** for motion / occupancy / contact / vibration binary
  sensors. Off→on transition triggers detected state.

No services fired, no aggregate-rate concerns, no power-cycling
risk. Existing fire-mode safety (vendor pairing thresholds,
critical-load deny-list, 5-min ceiling) unchanged.

## [1.12.20] — 2026-05-18

### Fixed — Identify safety floor + vendor-pairing-mode safe patterns

Three concurrent safety fixes for the identify pipeline + bundled
card v1.10.9 with the matching card-side hardening:

**Vendor pairing-mode safe light patterns.** Pre-v1.12.20 our
strobe fired 5 toggles in 1.4 s — that crossed the factory-reset
threshold of **every** major bulb vendor (Tuya 3×, Aqara 5×, Hue 5×,
IKEA 6×, Sengled 10×, LIFX 5×). Running identify on a Tuya bulb
would have factory-reset it. New ordering in `lib/identify_capability.py`:

  1. `FLASH_LIGHT` — native driver flash (no power cycle)
  2. `BRIGHTNESS_WIGGLE` — NEW: dim → bright → dim → bright with
     1.5 s gaps, **no off transitions**, always preferred for any
     light reporting a brightness-capable `color_mode`
  3. `STROBE_LIGHT` — last-resort 2-toggle 3 s cadence, stays
     below all vendor thresholds

Switch toggle reduced from 3× at 500 ms to **2× at 2.5 s** — stays
under Tuya's 3-in-10 s threshold and ends in the starting state.

**Critical-load deny-list.** New `lib/critical_load_keywords.py`
matches medical, HA-host, network infra, refrigeration, EV charger,
pumps, safety / security, and solar / battery keywords against
entity_id + friendly_name. WS handler refuses to fire identify on
matched entities (admin can't override — entity must be renamed).

Critically prevents the self-destruct case: toggling a switch that
powers HA itself (matches `homeassistant`, `hass`, `proxmox`,
`synology`, `raspberry_pi`, etc.) would terminate the running
session mid-identify and could corrupt the recorder DB.

**Power-cycle confirmation.** Methods that interrupt power
(`STROBE_LIGHT`, `SWITCH_TOGGLE`, `SIREN_CHIRP`) now require
`confirm_power_cycle=true` in the WS request. The card sends this
flag after the user clicks through a `window.confirm()` dialog
with a device-class-specific warning. Confirmation is session-
scoped — once acknowledged, subsequent fires proceed silently.

Includes `docs/device_identify_quirks.md` — comprehensive vendor
pairing-threshold table, current safe-pattern math, the
v1.10.10–13 roadmap (sensor touch-test integration into Find Device,
device-graph LED alternative selection, vendor-native primitives
like ZHA `effect: blink` / Z-Wave Indicator CC / LIFX `flash`, and
power-consumption-based critical detection).

### Bundled card v1.10.9

Card-side companion ships the same release:

- Identify modal restores entity state on Stop / Found / uncheck
  (honors Circadian Lighting and pre-identify scenes)
- 1-at-a-time default for multi-entity insights with "Fire all
  simultaneously (advanced)" toggle for power users
- Find Device modal filters to identifiable domains only
  (`light` / `switch` / `media_player` / `siren`); hides
  automation / scene / script / sensor with a pointer to 👆 Touch
  test for perturbable sensors
- Per-domain cadence (light 5 s, media 6 s, siren 10 s, switch 12 s)
- 5-min session ceiling + 30-fire-per-entity cap, both displayed
- Power-cycle confirm() dialog before each first-fire on power-
  cycling method

## [1.12.19] — 2026-05-18

### Added — bundled card v1.10.7 + v1.10.8 panel.js

Two card releases bundled in one integration release:

**Card v1.10.7** — 🔆 Identify looping modal + multi-entity support.
Pre-v1.10.7 the Identify button fired once with a toast outside the
dialog; users couldn't catch the flash. New flow: focused modal with
checkbox per referenced entity, fire every 5s (Find My iPhone style),
"Found it!" / "Stop" buttons. Multi-entity insights (cohorts,
physical_device_link with same device having both light + temp
sensor) work end-to-end — uncheck each row as you find it.

**Card v1.10.8** — 🔍 Find My HA Device in panel header. Top-level
entity picker — not scoped to insights. Open from panel header,
search by entity_id or friendly_name, tick checkboxes on candidates,
loop fires identify on each every 5s until you uncheck (found) or
close (done). Use cases: locate a Zigbee bulb after a rename, find
which Hue light is `light.kitchen_4` of 30 unnamed, identify a moved
switch with a cryptic name. Same backend as per-insight Identify;
different entry point so the feature is discoverable for ALL
entities, not just insight-referenced ones.

Also — v1.10.8 ships an honest BLE-find modal hint. Pre-v1.10.8 the
modal claimed "wave your phone around" but every BLE scanner in a
typical HA install is stationary, so the trend arrow was reading
per-advertisement RSSI noise, not user movement. Updated hint to
say "room-level localization via stationary proxies; true
warmer/colder UX requires a mobile scanner — pending an HA
Companion app active-scan feature." Memory roadmap captures the
upstream contribution path.

## [1.12.18] — 2026-05-18

### Added — bundled card v1.10.6 panel.js (📡 BLE find button surfaces)

Bundles card v1.10.6 which adds the 📡 BLE find button to the insight
detail-dialog action row, alongside v1.10.5's 🔆 Identify entity.

For BLE-trackable entities, one click subscribes to the live RSSI
stream and shows a focused modal with: big dBm readout, color bucket
(HOT/warm/cool/cold), trend arrow (↑↓→), last-seen scanner. Users
walk around with their phone and watch the trend tell them whether
they're closer or further.

Closes the last v1.12.16 UX-audit gap — physical device discovery
that was previously buried inside bulk-area-assign is now one click
from any insight.

## [1.12.17] — 2026-05-18

### Added — bundled card v1.10.5 panel.js (🔆 Identify entity button)

Bundles card v1.10.5 which adds a 🔆 Identify entity button to the
insight detail-dialog action row. Calls `home_insights/identify_entity`
to make the device flash / chime / flicker so users can confirm
which physical device an insight refers to.

Closes the largest "we built it but you can't find it" gap flagged
in the v1.12.16 UX audit. The capability already existed but was
only reachable via the bulk-area-assign dialog; now it's one click
from any insight that pins a primary entity.

## [1.12.16] — 2026-05-18

### Added — bundled card v1.10.4 panel.js (🔬 Diagnostics button surfaces)

Bundles the v1.10.4 panel.js which adds the 🔬 Diagnostics button to
the panel header. The button calls the `home_insights/export_dev_audit`
WS endpoint shipped in v1.12.15 and opens a modal with the redacted
JSON, copy-to-clipboard, and a clear hint about what's safe to share.

This closes the most visible "we shipped this but you can't find it"
gap in the v1.12.x line — until now the dev audit export was only
invokable via HA Developer Tools → WebSocket, which most users will
never discover.

## [1.12.15] — 2026-05-18

### Added — `home_insights/export_dev_audit` WS endpoint

Exposes the `lib/dev_audit.build_dev_audit_bundle` builder (shipped
in v1.12.12 Phase A) via a WS call. Admin-gated. Returns the full
redacted snapshot — install signature, per-detector activity counts,
event buffer signature, config fingerprint — as JSON.

Two intended uses: (1) attach to bug reports, (2) paste into an AI
chat for "are any of my detectors silent for the wrong reason?"
verification. The future v1.13 release will add an opt-in
in-integration "Run dev audit" button on the card.

Invoke from HA Developer Tools → WebSocket:
`{"type": "home_insights/export_dev_audit"}`.

## [1.12.14] — 2026-05-18

### Fixed — audit_rollups slow-warmup on installs with short recorder retention

Real-install SQL audit (2026-05-18) found 100+ entities sitting at
the same cursor position with the `audit_rollups` table **empty**
despite progress being recorded daily. The detector appeared broken
but was actually working — just walking through pre-recorder-retention
empty history before reaching any real data.

The math: with `audit_rollup_window_days = 180` (default) and recorder
retention of 10 days (HA default), the cursor starts at `now − 180d`
and walks forward in 7-day chunks. Each batch advances at most 56
days per entity. So it takes **~3 batches per entity** before the
cursor reaches recorder-retained data. During warmup, every query
returns empty → cursor advances → no rollups written → user sees a
broken-looking detector.

Fix: `_probe_recorder_oldest_ts()` probes the recorder's deepest
retained data **once per batch** (cheap — ~14 1-hour probe queries
total). Initial cursor is then clamped to `max(now − window_days,
recorder_oldest_ts)`, so warmup is **eliminated**: the first batch
starts producing rollups immediately on installs with short retention.

The probe mirrors the strategy in `ws_recorder_status` so the WS
endpoint and the rollup engine see the same retention number.

3 regression tests assert the probe helper exists, the per-entity
function accepts the clamp kwarg, and the probe ladder covers
typical recorder retentions (10–365d).

## [1.12.13] — 2026-05-18

### Fixed — cascade-event filter for cooccurrence + lagged_correlation

v1.12.12 documented this as a remaining gap. Closing it now.

Pre-fix: a user-created HA automation like _"when front_door opens,
turn on lounge_light"_ would re-emit as a CooccurrenceDetector
"automate this!" proposal because:
- The pair has no structural relationship (not scene/script/group
  members), so v1.5.20 `_pair_is_related` doesn't catch it
- HA executor latency (often 1-3s) is above the v1.7
  coupling-strength TIGHT threshold (<500ms), so coupling demotion
  doesn't catch it either
- The conflict scanner's `_already_automated` strict pattern match
  may miss it if the automation's trigger doesn't textually match
  the detector's proposed YAML

Fix: drop events with `context.parent_id != None` at the event-
collection step. Those events are downstream consequences of another
HA event (automation action, script execution, scene activation).
Genuine human-driven events have `parent_id=None` regardless of
whether `user_id` is set (dashboard tap, voice, mobile app, physical
sensor — all are root events).

LaggedCorrelationDetector inherits from CooccurrenceDetector, so
the fix applies to both. 3 new regression tests cover the
automation-driven, manual-user, and device-originated cases.

Remaining low-priority data-quality reviews tracked for v1.12.15+:
orphan_device, phone_charge_reminder, weather_correlation.

## [1.12.12] — 2026-05-18

### Fixed — human-vs-device fingerprint, multiple real-install bugs

Real-install SQL audit (2026-05-18) on the user's HA database revealed
three correctness bugs. All three trace to the same root: detectors and
filters were treating "looks human" and "looks device" as binary
verdicts when they're actually multi-signal classifications.

#### 1. `_is_low_confidence_filler` (v1.12.10) only checked one of six signals

The card's "🤖 device-managed" pill triggers on any of THREE strong
signals (`timing_class=device_likely`, `cooccurrence_class=isolated`,
`persistence_class=fixed_cycle`) OR 3+ stacked soft signals. The
Python filter only checked `timing_class=device_likely`, so a streak
with `persistence_class=fixed_cycle` (e.g. user's inverter switch at
10% confidence) rendered the device-managed pill but escaped
suppression.

Fix: new canonical `lib/device_managed_signal.py` exposes the verdict
as a pure function. `HumanLikelihoodFeatures.payload_keys()` now
stamps `_is_device_managed: bool` on every insight payload at emit
time — single source of truth instead of re-computing the rule in
two languages. The filler filter reads this canonical field, with a
recompute fallback for pre-v1.12.12 stored payloads.

13 new tests in `test_lib_device_managed_signal.py` cover all 7
classification combinations including the user's exact real-install
payload.

#### 2. `manual_habit` emitted 100%-confidence "you manually set …" on automation-driven events

The user reported a 7-day `light.porch -> off at ~23:27 (±0 min)`
insight claiming "you manually set" — but the light runs on a Hue
schedule inside the Hue bridge, never touched by the user. The
detector's `is_manual` classifier checked HA `context.user_id` +
`context.parent_id`, falling back to "local-integration entity =
physical switch" for events with no HA-side context. Hue is in the
local allow-list, so Hue-bridge schedules slipped through.

Real human jitter across multiple days is **≥15 seconds**. Zero or
near-zero stddev is the fingerprint of an automation or vendor-side
scheduler — even when the source event carries no HA context.

Fix: added `_TIME_STDDEV_MIN_MIN = 0.25` (15s) lower-bound gate
alongside the existing `_TIME_STDDEV_MAX_MIN = 45.0` upper bound.
Below the lower bound, the detector returns None instead of emitting
the misleading "you manually set" insight.

#### 3. `long_tail` proposed dangerous auto-off for fixed-cycle devices (CRITICAL)

Real-install incident: detector emitted at 100% confidence:

> `switch.inverter_5010kmsc252s0046_switch stays active for ~584 min (11 times in 14d, max 609 min). Auto-off after 120 min?`

That switch is a **solar inverter** that runs ~10 hours every day from
sunrise to sunset. Applying the suggested auto-off automation would
have **shut off solar generation every afternoon**. Same risk applies
to pool pumps, scheduled HVAC, vendor-side appliance timers.

The detector saw "active span ≥ threshold" repeated ≥3 times and
emitted full confidence. It had no signal to distinguish "user forgot
to turn off" from "device's intentional duty cycle."

Fix: added `_is_fixed_duty_cycle()` gate. Computes coefficient of
variation across all observed long spans. If CV < 5% (i.e. every
recorded duration is within ±5% of the average), the device has a
fixed duty cycle and we **suppress entirely** rather than risk
breaking a device the user relies on.

User's actual inverter pattern (~584 min mean, ~5 min stddev, CV ≈
0.85%) was the calibration target. Real-human "forgot to turn off"
patterns have CV well above 50% and pass through unchanged. 7 new
tests cover boundary, defensive, and the exact real-install spans.

This is the second pattern in v1.12.12 of "detector treats
human-vs-device as binary" — same root cause as Bug 1, but in a
detector that builds **applyable automations** rather than just
displaying. The blast radius is higher; the fix is more conservative
(hard suppress, not "downgrade confidence").

#### 4. `seasonality` had the same robotic-precision blind spot

SeasonalityDetector finds weekly patterns ("every Tuesday at 8am").
Same architecture as ManualHabitDetector: time-bucketed events,
stddev gate on top — but it *never checked `context.user_id`* AND
had **no lower bound** on stddev. So a Tuya weekly schedule firing
every Tuesday at exactly 8am across 4 weeks would emit at high
confidence as "you do this every Tuesday — automate it!" — even
though the user can't (the vendor device runs the schedule).

Fix: added `TIME_STDDEV_MIN_MIN = 0.25` (15s) — same threshold
as manual_habit's lower bound. A unit test asserts the two stay in
lockstep so a future threshold update propagates cleanly.

#### 5. Detector audit completed — remaining gaps deferred to v1.12.13

Audited every detector for the same human-vs-device blind spot. Most
are SAFE (informational tier, no applyable output) or already
defended by `assess_human_likelihood` + the canonical
`_is_device_managed` field.

Remaining gaps tracked for **v1.12.13**:

- **cooccurrence** + **lagged_correlation**: missing `context.parent_id`
  filter for cascade events. Existing defences (delta-stddev gate,
  hierarchy `_pair_is_related`, coupling-strength TIGHT demotion,
  conflict-scanner `_already_automated`) cover most cases but a
  user-applied automation whose pattern doesn't strict-match the
  conflict scanner could still re-emit at lower confidence.
- **orphan_device**: automation-driven recovery isn't distinguished
  from user-driven; low-risk because action is just `notify`.
- **phone_charge_reminder**: drain-rate model can be polluted by
  automations that toggle charging state; low-risk because the
  proposed automation is time-triggered, not state-reactive.
- **weather_correlation**: habit-time observations can be polluted
  by weather-aware automations; output is report-only so no apply
  risk.

#### 6. Dev audit export — for community + LLM-driven verification (preview)

New `lib/dev_audit.py` produces a redacted snapshot of install
signature + per-detector activity + config fingerprint as a single
JSON dict. Designed for two workflows:

- **Bug reports**: attach the JSON instead of describing your install
- **LLM verification (opt-in, planned for v1.12.13)**: send the same
  JSON to your chosen LLM agent to ask "are any of my detectors
  silent for the wrong reason?"

The WS endpoint + card button land in v1.12.13. v1.12.12 only ships
the builder so the canonical schema can settle before exposure.

### Documented — the human-vs-device fingerprint

For other detectors to apply the same logic, the canonical fingerprint
order is:

1. HA `context.user_id` — definitive when set (human triggered via
   UI / voice / mobile app)
2. HA `context.parent_id` — definitive when set (event is a
   downstream consequence of another HA event)
3. Timing stddev across N days:
   - `<15s` → device/automation (robotic precision)
   - `15s–5min` → indeterminate (could be voice routine or strict
     schedule)
   - `>5min` → human
4. Persistence (how long in new state):
   - `CV<5%` → fixed device timer
   - `CV>30%` → human-controlled
5. Co-occurrence (≤±5s consistency across days) → shared source

Steps 1–2 are HA-native semantics; 3–5 are the v1.5.x grader libs
already wired through `HumanLikelihoodFeatures`. v1.12.12 makes the
verdict canonical via `_is_device_managed`.

## [1.12.11] — 2026-05-17

### Added — 🆕 newly-added entity badge

Pairs with card v1.10.3. When an insight's primary entity was added
to Home Assistant within the last 14 days, `ws_list` now stamps
`entity_age_days` on the payload; the card surfaces it as a sky-blue
`🆕 added N days ago` badge next to the title and in the detail
dialog.

The badge surfaces the dataset-window limit visually. v1.12.9's
state_shift fix gates the detector internally on
`pre_shift_event_count`, but other detectors still surface findings
on brand-new entities — the badge gives users the context to spot
"this is hedged because the entity is 4 days old," instead of
treating every emitted insight as equally trustworthy.

`entity_age_days` is set ONLY when the entity is within
`NEWLY_ADDED_THRESHOLD_DAYS` (14). Absent field → no badge. Older
Home Assistant builds (pre-2024.10) without
`RegistryEntry.created_at` simply never get the field — graceful
degradation.

Pure helpers live in `lib/entity_age.py` (`days_since_added`,
`is_newly_added`); 11 unit tests cover boundary, defensive, and
clock-skew edges.

Bundled panel.js refreshed from card v1.10.3 so the sidebar panel
shows the badge too.

## [1.12.10] — 2026-05-17

### Fixed — setup_quality "Manage" links + low-confidence filler

Two real-install UX issues from user testing on v1.12.9.

#### 1. `setup_quality` Manage buttons now go to in-HA pages

**Reported**: in the PhoneActivity feature card at GREAT tier,
the "Manage" button pointed at
`https://companion.home-assistant.io/` — the public marketing
site. Useful for a user who DOESN'T have the app yet, dead
weight for one who does (the case this user was in).

**Fixed**:
- `phone_activity` recipe now links to
  `/config/integrations/integration/mobile_app`. That URL works
  for both states — opens HA's mobile_app integration page for
  installed users (manage devices, re-pair) and surfaces the
  add-integration dialog for users without it. Label changed
  from "Get the Companion App" to "Manage mobile devices."
- `manual_habit` recipe previously had `setup_url: None` because
  the remedy is behavioural ("use HA for a week"). User
  reported the missing button felt like a dead end — there was
  nowhere to GO to watch the feature work. Now links to
  `/ha-insights` (the panel itself) so users can watch
  manual_habit insights surface as the buffer fills. Label:
  "View HA Insights panel."

#### 2. Suppress low-confidence already-automated / device-managed insights

**Reported**: panel showed ~5 filler insights at 10-15%
confidence, all marked `🔁 already automated` or
`🤖 device-managed`. Specifically:
- `switch.main_room_led_bar → off 8 days at ~23:27` (10% conf,
  already automated)
- `light.back_garden_lights → off 5 days at ~23:27` (11% conf,
  device-managed)
- `switch.inverter_*_switch → on 3 days at ~07:22` (10% conf,
  device-managed)

None had action value: the pattern is either already automated
or device-internal logic, AND the detector wasn't even confident
in the pattern itself.

**Fixed**: new `_is_low_confidence_filler` filter in
`detectors/__init__.py::run_all_detectors`. Drops insights where
`confidence < 0.50` **AND** (either `conflicts_with` non-empty
**OR** `_timing_assessment.timing_class == "device_likely"`).

Tested both edges:
- High-confidence shadowed insights (≥ 0.50) preserved (user
  might want to refine/replace the existing automation)
- TIGHT_PATTERN timing class preserved (different signal from
  DEVICE_LIKELY — indicates coincident user routine, not
  device-internal logic)
- Low-confidence insights WITHOUT filler signals preserved
  (some legitimate emerging patterns start at low confidence)

13 unit tests in `test_low_confidence_filler_filter.py`.

### After this update + scan

User's panel should drop ~5 noise insights:
- All low-conf state_shift on newly-added entities (v1.12.9 fix)
- All low-conf `🔁 already automated` schedule/streak filler
- All low-conf `🤖 device-managed` schedule/streak filler

Net effect: 28 insights → ~18 actionable. Higher signal-to-noise.

## [1.12.9] — 2026-05-17

### Fixed — real-install false positives (StateShiftDetector)

User on v1.12.8 reported 5 state_shift insights that were
all the same class of false positive: devices that were just
added to the install registered as a "behavioral shift" from
0/day to N/day.

| Entity | "Shift" claim | Reality |
|---|---|---|
| 4× `switch.adguard_home_*` + 1× `binary_sensor.nas_security_status` | 0 → 11/day, 7 days ago | AdGuard + Synology integrations added 7 days ago |
| `light.passage`, `binary_sensor.porch_sensor_motion` | 0 → 131/day & 50/day, 10 days ago | Newly-added devices |

The v1.12.7 guard checked `(days_of_history < 5 AND
pre_shift_events < 10)` — but `days_of_history` was computed
from the **GLOBAL earliest event timestamp** across all
entities. If any other entity in the install had data older
than the cp, this check passed even when the current entity
had zero pre-shift events. Real installs always have at
least one long-running entity, so the days-AND guard never
fired in practice.

### What changed

Dropped the days-of-history check entirely. The guard is now
simply:

```python
if pre_shift_event_count < _MIN_PRE_SHIFT_EVENTS:  # < 10
    continue  # suppress
```

`pre_shift_event_count` is computed per-entity from
`day_buckets` (already in scope), so it correctly reflects
THIS entity's pre-shift activity. Zero events before the
"shift" → device-started-reporting; suppress.

#### Edge case: device that went legitimately silent

If an existing device fell offline for the entire pre-shift
period (sensor failure, broken integration), its
pre_shift_event_count is also 0 → also suppressed.

That's acceptable: the user can't usefully distinguish
"newly added device" from "previously broken device coming
back online" without registry timestamps we don't track. The
shift itself has no actionable signal in either case.

#### Test update

`test_state_shift_detector.py::test_data_window_guard_constant_exists`
now asserts that `_MIN_PRE_SHIFT_DAYS` is **absent**
(intentionally removed in v1.12.9), and only
`_MIN_PRE_SHIFT_EVENTS` remains.

### What v1.12.9 does NOT yet fix

Real-install testing also surfaced (deferred to v1.13):

- **Schedule + streak insights with <20% confidence on
  already-automated entities** (e.g.
  `switch.main_room_led_bar` at 10% conf with `🔁 already
  automated` tag). These produce filler insights that have
  no action value. Fix: per-detector post-emit filter that
  drops `confidence < 0.50` when the insight has tags
  `["already_automated", "device_managed"]`.

- **Newly-added entity badge** — even after start-of-data
  state_shift insights are suppressed, the user may still
  see *other* detectors emit on a newly-added entity (e.g.
  schedule with 1-day history). A "Newly added N days ago"
  badge on insight rows would give context without
  suppressing legitimate findings.

## [1.12.8] — 2026-05-17

### Added — card-renderer + test backfill (agent review pt. 2)

Second half of the agent-review fix pass. v1.12.7 covered the
critical privacy + composition + math issues; this release
handles the remaining rendering + test gaps.

#### Bundle card v1.10.2 panel.js — specialized renderers

Card v1.10.2 adds `_renderCardBody()` with per-payload-key
dispatch for the v1.7+ detectors that were rendering as raw JSON:

- `_state_shift` (v1.8.2 StateShiftDetector) → "Routine shift
  detected" body with date, pre/post means, magnitude
- `_physical_device_link` (v1.11.0 + v1.12.7) → "These look like
  the same physical device" body with entity pair, Pearson r,
  lag explanation. Reads both new `entity_id`/`peer_entity_id`
  AND legacy `entity_a`/`entity_b` for cached-insight back-compat
- `_location_proposal` (v1.11.5) → "Probably / Almost certainly
  in <area>" with alternative areas + advisory-only callout

Integration-only panel users get the rendering improvements for
free via this bundle. See `ha-insights-card` v1.10.2 changelog
for full UI details.

#### `tests/test_lib_identify_capability.py` — test backfill

The v1.10.0 `identify_capability` lib shipped with no dedicated
test file despite being used by two WS handlers. Added 17 tests
covering each tier (FLASH_LIGHT, STROBE_LIGHT, PLAY_CHIME,
SIREN_CHIRP, SWITCH_TOGGLE, NONE), bitwise feature checking,
defensive handling of malformed attributes, and stability of the
`IdentifyMethod` enum values that the WS contract serializes.

### Roadmap status after this release

**Agent-review tracks A-E fixes:**
- ✅ Track A (math) — TE noise floor raised; perturbation
  STDDEV_FLOOR unit-coupling noted as v1.13 calibration item;
  ChangepointKind.VARIANCE_SHIFT docstring TODO
- ✅ Track B (composition) — physical_device_link fingerprint
  renamed; managed_externally walker now picks up; setup_quality
  recipe wording fixed
- ✅ Track C (modal) — specialized card renderers added for
  v1.7+ payloads; raw-JSON-in-modal regression closed
- ✅ Track D (privacy) — identify_capability + ble_capability now
  admin-gated; payload-field privacy review confirmed clean
- ✅ Track E (tests) — identify_capability + physical_device_link
  + state_shift lib/detector tests added; WS endpoint integration
  tests deferred to v1.13 (needs pytest-homeassistant-custom-
  component setup)

**Ready for beta announcement** after real-install validation.

## [1.12.7] — 2026-05-17

### Fixed — agent-review pass before beta launch

Five-track parallel agent review (math / composition / modal /
privacy / test-coverage) flagged a batch of issues. The
**critical-severity ones land here**; rendering + remaining test
backfill follow in v1.12.8.

#### Privacy: admin-gate two unauthenticated WS endpoints (CRITICAL)

- **`home_insights/identify_capability`** was readable by any
  connected user. Response leaks the home's friendly-name
  inventory (`name_quality.chosen_name` — "Kitchen Floor Lamp",
  "Master Bedroom Door") AND the dedup `same_as` array (which
  entities the system thinks are duplicates of which). Both
  reveal device topology and naming scheme. Now admin-gated.
- **`home_insights/ble_capability`** was also readable by any
  connected user. Response leaks the Bluetooth address of every
  BLE-tracked device. Now admin-gated.

#### Composition: rename `physical_device_link` fingerprint keys (HIGH)

`entity_a`/`entity_b` matched neither
`lib/managed_externally.py::_is_entity_field_key` nor the cohort-
dedup bucket-key logic, so:
- Insights from this detector could NOT be suppressed via the
  v1.7.7 "managed externally" device flag.
- The cohort dedup never grouped multiple duplicates of the same
  entity — panel flooded on installs with many duplicate pairs.

Renamed to `entity_id` (canonical sorted-first) + `peer_entity_id`
(suffix matches the `*_entity_id` walker rule). Payload's
`_physical_device_link` block uses the same names for consistency.
**New tests in `test_physical_device_link_detector.py`** verify
the renamed keys + that fingerprints group by `entity_id` for
correct cohort behaviour.

#### Math: data-window suppression in StateShiftDetector (HIGH)

User-reported false positive:
> "Daily-count for light.main_bedroom averaged ~0.0/day before
> 2026-05-07 and ~48.2/day since."

Reality: the recorder only had 10 days of history. The "pre-shift"
period was just the empty window before the device was added —
not a behavioral shift.

Added two checks: if the changepoint sits within
`_MIN_PRE_SHIFT_DAYS=5` days of the buffer's earliest event AND
the pre-shift period contains < `_MIN_PRE_SHIFT_EVENTS=10` events,
suppress the insight. Real shifts on devices with enough history
still emit. **New tests in `test_state_shift_detector.py`** verify
both directions (start-of-data → suppressed; real shift with
adequate history → not suppressed).

#### Math: raise transfer-entropy noise floor 0.05 → 0.10 (MEDIUM)

The plug-in MLE entropy estimator is positively biased on small
samples (Miller-Madow correction unimplemented). At n=300 with
4-symbol alphabets, uncorrelated streams produce spurious TE of
0.1–0.3 bits. The previous 0.05 floor was below that bias and
let MLE noise pass as "directional flow."

Raised to 0.10 in `lib/transfer_entropy.py`. Existing tests still
pass; the heuristic is more conservative now. Bias-correction is
a v1.13 task if calibration data shows the new floor is still too
generous.

#### Composition: setup_quality recipe rewording (MEDIUM)

The "Research-backed pattern detection" recipe (v1.12.1) advised
"increase recorder retention" — misleading because StateShift +
LaggedCorrelation use the 14-day event buffer, not the recorder.
Reworded the `next_step`, scenarios, and tiers to split the two
data sources: event buffer (passive accumulation) for StateShift +
LaggedCorrelation; recorder retention for FrequencyAnomaly +
Seasonality.

### Deferred to v1.12.8 (not blocking the privacy fixes above)

- Card `_renderCardBody()` for `_state_shift`, `_physical_device_link`,
  `_location_proposal`, `_frequency_anomaly` payload types — currently
  rendering as raw JSON.
- Test backfill for `location_proposal`, `identify_capability` lib,
  and the 3 admin-gated WS endpoints (`identify_entity`,
  `perturbation_test`, `ble_live_find`).

## [1.12.6] — 2026-05-17

### Changed

- **Bundle card v1.10.1 panel.js** — picks up the maturity-badge
  alignment fix (Find-My-Device buttons now use the existing
  🟡 BETA / 🧪 EXPERIMENTAL convention instead of the duplicate
  visual language introduced in v1.10.0).

Bundle-only. Card source of truth: ha-insights-card v1.10.1.

## [1.12.5] — 2026-05-17

### Changed

- **Bundle card v1.10.0 panel.js** — picks up the 📡 BLE live-find
  button + RSSI scope modal that subscribes to v1.12.0's
  `home_insights/ble_live_find` endpoint. Integration-only users
  (no standalone HACS card) get the third Find-My-Device axis.
- Also picks up explicit **EXP/BETA maturity badges** on every
  Find-My-Device button so beta testers see the maturity of each
  feature at a glance (🔆 stable; 👆 BETA; 📡 EXP).

Bundle-only change. Card source of truth: ha-insights-card v1.10.0.

## [1.12.1] — 2026-05-17

### Added — setup_quality covers the v1.6+ research detectors

`SetupQualityDetector` previously only reported on 4 features
(phone_activity, presence_inference, manual_habit, goal_tracker).
The 15+ detectors added since v1.6 (button_press_habit,
frequency_anomaly, state_shift, seasonality, lagged_correlation,
physical_device_link, location_proposal, weather_correlation,
automation_audit, …) had no setup-quality coverage at all — new
users could see "your install is GREAT" while ⅔ of the detector
library couldn't fire.

#### Four new recipes

1. **Research-backed pattern detection** —
   FrequencyAnomaly, StateShift, Seasonality, LaggedCorrelation.
   Tiered on recorder retention (7d for basic, 14d for weekly
   seasonality). Without 7d retention the tier is USELESS with a
   direct link to HA's recorder docs.

2. **Cross-integration dedup + room inference** —
   PhysicalDeviceLink (v1.11.0) + LocationProposal (v1.11.5) +
   Find-My-Device buttons. Tiered on ≥2 area-tagged siblings per
   device_class (needed for the correlation math to have anything
   to compare). Links to the device dashboard.

3. **Per-area hardware coverage** — explicit gap analysis: how
   many areas have motion/temp/contact/lux sensors? Smart-button
   `event.*` entities? A weather integration? Tier ladder maps
   directly to detector unlocks. Links to device dashboard.

4. **Automation audit** —
   AutomationAuditDetector. Tiered on existence of any HA
   automations + recorder retention for drift detection.

#### Nine new predicates

`_device_class_areas` aggregator + per-class helpers
(`_has_motion_coverage`, `_has_temp_coverage`,
`_has_multi_temp_per_class`), entity-presence checks
(`_has_event_entities`, `_has_weather_integration`,
`_has_active_automations`), and retention thresholds
(`_has_recorder_7d`, `_has_recorder_14d`). All return
`(bool, detail_str)` so the recipe advice can include specifics
like "5/12 areas with motion sensor."

### Why this matters for the beta-launch story

Per the user's framing: "I'll test fundamentals, beta testers
will enhance." Setup quality is the first impression — if it
lies about coverage, beta testers report "the integration says
it's working but I see nothing happening." With this change,
new users see exactly which detectors are firing, which ones
are waiting on data/history, and which ones are blocked by
hardware gaps the user can choose to fill (or not).

This also lays the foundation for **v1.15
HardwareSuggestionDetector** — the per-area coverage predicates
here are the same primitives that detector will use to emit
actionable "consider adding a motion sensor in living_room"
insights.

## [1.12.0] — 2026-05-17

### Added — BLE live-find backend (Find My Device, axis 3)

The v1.10 Find-My-Device feature covers two capability axes:
🔆 identify-capable (active devices) and 👆 perturbation
(passive sensors). v1.12 adds the third: **📡 BLE-trackable**
— real-time RSSI scope ("warmer/colder" UX) using HA's
bluetooth integration.

#### Why BLE is the only "warmer/colder" signal that works

- **WiFi RSSI**: device→AP, doesn't change as you walk. Useless.
- **Zigbee LQI**: device→coordinator, same problem. Useless.
- **Matter/Thread**: mesh-based, same problem.
- **BLE**: bidirectional + short-range (~10 m). When the user's
  phone (companion app's BLE scanner) or a portable proxy is the
  receiver, RSSI tracks the user's movement.

#### `lib/ble_capability.py`

Pure: given an entity, derive whether it's BLE-trackable and
what its address is.
- Primary signal: `("bluetooth", "AA:BB:..")` in
  `device.connections`
- Fallback: `bluetooth_address` / `mac` / `address` in state
  attributes (for BTHome and similar)
- Normalization: all addresses canonicalized to
  `AA:BB:CC:DD:EE:FF` regardless of input separator/case
- Rejects Zigbee IEEE (8-byte) addresses to avoid
  misclassification

12 unit tests covering format normalization, attribute
fallback, Zigbee IEEE rejection, pluralization corners.

#### WS endpoints

- `home_insights/ble_capability` — read-only batch query.
  Returns per-entity `{is_trackable, bluetooth_address,
  seen_by_proxies, reason}`. Card uses this to know which rows
  should show the 📡 button.
- `home_insights/ble_live_find` — admin-gated streaming
  subscription. Opens a server-side BLE advertisement callback
  for the given address; forwards each advertisement received
  to the WS client with raw + EMA-smoothed RSSI (~3 s effective
  window) + which proxy saw it. Auto-unsubscribes when the
  client disconnects via HA's WS framework.

#### What's next

- v1.12.5 / card v1.10.0 — UI for the 📡 button + live RSSI
  scope (warm/cold buckets, trend arrows, optional haptic via
  companion app, multi-proxy triangulation view for users with
  several ESPHome BLE proxies)

### Roadmap progress

- v1.10 Phase A + B (identify + perturbation) ✅
- v1.10.3 + .4 static dedup hint ✅
- v1.11.0 correlation-based dedup ✅
- v1.11.5 location proposal ✅
- **v1.12.0 BLE live-find backend** ✅ (THIS)
- v1.12.5 BLE live-find UI (card v1.10.0) — next
- v1.13 survival analysis (lifelines AFT)
- v1.14 sequence mining (prefixspan)
- v1.15 HardwareSuggestionDetector
- v1.16 AdaptiveFeedbackDetector
- v2.0 per-person presence (with MRAR / Gamut PHD primitives)

## [1.11.5] — 2026-05-17

### Added — LocationProposalDetector

The detector pair to v1.11.0's dedup work. Same correlation
primitives (`lib/correlation_primitives.py`), different
application: instead of finding entities that look like the same
physical device, find the AREA an unassigned entity probably
belongs to by similarity to that area's tagged siblings.

> **Probably in Living Room**: `sensor.bt_a4c138_temperature`
> matches 3 tagged temperature siblings at median r=0.91.

#### Why it works

Spatial correlation in environmental signals is strong:

- Two temp sensors in the same room share the same air column;
  their diurnal curves track within minutes.
- Two humidity sensors react to the same cooking / shower event.
- Two illuminance sensors near the same window track sunrise + cloud
  passage together.

For each unassigned sensor, the detector computes correlation
against every already-tagged sibling of the same `device_class`,
groups by area, and picks the area with the highest median r. Above
a 0.75 threshold → emit PATTERN_OBSERVATION; above 0.90 → label
"almost certainly in X" instead of "probably in X."

#### `detectors/location_proposal.py`

BETA. Pre-filters:

- Only `sensor` domain (binary domains use cooccurrence / timing
  detectors instead)
- Only entities without an `area_id`
- Only when the entity's `device_class` has ≥ 2 area-tagged
  siblings in some area (otherwise no comparison data)
- ≥ 30 events per entity in the 7-day lookback
- Hard cap 10 proposals per scan

Median r per area (robust to one window-side outlier) over Pearson
of time-aligned 10-min bins, lag-tolerant within ±2 bins.

#### Insight payload

`_location_proposal` block with:
- `proposed_area_id`, `proposed_area_name`, `median_r`, `n_siblings`
- `alternatives: [{area_id, median_r, n_siblings}]` — top 3
  next-best candidates so the user can see they're picking the
  best of several rather than the only one above threshold.

**Advisory only.** Never auto-assigns. User opens the insight,
sees the candidate area + alternatives, and either confirms
(applies through the area-assign flow) or overrides.

### What's still open for v1.12+

- Cross-modal inference: a humidity sensor that doesn't match any
  humidity siblings might still match the temp siblings in
  `Bathroom` because the cooking/shower events happen in the same
  place. v1.12 future work.
- "I'm not sure" surface: when no area scores above threshold,
  could emit a softer "couldn't auto-locate this; try touch test"
  insight pointing at v1.10 Phase B. v1.12.x.

### Roadmap progress

- v1.10 Phase A + B (identify + perturbation) ✅
- v1.10.3 + v1.10.4 static dedup hint + 🔗 pill ✅
- v1.11.0 correlation-based dedup ✅
- **v1.11.5 location inference** ✅ (THIS)
- v1.12 BLE live-find
- v1.13 survival analysis
- v1.14 sequence mining
- v1.15 HardwareSuggestionDetector

## [1.11.0] — 2026-05-17

### Added — PhysicalDeviceLinkDetector (correlation-based dedup)

v1.10.3 catches duplicate entities via **static identifiers** —
shared MAC, Bluetooth address, Zigbee IEEE, etc. That covers
roughly 50–70 % of typical duplicates. The rest hide:

- Govee Cloud + Govee BLE — different internal IDs in each
- Aqara via Zigbee2MQTT + same device via ZHA mid-migration
- HACS custom component + official integration on same hardware
- ESPHome reflash with the old cloud entry still lingering

For those, the only remaining signal is the values themselves.
If two temperature sensors report implausibly correlated values
over a week (r > 0.95 across hundreds of aligned samples), they
are almost certainly the same physical sensor seen through two
integrations.

#### `lib/correlation_primitives.py`

Pure functions: Pearson r with zero-variance protection, fixed-
bin time-alignment of arbitrary-cadence event streams (10 min
default — absorbs cadence differences while preserving real
coupling), carry-forward interpolation for stateful sensors,
small-lag scan (±2 bins) to tolerate clock drift between
integrations. 18 unit tests.

#### `detectors/physical_device_link.py`

BETA `PATTERN_OBSERVATION` detector. Pre-filters aggressively:

- Same `device_class` only (a temp sensor and a humidity sensor
  accidentally correlating isn't a duplicate finding)
- Same-`device_id` pairs skipped (HA already groups those)
- Pairs already flagged by static dedup skipped (no piling on)
- Minimum 30 events per entity in 7-day lookback
- Minimum variance gate (a battery sensor stuck at 100 % would
  "correlate" with anything)
- Hard cap of 15 insights per scan

When a pair clears all filters and r > 0.95, emits a
PATTERN_OBSERVATION explaining the finding, the matching r,
the lag at which it was found, and the common scenarios
(Tuya Cloud + BLE, Govee Cloud + Govee BLE, Hue Bridge +
Matter bridging, etc.). Suggests the user mark one as
"managed externally" (v1.7.7) or remove the duplicate
integration.

#### Roadmap progress

- v1.10 Phase A + B (identify + perturbation) ✅
- v1.10.3 static dedup hint ✅
- **v1.11.0 correlation-based dedup detector** ✅ (THIS)
- v1.11.5 LocationProposalDetector (next — uses the same
  correlation primitives to score unassigned entities against
  area-tagged siblings)
- v1.12 BLE live-find
- v1.13 survival analysis
- v1.14 sequence mining
- v1.15 HardwareSuggestionDetector

#### Calibration caveats (Maturity.BETA)

r > 0.95 is the "implausibly high" threshold. Two real sensors
in the same room typically correlate r ≈ 0.85–0.92 — there's
room above that band that's genuinely "same physical device"
territory, but the lower edge will need real-install
calibration. Pre-filtering (same device_class, same-device_id
skipped, static-dedup skipped, min variance) keeps false-
positives manageable; field data will tune the threshold.

## [1.10.8] — 2026-05-17

### Changed

- **Bundle card v1.9.0 panel.js** — picks up the polish pass
  paired with v1.10.7's new `perturbable` field. Integration-only
  users (no standalone HACS card) get the server-authoritative
  perturbable-check, the `unit_of_measurement`-aware touch-test
  result, and the z-index fix that prevents the touch-test modal
  from rendering behind the parent dialog.

  Bundle-only change. Card source of truth: ha-insights-card
  v1.9.0.

## [1.10.7] — 2026-05-17

### Changed

- **`identify_capability` response now includes `device_class`,
  `perturbable`, and `perturbation_state` per entity.** Card no
  longer has to maintain a parallel hardcoded list of perturbable
  device_classes — it just reads `cap.perturbable` to decide
  whether to render the 👆 touch-test button. Single source of
  truth is now `lib/perturbation_capability.py`.

  `perturbation_state` is `"supported"`, `"explicitly_unsupported"`
  (PM2.5/battery/etc — documented reasons), or `"unknown"` (no
  device_class set or class we don't know about). The card can
  use this to differentiate "touch test won't help" from "touch
  test might work, but no instructions yet."

  Additive change — old card versions ignore the new fields with
  no breakage. Card v1.9.0 will consume them and drop its
  hardcoded duplicate set.

## [1.10.6] — 2026-05-17

### Changed

- **Bundle card v1.8.0 panel.js** — closes the v1.10 Find-My-Device
  Phase B loop in the integration-only panel surface. Picks up
  the 👆 touch-test button + modal that fires v1.10.5's
  `home_insights/perturbation_test`, runs the listening window
  countdown, and displays the ranked result — including the
  **elimination banner** when the entity that spiked isn't the
  one the user clicked.

  Combined with v1.10.4 (🔗 dedup pill) and earlier bundles, the
  bulk-area-assign dialog now has the complete Find-My-Device
  UI surface: sorted worst-name-first, tier badges, 🔆 identify
  for active devices, 👆 touch-test for passive sensors,
  🔗 dedup pill for likely duplicates.

  Bundle-only change. Card source of truth: ha-insights-card
  v1.8.0.

## [1.10.5] — 2026-05-17

### Added — Find My Device, Phase B backend (perturbation touch-test)

Phase A made entities that can announce themselves discoverable
(🔆 button fires `light.flash` / `media_player.play_media` / etc.).
Phase B handles the passive sensors that can't — temp, humidity,
illuminance, CO₂, sound. The user **physically perturbs** the
sensor (touches it / breathes on it / shines a light), HA Insights
watches every entity of the same `device_class`, and tells the
user which entity actually spiked.

**Killer outcome — elimination.** When the user touched what they
THINK is `sensor.foo` but the spike appears on `sensor.bar`, the
result says "top_match = sensor.bar." The card can render
"you touched what you said was foo but bar actually spiked —
they're probably mislabeled." Mislabeling is endemic in HA
installs; this is the most powerful moment of the whole
Find-My-Device feature.

#### `lib/perturbation_capability.py`

Pure function mapping `device_class` → per-class perturbation
instruction + expected magnitude + listening window:

| device_class | Instruction | Window | Δ |
|---|---|---|---|
| `temperature` | Place a finger / cup warm hand | 30 s | ~2 °C |
| `humidity` | Breathe gently onto it | 20 s | ~10 %RH |
| `carbon_dioxide` | Breathe out directly onto it | 60 s | ~500 ppm |
| `illuminance` | Cover with hand or shine flashlight | 10 s | ~200 lx |
| `sound_pressure` | Clap loudly nearby | 10 s | ~20 dB |
| `moisture` | Damp finger on probes | 20 s | varies |

Explicitly unsupported (documented with reasons): `pm25`,
`atmospheric_pressure`, `battery`, `signal_strength`, `voltage`,
etc. — too slow, fundamentally unperturbable, or already handled
by Phase A.

#### `lib/perturbation_detection.py`

Pure z-score ranking. For each candidate:

1. Baseline mean + stddev (floored at 0.1 native-units so a
   perfectly-stable sensor doesn't divide by zero).
2. Find max-absolute-deviation sample during the test window
   (works in both directions — illuminance covering → drop is
   still a "spike").
3. z-score = |peak - mean| / stddev.

Decision: **clear** (top z > z_threshold AND gap to runner-up >
ambiguity_gap), **ambiguous** (multiple above threshold within
the gap — typically multi-function devices like Aqara
temp+humid+CO₂ on one PCB), or **no_signal** (retry or wrong
sensor type).

#### WS endpoints

- `home_insights/perturbation_guide` — read-only; returns the
  per-device_class instruction the card shows
- `home_insights/perturbation_test` — admin-gated; opens a
  listening window for N seconds, captures baseline from the HA
  Insights event buffer (fallback: current state value), records
  every state change on candidates during the window, runs the
  detection lib, returns ranked result with decision + reason

#### Tests

`tests/test_lib_perturbation.py` — 19 cases covering each
device_class guide, the elimination case (top_match ≠ caller's
expected entity), no-signal handling, ambiguous multi-sensor
device case, illuminance drops counting as spikes, the stddev
floor preventing infinity, single-sample baseline fallback, and
threshold tuning.

#### What's next

- v1.10.6 / card v1.8.0 — card-side 👆 button + countdown modal
  + results display ("Top match: sensor.kitchen_temp — assign to
  area? [dropdown]") with elimination prompt when top_match
  doesn't equal the expected entity.

### Roadmap progress

- v1.10 Phase A (identify-capable) ✅
- v1.10.3 dedup hint (static signals) ✅
- v1.10.4 card 🔗 dedup pill ✅
- **v1.10.5 Phase B backend (perturbation libs + WS)** ✅ (THIS)
- v1.10.6 / card v1.8.0 — Phase B card UX (next)
- v1.11 correlation-based dedup + location inference
- v1.12 BLE live-find
- v1.13 survival analysis
- v1.14 sequence mining
- v1.15 HardwareSuggestionDetector

## [1.10.4] — 2026-05-17

### Changed

- **Bundle card v1.7.0 panel.js** — picks up the 🔗 dedup pill in
  the bulk-area-assign dialog. With this bundle, integration-only
  users (no standalone HACS card) see "🔗 likely same as
  `<other-entity>`" inline next to rows that match v1.10.3's
  static-signal dedup at confidence ≥ 0.7.

  **Closes the v1.10 Find-My-Device user-facing loop in the
  bulk dialog**: sort + tier badge + 🔆 identify button + 🔗 dedup
  pill all visible per row. Together they answer "what is this
  entity, where is it, can I make it tell me, and is it actually
  a duplicate of one I already know?"

  Bundle-only change. Card source of truth: ha-insights-card
  v1.7.0.

## [1.10.3] — 2026-05-17

### Added — Find My Device, phase A.5 (static-signal dedup hint)

Two HA entities from different integrations can be the SAME
physical device (Tuya cloud + BLE scanner both seeing the same
plug; Govee Cloud + Govee BLE; Hue Bridge + Matter bridging the
same Hue light). HA's data model treats them as separate
`device_id`s — bulk-area-assign asks the user to assign area
twice, the future 🔆 button will flash "two lights" when one
physical thing exists, our cohort dedup gets confused.

This release adds **static-signal physical-device dedup**: cheap,
deterministic, no correlation math, no waiting period. Five
signals checked per pair:

| Signal | Where it comes from | Confidence |
|---|---|---|
| Shared MAC | `device.connections[("mac", ...)]` | 0.95 |
| Shared Bluetooth address | `device.connections[("bluetooth", ...)]` | 0.95 |
| Shared Zigbee IEEE | `device.connections[("zigbee", ...)]` | 0.95 |
| Identifier overlap (Matter bridging) | `device.identifiers` set intersection | 0.90 |
| Shared IP / host | `state.attributes.ip_address` or `host` | 0.75 |
| Manufacturer + model + via_device | weak fallback when nothing else matches | 0.55 |

#### `lib/dedup_signals.py`

Pure function: `find_dedup_candidates(entity_id, *, entity_records,
device_records, state_attributes, max_candidates=5) ->
list[DedupCandidate]`. Returns ranked candidates above
`EMIT_THRESHOLD=0.5`. Same-`device_id` pairs are explicitly
excluded — HA already treats them as one device.

`mfr_model_via` requires `via_device_id` to be set on BOTH; this
prevents flagging every pair of identical Hue bulbs as "same
physical device" (they only differ in `via_device_id` when one
is bridged via Matter and the other via Hue).

#### WS endpoint enrichment

The existing `home_insights/identify_capability` response now
includes a `same_as: [{entity_id, reason, confidence}]` field per
entity. Card-side rendering lands in card v1.7.0.

#### Tests

`tests/test_lib_dedup_signals.py` — 11 cases covering each
signal, case-insensitive MAC matching, identifier overlap (Matter
bridging scenario), the same-device-id exclusion, the
via_device_id requirement, max-candidates cap, and sort order.

#### What this does NOT do

**Correlation-based** dedup ("two temp sensors with r=0.99 over
7 days are the same physical sensor") is the v1.11 follow-up.
Static signals catch ~50–70 % of duplicates today; the rest need
event-stream correlation that this lib intentionally doesn't
touch.

### Roadmap progress

- v1.10 Phase A backend (identify + name_quality) ✅
- v1.10.1 card sort + tier badges ✅
- v1.10.2 card 🔆 identify button ✅
- **v1.10.3 dedup hint (static signals)** ✅ (THIS)
- v1.10.4 / card v1.7.0 — render 🔗 dedup pill (next)
- v1.10 Phase B perturbation touch-test (v1.10.5+)
- v1.11 correlation-based dedup + location inference
- v1.12 BLE live-find

## [1.10.2] — 2026-05-17

### Changed

- **Bundle card v1.6.0 panel.js** — picks up the 🔆 identify
  button in the bulk-area-assign dialog. With this bundle,
  integration-only users (no standalone HACS card) can click the
  button to fire the v1.10.0 `home_insights/identify_entity`
  endpoint and physically locate orphans.

  Closes the v1.10 Phase A user-facing loop. Backend libs +
  WS endpoints shipped in v1.10.0; name_quality sorting +
  identification button now both visible in the bundled panel.

  Bundle-only change. Card source of truth: ha-insights-card
  v1.6.0.

## [1.10.1] — 2026-05-17

### Changed

- **Bundle card v1.5.0 panel.js** — picks up the smart sort + tier
  badges in the bulk-area-assign dialog. With this bundle, users
  on only the integration-bundled panel surface (no standalone
  HACS card) see worst-named entities float to the top and get
  the 🆔/❓/🏷️/☁️/✏️ tier icons.

  Bundle-only change; no integration-side code or contract
  changes. See `ha-insights-card` v1.5.0 changelog for rendering
  details.

## [1.10.0] — 2026-05-17

### Added — Find My Device, phase A

Two foundational libs that future v1.10–v1.12 features will build on,
plus the first user-callable WS endpoints. The card-side 🔆 button
lands in a follow-up card release (this is the backend half).

#### `lib/identify_capability.py` — what signal an entity can emit

Pure function: given an entity_id + state snapshot, return the BEST
identify method available:

| Method | Trigger | Use case |
|---|---|---|
| `flash_light` | `light.turn_on` with `flash: short` | Lights with `SUPPORT_FLASH` |
| `strobe_light` | manual on/off/on/off/on at 350ms | Any light |
| `play_chime` | `media_player.play_media` with a chime URL | Speakers |
| `siren_chirp` | `siren.turn_on` for 1s | Sirens |
| `switch_toggle` | toggle 3× (relay click audible) | Switches |
| `none` | — | Passive sensors; falls back to v1.10 Phase B |

Returns a frozen `IdentifyCapability(method, description,
service_calls, inter_call_delay_ms)`. Caller (the WS handler) does
the actual `hass.services.async_call`, keeping I/O out of the
testable layer.

#### `lib/name_quality.py` — how meaningful is the entity's name

Pure function: scores an entity's name on a 5-tier scale:

| Tier | Score | Detected by |
|---|---|---|
| `user_override` | 1.00 | `EntityRegistryEntry.name` is set |
| `cloud` | 0.85 | Integration ∈ Tuya/Hue/HomeKit/Lutron/etc. + name ≠ MAC-ish |
| `friendly_set` | 0.70 | `friendly_name` attribute reads as ≥2 real words |
| `mfr_model` | 0.50 | Name contains manufacturer + model (ZHA pattern) |
| `generic_domain` | 0.25 | Fallback object_id rendering |
| `mac_pattern` | 0.10 | Hex blob / `xx:xx` segments (BLE scanner pattern) |

Recognizes ~25 cloud-name integrations and ~7 known-low-quality
integrations (bluetooth, bthome, ble_monitor, xiaomi_ble, govee_ble,
switchbot, inkbird). Word-detection requires vowel + ≥3 chars so
"ATC" doesn't count as a word.

Critical for routing v1.10+ Find-My-Device features: high-quality
names ("Kitchen Floor Lamp") don't need identification; low-quality
names ("ATC_a4c138") are exactly when 🔆 earns its keep. Without
this scoring, every orphan entity would show an identify button —
spamming UI for users with well-named cloud integrations.

Future uses:
- v1.10.1 dedup hint (name similarity is one signal)
- v1.11 location inference ("Kitchen Lamp" → kitchen, no
  correlation math needed)
- v1.11 physical-device-link detector (similar names + similar
  state = likely same physical device)

#### WS endpoints

- `home_insights/identify_capability` — read-only; returns
  capability + name_quality for a batch of entity_ids. The card
  calls this once per panel open. Not admin-gated (read-only).
- `home_insights/identify_entity` — admin-gated; actually fires
  the service calls for one entity. Returns method used + count
  of calls fired. Logs warning on partial failure.

### Tests

- `tests/test_lib_name_quality.py` — 20 cases covering each tier,
  user-override precedence, MAC-ish detection corner cases, word
  detection (vowel + length), and assessment shape.

### Roadmap progress

- v1.10 Phase A backend ✅ (THIS)
- v1.10 Phase A card 🔆 button (next — card v1.5.0)
- v1.10.1 dedup hint (cheap; uses MAC/IP attrs + name similarity)
- v1.10 Phase B perturbation (👆 touch-test; v1.10.5 or v1.11)
- v1.11 location inference + physical-device-link detector
- v1.12 BLE live-find

## [1.9.2] — 2026-05-17

### Changed

- **Bundle card v1.4.0 panel.js** — picks up the 🔀 directionality
  badge in the integration's bundled panel surface. With this
  bundle, users who install only the integration (without the
  standalone HACS card) see the v1.9.1 directionality stamps
  rendered as badges. Standalone-card users on v1.4.0+ already
  see them.

  Bundle-only change; no integration-side code or contract
  changes. See `ha-insights-card` v1.4.0 changelog for the
  rendering details.

## [1.9.1] — 2026-05-17

### Added

- **LaggedCorrelationDetector: transfer-entropy direction check**.
  Wires v1.9.0's `lib/transfer_entropy.py` into the BETA detector.
  Temporal ordering ("Y fires after X") is necessary but not
  sufficient for "X causes Y": two entities both driven by sunset,
  by a manual ritual, or by an unseen third factor produce
  identical-looking temporal-lag patterns. TE measures whether X's
  past actually reduces uncertainty about Y's future beyond Y's own
  past.

  Per-pair behaviour:
  - **Reversed direction** (TE(Y→X) dominates) → confidence × 0.5.
    Heavy demotion — the proposal is backwards; the follower is
    actually the leader. Usually drops the insight below
    `MIN_CONFIDENCE_TO_EMIT` (0.55).
  - **Symmetric flow** with non-zero magnitude → confidence × 0.85.
    Mild demotion; both directions have flow, suggesting both are
    driven by a third factor.
  - **Uninformative** (both TEs below noise floor) → no demotion.
    Sparse data; don't penalize what we can't measure.
  - **Confirmed direction** (TE(X→Y) dominates) → no demotion.

  Bin width is matched to the observed lag (`avg(deltas)` clamped
  to [60s, 300s]) so single-step TE picks up the coupling. A 180s
  lag with 60s bins places transitions three bins apart and TE
  picks up nothing; matching the bin to the lag puts related
  transitions one step apart.

  Per-entity event streams are computed ONCE per scan (O(N)),
  cached on the detector, and reused across all pair evaluations.
  Stream cache is cleared in a `finally` block to prevent
  cross-scan leakage.

### Card-facing

- Every lagged_correlation insight now carries a `_directionality`
  payload key. Shape:
  ```json
  {
    "assessed": true,
    "direction": "x_to_y" | "y_to_x" | "symmetric",
    "te_x_to_y": 0.9,
    "te_y_to_x": 0.05,
    "asymmetry": 0.85,
    "confidence": 0.95,
    "n_samples": 200
  }
  ```
  When TE wasn't run (no events, sparse pair), `{"assessed": false}`.
  The card UI for a 🔀 "verified direction" badge lands in a follow-up
  card release.

### Tests

- `tests/test_lagged_correlation_directionality.py` — 11 new tests
  covering: factor selection by direction × confidence × signal
  strength, payload helper structure, end-to-end synthetic flows
  (real X→Y, reversed, missing entity), payload stamp on emitted
  insights, and stream-cache cleanup between scans.

### Roadmap progress

- v1.8.0 — changepoint lib ✅
- v1.8.1 — FrequencyAnomalyDetector wiring ✅
- v1.8.2 — StateShiftDetector ✅
- v1.9.0 — transfer entropy lib ✅
- **v1.9.1 — wire into LaggedCorrelationDetector** ✅ (THIS)
- v1.10 — survival analysis (lifelines AFT)
- v1.11 — sequence mining (prefixspan)

## [1.9.0] — 2026-05-17

### Added

- **`lib/transfer_entropy.py`** — pure-stdlib transfer entropy
  (Schreiber 2000) on discrete state sequences. Next building
  block of the v1.8+ research-backed detector roadmap.

  Quantifies DIRECTIONAL information flow between two time
  series. `TE(X→Y)` measures how much knowing X's past reduces
  uncertainty about Y's future, BEYOND what Y's own past already
  tells you. This is the signal LaggedCorrelationDetector needs
  to separate "Y follows X temporally" from "Y is actually
  driven by X."

  API:
  ```python
  transfer_entropy(x_seq, y_seq) -> TransferEntropyAssessment(
      te_x_to_y, te_y_to_x, asymmetry, dominant_direction,
      n_samples, confidence,
  )

  # Convenience for callers binning event streams:
  discretize_event_stream(events, bin_size, total_duration)
  ```

  Pure stdlib (collections.Counter, math.log2). pyinform has the
  math but development stalled in 2018; rolling our own keeps
  the dep footprint zero and the math auditable.

  Performance: 50–500 sample inputs finish in single-digit
  milliseconds. Asymptotic O(N) per direction.

### Use cases (not yet wired into any detector — that's v1.9.1+)

- **LaggedCorrelationDetector confidence demotion**: high temporal
  correlation but near-zero TE → pair is likely coincident (both
  driven by time of day, not causal).
- **Cooccurrence direction check**: TE(X→Y) vs TE(Y→X) tells
  whether motion drives the light or vice versa.
- **General sanity check on cohorts**: a "10 lights all fire at
  17:30" cohort with no TE between any pair is likely scene-
  driven, not behaviour-driven.

### Roadmap progress

- v1.8.0 — changepoint lib ✅
- v1.8.1 — FrequencyAnomalyDetector wiring ✅
- v1.8.2 — StateShiftDetector ✅
- **v1.9.0 — transfer entropy lib** ✅ (THIS)
- v1.9.1 — wire into LaggedCorrelationDetector (next)
- v1.10 — survival analysis
- v1.11 — sequence mining

## [1.8.2] — 2026-05-17

### Added

- **`StateShiftDetector`** — new BETA detector that surfaces
  "your routine shifted on YYYY-MM-DD" as PATTERN_OBSERVATION
  insights. Uses v1.8.0's changepoint detection.

  Different from v1.8.1's `FrequencyAnomalyDetector` wiring:
  - v1.8.1 uses changepoints INTERNALLY (to compute a smarter
    baseline for anomaly detection).
  - v1.8.2 EXPOSES changepoints to the user as their own visible
    insight type — "I noticed your daily activity for X shifted
    on date Y, here are the numbers."

  ### Why this matters

  When life changes (new job, baby, school start, device added
  to a routine), patterns shift across many entities at once.
  Without flagging this, the schedule / streak / frequency
  detectors treat post-shift data as noise → weaker insights or
  silence. Users staring at the panel can't tell whether HA
  Insights is broken or their pattern actually changed.

  Title shape:
  > `binary_sensor.coffee_maker activity shifted ~5 days ago
  >  (2026-05-12): ~2.4/day → ~5.8/day.`

  Payload includes pre/post means, magnitude, shift date, and
  the backend that detected it (PELT vs fallback — affects
  confidence weighting). Card format = `card` (history-graph)
  pointing at the 14-day window so the user can visually
  confirm the shift.

  ### Filters

  - Lookback: 14 days (matches FrequencyAnomalyDetector).
  - Recency: 2–10 days ago (older shifts the user already
    noticed; newer shifts lack post-shift stability).
  - Min events per entity: 20 in window (very sparse signals
    can't yield reliable changepoints).
  - Min magnitude: 5.0 units (filters trivial wobbles).
  - Cap: 10 insights per scan (cohort dedup typically reduces
    much further).
  - Excludes bursty domains (device_tracker, media_player when
    media-bursty, person) per the existing `_RELEVANT_DOMAINS`
    set.

  ### Cohort dedup applies

  10 lights shifting from 06:00 to 07:00 on the same day get
  collapsed into one merged insight via the standard
  `_dedup_grouped_insights` pipeline.

### Roadmap progress

- v1.8.0 — changepoint lib ✅
- v1.8.1 — FrequencyAnomalyDetector integration ✅
- **v1.8.2 — StateShiftDetector** ✅ (THIS)
- v1.9 — transfer entropy (next)

## [1.8.1] — 2026-05-17

### Changed

- **FrequencyAnomalyDetector now uses changepoint-aware baseline.**
  Wires v1.8.0's `lib/changepoint_detection.py` into the detector
  so a routine that shifted within the 13-day baseline window no
  longer poisons the baseline mean.

  **The problem**: an entity that used to fire 5/day for 8 days
  then shifted to 25/day for the past 5 days has an unadjusted
  baseline of (5×8 + 25×5)/13 ≈ 12.7/day. Today firing 100 times
  reads as ~8× — barely above the alert threshold. But the
  ACTUAL current normal is 25/day, so today's 100 is really a
  4× spike against the post-shift baseline, not 8× against the
  averaged-pre-and-post baseline.

  **The fix**: per-entity daily-count series fed to
  `detect_changepoints`. If a recent changepoint (2-10 days
  ago) is found, the baseline is recomputed using only
  post-changepoint days. Title and payload reflect this:
  - Title: `"... ~25.0/day NEW baseline since 2026-05-12, 4.0x..."`
  - Payload: `_baseline_changepoint: {detected_at, magnitude}`

  Healthy stable signals are untouched — the changepoint detector
  returns empty for them. Performance impact: one
  `detect_changepoints` call per candidate entity (cheap; per
  v1.8.0 benchmarks).

### Roadmap progress

- v1.8.0 — changepoint lib ✅
- **v1.8.1 — wire into FrequencyAnomalyDetector** ✅ (THIS)
- v1.8.2 — new StateShiftDetector (next)
- v1.9 — transfer entropy
- v1.10 — survival analysis
- v1.11 — sequence mining

## [1.8.0] — 2026-05-17

### Added

- **`lib/changepoint_detection.py`** — pure-function changepoint
  detection on univariate time series. First building block of the
  v1.8+ research-backed detector roadmap (per agent memory
  `ha_insights_research_answers_v1`).

  Use cases targeted (not yet wired into any detector — that's
  v1.8.1+):
  - Morning routine moves from 06:50 to 08:30 (new job).
  - A binary_sensor's daily firing count drops to zero (battery
    dying / device retired — distinct from "orphan/silent").
  - A weekday-07:15 schedule starts firing at 09:00.

  Without this, the schedule / streak / frequency detectors treat
  post-shift data as noise that pollutes the pattern — a 4-month
  routine that just shifted last week looks like "weak signal"
  rather than "strong signal that recently shifted."

  API:
  - `detect_changepoints(timestamps, values) -> list[ChangepointAssessment]`
  - `ChangepointAssessment(detected_at, kind, magnitude, confidence, backend)`
  - `backend_in_use() -> ChangepointBackend` for one-shot logging.

  Backend: prefers `ruptures.Pelt` (Pruned Exact Linear Time,
  Killick 2012) when the optional dependency is installed; falls
  back to a pure-Python cumulative-mean-shift detector otherwise.
  Both emit the same `ChangepointAssessment` shape. Fallback
  catches the dominant single-shift case at worse sensitivity;
  detectors should treat fallback-backend results as lower
  confidence (the `backend` field on the assessment surfaces this).

  **Not adding `ruptures` to requirements yet.** The fallback is
  honest and adequate for v1.8.0; adding the dep would force
  install on every HACS user. Users wanting better sensitivity
  can `pip install ruptures` in their HA Python env; integration
  picks it up automatically on next load.

### Roadmap context

This is the v1.7-target lib that got skipped while v1.7.x focused
on the coupling badge. v1.8.x picks up the research roadmap:
- v1.8.0 — changepoint detection lib (THIS RELEASE)
- v1.8.1 — wire into FrequencyAnomalyDetector / SeasonalityDetector
  to demote insights spanning a changepoint
- v1.8.2 — new `StateShiftDetector` emitting "your routine shifted
  on YYYY-MM-DD" meta-insights
- v1.9 — `lib/transfer_entropy.py` (custom NumPy)
- v1.10 — `lib/survival_likelihood.py` (lifelines AFT)
- v1.11 — `lib/sequence_mining.py` (prefixspan)

## [1.7.8] — 2026-05-17

### Added

- **Per-device "managed externally" flag** — Strategy 2 from the
  device-internal-logic memory. The user can mark any device "this
  handles its own logic" and HA Insights stops surfacing patterns
  from it entirely. Different from the existing automatic 🤖
  device-managed pill (statistical inference) and 🏷️ managed-
  externally pill (integration-platform whitelist): this is the
  explicit user assertion.

- **`lib/managed_externally.py`** — pure suppression library:
  - `collect_referenced_entities(fingerprint, payload)` walks an
    insight and gathers every entity_id referenced via
    entity-id-bearing fields. Safer than enumerating per-detector
    fingerprint keys.
  - `is_suppressed(...)` returns True when any referenced entity
    belongs to a managed device.
  - `filter_insights(...)` splits an insight list into
    (kept, suppressed) for the detector pipeline. Zero-cost fast
    path when no devices are flagged.

- **Detector pipeline integration** — `run_all_detectors` reads
  `managed_externally_devices` from entry options and filters each
  detector's output before dedup. Suppressed insights never enter
  the store. Stale active insights from a newly-flagged device get
  cleaned up by the next scan's stale-sweep.

- **WS endpoints**:
  - `home_insights/list_managed_devices` — returns
    `[{device_id, name, manufacturer, model, entity_count, deleted}]`
    for currently-flagged devices. Admin-only.
  - `home_insights/set_device_managed {device_id, managed}` — add or
    remove from the flagged set. Idempotent. Admin-only.

- **WS list enrichment** — every insight returned by
  `home_insights/list` now carries `referenced_devices: [{device_id,
  name, managed}]` so the card can render per-device toggles
  without walking payloads itself.

- **OptionsFlow management screen** — new "Managed-externally
  devices" menu entry showing all currently-flagged devices with
  a multi-select to restore any (uncheck to clear the flag).
  Empty-state shows discovery hint.

- **Config option** `CONF_MANAGED_EXTERNALLY_DEVICES =
  "managed_externally_devices"`. Stored as `list[str]` of device
  registry IDs in entry options.

### Pairs with

Card v1.3.5 adds the per-device toggle to the insight detail
dialog. Without the card update, the backend works (flags can be
managed via OptionsFlow); with it, the in-context per-insight
toggle is the discoverable path.

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
