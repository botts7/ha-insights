# Setting up Chrome DevTools MCP for Claude Code

This doc walks through installing the Chrome DevTools MCP server so Claude Code can drive your browser directly — open URLs, inspect the live DOM (including shadow roots), evaluate JS, take screenshots, watch network frames — without you copy-pasting console snippets.

Written for **Windows** (botts7's setup) but the steps are nearly identical on macOS / Linux.

---

## Why bother

When debugging the HA Insights panel, every "blank panel" or "badge missing" report previously needed you to paste a console snippet, copy the output back, and forward it to Claude. With Chrome DevTools MCP installed:

- Claude opens `/ha-insights` itself.
- Reads the actual rendered DOM (cross-shadow-root, not just `document.body`).
- Evaluates expressions like `window.__haInsightsPanelRecovery` directly.
- Takes a screenshot before/after a fix.
- Watches WebSocket frames to confirm the `_coupling` payload arrived.

No more "paste this and tell me what it says" loops.

---

## Prerequisites

1. **Node.js 18+** — the MCP server is a Node process.
   ```pwsh
   node --version
   ```
   If you don't have it, install from <https://nodejs.org/> (LTS).

2. **Chrome installed** — Chromium also works. The MCP attaches to it via Chrome DevTools Protocol.

3. **Claude Code** (already running, since you're reading this) — version recent enough to support MCP. If `claude --version` shows ≥ 1.x, you're fine.

---

## Step 1 — Verify the package name

The official package is published by Google as **`chrome-devtools-mcp`** on npm:

```pwsh
npm view chrome-devtools-mcp version
```

If that returns a version number, you're good. (If it 404s or has been renamed, search npm for `chrome-devtools-mcp` and use whatever name comes up; the config below just needs the right package name.)

---

## Step 2 — Add to your Claude Code MCP config

Open (create if missing) `C:\Users\botts\.claude\mcp.json`:

```pwsh
# View the file
notepad $env:USERPROFILE\.claude\mcp.json
```

If the file doesn't exist yet, create it with this content:

```json
{
  "mcpServers": {
    "chrome-devtools": {
      "command": "npx",
      "args": ["-y", "chrome-devtools-mcp@latest"]
    }
  }
}
```

If it already exists, merge the `chrome-devtools` entry into the existing `mcpServers` object. **Don't replace the whole file** — you'll lose any other MCP servers configured (e.g., Gmail, Calendar, Drive seen in your session).

> ⚠️ Your global memory says `dont use node kills it stops claude`. That note appears to refer to using `node` as a shell command (which would block Claude's terminal), not to MCP servers running Node out-of-process. MCP servers run alongside Claude, not inside it. But if you start seeing Claude hang after enabling this, disable it by deleting the `chrome-devtools` block from `mcp.json` and restarting Claude.

---

## Step 3 — Launch Chrome with remote debugging enabled

The MCP needs a Chrome instance to attach to. Easiest path: keep a dedicated Chrome window open with debugging on.

Create a desktop shortcut **`Chrome (Debug)`** pointing at:

```
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:\Users\botts\chrome-debug-profile"
```

The `--user-data-dir` creates a separate profile so your normal Chrome sessions aren't affected.

Launch this shortcut and navigate to your Home Assistant (`http://192.168.86.68:8123`). Log in once; the profile persists.

Verify the debug port is open:

```pwsh
curl http://localhost:9222/json/version
```

Should return JSON with `Browser`, `Protocol-Version`, etc. If it returns nothing or connection-refused, Chrome didn't start with the flag — check the shortcut path.

---

## Step 4 — Restart Claude Code

MCP servers are loaded at session start. In your current Claude Code session:

```
/exit
```

Then re-launch Claude Code (`claude` in a fresh terminal).

On startup you should see a "Connected to chrome-devtools" message or similar. Run `/mcp` to list active servers.

---

## Step 5 — Verify in a Claude session

In Claude, ask:

> Use the chrome-devtools MCP to navigate to my Home Assistant `/ha-insights` page and tell me how many `ha-insights-panel` elements are in the DOM.

If Claude responds with a number (likely 1 if v1.7.5+ is healthy), the setup works.

---

## What I'll be able to do once this is live

| Action | MCP tool |
|---|---|
| Open a URL | `mcp__chrome-devtools__navigate_page` |
| Read live DOM (cross-shadow) | `mcp__chrome-devtools__evaluate_script` |
| Take a screenshot | `mcp__chrome-devtools__take_screenshot` |
| Watch WS / fetch frames | `mcp__chrome-devtools__list_network_requests` |
| Click / type | `mcp__chrome-devtools__click` / `type` |
| Read console logs | `mcp__chrome-devtools__list_console_messages` |

(Exact tool names vary by MCP version — `/mcp` after restart shows the live set.)

---

## Common gotchas

- **Port 9222 already in use**: another Chrome debug instance is running. Either close it or pick a different port and update both the Chrome shortcut and the MCP's `args` (some versions accept `--port=9223`).
- **MCP says "no Chrome instance found"**: Chrome was launched without `--remote-debugging-port`. Check the shortcut.
- **HA blocks the connection**: HA's frontend should be fine to access locally; if you hit a "Connection refused" in browser, that's your HA URL/auth, not the MCP.
- **`npx` first-run is slow** (~30s while it downloads the package). After that it's cached and instant.

---

## Disabling later

Remove the `chrome-devtools` block from `mcp.json`, save, restart Claude Code. Or rename the file to `mcp.json.disabled` to keep the config around for later.

---

## Related

- Official MCP docs: <https://modelcontextprotocol.io/>
- Chrome DevTools Protocol: <https://chromedevtools.github.io/devtools-protocol/>
- HA Insights panel diagnostic page: `docs/panel-troubleshooting.md` *(future)*
