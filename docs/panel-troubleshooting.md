# HA Insights — Panel troubleshooting runbook

Self-serve diagnostic snippets for the most common things that go wrong with the sidebar panel. Paste into browser DevTools console (F12 → Console) while on the affected HA page.

All snippets are **read-only** unless marked otherwise. Safe to run on a production install.

---

## 1. "What version am I actually running?"

```js
(async () => {
  const hass = document.querySelector('home-assistant').hass;
  const hello = await hass.callWS({type: 'home_insights/hello'});
  console.log('Integration version:', hello.integration_version);
  console.log('WS protocol version:', hello.ws_protocol_version);
  const fetched = await fetch('/ha_insights_static/panel.js').then(r => ({
    status: r.status,
    size: r.headers.get('content-length'),
  })).catch(e => ({error: String(e)}));
  console.log('Bundled panel.js fetch:', fetched);
})();
```

**Reading the output:**

| Output | Meaning |
|---|---|
| `Integration version: 1.7.6` or later | ✅ Modern integration with bundled panel.js |
| `Integration version: 1.5.x` or earlier | ⚠ Old integration; panel.js loaded from HACS card path, may be stale |
| `Bundled panel.js fetch: {status: 200, size: ~330000}` | ✅ Integration-served panel is reachable |
| `Bundled panel.js fetch: {status: 404}` | ❌ v1.7.6+ static path didn't register; check HA logs for `register_static_paths` errors |

---

## 2. "Blank panel — nothing renders on /ha-insights"

Run this **on the blank page** before hard-refreshing:

```js
(() => {
  const ha = document.querySelector('home-assistant');
  const main = ha?.shadowRoot?.querySelector('home-assistant-main');
  const wrap = main?.shadowRoot?.querySelector('ha-panel-custom');
  const sentinel = window.__haInsightsPanelRecovery;
  console.log('===== BLANK PANEL DIAGNOSTIC =====');
  console.log('URL:', window.location.pathname);
  console.log('home-assistant-main present?', !!main);
  console.log('ha-panel-custom present?', !!wrap);
  console.log('  → children count:', wrap?.children.length);
  console.log('  → outerHTML (first 200):', wrap?.outerHTML?.slice(0, 200));
  console.log('  → wrap.panel:', wrap?.panel);
  console.log('  → wrap.hass set?', !!wrap?.hass);
  console.log('Element registered?', !!customElements.get('ha-insights-panel'));
  console.log('Recovery sentinel:', sentinel);
  if (sentinel && typeof sentinel === 'object') {
    console.log('  → attempts:', sentinel.attempts);
    console.log('  → forcedMounts:', sentinel.forcedMounts);
    console.log('  → lastAttemptAt:', sentinel.lastAttemptAt && new Date(sentinel.lastAttemptAt).toISOString());
  }
  console.log('==================================');
})();
```

**Interpretation matrix:**

| `ha-panel-custom present?` | `children count` | `Recovery sentinel` | Diagnosis |
|---|---|---|---|
| `true` | `> 0` | any | Not actually blank — check for CSS hiding |
| `true` | `0` | `undefined` / `false` | Pre-v1.2.26 bundle (no recovery code shipped) → update integration to v1.7.6+ |
| `true` | `0` | `{installed: true, attempts: 0}` | Recovery installed but observer never fired → likely fixed by v1.7.6's `ha-insights-card-bundled` alias |
| `true` | `0` | `{installed: true, attempts: N>0, forcedMounts: 0}` | Recovery ran but couldn't mount — check console for errors during `tryRecover` |
| `false` | — | — | HA's panel resolver didn't insert the wrapper at all → integration registration issue; check HA logs |

**Quick force-mount (modifies DOM):**

```js
(() => {
  const wrap = document.querySelector('home-assistant')
    ?.shadowRoot?.querySelector('home-assistant-main')
    ?.shadowRoot?.querySelector('ha-panel-custom');
  if (!wrap || wrap.children.length > 0) return console.log('Nothing to recover');
  const el = document.createElement('ha-insights-panel');
  el.hass = wrap.hass;
  el.narrow = wrap.narrow;
  el.panel = wrap.panel;
  wrap.appendChild(el);
  console.log('Force-mounted ha-insights-panel');
})();
```

---

## 3. "Two panels stacked / duplicate render"

**Quick cleanup (modifies DOM):**

```js
document.querySelector('home-assistant').shadowRoot
  .querySelector('home-assistant-main').shadowRoot
  .querySelector('ha-panel-custom')
  .querySelectorAll('ha-insights-panel')
  .forEach((el, i) => i > 0 && el.remove());
```

Fixed permanently in card v1.3.3 / integration v1.7.5+. If you see this on v1.7.5+, run the version probe (snippet 1) to confirm you actually have the new bundle loaded.

---

## 4. "🔗 coupling badge not appearing"

