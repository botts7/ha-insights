# Screenshots

Live captures of HA Insights running on a 1000-entity install. Captured at
1400×900 in a light HA theme.

| File | What it shows |
|---|---|
| `01-panel.png` | Main panel — full insights list with audit, streak, schedule, orphan_device, etc. Header shows version + filter chips |
| `02-preview-diff.png` | 📋 Preview deterministic fix — side-by-side YAML diff of redundant_target removal (no LLM) |
| `03-llm-refine-diff.png` | 🤖 Algorithm + LLM Refine stage 2 — line-aligned diff with the refine-with-more-guidance textarea |
| `04-repairs.png` | Standard HA Repairs page showing audit findings dual-emitted into the issue registry |
| `05-options-flow.png` | Configure dialog — privacy mode, lookback, notifications, digest, audit options |

## Re-capturing

The README at the repo root references these by filename. To re-shoot:

1. **Panel** — open `/ha-insights` from sidebar, screenshot full panel.
2. **Preview diff** — click 📋 Preview on an `automation_audit` row with a
   `redundant_target` finding. Screenshot the modal.
3. **LLM refine diff** — click 🤖 Suggest, wait for the LLM round-trip,
   screenshot the resulting stage-2 modal.
4. **Repairs page** — Settings → Repairs. Show at least one
   `HA Insights: review automation '<name>'` entry, click to open the
   detail modal, screenshot.
5. **OptionsFlow** — Settings → Devices & Services → HA Insights →
   Configure. Screenshot the full form.

Keep them small: PNG, ≤ 200 KB each. Crop to content (don't include the
whole browser chrome).

## Bonus shots (optional)

- `06-rollup-progress.png` — progress bar mid-rollup (catch it during a
  fresh chunk batch)
- `07-recorder-hint.png` — the recorder-retention hint row when configured
  window exceeds recorder retention (shows the amber warning + tip)
- `08-multi-turn-refine.png` — the conversation-id continuation flow where
  you re-prompt the same insight with new feedback
