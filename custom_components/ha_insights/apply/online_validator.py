"""Layer 2 validator — uses HA's own automation config validation.

Layer 1 (`validator.py`) is offline shape-checking: required keys,
correct types, mode is one of the valid enum values. Useful but
doesn't catch:
  - Services that don't exist on the user's HA install
  - Entities not in the registry
  - Conditions that reference unloaded integrations
  - Trigger platforms with bad parameter shapes

Layer 2 plugs into HA's automation domain validator so we catch all of
the above before we write to automations.yaml. Cheaper than the
runtime failure path (silent log, no UI feedback) and lets us return
the actual reason to the user.

The HA-side validator's API has shifted slightly across versions; we
resolve the function dynamically and return a graceful empty-error
list if it can't be imported (so older HA versions still apply via
Layer 1 only).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


async def validate_automation_online(
    hass: HomeAssistant, config: dict[str, Any]
) -> list[str]:
    """Run HA's automation config validator on `config`.

    Returns a list of human-readable error strings (empty = valid).
    Errors include things like:
      - "Service light.turn_oN does not exist"
      - "Entity light.kitchen not found"
      - "expected dict for dictionary value @ data['action'][0]"

    Falls back to no-op (returns []) if HA's validator can't be imported,
    so we never block apply on a missing helper.
    """
    validate = _resolve_validator()
    if validate is None:
        _LOGGER.debug(
            "online validator unavailable; falling back to Layer 1 only"
        )
        return []

    try:
        await validate(hass, config)
        return []
    except Exception as exc:
        # vol.Invalid renders nicely; other exceptions get a generic prefix
        message = str(exc).strip() or exc.__class__.__name__
        return [message]


def _resolve_validator():
    """Find HA's automation config validator across version drift.

    Returns an awaitable callable `(hass, config) -> None` that raises on
    invalid config, or None if no compatible function exists.
    """
    try:
        # Modern (HA 2024.x+): direct module-level coroutine
        from homeassistant.components.automation.config import (
            async_validate_config_item,  # type: ignore[attr-defined]
        )
        return async_validate_config_item
    except ImportError:
        pass

    try:
        # Older path some HA versions used
        from homeassistant.components.automation import (
            async_validate_config,  # type: ignore[attr-defined]
        )

        async def _wrapper(hass, config):
            await async_validate_config(hass, [config])

        return _wrapper
    except ImportError:
        pass

    return None
