"""Tests for the privacy redactor."""
from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from custom_components.ha_insights.llm import (
    ALWAYS_REDACT_ATTRIBUTES,
    RedactionMode,
    Redactor,
)
from custom_components.ha_insights.store import InsightStore


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[InsightStore]:
    db = InsightStore(tmp_path / "test.db")
    await db.open()
    yield db
    await db.close()


# --- Per-entity opt-out (v0.6) ---


async def test_blocked_entity_in_string_value(store: InsightStore) -> None:
    """A blocked entity_id in a top-level string is replaced with [blocked]."""
    redactor = Redactor(
        store,
        mode=RedactionMode.AGGRESSIVE,
        blocked_entities=frozenset({"lock.front_door"}),
    )
    cleaned, redaction_map = await redactor.redact_insight_payload(
        {"alias": "Test", "trigger_entity": "lock.front_door"}
    )
    assert cleaned["trigger_entity"] == "[blocked]"
    assert "lock.front_door" in redaction_map.entities_blocked


async def test_blocked_entity_in_target_dict(store: InsightStore) -> None:
    """target.entity_id pointing at a blocked entity is dropped to [blocked]."""
    redactor = Redactor(
        store,
        mode=RedactionMode.AGGRESSIVE,
        blocked_entities=frozenset({"lock.front_door"}),
    )
    payload = {
        "action": [
            {"service": "lock.unlock", "target": {"entity_id": "lock.front_door"}}
        ]
    }
    cleaned, redaction_map = await redactor.redact_insight_payload(payload)
    assert cleaned["action"][0]["target"] == {"entity_id": "[blocked]"}
    assert "lock.front_door" in redaction_map.entities_blocked


async def test_blocked_entity_filtered_from_list(store: InsightStore) -> None:
    """A list of entity_ids has blocked entries filtered out."""
    redactor = Redactor(
        store,
        mode=RedactionMode.AGGRESSIVE,
        blocked_entities=frozenset({"lock.front_door"}),
    )
    payload = {
        "target": {
            "entity_id": ["light.kitchen", "lock.front_door", "switch.fan"]
        }
    }
    cleaned, redaction_map = await redactor.redact_insight_payload(payload)
    assert "lock.front_door" not in cleaned["target"]["entity_id"]
    assert "light.kitchen" in cleaned["target"]["entity_id"]
    assert "switch.fan" in cleaned["target"]["entity_id"]
    assert "lock.front_door" in redaction_map.entities_blocked


async def test_blocked_entity_in_pseudonymized_text(store: InsightStore) -> None:
    """Inside free-text, blocked entities become [blocked], not pseudonyms."""
    redactor = Redactor(
        store,
        mode=RedactionMode.AGGRESSIVE,
        blocked_entities=frozenset({"lock.front_door"}),
    )
    cleaned_text, redaction_map = await redactor.redact_text(
        "Open lock.front_door when light.kitchen turns on"
    )
    assert "lock.front_door" not in cleaned_text
    assert "[blocked]" in cleaned_text
    # light.kitchen still gets a pseudonym
    assert "light.entity_" in cleaned_text
    assert "lock.front_door" in redaction_map.entities_blocked


async def test_unblocked_entity_passes_through_normally(store: InsightStore) -> None:
    """Empty blocklist means no behavior change."""
    redactor = Redactor(
        store,
        mode=RedactionMode.AGGRESSIVE,
        blocked_entities=frozenset(),
    )
    cleaned, redaction_map = await redactor.redact_insight_payload(
        {"target": {"entity_id": "light.kitchen"}}
    )
    # Pseudonymized but not blocked
    assert cleaned["target"]["entity_id"].startswith("light.entity_")
    assert redaction_map.entities_blocked == []


# --- Always-redact attributes ---


async def test_strips_gps_attributes(store: InsightStore) -> None:
    redactor = Redactor(store, mode=RedactionMode.AGGRESSIVE)
    payload = {
        "name": "test",
        "gps_lat": 37.7749,
        "gps_lon": -122.4194,
        "latitude": 37.7749,
        "longitude": -122.4194,
        "altitude": 50,
    }
    cleaned, _ = await redactor.redact_insight_payload(payload)
    assert "gps_lat" not in cleaned
    assert "gps_lon" not in cleaned
    assert "latitude" not in cleaned
    assert "longitude" not in cleaned
    assert "altitude" not in cleaned
    assert cleaned["name"] == "test"


