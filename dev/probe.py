#!/usr/bin/env python3
"""End-to-end probe for HA Insights integration.

Connects to dev HA at localhost:8123, exercises the WS API, asserts
expected pipeline behavior. Used by the autonomous dev loop and CI.

Stub for G1 — actual assertions land at later critical-path steps:
- step 11: WS API hello/list/subscribe handshake assertions
- step 13: apply pipeline assertions
- step 18: explain + redaction preview assertions
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path


def read_token() -> str | None:
    """Read long-lived token from dev/token.txt."""
    token_path = Path(__file__).parent / "token.txt"
    if not token_path.exists():
        return None
    text = token_path.read_text(encoding="utf-8").strip()
    return text or None


async def probe_alive() -> bool:
    """Stub: confirms script runs. Real assertions land at later steps."""
    print("HA Insights probe — G1 stub")
    print(f"Token present: {read_token() is not None}")
    print("Real assertions land at critical-path steps 11, 13, 18.")
    return True


async def main() -> int:
    return 0 if await probe_alive() else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
