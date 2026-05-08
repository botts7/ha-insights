# Dev harness

Spin a dockerized Home Assistant instance with the HA Insights integration mounted, seed it with synthetic state, and run end-to-end probes. Used by the autonomous dev loop and by humans for manual verification.

## Prereqs

- Docker Desktop (running)
- Python 3.13+
- Bash (Linux/macOS native; Windows via Git Bash or WSL)

## Quick start

Optional: copy `.env.example` to `.env` and set `TZ=` (timezone, defaults to UTC) or `HA_PORT=` (host port, defaults to 8125 — chosen to avoid clashing with HA's default 8123 or any other HA dev/test container you may already be running). `.env` is gitignored.

```bash
./up.sh                  # Boots HA at http://localhost:8125 (or $HA_PORT)
# First time: open browser, complete onboarding, create a long-lived
# token, save it to dev/token.txt
python probe.py          # End-to-end pipeline assertion
./down.sh                # Stop the container (preserves state)
./reset.sh               # Wipe state and start fresh
```

## What gets mounted

The integration's `custom_components/ha_insights/` is volume-mounted at `/config/custom_components/ha_insights/` inside the HA container. Code changes take effect on HA restart (`docker compose restart homeassistant`).

## State

`dev/config/` and `dev/token.txt` are gitignored. Wiped by `reset.sh`.

## Why this exists at v0.1

Per the charter (§Testing harness & autonomous dev loop): HA Insights claims to detect routines from observed state — that claim must be demonstrable end-to-end before any insight code is trusted. This harness lets a developer (or autonomous agent) seed a fresh HA, run the full pipeline, and assert the result, in under 2 minutes.
