# Conflict scanner

*"HA noticed this pattern — but you already have an automation for it."*

The conflict scanner checks every automation-proposal insight against your **existing
automations** and tags the ones that overlap. It answers the most common panel question:
*why am I seeing suggestions for things I already automated?* — and, just as often, *why
am I NOT seeing the "already automated" pill on something I know is covered?*

## There is nothing to start

The scanner is **not a separate tool**. It runs automatically inside every scan —
scheduled scans and **Scan now** alike. There is no button, service call, or option to
trigger it on its own.

When it finds a match, the insight:

- keeps showing in the panel (matches are **annotated, never hidden or suppressed**),
- gets the **🔁 already automated** pill, listing the matching automation(s) with links,
- loses its "Automate this?" call-to-action in notifications.

The **"Hide 🔁 already automated"** checkbox in the panel filter bar hides exactly the
insights carrying that pill. If a finding you consider covered isn't disappearing when
you enable the filter, it means the scanner didn't match it — see the rules below.

## What counts as a match

A match always requires **overlapping action targets**: both the insight and the existing
automation must act on at least one common entity. Groups and scenes are expanded to
their members on both sides, so an insight targeting `light.garden_group` matches an
automation that targets `light.deck_01`.

On top of target overlap, one of these trigger rules must hit:

| Rule | Insight trigger | Existing automation trigger | Extra requirement |
|---|---|---|---|
| Time window | `time` | `time` | trigger times within ±10 minutes |
| Same state trigger | `state` | `state` | same source entity, same `to:` value, same `for:` duration |
| Schedule-like | any of `time` / `time_pattern` / `sun` / `calendar` | any of the same set | — |
| Cross-trigger shadow | schedule-like | event-driven (`state`, `numeric_state`, `template`, `zone`, `device`) — or the reverse | both call the **same service** (e.g. `light.turn_on`) on the common target |

The *cross-trigger shadow* rule is what catches the classic case: the streak detector
learns "these lights come on around 17:34 every day", but the reason they do is your
**motion automation**. Same lights, same `light.turn_on` — different trigger platform.
The same-service requirement keeps complementary pairs apart: a "motion → lights on"
automation does **not** match a "22:00 → lights off" insight.

## Known limits

- Matching is **static YAML analysis** — the scanner never evaluates templates or
  entity states at runtime.
- Two `state` triggers on **different source entities** only match via the
  cross-trigger rule (which needs one schedule-like side). Two motion automations from
  different sensors covering the same light are treated as additive coverage, not
  duplicates.
- Scripts called from automations (`script.turn_on` indirection) are not unrolled.
- Blueprints are compared by their rendered trigger/action config.

## When the scanner is wrong

- **False negative** (covered, but no pill): use **Dismiss** on the insight — that is
  the manual "I already have this" action today.
- **False positive** (pill on something not actually covered): the pill is informational
  only; the insight remains fully applicable. Apply it as normal.

## For detector authors

Matches set `Insight.conflicts_with` (a tuple of automation ids/aliases) during the
post-detector annotation pass — detectors don't need to do anything. See
`custom_components/ha_insights/apply/conflict_scanner.py` and
[ARCHITECTURE.md](ARCHITECTURE.md) for the pipeline position.