async def test_strips_credentials(store: InsightStore) -> None:
    redactor = Redactor(store, mode=RedactionMode.AGGRESSIVE)
    payload = {
        "username": "alice",
        "password": "hunter2",
        "token": "abc123",
        "access_token": "xyz",
        "api_key": "k1",
        "secret": "shh",
    }
    cleaned, redaction_map = await redactor.redact_insight_payload(payload)
    for blocked in ("password", "token", "access_token", "api_key", "secret"):
        assert blocked not in cleaned
    assert cleaned["username"] == "alice"
    assert set(redaction_map.attributes_stripped) >= {
        "password", "token", "access_token", "api_key", "secret",
    }


async def test_strips_network_identifiers(store: InsightStore) -> None:
    redactor = Redactor(store, mode=RedactionMode.AGGRESSIVE)
    payload = {
        "hostname": "kitchen-pi",
        "mac": "aa:bb:cc:dd:ee:ff",
        "ip": "192.168.1.5",
        "ip_address": "192.168.1.5",
        "bssid": "00:11:22:33:44:55",
        "ssid": "MyWiFi",
    }
    cleaned, _ = await redactor.redact_insight_payload(payload)
    for blocked in ("mac", "ip", "ip_address", "bssid", "ssid"):
        assert blocked not in cleaned
    assert cleaned["hostname"] == "kitchen-pi"


async def test_strips_attributes_recursively(store: InsightStore) -> None:
    """Nested dicts have their sensitive keys stripped too."""
    redactor = Redactor(store, mode=RedactionMode.AGGRESSIVE)
    payload = {
        "device": {
            "name": "router",
            "mac": "aa:bb:cc:dd:ee:ff",
            "metadata": {"ip": "10.0.0.1", "model": "ax6000"},
        },
    }
    cleaned, _ = await redactor.redact_insight_payload(payload)
    assert "mac" not in cleaned["device"]
    assert "ip" not in cleaned["device"]["metadata"]
    assert cleaned["device"]["metadata"]["model"] == "ax6000"


async def test_strips_attributes_in_lists(store: InsightStore) -> None:
    redactor = Redactor(store, mode=RedactionMode.AGGRESSIVE)
    payload = {
        "devices": [
            {"name": "a", "mac": "00:00:00:00:00:01"},
            {"name": "b", "mac": "00:00:00:00:00:02"},
        ],
    }
    cleaned, _ = await redactor.redact_insight_payload(payload)
    assert all("mac" not in d for d in cleaned["devices"])
    assert [d["name"] for d in cleaned["devices"]] == ["a", "b"]


async def test_attribute_keys_are_case_insensitive(store: InsightStore) -> None:
    redactor = Redactor(store, mode=RedactionMode.AGGRESSIVE)
    payload = {"Password": "hunter2", "MAC": "aa:bb:cc:dd:ee:ff"}
    cleaned, _ = await redactor.redact_insight_payload(payload)
    assert "Password" not in cleaned
    assert "MAC" not in cleaned


# --- Mode behavior ---


async def test_off_mode_strips_attributes_only(store: InsightStore) -> None:
    """OFF doesn't pseudonymize but still strips sensitive attrs (defensive)."""
    redactor = Redactor(store, mode=RedactionMode.OFF)
    payload = {
        "trigger": [{"platform": "state", "entity_id": "light.kitchen"}],
        "password": "hunter2",
    }
    cleaned, redaction_map = await redactor.redact_insight_payload(payload)
    assert "password" not in cleaned
    # entity_id NOT pseudonymized in OFF
    assert cleaned["trigger"][0]["entity_id"] == "light.kitchen"
    assert redaction_map.entity_to_pseudonym == {}


async def test_permissive_mode_keeps_entity_ids(store: InsightStore) -> None:
    redactor = Redactor(store, mode=RedactionMode.PERMISSIVE)
    payload = {"entity_id": "light.kitchen"}
    cleaned, redaction_map = await redactor.redact_insight_payload(payload)
    assert cleaned["entity_id"] == "light.kitchen"
    assert redaction_map.entity_to_pseudonym == {}


