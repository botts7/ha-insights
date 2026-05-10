# Writing a detector

Detectors are the primary extension point of HA Insights. Each detector looks at observed state and emits Insight objects.

## The Detector contract

```python
from custom_components.ha_insights.detectors.base import (
    Detector,
    DetectorContext,
    register_detector,
)
from custom_components.ha_insights.insight import Insight, InsightKind


@register_detector
class MyDetector(Detector):
    name = "my_detector"               # unique across all detectors
    kind = InsightKind.AUTOMATION_PROPOSAL  # or another kind
    requires_recorder = False          # True if you need HA's recorder DB
    # domains_default_blocked is inherited (camera, person, tracker, lock)

    async def scan(self, ctx: DetectorContext) -> list[Insight]:
        # Pull events from ctx.event_buffer (StateEventBuffer)
        # Apply your heuristic
        # Return zero or more Insight objects
        ...
```

The `@register_detector` decorator registers your class in the global registry. You don't have to import it anywhere else — see "Auto-discovery" below.

## What `DetectorContext` carries

| Field | Type | Notes |
|---|---|---|
| `hass` | `HomeAssistant` | The HA instance |
| `detector_config` | `dict[str, Any]` | Per-detector options from the OptionsFlow (v0.2+) |
| `area_filter` | `frozenset[str]` | Areas the user has scoped to |
| `event_buffer` | `StateEventBuffer \| None` | Rolling state-change buffer |

Stable shape from v0.1 — new optional fields will be appended over time as later steps add capabilities (recorder helper, redactor for explanations, etc.).

## What an Insight needs

```python
Insight(
    id=Insight.compute_id(kind, fingerprint),  # stable hash
    kind=InsightKind.AUTOMATION_PROPOSAL,
    detector=self.name,
    area_id="kitchen",                      # or None
    title="...",                            # human-readable, no LLM
    confidence=0.85,                        # 0.0..1.0
    fingerprint={...},                      # JSON-serializable dedup key
    payload={...},                          # the YAML/config to apply
    payload_format="automation",            # or blueprint, card, etc.
    created_at=datetime.now(tz=UTC),
)
```

`compute_id` makes the same routine produce the same id across re-scans, so the store dedupes. The fingerprint must be JSON-canonicalizable.

## Auto-discovery

Drop your file in `custom_components/ha_insights/detectors/your_name.py`. The registry's `__init__.py` calls `pkgutil.iter_modules` at integration load and imports every sibling — your `@register_detector` runs as a side effect.

## Performance budget

Per [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) §Operational policies:

- Per-detector scan budget: **500ms p95** wall-clock
- Total nightly scan job (across all detectors): **≤ 30s**
- Memory ceiling: **50 MB resident** (RPi 4 reality)

If your detector needs more, document why and consider splitting the work across multiple scan calls.

## Idempotency

The same `(kind, fingerprint)` must always produce the same `id`. Re-runs upsert; the store handles dedup. If your detector emits a slightly different fingerprint each run for the same logical pattern, you'll get duplicate insights — fix the fingerprint to be stable.

## Default-blocked domains

`domains_default_blocked` (inherited from `Detector`) is `{camera, person, device_tracker, lock}`. Your detector can:

- Inherit the default (recommended) — respects user privacy + safety
- Override the class attribute — if you genuinely need a different set, document the rationale

The `lock` domain stays blocked regardless — never emit an insight that would automate a lock without explicit user approval through a separate UX path.

## User-supplied detectors (sandbox)

If your detector ships outside the integration repo and lands in a user's `<config>/ha_insights_detectors/*.py`, the AST sandbox enforces:

- **Off by default.** The user must toggle `allow_user_detectors` ON in the OptionsFlow before any user-supplied file is loaded.
- **Forbidden imports.** Any of `os`, `subprocess`, `socket`, `ssl`, `urllib`, `urllib3`, `http`, `requests`, `httpx`, `aiohttp`, `websocket`, `websockets`, `ftplib`, `smtplib`, `telnetlib`, `imaplib`, `poplib`, `shutil`, `tempfile`, `fcntl`, `termios`, `pwd`, `grp`, `spwd`, `ctypes`, `cffi`, `pickle`, `marshal`, `shelve`, `code`, `codeop` causes the module to be rejected at load time with a logged WARNING.
- **Forbidden names.** `__import__`, `__builtins__`, `__loader__`, `__spec__`, `eval`, `exec`, `compile` (as Name OR Attribute access) trip the same rejection.
- **Underscore-prefixed filenames are skipped.** Loader internals only.
- **Module namespace isolation.** Your file is imported as `ha_insights_user.<filename>` — even if you name yours `schedule.py`, the built-in `ScheduleDetector` is not shadowed.

The check is best-effort, not an actual subprocess sandbox. A determined attacker could bypass it with `getattr(...)` tricks. Real isolation requires HA-level subprocess work; the combination of opt-in + allowlist matches the actual threat model: protect users from accidentally trusting a community detector that wasn't properly reviewed.

**For detectors that need allowed modules** — `typing`, `dataclasses`, `enum`, `re`, `math`, `statistics`, `itertools`, `functools`, `collections`, `datetime`, `time`, plus the HA Insights detector API (`base`, `insight`, `observers.state_event_buffer`) — there's nothing to declare. Just write idiomatic Python.

## Testing

`tests/test_<your_detector>.py` — construct a `StateEventBuffer` directly with synthetic events, build a `DetectorContext` with a `MagicMock` hass, call `await detector.scan(ctx)` and assert on the returned insights.

See [`tests/test_schedule_detector.py`](https://github.com/botts7/ha-insights/blob/main/tests/test_schedule_detector.py) for the full pattern.

## Submitting

PR to `main`. Include:

1. Your detector module
2. A test file with at minimum: positive case (insight produced), negative case (no insight), confidence-edge case
3. A one-paragraph description in the PR body explaining what your detector finds and how it differs from existing detectors

For larger contributions, open an issue first to discuss the detector kind and confidence calibration.
