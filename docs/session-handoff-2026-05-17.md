# Handoff: 2026-05-17 — what to verify in next session (Chrome DevTools MCP)

> **VERIFIED 2026-05-17 (follow-up session via Chrome DevTools MCP):**
> The 🔗 coupling badge renders correctly on the running HA install (integration **v1.7.4**, no upgrade needed for this fix). Live probe found:
> - `_coupling: {tier: TIGHT, consistency: 0.94, median_lag_ms: 180}` on the Kitchen scene controller cooccurrence insight
> - 1 `.coupling-badge` element in DOM, text `"🔗 coupled"`, tooltip `"These entities change together within ~180ms (94% consistency) — looks like a device binding…"`, computed `display:inline visibility:visible opacity:0.85`
> - Static path `/ha_insights_static/panel.js` → 200 OK, 332461 bytes
> - Recovery sentinel: `forcedMounts: 0` (normal mount path is healthy)
>
> Conclusion: v1.7.6 + card v1.3.4 (`ha-insights-card-bundled` alias) remain in the repo as defense-in-depth against a hypothetical HACS-card name collision, but are **not** required to make the badge work. The original "badge missing on v1.7.5" report was likely a browser-cache artifact that resolved itself before v1.7.6 was even tested.
>
> Sections below preserved for historical context.

---

This is a note from one Claude Code session to the next. The previous session shipped a chain of integration + card releases trying to fix the side-panel rendering, but the final verification ran into the limit that Claude couldn't see the user's browser directly. If you have Chrome DevTools MCP set up (`docs/setup-chrome-devtools-mcp.md`), use it to drive the actual verifications below.

## TL;DR for the next session

1. The 🔗 coupling badge SHOULD now render after v1.7.6 + card v1.3.4 ship.
2. **It was never verified end-to-end on real hardware.** Last test on v1.7.5 showed badge still missing despite all upstream data correct. v1.7.6 was the diagnostic fix for the cause we identified (custom-element name collision with stale HACS card).
3. If v1.7.6 didn't fix it, the next hypothesis to chase is "the panel embeds via a render path that doesn't go through `_renderRow`" — needs source-walk + live DOM inspection.

---

## State as of session end

### Recent releases (today, 2026-05-17)

