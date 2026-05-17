"""Tests for lib/name_quality."""
from __future__ import annotations

from custom_components.ha_insights.lib.name_quality import (
    NameQuality,
    NameQualityTier,
    score_name_quality,
)

# ---------- Tier 5: USER_OVERRIDE --------------------------------------


def test_user_override_wins_over_everything() -> None:
    """name_by_user trumps cloud / friendly / model."""
    q = score_name_quality(
        "light.cryptic_id",
        name_by_user="My Reading Lamp",
        original_name="Tuya Smart Light",
        friendly_name="Tuya Smart Light",
        manufacturer="Tuya",
        model="WBL01",
        integration_domain="tuya",
    )
    assert q.tier == NameQualityTier.USER_OVERRIDE
    assert q.score == 1.0
    assert q.chosen_name == "My Reading Lamp"


def test_user_override_whitespace_only_does_not_count() -> None:
    """Empty / whitespace name_by_user falls through."""
    q = score_name_quality(
        "light.foo",
        name_by_user="   ",
        original_name="Kitchen Lamp",
        integration_domain="hue",
    )
    assert q.tier == NameQualityTier.CLOUD_AUTHORITATIVE


# ---------- Tier 4: CLOUD_AUTHORITATIVE --------------------------------


def test_tuya_cloud_name_is_authoritative() -> None:
    q = score_name_quality(
        "light.tuya_kitchen",
        original_name="Kitchen Floor Lamp",
        integration_domain="tuya",
    )
    assert q.tier == NameQualityTier.CLOUD_AUTHORITATIVE
    assert q.score == 0.85
    assert q.chosen_name == "Kitchen Floor Lamp"
    assert "tuya" in q.source


def test_hue_cloud_name_is_authoritative() -> None:
    q = score_name_quality(
        "light.hue_office",
        original_name="Office Desk Light",
        integration_domain="hue",
    )
    assert q.tier == NameQualityTier.CLOUD_AUTHORITATIVE


def test_homekit_cloud_name_is_authoritative() -> None:
    q = score_name_quality(
        "light.foo",
        original_name="Living Room Ceiling",
        integration_domain="homekit_controller",
    )
    assert q.tier == NameQualityTier.CLOUD_AUTHORITATIVE


def test_cloud_with_mac_pattern_falls_back() -> None:
    """Even cloud integrations sometimes emit MAC-looking names; reject."""
    q = score_name_quality(
        "light.tuya_a4c138",
        original_name="tuya_a4c138_light",
        integration_domain="tuya",
    )
    assert q.tier != NameQualityTier.CLOUD_AUTHORITATIVE


# ---------- Tier 3: FRIENDLY_SET ---------------------------------------


def test_friendly_name_with_real_words_is_friendly_tier() -> None:
    q = score_name_quality(
        "sensor.esphome_node_temp",
        friendly_name="Bedroom Air Quality",
        integration_domain="esphome",
    )
    assert q.tier == NameQualityTier.FRIENDLY_SET
    assert q.score == 0.70


def test_friendly_name_overrides_low_quality_original() -> None:
    """ESPHome often: original_name is generic, friendly_name is real."""
    q = score_name_quality(
        "sensor.esp32_kitchen_temp",
        original_name="esp32_kitchen_temp_sensor",
        friendly_name="Kitchen Temperature",
        integration_domain="esphome",
    )
    assert q.tier == NameQualityTier.FRIENDLY_SET


# ---------- Tier 2: MANUFACTURER_MODEL ---------------------------------


def test_zha_manufacturer_model_pattern() -> None:
    q = score_name_quality(
        "sensor.aqara_temp",
        original_name="Aqara WSDCGQ11LM Temperature",
        manufacturer="Aqara",
        model="WSDCGQ11LM",
        integration_domain="zha",
    )
    assert q.tier == NameQualityTier.MANUFACTURER_MODEL
    assert q.score == 0.50


# ---------- Tier 1: MAC_PATTERN ----------------------------------------


def test_mac_address_pattern_lowest_tier() -> None:
    q = score_name_quality(
        "sensor.ble_a4c138aa_temperature",
        original_name="ATC a4:c1:38:aa:bb:cc Temperature",
        integration_domain="bluetooth",
    )
    assert q.tier == NameQualityTier.MAC_PATTERN
    assert q.score == 0.10


def test_long_hex_blob_is_mac_pattern() -> None:
    """Hex blob without explicit MAC separators still scores low."""
    q = score_name_quality(
        "light.0x00158d000a1b2c3d",
        original_name="0x00158d000a1b2c3d",
        integration_domain="zha",
    )
    assert q.tier == NameQualityTier.MAC_PATTERN


def test_ble_integration_low_name_with_mac() -> None:
    q = score_name_quality(
        "sensor.bthome_a4c138_temp",
        original_name="bthome_a4c138_temp",
        integration_domain="bthome",
    )
    assert q.tier == NameQualityTier.MAC_PATTERN
    assert "bthome" in q.source


# ---------- Tier 0/1 fallback: GENERIC_DOMAIN --------------------------


def test_generic_object_id_no_words() -> None:
    """`light.lamp1` — one short token, no clear word signal."""
    q = score_name_quality(
        "light.lamp1",
        original_name=None,
        friendly_name=None,
    )
    # Falls through to generic_domain — single short word isn't enough
    # to call it "reads like words" but it's also not MAC-ish.
    assert q.tier == NameQualityTier.GENERIC_DOMAIN
    assert q.score == 0.25


# ---------- Word vs MAC detection corners ------------------------------


def test_reads_like_words_two_real_words() -> None:
    q = score_name_quality(
        "sensor.foo",
        original_name="Hallway Motion",
    )
    # No integration → not cloud tier. Should land at friendly_set
    # because the name itself reads like words.
    assert q.tier == NameQualityTier.FRIENDLY_SET


def test_single_word_with_number_is_generic() -> None:
    q = score_name_quality(
        "sensor.foo",
        original_name="sensor 1",
    )
    assert q.tier == NameQualityTier.GENERIC_DOMAIN


def test_short_word_with_consonant_blob_does_not_count() -> None:
    """A name like "Hi xy" has one too-short word + one no-vowel
    blob → no real words → not friendly."""
    q = score_name_quality(
        "sensor.foo",
        original_name="Hi xy",
    )
    # "Hi" is 2 chars (< 3); "xy" has no vowel. Zero real words →
    # falls through past friendly_set.
    assert q.tier != NameQualityTier.FRIENDLY_SET


# ---------- Output shape -----------------------------------------------


def test_assessment_includes_chosen_name_and_reason() -> None:
    q = score_name_quality(
        "light.foo",
        original_name="Kitchen Lamp",
        integration_domain="hue",
    )
    assert isinstance(q, NameQuality)
    assert q.chosen_name == "Kitchen Lamp"
    assert q.reason  # non-empty
    assert q.source  # non-empty


def test_score_matches_tier_table() -> None:
    """Per-tier score values are stable — the WS contract uses them."""
    assert score_name_quality(
        "light.x", name_by_user="X"
    ).score == 1.0
    assert score_name_quality(
        "light.x", original_name="Kitchen Lamp", integration_domain="hue"
    ).score == 0.85
    assert score_name_quality(
        "light.x", friendly_name="Bedroom Ceiling Fan"
    ).score == 0.70
    assert score_name_quality(
        "light.x",
        original_name="Aqara WSDCGQ11LM Temperature",
        manufacturer="Aqara",
        model="WSDCGQ11LM",
    ).score == 0.50
