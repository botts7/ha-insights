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

## Why this harness exists

HA Insights claims to detect routines from observed state — that claim must be demonstrable end-to-end before any detector or pipeline change is trusted. This harness lets a developer (or autonomous agent) seed a fresh HA, run the full pipeline, and assert the result, in under 2 minutes.

## Probe scripts

| Script | Purpose |
|---|---|
| `probe.py` | End-to-end happy path: seed → scan → list → apply → verify automation written |
| `seed.py` | CLI seeder for arbitrary entity / state / time-of-day patterns |
| `_demo_seed.py` | Quick weekday-routine demo against `light.dashboard_demo` |
| `_cooccurrence_seed.py` | Door-then-light pairs to exercise CooccurrenceDetector |
| `_refine_probe.py` | Drives `home_insights/refine` against the live LLM, prints raw response (use with `--detector cooccurrence` to pick a specific insight) |
| `_backfill_probe.py` | Calls `ha_insights.backfill` service and prints status |
