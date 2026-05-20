"""Tests for v1.22.3 multi-word suffix matcher in wifi_find_self.

Previous (v1.21.2/v1.22.2) heuristic used `rsplit("_", 1)[-1]` which
only captured single-word suffixes. The HA Companion app names its
Wi-Fi signal sensors like `sensor.<device>_wifi_signal_strength` —
the single trailing segment is `"strength"`, which wasn't in any
recognised set, so the entire device got rejected as untrackable.

v1.22.3 introduces `_match_name_suffix` which matches multi-word
suffix patterns (longest-first). This file pins the contract.
"""
from __future__ import annotations

from custom_components.ha_insights.ws_api.wifi_find_self import (
    _AP_NAME_SUFFIXES,
    _SIGNAL_NAME_SUFFIXES,
    _match_name_suffix,
)


class TestCompanionAppNames:
    """The user-visible bug — Companion app sensors must match."""

    def test_wifi_signal_strength_matches(self):
        """`sensor.dans_s23_wifi_signal_strength` — the actual bug."""
        result = _match_name_suffix(
            "dans_s23_wifi_signal_strength", _SIGNAL_NAME_SUFFIXES
        )
        assert result is not None
        suf, key = result
        assert suf == "wifi_signal_strength"
        assert key == "signal_strength"

    def test_wifi_signal_strength_dbm_matches(self):
        """Some Android variants append `_dbm`."""
        result = _match_name_suffix(
            "phone_wifi_signal_strength_dbm", _SIGNAL_NAME_SUFFIXES
        )
        assert result is not None
        suf, key = result
        assert suf == "wifi_signal_strength_dbm"
        assert key == "signal_strength"

    def test_wifi_bssid_matches(self):
        """Companion app's WiFi BSSID auto-sensor (when enabled)."""
        result = _match_name_suffix(
            "phone_wifi_bssid", _AP_NAME_SUFFIXES
        )
        assert result is not None
        suf, key = result
        assert suf == "wifi_bssid"
        assert key == "bssid"

    def test_wifi_connection_matches_ap(self):
        """Companion app's WiFi Connection sensor reports SSID."""
        result = _match_name_suffix(
            "phone_wifi_connection", _AP_NAME_SUFFIXES
        )
        assert result is not None
        suf, key = result
        assert suf == "wifi_connection"
        assert key == "ap_name"


class TestUnifiOmadaNames:
    """Controller-side sensors must still match (v1.21.2 contract)."""

    def test_rx_signal_matches(self):
        """UniFi: `sensor.<client>_rx_signal`."""
        result = _match_name_suffix(
            "alice_phone_rx_signal", _SIGNAL_NAME_SUFFIXES
        )
        assert result is not None
        suf, key = result
        assert suf == "rx_signal"
        assert key == "rx_rssi"

    def test_rssi_single_word_matches(self):
        """zachcheatham/ha-omada: `sensor.<client>_rssi`."""
        result = _match_name_suffix(
            "daniel_s_s23_ultra_rssi", _SIGNAL_NAME_SUFFIXES
        )
        assert result is not None
        suf, key = result
        assert suf == "rssi"
        assert key == "rssi"

    def test_access_point_matches(self):
        """UniFi: `sensor.<client>_access_point`."""
        result = _match_name_suffix(
            "phone_access_point", _AP_NAME_SUFFIXES
        )
        assert result is not None
        suf, key = result
        assert suf == "access_point"
        assert key == "access_point"


class TestLongestFirstOrdering:
    """When multiple suffixes overlap, the longest must win."""

    def test_signal_strength_beats_strength(self):
        """`wifi_signal_strength` must NOT match as just `signal`."""
        result = _match_name_suffix(
            "phone_wifi_signal_strength", _SIGNAL_NAME_SUFFIXES
        )
        # If ordering were wrong, `signal` would match first because
        # `phone_wifi_signal_strength` ends with "_signal_strength"
        # but ALSO contains "_signal" earlier — we want the most-
        # specific match.
        assert result is not None
        suf, _ = result
        # The full multi-word suffix should win.
        assert suf == "wifi_signal_strength"

    def test_wifi_signal_strength_dbm_beats_strength(self):
        result = _match_name_suffix(
            "phone_wifi_signal_strength_dbm", _SIGNAL_NAME_SUFFIXES
        )
        assert result is not None
        suf, _ = result
        assert suf == "wifi_signal_strength_dbm"


class TestExactMatch:
    """Sensor entity name == suffix exactly (no device prefix)."""

    def test_exact_rssi(self):
        """Edge case: `sensor.rssi` (unlikely but harmless)."""
        result = _match_name_suffix("rssi", _SIGNAL_NAME_SUFFIXES)
        assert result is not None
        assert result == ("rssi", "rssi")

    def test_exact_wifi_signal_strength(self):
        result = _match_name_suffix(
            "wifi_signal_strength", _SIGNAL_NAME_SUFFIXES
        )
        assert result is not None
        assert result[0] == "wifi_signal_strength"


class TestNonMatch:
    """Random sensor names must NOT spuriously match."""

    def test_temperature_no_match(self):
        assert (
            _match_name_suffix("phone_battery_level", _SIGNAL_NAME_SUFFIXES)
            is None
        )

    def test_battery_state_no_match(self):
        assert (
            _match_name_suffix("phone_battery_state", _SIGNAL_NAME_SUFFIXES)
            is None
        )

    def test_word_strength_alone_no_match(self):
        """Plain `strength` (no `signal` prefix) should NOT match.

        v1.21.2 incorrectly matched this case if 'strength' had been
        in its single-word set. v1.22.3's suffix list intentionally
        excludes 'strength' alone — too generic, would catch e.g.
        `signal_strength_warning` type custom sensors.
        """
        assert (
            _match_name_suffix("phone_strength", _SIGNAL_NAME_SUFFIXES)
            is None
        )

    def test_empty_string_no_match(self):
        assert _match_name_suffix("", _SIGNAL_NAME_SUFFIXES) is None
