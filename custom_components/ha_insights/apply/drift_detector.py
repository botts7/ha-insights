"""Drift detection for applied automations.

When the user accepts an insight we record a snapshot of the automation we
wrote. If the user later edits that automation in HA's UI and then asks to
undo our apply, drift detection lets us warn them before reverting their
manual edits.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def hash_config(config: dict[str, Any]) -> str:
    """Stable canonical hash of an automation config."""
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return hashlib.blake2b(canonical.encode("utf-8"), digest_size=16).hexdigest()


def detect_drift(snapshot: dict[str, Any], current: dict[str, Any]) -> bool:
    """True if the live config has changed since the snapshot was taken."""
    return hash_config(_strip_volatile(snapshot)) != hash_config(_strip_volatile(current))


def _strip_volatile(config: dict[str, Any]) -> dict[str, Any]:
    """Drop fields that HA may rewrite on save without the user editing them.

    For now: nothing — but the hook is here so we can add fields like
    `last_triggered` if HA starts persisting them inside config.
    """
    return {k: v for k, v in config.items() if not k.startswith("_")}