| Release | What |
|---|---|
| **integration v1.7.0** | Coupling badge feature (server side stamps `payload._coupling`) |
| **integration v1.7.1** | TIGHT-coupled example fixture for `inject_examples` |
| **integration v1.7.2** | AutomationAudit round-robin rotation (closes #12) |
| **integration v1.7.3** | Bundle `panel.js` inside integration, serve via `register_static_path` (broken — wrong API) |
| **integration v1.7.4** | Fix: use `async_register_static_paths` + non-`/api/` URL |
| **integration v1.7.5** | Bump bundled `panel.js` to card v1.3.3 (double-mount race fix) |
| **integration v1.7.6** | Bump bundled `panel.js` to card v1.3.4 (panel-card alias fix — should make badge work) |
| **card v1.3.0** | Add 🔗 coupling badge to `_renderRow` + dialog |
| **card v1.3.1** | Fix shadow-DOM observer scope in panel-mount recovery |
| **card v1.3.2** | Release workflow attaches `panel.js` too (was missing for months) |
| **card v1.3.3** | Dedup + 500ms delay — fixes double-mount race |
| **card v1.3.4** | Panel registers `ha-insights-card-bundled` alias — should fix badge visibility |

### Verified working today

- ✅ Blank panel issue fixed by browser restart after v1.3.3 + v1.7.5 install
- ✅ Integration WS API returns `_coupling: {tier: TIGHT}` correctly
- ✅ Card's internal `_insights` state has the TIGHT insight
- ✅ Badge code is shipped in bundled panel.js (3+ references to `_renderCouplingBadge`)

### Unverified (test in next session)

- ❓ **v1.7.6 actually fixes the badge rendering on a real install.** User was offline before they could update + verify.
- ❓ Recovery sentinel state after navigation (does `forcedMounts` stay at 0 with v1.7.6?)
- ❓ Are there any other render paths besides `_renderRow` that handle cooccurrence insights?

---

## Specific verifications to run via Chrome DevTools MCP

Once MCP is connected (Chrome on `--remote-debugging-port=9222`, MCP loaded, HA logged in):

### Verification 1 — v1.7.6 deployed correctly

```
mcp__chrome-devtools__navigate_page: http://192.168.86.68:8123/ha-insights
mcp__chrome-devtools__evaluate_script:
  (async () => {
    const hass = document.querySelector('home-assistant').hass;
    const hello = await hass.callWS({type: 'home_insights/hello'});
    return {
      integration_version: hello.integration_version,
      panel_url: '/ha_insights_static/panel.js',
      panel_size: (await fetch('/ha_insights_static/panel.js')).headers.get('content-length'),
    };
  })()
```

Expected: `integration_version: "1.7.6"`, `panel_size: "~333000"` (card v1.3.4 build).

### Verification 2 — `ha-insights-card-bundled` registered

```
mcp__chrome-devtools__evaluate_script:
  ({
    card_class_registered: !!customElements.get('ha-insights-card'),
    bundled_class_registered: !!customElements.get('ha-insights-card-bundled'),
    bundled_instances: document.querySelectorAll('ha-insights-card-bundled').length,
  })
```

Expected: `bundled_class_registered: true`. If `false`, the v1.3.4 alias didn't ship — re-check panel.js content.

### Verification 3 — Badge renders on injected example

```
mcp__chrome-devtools__evaluate_script:
  (async () => {
    const hass = document.querySelector('home-assistant').hass;
    await hass.callWS({type: 'home_insights/clear_examples'});
    await hass.callWS({type: 'home_insights/inject_examples'});
    // Wait for re-render
    await new Promise(r => setTimeout(r, 1000));
    return null;
  })()

mcp__chrome-devtools__navigate_page: http://192.168.86.68:8123/ha-insights
mcp__chrome-devtools__take_screenshot
mcp__chrome-devtools__evaluate_script:
  // Cross-shadow walker for .coupling-badge
  (() => {
    const findAll = (root, sel, acc = []) => {
      if (!root) return acc;
      if (root.querySelectorAll) acc.push(...root.querySelectorAll(sel));
      const els = root.querySelectorAll ? root.querySelectorAll('*') : [];
      for (const el of els) if (el.shadowRoot) findAll(el.shadowRoot, sel, acc);
      return acc;
    };
    const badges = findAll(document, '.coupling-badge');
    return {
      count: badges.length,
      first_text: badges[0]?.textContent,
      first_tooltip: badges[0]?.title,
    };
  })()
```

Expected: `count: 1`, `first_text: "🔗 coupled"`, tooltip starts with "These entities change together within ~180ms".

### Verification 4 — Recovery sentinel is clean

```
mcp__chrome-devtools__evaluate_script:
  window.__haInsightsPanelRecovery
```

Expected: state object with `forcedMounts: 0`. If `forcedMounts > 0`, recovery is having to save us — investigate why HA's normal mount isn't completing on first nav (probably a different race).

---

## If badge still missing after v1.7.6

Hypotheses to chase, in order of likelihood:

### A. Cache (most likely)

Browser still serving v1.7.5 panel.js. Verify by checking the `<script>` src URL in the panel's parent DOM — should contain `v=1.7.6-...`.

```
mcp__chrome-devtools__evaluate_script:
  Array.from(document.querySelectorAll('script'))
    .map(s => s.src)
    .filter(s => s.includes('ha_insights'))
```

If URL says `v=1.7.5-...`, hard-refresh hasn't pulled the new bundle. Force-refresh via HA → HACS → ⋮ → Reload.

### B. Different render path

Panel embeds card via `<ha-insights-card-bundled>` (v1.3.4+). The bundled class is a trivial subclass of `HaInsightsCard`. It SHOULD inherit `_renderRow` and call `_renderCouplingBadge`. But maybe there's a different code path:

- `_renderCompactTile` at card.ts:3529 — could be called for some insight types
- `_renderRefinedPreview`, `_renderAuditBody`, `_renderSetupGuideBody` — specialized renderers

If cooccurrence insights are getting routed to a different renderer, the badge won't render. Inspect:

```
mcp__chrome-devtools__evaluate_script:
  // Find the rendered row for the kitchen scene controller insight
  const findAll = (root, sel, acc = []) => {
    if (!root) return acc;
    if (root.querySelectorAll) acc.push(...root.querySelectorAll(sel));
    const els = root.querySelectorAll ? root.querySelectorAll('*') : [];
    for (const el of els) if (el.shadowRoot) findAll(el.shadowRoot, sel, acc);
    return acc;
  };
  const rows = findAll(document, '.row, .row-title, [class*="row"]');
  return rows.map(r => ({
    tag: r.tagName,
    class: r.className,
    text: r.textContent?.slice(0, 100),
  })).filter(r => r.text?.includes('Kitchen scene'));
```

Then read the surrounding HTML to identify which renderer produced it.

### C. CSS hiding the badge

```
mcp__chrome-devtools__evaluate_script:
  const findAll = (root, sel, acc = []) => { /* ...as above... */ };
  const badges = findAll(document, '.coupling-badge');
  return badges.map(b => ({
    visible: b.offsetParent !== null,
    display: getComputedStyle(b).display,
    visibility: getComputedStyle(b).visibility,
    opacity: getComputedStyle(b).opacity,
    rect: b.getBoundingClientRect(),
  }));
```

If `display: none` or `visibility: hidden`, CSS is hiding it. If `rect: {width: 0, height: 0}`, it's collapsed. Bug in v1.3.0 CSS.

### D. Lit render race

Long shot: the badge renders, then a re-render strips it. Use MutationObserver via MCP to watch what happens to a specific row across time.

---

## Code orientation for the next session

If you need to read source:

- **Badge logic**: `C:\Users\botts\ha-insights-card\src\ha-insights-card.ts:3967` (`_renderCouplingBadge`)
- **Badge invocation in row**: card.ts:3624 (`${this._renderCouplingBadge(insight)}` inside `_renderRow`)
- **Panel embeds card**: `C:\Users\botts\ha-insights-card\src\ha-insights-panel.ts:1685` (`_renderCard`)
- **Bundled alias registration**: panel.ts:18-39 (v1.3.4 addition)
- **Integration stamps coupling**: `C:\Users\botts\ha-insights\custom_components\ha_insights\detectors\cooccurrence.py` — see `_evaluate_pair`
- **Coupling lib**: `C:\Users\botts\ha-insights\custom_components\ha_insights\lib\coupling_strength.py`
- **Example fixtures**: `C:\Users\botts\ha-insights\custom_components\ha_insights\examples.py:107` (cooccurrence examples)
- **Static path registration**: `C:\Users\botts\ha-insights\custom_components\ha_insights\__init__.py:1395+` (`_async_register_panel`)

## Memory items relevant to this session

If you have memory access:

- `reference_device_internal_logic_problem` — design rationale for the coupling badge
- `feedback_serial_reset_masks_freeze` — generally relevant pattern (a "fix" can mask the real bug)
- `feedback_treat_codebase_like_an_os` — why the panel/card layer separation matters
- `ha_insights_two_panel_js_paths` — historical context for why panel.js delivery has been fragile

## Past failures to avoid repeating

- v1.7.3 used the removed `register_static_path` API. Always grep HA source to verify API exists before using.
- v1.7.3 used `/api/*` URL prefix which is reserved. Use `/ha_insights_static/*` or similar.
- v1.2.26 recovery used `document.body` MutationObserver — doesn't cross shadow roots. Watch the right tree.
- v1.3.1 ran `tryRecover()` synchronously at module load — beat HA's normal mount → double panel. Always delay recovery probes.

## What good looks like

A session done well:

1. Open the panel via MCP
2. Take a screenshot — visually confirm one panel, with 🔗 badge on the Kitchen scene controller insight
3. Run the verification snippets above, confirm all expected outputs
4. If anything fails, drill into the hypothesis chain above
5. If a code change is needed, make it surgical, ship via the established release pipeline (card → integration bundle → tag)
6. Update this handoff with the new state at the end

Don't try to fix things you can't reproduce — use the MCP to reproduce first, then fix.