async def test_aggressive_mode_pseudonymizes_entity_ids(store: InsightStore) -> None:
    redactor = Redactor(store, mode=RedactionMode.AGGRESSIVE)
    payload = {"entity_id": "light.kitchen"}
    cleaned, redaction_map = await redactor.redact_insight_payload(payload)
    pseudonym = cleaned["entity_id"]
    assert pseudonym != "light.kitchen"
    assert pseudonym.startswith("light.")  # domain preserved
    assert redaction_map.entity_to_pseudonym == {"light.kitchen": pseudonym}


async def test_aggressive_mode_pseudonymizes_in_strings(store: InsightStore) -> None:
    redactor = Redactor(store, mode=RedactionMode.AGGRESSIVE)
    text = "On weekdays light.kitchen turns on at 06:47"
    redacted, _ = await redactor.redact_text(text)
    assert "light.kitchen" not in redacted
    # Should still mention the domain
    assert "light." in redacted


# --- Pseudonym stability ---


async def test_same_entity_same_pseudonym_within_call(store: InsightStore) -> None:
    """An entity referenced twice in one payload gets the same pseudonym."""
    redactor = Redactor(store, mode=RedactionMode.AGGRESSIVE)
    payload = {
        "trigger": [{"entity_id": "light.kitchen"}],
        "action": [{"target": {"entity_id": "light.kitchen"}}],
    }
    cleaned, redaction_map = await redactor.redact_insight_payload(payload)
    p1 = cleaned["trigger"][0]["entity_id"]
    p2 = cleaned["action"][0]["target"]["entity_id"]
    assert p1 == p2
    assert len(redaction_map.entity_to_pseudonym) == 1


async def test_pseudonyms_stable_across_calls(store: InsightStore) -> None:
    """The same entity_id always pseudonymizes to the same string."""
    redactor = Redactor(store, mode=RedactionMode.AGGRESSIVE)
    text = "light.kitchen"
    redacted_a, _ = await redactor.redact_text(text)
    redacted_b, _ = await redactor.redact_text(text)
    assert redacted_a == redacted_b


async def test_distinct_entities_distinct_pseudonyms(store: InsightStore) -> None:
    redactor = Redactor(store, mode=RedactionMode.AGGRESSIVE)
    text = "light.kitchen and light.bedroom"
    _, redaction_map = await redactor.redact_text(text)
    assert len(redaction_map.entity_to_pseudonym) == 2
    pseudonyms = set(redaction_map.entity_to_pseudonym.values())
    assert len(pseudonyms) == 2  # distinct


# --- Round-trip ---


async def test_redaction_map_dereferences_response(store: InsightStore) -> None:
    """LLM responses mentioning pseudonyms can be deref'd back to real ids."""
    redactor = Redactor(store, mode=RedactionMode.AGGRESSIVE)
    text = "light.kitchen turns on at 06:47"
    _, redaction_map = await redactor.redact_text(text)
    pseudonym = next(iter(redaction_map.entity_to_pseudonym.values()))

    # Simulated LLM response that mentions the pseudonym
    llm_response = f"This automation turns on {pseudonym} every weekday morning."
    deref = redaction_map.dereference(llm_response)
    assert "light.kitchen" in deref
    assert pseudonym not in deref


async def test_dereference_is_no_op_with_empty_map(store: InsightStore) -> None:
    redactor = Redactor(store, mode=RedactionMode.PERMISSIVE)
    _, redaction_map = await redactor.redact_text("hello world")
    assert redaction_map.dereference("hello world") == "hello world"


# --- Extra blocklist ---


async def test_extra_blocklist_extends_default(store: InsightStore) -> None:
    """User-supplied attribute names are stripped on top of always-redacted."""
    redactor = Redactor(
        store,
        mode=RedactionMode.AGGRESSIVE,
        extra_attribute_blocklist=frozenset({"custom_secret"}),
    )
    payload = {"custom_secret": "x", "password": "y", "username": "z"}
    cleaned, _ = await redactor.redact_insight_payload(payload)
    assert "custom_secret" not in cleaned
    assert "password" not in cleaned  # default still applies
    assert cleaned["username"] == "z"


# --- Sanity: ALWAYS_REDACT_ATTRIBUTES is a frozen set ---


def test_always_redact_attributes_is_frozen() -> None:
    assert isinstance(ALWAYS_REDACT_ATTRIBUTES, frozenset)
    # Some load-bearing entries
    assert "password" in ALWAYS_REDACT_ATTRIBUTES
    assert "gps_lat" in ALWAYS_REDACT_ATTRIBUTES
    assert "mac" in ALWAYS_REDACT_ATTRIBUTES
