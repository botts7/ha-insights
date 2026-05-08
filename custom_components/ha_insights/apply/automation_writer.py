"""Apply automation insights to HA via the canonical automations.yaml path.

This mirrors what HA's own UI editor does (POST /api/config/automation/config/{id}):
  - Writes the entry into <config>/automations.yaml
  - Triggers `automation.reload` so HA picks up the new entry as a runtime entity

Why not the storage helper? `Store(hass, version=1, key="automations")` writes
to `.storage/automations` which the automation domain does NOT read for
runtime registration. The entry would persist on disk but never become a
working automation entity.

Drift detection (separate module) compares snapshot vs current YAML so undo
flows can warn the user before reverting their manual edits.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


_AUTOMATION_FILE = "automations.yaml"
_ID_PREFIX = "ha_insights_"


class AutomationWriter:
    """Read / create / delete automations in HA's automations.yaml."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._path = Path(hass.config.path(_AUTOMATION_FILE))

    async def write(
        self,
        payload: dict[str, Any],
        *,
        auto_id: str | None = None,
    ) -> str:
        """Create or replace an automation. Returns the automation id."""
        if auto_id is None:
            auto_id = f"{_ID_PREFIX}{uuid.uuid4().hex[:8]}"

        config = dict(payload)
        config["id"] = auto_id

        await self._hass.async_add_executor_job(
            self._write_yaml_sync, auto_id, config
        )
        await self._hass.services.async_call(
            "automation", "reload", blocking=True
        )
        return auto_id

    async def read(self, auto_id: str) -> dict[str, Any] | None:
        return await self._hass.async_add_executor_job(self._read_yaml_sync, auto_id)

    async def delete(self, auto_id: str) -> bool:
        deleted = await self._hass.async_add_executor_job(
            self._delete_yaml_sync, auto_id
        )
        if deleted:
            await self._hass.services.async_call(
                "automation", "reload", blocking=True
            )
        return deleted

    # --- Sync file I/O (called via executor) ---

    def _load_existing(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        text = self._path.read_text(encoding="utf-8")
        if not text.strip():
            return []
        loaded = yaml.safe_load(text)
        if loaded is None:
            return []
        if isinstance(loaded, list):
            return [item for item in loaded if isinstance(item, dict)]
        if isinstance(loaded, dict):
            return [loaded]
        return []

    def _save_existing(self, items: list[dict[str, Any]]) -> None:
        self._path.write_text(
            yaml.safe_dump(items, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

    def _write_yaml_sync(self, auto_id: str, config: dict[str, Any]) -> None:
        existing = self._load_existing()
        for i, item in enumerate(existing):
            if item.get("id") == auto_id:
                existing[i] = config
                break
        else:
            existing.append(config)
        self._save_existing(existing)

    def _read_yaml_sync(self, auto_id: str) -> dict[str, Any] | None:
        for item in self._load_existing():
            if item.get("id") == auto_id:
                return dict(item)
        return None

    def _delete_yaml_sync(self, auto_id: str) -> bool:
        existing = self._load_existing()
        for i, item in enumerate(existing):
            if item.get("id") == auto_id:
                del existing[i]
                self._save_existing(existing)
                return True
        return False
