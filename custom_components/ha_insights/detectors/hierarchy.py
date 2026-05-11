"""EntityHierarchy — the single authoritative entity-relationship view.

Replaces the previous scattered dicts (device_id_by_entity,
entity_dependencies, container_to_members, …) with one frozen
dataclass built from HA's actual registries:

  - entity_registry — entity → device, platform, device_class, category
  - device_registry — devices → areas
  - area_registry   — areas → floors
  - floor_registry  — (HA 2024+, optional)
  - label_registry  — (HA 2024+, optional)
  - hass.states     — group/scene/script attribute relationships
  - hass.data["script"] — script action targets

Built ONCE per scan on the event loop, then handed to worker threads
read-only. Includes both forward (entity → device, etc.) and inverse
(device → entities) maps for O(1) lookup in either direction.

The integration / platform axis is first-class: every entity_id maps
to its integration name (zigbee2mqtt, hue, tuya, mqtt, ...). Drives
the 🏷️ pill and a future per-integration filter chip.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


# Integrations whose entities commonly carry device-side automation
# (vendor app schedules, hardware timers, etc.). Used by the
# `is_externally_managed` helper to drive the 🏷️ pill and to suppress
# "create new HA automation" suggestions where the schedule lives
# outside HA. List is extensible — adding a platform here changes
# behavior for every detector + the pill.
_EXTERNAL_SCHEDULE_PLATFORMS: frozenset[str] = frozenset(
    {
        "tuya",
        "tuya_local",
        "localtuya",
        "smartlife",
        "ewelink",
        "ewelink_local",
        "smartthinq",
        "samsungtv_smart",
        "roborock",
        "xiaomi_vacuum",
        "miio",
        "midea_ac_lan",
        "homematic",
        "homematicip_local",
        "tasmota_irhvac",
        "petkit",
    }
)

# Human-readable labels for the 🏷️ pill text. Falls back to the
# platform name when not in the map.
_EXTERNAL_PLATFORM_LABEL: dict[str, str] = {
    "tuya": "Tuya app",
    "tuya_local": "Tuya app",
    "localtuya": "Tuya app",
    "smartlife": "Smart Life app",
    "ewelink": "eWeLink app",
    "ewelink_local": "eWeLink app",
    "smartthinq": "LG ThinQ app",
    "roborock": "Roborock app",
    "xiaomi_vacuum": "Mi Home app",
    "miio": "Mi Home app",
    "midea_ac_lan": "Midea app",
    "homematic": "HomeMatic CCU",
    "homematicip_local": "HomeMatic CCU",
    "petkit": "PetKit app",
    "samsungtv_smart": "SmartThings app",
}


# Member-list attribute names HA integrations use for group/scene
# membership. Walked in order — the first match wins per state.
_GROUP_MEMBER_ATTRS: tuple[str, ...] = ("entity_id", "group_members", "lights")


@dataclass(frozen=True)
class EntityHierarchy:
    """Frozen snapshot of every entity relationship we care about.

    Built once per scan on the event loop via `build_hierarchy(hass)`.
    Safe to pass across threads since it's immutable.

    All keys are HA entity_ids (e.g., `light.kitchen`); all values are
    frozensets / dicts / Nones — never live HA objects.
    """

    # Forward lookups (entity → something)
    device_of: dict[str, str | None] = field(default_factory=dict)
    area_of: dict[str, str | None] = field(default_factory=dict)
    floor_of: dict[str, str | None] = field(default_factory=dict)
    labels_of: dict[str, frozenset[str]] = field(default_factory=dict)
    integration_of: dict[str, str | None] = field(default_factory=dict)
    device_class_of: dict[str, str | None] = field(default_factory=dict)
    entity_category_of: dict[str, str | None] = field(default_factory=dict)
    disabled: frozenset[str] = field(default_factory=frozenset)
    hidden: frozenset[str] = field(default_factory=frozenset)

    # Inverse lookups (X → entities)
    entities_on_device: dict[str, frozenset[str]] = field(default_factory=dict)
    entities_in_area: dict[str, frozenset[str]] = field(default_factory=dict)
    entities_on_floor: dict[str, frozenset[str]] = field(default_factory=dict)
    entities_with_label: dict[str, frozenset[str]] = field(default_factory=dict)
    entities_from_integration: dict[str, frozenset[str]] = field(default_factory=dict)

    # Logical grouping via state attributes + script targets
    members_of: dict[str, frozenset[str]] = field(default_factory=dict)
    """Strict parent → children, asymmetric. group/scene/group_light/script."""

    container_of: dict[str, frozenset[str]] = field(default_factory=dict)
    """Inverse of members_of: child → set of containers it belongs to."""

    derived_of: dict[str, frozenset[str]] = field(default_factory=dict)
    """source_entity → set of entities derived from it (statistics, utility_meter)."""

    source_of: dict[str, str | None] = field(default_factory=dict)
    """Inverse of derived_of: derived_entity → its source entity."""

    # Convenience: pre-computed sibling sets for small groups + small
    # device-groups, used by cooccurrence dedup. Symmetric.
    siblings_of: dict[str, frozenset[str]] = field(default_factory=dict)

    # Configuration knob — same threshold as before so behavior is preserved.
    SIBLING_GROUP_MAX_SIZE: int = 6

    # ----- Query helpers (these get called from detectors) -----

    def is_externally_managed(self, entity_id: str) -> str | None:
        """Return the vendor app name if this entity comes from an
        integration that commonly carries device-side schedules, else
        None. Used for the 🏷️ pill."""
        platform = self.integration_of.get(entity_id)
        if not platform or platform not in _EXTERNAL_SCHEDULE_PLATFORMS:
            return None
        return _EXTERNAL_PLATFORM_LABEL.get(platform, platform)

    def is_user_facing(self, entity_id: str) -> bool:
        """Whether this entity is user-facing (not diagnostic/config).
        Used to filter out HA telemetry from pattern detection."""
        cat = self.entity_category_of.get(entity_id)
        if cat in ("diagnostic", "config"):
            return False
        if entity_id in self.disabled or entity_id in self.hidden:
            return False
        return True

    def find_common_parent(self, entity_ids: list[str]) -> str | None:
        """Best-effort: a container (group/scene/device) holding every
        input entity. Returns None when no single parent qualifies.

        Cases handled in priority order:
          1. All inputs share the same device_id → "device:..." synthetic
             label (or the longest-common-entity-prefix as a friendlier
             alternative — caller renders).
          2. One input IS itself the parent of the others.
          3. A third-party container holds all inputs.
        """
        if len(entity_ids) < 2:
            return None

        # Case 1: same device_id
        device_ids = {self.device_of.get(eid) for eid in entity_ids}
        device_ids.discard(None)
        if len(device_ids) == 1:
            shared = next(iter(device_ids))
            if shared:
                return f"device:{shared}"

        # Case 2: one input is the parent
        for candidate in entity_ids:
            members = self.members_of.get(candidate, frozenset())
            if not members:
                continue
            if all(eid == candidate or eid in members for eid in entity_ids):
                return candidate

        # Case 3: third-party container — intersect "containers each entity
        # is a member of" and find one whose members include all inputs.
        candidate_sets = [self.container_of.get(eid, frozenset()) for eid in entity_ids]
        if not all(candidate_sets):
            return None
        common = candidate_sets[0]
        for s in candidate_sets[1:]:
            common = common & s
            if not common:
                return None
        for candidate in sorted(common):
            cand_members = self.members_of.get(candidate, frozenset())
            if all(eid in cand_members for eid in entity_ids):
                return candidate
        return None

    def share_device(self, eid_a: str, eid_b: str) -> bool:
        """Whether two entities live on the same physical device.
        Used by cooccurrence to drop same-device pairs."""
        da = self.device_of.get(eid_a)
        db = self.device_of.get(eid_b)
        return da is not None and da == db

    def are_related(self, eid_a: str, eid_b: str) -> bool:
        """Whether two entities are connected via ANY hierarchy edge —
        same device, member ↔ container, sibling small-group member,
        source ↔ derived. Used by cooccurrence to drop pairs that
        reflect the same root event."""
        if eid_a == eid_b:
            return True
        if self.share_device(eid_a, eid_b):
            return True
        if eid_b in self.siblings_of.get(eid_a, frozenset()):
            return True
        if eid_b in self.members_of.get(eid_a, frozenset()):
            return True
        if eid_a in self.members_of.get(eid_b, frozenset()):
            return True
        if eid_b in self.derived_of.get(eid_a, frozenset()):
            return True
        if eid_a in self.derived_of.get(eid_b, frozenset()):
            return True
        if self.source_of.get(eid_a) == eid_b:
            return True
        if self.source_of.get(eid_b) == eid_a:
            return True
        return False


# ---------- Builder ---------------------------------------------------------


def build_hierarchy(hass: HomeAssistant) -> EntityHierarchy:
    """Snapshot every relationship we care about from HA's registries.

    Runs on the event loop. Total cost ~5-15ms on a 1000-entity install
    — single sweep of each registry + the state machine, no I/O.
    """
    # Forward lookups, populated below
    device_of: dict[str, str | None] = {}
    area_of: dict[str, str | None] = {}
    integration_of: dict[str, str | None] = {}
    device_class_of: dict[str, str | None] = {}
    entity_category_of: dict[str, str | None] = {}
    labels_of: dict[str, frozenset[str]] = {}
    floor_of: dict[str, str | None] = {}
    disabled_set: set[str] = set()
    hidden_set: set[str] = set()

    # Build device → area mapping first; we'll fall back to it when an
    # entity has no area_id but its device does.
    device_to_area: dict[str, str | None] = {}
    try:
        from homeassistant.helpers import device_registry as dr

        dev_reg = dr.async_get(hass)
        for device in dev_reg.devices.values():
            device_to_area[device.id] = device.area_id
    except Exception:  # pragma: no cover — defensive
        pass

    # Build area → floor mapping (HA 2024+).
    area_to_floor: dict[str, str | None] = {}
    try:
        from homeassistant.helpers import area_registry as ar

        area_reg = ar.async_get(hass)
        for area in area_reg.areas.values():
            area_to_floor[area.id] = getattr(area, "floor_id", None)
    except Exception:  # pragma: no cover
        pass

    # Walk entity registry.
    try:
        from homeassistant.helpers import entity_registry as er

        ent_reg = er.async_get(hass)
        for entry in ent_reg.entities.values():
            eid = entry.entity_id
            device_of[eid] = entry.device_id
            integration_of[eid] = entry.platform
            device_class_of[eid] = (
                entry.device_class or entry.original_device_class
            )
            entity_category_of[eid] = (
                entry.entity_category.value
                if entry.entity_category is not None
                else None
            )
            # Area: prefer entity's own, fall back to its device's
            entity_area = entry.area_id
            if entity_area is None and entry.device_id:
                entity_area = device_to_area.get(entry.device_id)
            area_of[eid] = entity_area
            # Floor: derived from area
            if entity_area and entity_area in area_to_floor:
                floor_of[eid] = area_to_floor[entity_area]
            # Labels (HA 2024+)
            raw_labels = getattr(entry, "labels", None)
            if raw_labels:
                labels_of[eid] = frozenset(raw_labels)
            if entry.disabled_by is not None:
                disabled_set.add(eid)
            if entry.hidden_by is not None:
                hidden_set.add(eid)
    except Exception:  # pragma: no cover
        pass

    # Build inverse lookups (entities_on_device, entities_in_area, etc.).
    entities_on_device: dict[str, set[str]] = defaultdict(set)
    entities_in_area: dict[str, set[str]] = defaultdict(set)
    entities_on_floor: dict[str, set[str]] = defaultdict(set)
    entities_from_integration: dict[str, set[str]] = defaultdict(set)
    entities_with_label: dict[str, set[str]] = defaultdict(set)

    for eid, did in device_of.items():
        if did:
            entities_on_device[did].add(eid)
    for eid, aid in area_of.items():
        if aid:
            entities_in_area[aid].add(eid)
    for eid, fid in floor_of.items():
        if fid:
            entities_on_floor[fid].add(eid)
    for eid, plat in integration_of.items():
        if plat:
            entities_from_integration[plat].add(eid)
    for eid, lbls in labels_of.items():
        for lbl in lbls:
            entities_with_label[lbl].add(eid)

    # Walk state machine for group/scene/etc. membership + derived sources.
    members_of: dict[str, set[str]] = defaultdict(set)
    container_of: dict[str, set[str]] = defaultdict(set)
    derived_of: dict[str, set[str]] = defaultdict(set)
    source_of: dict[str, str | None] = {}
    try:
        for state in hass.states.async_all():
            seid = state.entity_id
            # Container relationships
            for attr_name in _GROUP_MEMBER_ATTRS:
                raw = state.attributes.get(attr_name)
                if not isinstance(raw, (list, tuple)):
                    continue
                members = [
                    m for m in raw if isinstance(m, str) and "." in m
                ]
                if not members:
                    continue
                for m in members:
                    members_of[seid].add(m)
                    container_of[m].add(seid)
            # Source / derived sensor relationships
            for src_attr in ("source", "source_entity_id"):
                src = state.attributes.get(src_attr)
                if isinstance(src, str) and "." in src:
                    source_of[seid] = src
                    derived_of[src].add(seid)
    except Exception:  # pragma: no cover
        pass

    # Walk scripts for action target relationships (treat script as a
    # logical container of the entities its actions touch).
    try:
        from .._script_targets import collect_script_targets

        for script_eid, targets in collect_script_targets(hass).items():
            for target in targets:
                members_of[script_eid].add(target)
                container_of[target].add(script_eid)
    except Exception:  # pragma: no cover
        pass

    # Sibling sets: members of small containers (≤ N) PLUS entities on
    # the same device (no size cap for device — small by definition).
    # Symmetric.
    siblings: dict[str, set[str]] = defaultdict(set)
    # Container-based siblings (small groups only)
    for container, members in members_of.items():
        if 1 < len(members) <= EntityHierarchy.SIBLING_GROUP_MAX_SIZE:
            member_set = set(members)
            for m in members:
                siblings[m] |= member_set - {m}
    # Device-based siblings (always — devices have few entities typically)
    for device, ents in entities_on_device.items():
        if len(ents) > 1:
            ent_list = list(ents)
            for e in ent_list:
                siblings[e] |= set(ent_list) - {e}

    return EntityHierarchy(
        device_of=device_of,
        area_of=area_of,
        floor_of=floor_of,
        labels_of=labels_of,
        integration_of=integration_of,
        device_class_of=device_class_of,
        entity_category_of=entity_category_of,
        disabled=frozenset(disabled_set),
        hidden=frozenset(hidden_set),
        entities_on_device={k: frozenset(v) for k, v in entities_on_device.items()},
        entities_in_area={k: frozenset(v) for k, v in entities_in_area.items()},
        entities_on_floor={k: frozenset(v) for k, v in entities_on_floor.items()},
        entities_with_label={k: frozenset(v) for k, v in entities_with_label.items()},
        entities_from_integration={
            k: frozenset(v) for k, v in entities_from_integration.items()
        },
        members_of={k: frozenset(v) for k, v in members_of.items()},
        container_of={k: frozenset(v) for k, v in container_of.items()},
        derived_of={k: frozenset(v) for k, v in derived_of.items()},
        source_of=source_of,
        siblings_of={k: frozenset(v) for k, v in siblings.items()},
    )
