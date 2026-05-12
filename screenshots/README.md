# Screenshot capture guide

The README references four screenshots in this directory. Capture them in this
order — each one builds visual momentum for the HACS browse-and-click flow.

All shots: **light HA theme**, browser at **1440 × 900**, dev-tools closed.

## 1. `panel-overview.png` — the integration's main panel

**URL:** `/ha-insights` (sidebar entry)

**Setup:**
- Several insights of mixed types visible (audit, streak, schedule, orphan_device)
- At least one row with the 🔁 already-automated pill expanded showing 2+ automations
- At least one row with the 🏷️ "managed externally (Tuya app)" pill
- At least one row with a ▸ show N cohort expander

**Crop:** entire panel content, including the title bar with detector count chips.

## 2. `audit-row.png` — an audit insight with findings expanded

**URL:** `/ha-insights`

**Setup:**
- Find an `automation_audit` row with `payload_format="automation"` (deterministic-fix)
- Click the **▾** to expand the findings list
- Should show observations as bullet points + the green "🔧 Auto-fix preview" block
- Apply / 📋 Preview / 🔁 already-automated pill all visible

**Crop:** just the one expanded row from title down through the green block.

## 3. `diff-modal.png` — the side-by-side IDE-style diff

**URL:** `/ha-insights` → click 📋 Preview on any audit row

**Setup:**
- Modal open with the diff visible
- Title shows `📋 Preview deterministic fix for '<automation name>'`
- Left pane: red border + "Current YAML (live)" header
- Right pane: green border + "Algorithm Fix (no LLM)" header
- Red `-` rows and green `+` rows clearly visible somewhere mid-diff
- "🤖 Refine again with more guidance?" textarea visible at the bottom

**Crop:** entire modal including the gray overlay edges so it looks like a dialog.

## 4. `repairs-entry.png` — HA's Repairs page showing an audit finding

**URL:** **Settings → Repairs**

**Setup:**
- At least one `HA Insights: review automation '<name>'` Repairs entry
- Click it open so the description text is visible
- Should show the finding summary inside HA's standard repair dialog

**Crop:** the open Repairs detail panel.

---

## Bonus shots (if time)

- `concise-vs-indepth.png` — the panel's depth toggle dropdown open showing
  both options
- `apply-button-stages.png` — three modal screenshots stacked vertically
  showing the apply button label changing per stage
- `token-usage.png` — the rationale block with the `≈ X in / Y out tokens`
  line visible underneath

## Tools

GIFs (for animated demos):
- macOS / Linux: `peek`, `gifski`
- Windows: ScreenToGif (free, works well)
- Target 720p, ≤ 6 MB, 4-12 seconds per loop