```js
(async () => {
  const hass = document.querySelector('home-assistant').hass;
  
  // Step 1: confirm integration stamps _coupling
  await hass.callWS({type: 'home_insights/clear_examples'});
  await hass.callWS({type: 'home_insights/inject_examples'});
  const {insights} = await hass.callWS({type: 'home_insights/list'});
  const tight = insights.find(i =>
    i.detector === 'cooccurrence' && i.payload?._coupling?.tier === 'TIGHT'
  );
  console.log('TIGHT example payload present:', !!tight);
  if (tight) console.log('  _coupling:', tight.payload._coupling);
  
  // Step 2: check if badge is in DOM (cross-shadow walk)
  const findAll = (root, sel, acc = []) => {
    if (!root) return acc;
    if (root.querySelectorAll) acc.push(...root.querySelectorAll(sel));
    const candidates = root.querySelectorAll ? root.querySelectorAll('*') : [];
    for (const el of candidates) {
      if (el.shadowRoot) findAll(el.shadowRoot, sel, acc);
    }
    return acc;
  };
  const badges = findAll(document, '.coupling-badge');
  console.log('Badge elements in DOM:', badges.length);
  
  // Step 3: check which card class is registered (collision detector)
  const cards = findAll(document, 'ha-insights-card');
  const bundled = findAll(document, 'ha-insights-card-bundled');
  console.log('ha-insights-card instances:', cards.length);
  console.log('ha-insights-card-bundled instances:', bundled.length);
  console.log('Bundled class registered?', !!customElements.get('ha-insights-card-bundled'));
})();
```

**Interpretation:**

| Output | Diagnosis |
|---|---|
| `TIGHT example payload present: false` | Integration didn't stamp coupling — likely pre-v1.7.0 integration |
| `TIGHT example payload present: true` AND `Badge elements: 1+` | ✅ Working as designed |
| `TIGHT...: true` AND `Badge elements: 0` AND `Bundled class registered? false` | Most likely a browser-cache miss: the bundled panel.js loaded is stale. Hard-refresh (snippet 6) before assuming a class-name collision. (Live MCP verification on v1.7.4 showed the badge renders without the bundled alias.) |
| `TIGHT...: true` AND `Badge elements: 0` AND `Bundled class registered? true` AND `ha-insights-card-bundled instances: 0` | v1.7.6+ deployed but panel still embeds the OLD element. Check panel.js content for `<ha-insights-card-bundled>` |
| `TIGHT...: true` AND `Badge elements: 0` AND `ha-insights-card-bundled instances: 1+` | Render path bypasses `_renderCouplingBadge`. Different render method handles this insight type — needs source investigation. |

---

## 5. "Detector X isn't producing insights"

```js
(async () => {
  const hass = document.querySelector('home-assistant').hass;
  const dir = await hass.callWS({type: 'home_insights/detector_directory'});
  console.log('All detectors:', dir.detectors.map(d => ({
    name: d.name,
    maturity: d.maturity,
  })));
  const {insights} = await hass.callWS({type: 'home_insights/list'});
  const byDetector = {};
  for (const i of insights) byDetector[i.detector] = (byDetector[i.detector] || 0) + 1;
  console.log('Insights by detector:', byDetector);
  const rec = await hass.callWS({type: 'home_insights/recorder_status'});
  console.log('Recorder window:', rec);
})();
```

Cooccurrence / lagged_correlation / button_press_habit need:
- ≥15 occurrences per entity (MIN_OCCURRENCES floor)
- ≥60% consistency
- Sub-30s (cooccurrence) or 60s-10min (lagged) lag
- A 14-day event-buffer history

If your install doesn't have device-binding patterns or button-press wiring, these may genuinely never produce output. **Not always a bug.**

---

## 6. "Panel was working yesterday, broken after HACS update"

Most common: browser cache serving the old bundle.

1. **Hard refresh**: `Ctrl+Shift+R` (Windows) / `Cmd+Shift+R` (Mac)
2. If that fails, **HACS → HA Insights → ⋮ → Update information** then HA restart
3. Then version probe (snippet 1) — confirm the version matches what HACS shows installed
4. If still wrong: **incognito window** rules out persistent cache entirely

---

## 7. "AbortError: Transition was skipped" in console

```
Uncaught (in promise) AbortError: Transition was skipped
logging-mixin.ts:77 Failure writing unhandled promise rejection to system log: Error: Cannot parse given Error object
```

**Not an HA Insights bug.** HA's Vaadin Router throws AbortError whenever a route transition is superseded by another navigation — normal browser behavior. The second message is HA's logging mixin failing to serialize the DOMException — HA bug.

Both messages are cosmetic and persist regardless of HA Insights version. They become relevant only when the AbortError interrupts the panel mount, which is what the v1.2.26 recovery (refined in v1.3.1 / v1.3.4) addresses.

---

## Quick reference: file paths

When investigating with a clone of the repos:

```
custom_components/ha_insights/__init__.py         # _async_register_panel
custom_components/ha_insights/static/panel.js     # bundled panel JS (v1.7.3+)
custom_components/ha_insights/lib/coupling_strength.py   # CouplingScore logic
src/ha-insights-card.ts                           # _renderRow, _renderCouplingBadge
src/ha-insights-panel.ts                          # panel shell, recovery IIFE, card alias
```

## When all else fails

If a diagnostic doesn't fit anything in this doc:

1. Run all the snippets above and save the console output.
2. Take a screenshot of the panel state.
3. Note the integration version, card version (if visible in HACS), and HA version.
4. File an issue at <https://github.com/botts7/ha-insights/issues> with all of the above.
