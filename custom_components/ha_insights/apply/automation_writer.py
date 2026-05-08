"""Apply automation insights to HA via the storage-helper for storage-mode automations.

Writes through `homeassistant.helpers.storage.Store` keyed `"automations"` so HA's
own automation editor can pick the entry up immediately. After write, fires
`automation.reload` so HA registers the new trigger.

Drift detection (separate module) compares current vs the snapshot we record
at apply time, so undo flows can warn the user before reverting their edits.
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.storage import Store

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


_AUTOMATION_STORAGE_KEY = "automations"
_AUTOMATION_STORAGE_VERSION = 1
_ID_PREFIX = "ha_insights_"


class AutomationWriter:
    """Read / create / delete storage-mode automations on behalf of HA Insights."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._store: Store = Store(
            hass, _AUTOMATION_STORAGE_VERSION, _AUTOMATION_STORAGE_KEY
        )

    async def write(
        self,
        payload: dict[str, Any],
        *,
        auto_id: str | None = None,
    ) -> str:
        """Create or replace an automation. Returns the automation id."""
        if auto_id is None:
            auto_id = f"{_ID_PREFIX}{uuid.uuid4().hex[:8]}"

        existing = await self._load()
        config = dict(payload)
        config["id"] = auto_id

        for i, item in enumerate(existing):
            if item.get("id") == auto_id:
                existing[i] = config
                break
        else:
            existing.append(config)

        await self._store.async_save(existing)
        await self._hass.services.async_call(
            "automation", "reload", blocking=True
        )
        return auto_id

    async def read(self, auto_id: str) -> dict[str, Any] | None:
        for item in await self._load():
            if item.get("id") == auto_id:
                return dict(item)
        return None

    async def delete(self, auto_id: str) -> bool:
        existing = await self._load()
        for i, item in enumerate(existing):
            if item.get("id") == auto_id:
                del existing[i]
                await self._store.async_save(existing)
                await self._hass.services.async_call(
                    "automation", "reload", blocking=True
                )
                return True
        return False

    async def _load(self) -> list[dict[str, Any]]:
        loaded = await self._store.async_load()
        if loaded is None:
            return []
        if isinstance(loaded, list):
            return loaded
        # Some HA versions wrap the list in {"items": [...]} or similar.
        if isinstance(loaded, dict) and isinstance(loaded.get("items"), list):
            return loaded["items"]
        return []
