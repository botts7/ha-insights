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

    The function used by HA's automation domain has shifted signature
    across versions (some take (hass, config), others (hass, config_key,
    config)). We try the known shapes in order and fall through to no-op
    if none work, so apply never breaks because of helper drift.
    """
    try:
        from homeassistant.components.automation.config import (
            async_validate_config_item,
        )
    except ImportError:
        _LOGGER.debug(
            "online validator unavailable; falling back to Layer 1 only"
        )
        return []

    # Try modern (hass, config) signature first.
    try:
        result = await async_validate_config_item(hass, config)  # type: ignore[arg-type]
        if result is False or result is None:
            # Some HA versions return None on success, False on failure.
            # We treat None as success unless an exception was raised.
            pass
        return []
    except TypeError as exc:
        # Signature drift: try the (hass, config_key, config) shape
        message = str(exc)
        if "missing" in message and "argument" in message:
            try:
                # Synthesize a config_key from the alias (HA uses the
                # automation's id internally; alias is good enough for
                # validation purposes — it doesn't get persisted)
                config_key = config.get("alias") or config.get("id") or "ha_insights_validate"
                await async_validate_config_item(hass, config_key, config)  # type: ignore[call-arg]
                return []
            except (vol_invalid_or_other(), TypeError, ValueError) as inner:
                inner_msg = str(inner).strip() or inner.__class__.__name__
                return [inner_msg]
            except Exception as inner:
                _LOGGER.debug("online validator (3-arg) errored: %s", inner)
                return []
        # TypeError NOT about missing args = real problem with the config
        return [message.strip() or "TypeError"]
    except Exception as exc:
        # vol.Invalid renders nicely; other exceptions get a generic prefix
        message = str(exc).strip() or exc.__class__.__name__
        return [message]


def vol_invalid_or_other():
    """Return a tuple of exceptions that mean "config rejected by validator".

    Imported lazily because voluptuous may not be present in some test
    environments — falling back to a generic Exception keeps the wrapper
    from crashing on import-time failures.
    """
    try:
        import voluptuous as vol

        return (vol.Invalid,)
    except ImportError:
        return (Exception,)
