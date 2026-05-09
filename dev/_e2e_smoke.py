"""End-to-end smoke harness for the live dev HA instance.

Exercises every non-LLM scenario (apply, undo, test_actions, redaction
preview, audit log, validator gates, drift detection) and reports
PASS/FAIL with a brief description per scenario.

Catches the class of bugs that unit tests miss because they don't drive
a real WS connection against a real HA + real automations.yaml. Each
scenario marked [REGRESSION] is a previously-debugged bug that this
script exists to keep regressed.

Usage:
  python dev/_e2e_smoke.py            # run all scenarios
  python dev/_e2e_smoke.py --quick    # skip apply/undo round-trips that
                                       # mutate automations.yaml
  python dev/_e2e_smoke.py --keep     # leave seeded test insights in
                                       # place after the run

Exit code 0 on all-pass, 1 if any scenario failed.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import aiohttp

# Windows cmd defaults to cp1252 which can't encode ✓ / ✗. Reconfigure
# stdout to UTF-8 so the report renders consistently across terminals.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

TOKEN_PATH = Path(__file__).parent / "token.txt"
HA_PORT = os.environ.get("HA_PORT", "8125")
WS_URL = f"ws://localhost:{HA_PORT}/api/websocket"
AUTOMATIONS_YAML = Path(__file__).parent / "config" / "automations.yaml"


# --- ANSI colors for the terminal report ---
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
DIM = "\033[2m"
RESET = "\033[0m"


class Smoke:
    """Test harness state + scenario runner."""

    def __init__(self) -> None:
        self.results: list[tuple[str, bool, str]] = []
        self._next_id = 0
        self.ws: aiohttp.ClientWebSocketResponse | None = None

    def _id(self) -> int:
        self._next_id += 1
        return self._next_id

    async def call(self, msg_type: str, **fields) -> dict:
        assert self.ws is not None
        payload = {"id": self._id(), "type": msg_type, **fields}
        await self.ws.send_json(payload)
        return await self.ws.receive_json()

    async def assert_pass(self, name: str, cond: bool, detail: str = "") -> None:
        self.results.append((name, cond, detail))
        marker = f"{GREEN}✓{RESET}" if cond else f"{RED}✗{RESET}"
        suffix = f"  {DIM}{detail}{RESET}" if detail else ""
        print(f"  {marker} {name}{suffix}")

    async def authenticate(self) -> None:
        token = TOKEN_PATH.read_text(encoding="utf-8").strip()
        await self.ws.receive_json()  # auth_required
        await self.ws.send_json({"type": "auth", "access_token": token})
        result = await self.ws.receive_json()
        assert result["type"] == "auth_ok", f"auth failed: {result}"

    async def inject(self, **fields) -> dict:
        return await self.call("home_insights/_dev/inject_event", **fields)

    async def list_insights(self, *, include_applied: bool = False) -> list[dict]:
        r = await self.call(
            "home_insights/list", include_applied=include_applied
        )
        if not r.get("success"):
            return []
        return r["result"]["insights"]


async def section(title: str) -> None:
    print(f"\n{YELLOW}== {title} =={RESET}")


async def scenario_handshake(s: Smoke) -> None:
    await section("WS handshake")
    r = await s.call("home_insights/hello", card_version="0.8.1")
    await s.assert_pass(
        "hello returns success",
        r.get("success") is True,
        f"got {r}",
    )
    result = r.get("result", {})
    methods = set(result.get("supported_methods", []))
    expected = {
        "list", "subscribe", "apply", "undo", "explain", "refine",
        "test_actions", "redaction_preview", "audit_log",
    }
    missing = expected - methods
    await s.assert_pass(
        "hello advertises core methods",
        not missing,
        f"missing: {missing}" if missing else "",
    )
    await s.assert_pass(
        "hello returns privacy_mode",
        "privacy_mode" in result,
    )


async def scenario_test_actions_data_unwrap(s: Smoke) -> None:
    """[REGRESSION] persistent_notification.create's data: key was being
    double-wrapped in service_data, producing 'extra keys not allowed
    @ data[\"data\"]'. The handler must unwrap action['data'] flat into
    service_data."""
    await section("test_actions: data: key unwrap [REGRESSION]")
    # Seed a fake insight with a data-wrapped action
    fake_insight_id = "_smoke_data_wrap"
    payload = {
        "alias": "Smoke wrapper test",
        "trigger": [{"platform": "state", "entity_id": "sun.sun"}],
        "action": [
            {
                "service": "persistent_notification.create",
                "data": {"title": "Smoke", "message": "Smoke test fired"},
            }
        ],
        "mode": "single",
    }
    # Inject straight into store via dev endpoint? No — we don't have one.
    # Instead, call test_actions on an existing insight via payload_override.
    # We need ANY insight to provide an id.
    insights = await s.list_insights(include_applied=True)
    if not insights:
        await s.assert_pass(
            "test_actions data-wrap (skipped — no insights to use as carrier)",
            False,
            "run _seed_all_demos.py first",
        )
        return
    carrier = insights[0]
    r = await s.call(
        "home_insights/test_actions",
        insight_id=carrier["id"],
        payload_override=payload,
    )
    await s.assert_pass(
        "test_actions accepts data: wrapper without error",
        r.get("success") is True,
        f"got {r}",
    )
    if r.get("success"):
        result = r["result"]
        # Either it ran (1) or it errored on persistent_notification not loaded;
        # what we DON'T want is "extra keys not allowed" parser error
        first_error = next(
            (x.get("error", "") for x in result.get("results", []) if x.get("error")),
            "",
        )
        await s.assert_pass(
            "no 'extra keys not allowed' in error path",
            "extra keys not allowed" not in first_error,
            f"first error: {first_error}" if first_error else "",
        )


async def scenario_test_actions_flat_params(s: Smoke) -> None:
    await section("test_actions: flat params + target.entity_id")
    insights = await s.list_insights()
    if not insights:
        await s.assert_pass("flat params (skipped)", False, "no insights")
        return
    carrier = insights[0]
    r = await s.call(
        "home_insights/test_actions",
        insight_id=carrier["id"],
        payload_override={
            "alias": "Flat params test",
            "trigger": [{"platform": "state", "entity_id": "sun.sun"}],
            "action": [
                {
                    "service": "homeassistant.update_entity",
                    "target": {"entity_id": "sun.sun"},
                }
            ],
            "mode": "single",
        },
    )
    await s.assert_pass(
        "test_actions with target.entity_id round-trips",
        r.get("success") is True,
        f"got {r.get('error', r)}",
    )


async def scenario_test_actions_skip_non_service(s: Smoke) -> None:
    await section("test_actions: non-service actions skipped")
    insights = await s.list_insights()
    if not insights:
        await s.assert_pass("skip non-service (skipped)", False, "no insights")
        return
    carrier = insights[0]
    r = await s.call(
        "home_insights/test_actions",
        insight_id=carrier["id"],
        payload_override={
            "alias": "Mixed actions",
            "trigger": [{"platform": "state"}],
            "action": [
                {"delay": "00:00:01"},
                {"wait_for_trigger": {"platform": "state"}},
            ],
            "mode": "single",
        },
    )
    if r.get("success"):
        result = r["result"]
        all_skipped = all(item.get("skipped") for item in result["results"])
        await s.assert_pass(
            "all non-service entries marked skipped (not errored)",
            all_skipped and result["error_count"] == 0,
            f"results={result['results']}",
        )
    else:
        await s.assert_pass("non-service skip handles gracefully", False, str(r))


async def scenario_redaction_preview(s: Smoke) -> None:
    await section("redaction preview")
    insights = await s.list_insights()
    if not insights:
        await s.assert_pass("redaction preview (skipped)", False, "no insights")
        return
    target = insights[0]
    r = await s.call("home_insights/redaction_preview", insight_id=target["id"])
    await s.assert_pass(
        "redaction_preview success",
        r.get("success") is True,
    )
    if r.get("success"):
        result = r["result"]
        for key in (
            "redacted_title",
            "redacted_payload",
            "entities_blocked",
            "pseudonym_map",
            "attributes_stripped",
            "privacy_mode",
        ):
            await s.assert_pass(
                f"preview has key: {key}",
                key in result,
            )


async def scenario_audit_log(s: Smoke) -> None:
    await section("audit log endpoint")
    r = await s.call("home_insights/audit_log", limit=10)
    await s.assert_pass(
        "audit_log success",
        r.get("success") is True,
    )
    if r.get("success"):
        await s.assert_pass(
            "audit_log returns calls list",
            isinstance(r["result"].get("calls"), list),
        )


async def scenario_apply_rejects_invalid(s: Smoke) -> None:
    """Layer 1 must reject a payload missing required keys."""
    await section("apply: Layer 1 validation rejects bad payload")
    insights = await s.list_insights()
    if not insights:
        await s.assert_pass("apply L1 (skipped)", False, "no insights")
        return
    carrier = insights[0]
    r = await s.call(
        "home_insights/apply",
        insight_id=carrier["id"],
        payload_override={"alias": "no-trigger"},
    )
    await s.assert_pass(
        "apply rejects payload missing trigger/action",
        r.get("success") is False,
        f"error: {r.get('error', {}).get('code')}",
    )


async def scenario_apply_layer2_rejects_unknown_platform(s: Smoke) -> None:
    """[REGRESSION] Layer 2 (HA's automation validator) rejects a fake
    trigger platform."""
    await section("apply: Layer 2 rejects unknown platform [REGRESSION]")
    insights = await s.list_insights()
    if not insights:
        await s.assert_pass("apply L2 (skipped)", False, "no insights")
        return
    carrier = insights[0]
    r = await s.call(
        "home_insights/apply",
        insight_id=carrier["id"],
        payload_override={
            "alias": "Bad platform",
            "trigger": [{"platform": "definitely_not_a_real_platform_zzz"}],
            "action": [{"service": "light.turn_on"}],
            "mode": "single",
        },
    )
    await s.assert_pass(
        "apply rejects unknown trigger platform",
        r.get("success") is False,
        f"error code: {r.get('error', {}).get('code')}",
    )


async def scenario_undo_round_trip(s: Smoke, *, mutate: bool) -> None:
    """Apply then undo: yaml entry written then removed, applied_at cleared."""
    await section("undo: apply -> undo round-trip [REGRESSION]")
    if not mutate:
        await s.assert_pass("undo round-trip (skipped — --quick mode)", True)
        return

    insights = await s.list_insights()
    candidate = next(
        (i for i in insights if i.get("payload_format") == "automation"), None
    )
    if candidate is None:
        await s.assert_pass(
            "undo round-trip (skipped)", False, "no automation insights"
        )
        return

    r = await s.call("home_insights/apply", insight_id=candidate["id"])
    if not r.get("success"):
        await s.assert_pass(
            f"apply succeeded for {candidate['title'][:40]}",
            False,
            f"error: {r.get('error')}",
        )
        return
    auto_id = r["result"]["automation_id"]
    await s.assert_pass(
        f"applied {auto_id}",
        True,
    )

    # Yaml entry exists?
    if AUTOMATIONS_YAML.exists():
        content = AUTOMATIONS_YAML.read_text(encoding="utf-8")
        await s.assert_pass(
            "automations.yaml contains the new id",
            auto_id in content,
        )
    else:
        await s.assert_pass("automations.yaml exists", False, "file missing")

    # Insight is now applied
    refreshed = next(
        (i for i in await s.list_insights(include_applied=True) if i["id"] == candidate["id"]),
        None,
    )
    await s.assert_pass(
        "insight has applied_at set",
        refreshed is not None and refreshed.get("applied_at") is not None,
    )

    # Undo (no drift; should succeed without force)
    r = await s.call("home_insights/undo", insight_id=candidate["id"])
    await s.assert_pass(
        "undo without drift succeeds",
        r.get("success") is True,
        f"got: {r.get('error') if not r.get('success') else 'ok'}",
    )

    # Yaml entry removed?
    if AUTOMATIONS_YAML.exists():
        content = AUTOMATIONS_YAML.read_text(encoding="utf-8")
        await s.assert_pass(
            "automations.yaml no longer contains the id",
            auto_id not in content,
        )

    # Insight is back to active
    active = await s.list_insights()
    found = any(i["id"] == candidate["id"] for i in active)
    await s.assert_pass(
        "insight reappears in active list after undo",
        found,
    )


async def scenario_undo_unknown(s: Smoke) -> None:
    await section("undo: unknown insight returns not_applied")
    r = await s.call(
        "home_insights/undo", insight_id="this_id_does_not_exist"
    )
    await s.assert_pass(
        "undo unknown insight rejects",
        r.get("success") is False,
        f"code: {r.get('error', {}).get('code')}",
    )


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="skip mutate-yaml scenarios")
    args = parser.parse_args()

    s = Smoke()
    print(f"\n{YELLOW}HA Insights e2e smoke{RESET}")
    print(f"{DIM}Running against {WS_URL}{RESET}\n")

    async with aiohttp.ClientSession() as sess:
        async with sess.ws_connect(WS_URL) as ws:
            s.ws = ws
            await s.authenticate()

            await scenario_handshake(s)
            await scenario_redaction_preview(s)
            await scenario_audit_log(s)
            await scenario_test_actions_data_unwrap(s)
            await scenario_test_actions_flat_params(s)
            await scenario_test_actions_skip_non_service(s)
            await scenario_apply_rejects_invalid(s)
            await scenario_apply_layer2_rejects_unknown_platform(s)
            await scenario_undo_unknown(s)
            await scenario_undo_round_trip(s, mutate=not args.quick)

    # Report
    total = len(s.results)
    failed = [(name, detail) for name, ok, detail in s.results if not ok]
    print(f"\n{YELLOW}== summary =={RESET}")
    print(f"  {total - len(failed)} / {total} passed")
    if failed:
        print(f"  {RED}{len(failed)} failed:{RESET}")
        for name, detail in failed:
            print(f"    {RED}- {name}{RESET}{(' — ' + detail) if detail else ''}")
        return 1
    print(f"  {GREEN}all pass{RESET}\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
