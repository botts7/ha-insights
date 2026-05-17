"""Tests for lib/perturbation_capability + lib/perturbation_detection."""
from __future__ import annotations

from custom_components.ha_insights.lib.perturbation_capability import (
    PerturbationGuide,
    is_perturbation_unsupported,
    perturbation_guide_for,
    supported_device_classes,
)
from custom_components.ha_insights.lib.perturbation_detection import (
    analyze_perturbation,
)

# ============ perturbation_capability ============================


def test_temperature_guide_set() -> None:
    g = perturbation_guide_for("temperature")
    assert isinstance(g, PerturbationGuide)
    assert g.device_class == "temperature"
    assert "finger" in g.instruction.lower() or "hand" in g.instruction.lower()
    assert g.expected_delta > 0
    assert g.listening_window_s > 0
    assert g.perturb_duration_s > 0


def test_humidity_guide_mentions_breathe() -> None:
    g = perturbation_guide_for("humidity")
    assert g is not None
    assert "breathe" in g.instruction.lower()


def test_co2_guide_long_window() -> None:
    """CO₂ needs a longer listening window than temp (slower response)."""
    co2 = perturbation_guide_for("carbon_dioxide")
    temp = perturbation_guide_for("temperature")
    assert co2 is not None
    assert temp is not None
    assert co2.listening_window_s >= temp.listening_window_s


def test_illuminance_short_window() -> None:
    """Illuminance is instantaneous; window can be tight."""
    lux = perturbation_guide_for("illuminance")
    assert lux is not None
    assert lux.listening_window_s <= 15


def test_case_insensitive() -> None:
    assert perturbation_guide_for("Temperature") is not None
    assert perturbation_guide_for("TEMPERATURE") is not None


def test_unknown_returns_none() -> None:
    assert perturbation_guide_for("custom_metric") is None
    assert perturbation_guide_for("") is None
    assert perturbation_guide_for(None) is None


def test_pm25_explicitly_unsupported() -> None:
    """Some device_classes are deliberately not perturbable."""
    assert perturbation_guide_for("pm25") is None
    assert is_perturbation_unsupported("pm25")


def test_battery_unsupported() -> None:
    assert is_perturbation_unsupported("battery")


def test_supported_list_includes_basics() -> None:
    classes = supported_device_classes()
    assert "temperature" in classes
    assert "humidity" in classes
    assert "illuminance" in classes


# ============ perturbation_detection =============================


def _flat_baseline(value: float, n: int = 10) -> list[float]:
    """Stable baseline: all samples at the same value (zero stddev →
    will floor to STDDEV_FLOOR)."""
    return [value] * n


def _noisy_baseline(value: float, n: int = 20, jitter: float = 0.5) -> list[float]:
    """Realistic baseline with controlled noise."""
    out: list[float] = []
    for i in range(n):
        # Deterministic "noise" via sine pattern (no random for repeatability).
        import math
        out.append(value + jitter * math.sin(i * 0.7))
    return out


# ---------- clear single-winner case ----------------------------------


def test_clear_match_top_dominates() -> None:
    """Touched sensor.temp_a → it spikes; others stay flat."""
    baseline = {
        "sensor.temp_a": _flat_baseline(22.0),
        "sensor.temp_b": _flat_baseline(21.5),
        "sensor.temp_c": _flat_baseline(23.0),
    }
    test = {
        "sensor.temp_a": [22.0, 22.5, 24.5, 25.0, 24.7, 23.5],  # spike!
        "sensor.temp_b": [21.5, 21.5, 21.6, 21.5, 21.5, 21.5],
        "sensor.temp_c": [23.0, 23.0, 23.0, 23.0, 23.0, 23.0],
    }
    result = analyze_perturbation(baseline, test)
    assert result.decision == "clear"
    assert result.top_match == "sensor.temp_a"
    assert result.candidates[0].entity_id == "sensor.temp_a"
    assert result.candidates[0].z_score > 3.0
    assert "temp_a" in result.reason


# ---------- elimination case (THE killer outcome) ---------------------


def test_elimination_user_touched_wrong_sensor() -> None:
    """User touched what they thought was sensor.foo but sensor.bar
    actually spiked. Result must clearly identify bar, not foo."""
    baseline = {
        "sensor.foo": _flat_baseline(20.0),
        "sensor.bar": _flat_baseline(20.0),
    }
    test = {
        "sensor.foo": [20.0, 20.0, 20.1, 20.0, 20.0],
        "sensor.bar": [20.0, 21.0, 23.0, 24.0, 23.5],  # the actual touch
    }
    result = analyze_perturbation(baseline, test)
    assert result.decision == "clear"
    assert result.top_match == "sensor.bar"
    # The card uses this to render the "you touched X but Y spiked"
    # elimination message — top_match != caller's expected entity.


# ---------- no spike at all ------------------------------------------


def test_no_signal_when_nothing_spikes() -> None:
    baseline = {
        "sensor.temp_a": _noisy_baseline(22.0),
        "sensor.temp_b": _noisy_baseline(21.5),
    }
    test = {
        "sensor.temp_a": [22.0, 22.1, 22.05, 22.1, 22.0],
        "sensor.temp_b": [21.5, 21.5, 21.6, 21.5, 21.5],
    }
    result = analyze_perturbation(baseline, test)
    assert result.decision == "no_signal"
    assert result.top_match is None
    assert "stronger perturbation" in result.reason.lower() or (
        "didn't spike" in result.reason.lower()
        or "no candidate" in result.reason.lower()
    )


def test_empty_test_samples_no_signal() -> None:
    """When no candidates report during the window — sensors too slow."""
    result = analyze_perturbation({}, {})
    assert result.decision == "no_signal"
    assert result.top_match is None
    assert "report" in result.reason.lower() or "infrequent" in result.reason.lower()


# ---------- ambiguous case -------------------------------------------


def test_ambiguous_two_candidates_within_gap() -> None:
    """Two sensors on a multi-function device both spike together
    (one physical sensor, two HA entities)."""
    baseline = {
        "sensor.aqara_temp": _flat_baseline(22.0),
        "sensor.aqara_humid": _flat_baseline(45.0),
        "sensor.unrelated_temp": _flat_baseline(22.0),
    }
    test = {
        "sensor.aqara_temp": [22.0, 23.5, 24.0, 23.8],
        "sensor.aqara_humid": [45.0, 46.5, 47.0, 46.8],
        "sensor.unrelated_temp": [22.0, 22.0, 22.0, 22.0],
    }
    result = analyze_perturbation(baseline, test)
    # Both aqara candidates spike with similar z; unrelated stays flat.
    # The two aqara entities have the same delta in their respective
    # units, so their z-scores are equal → ambiguous (gap < 1.5).
    assert result.decision == "ambiguous"
    assert result.top_match is None
    # Both aqara candidates should be in the spike list.
    spiked = [c for c in result.candidates if c.spike_detected]
    assert len(spiked) >= 2
    spiked_eids = {c.entity_id for c in spiked}
    assert "sensor.aqara_temp" in spiked_eids
    assert "sensor.aqara_humid" in spiked_eids


# ---------- direction-aware (drop counts as spike) -------------------


def test_illuminance_drop_counts_as_spike() -> None:
    """Cover a light sensor → reading DROPS. Should still register."""
    baseline = {"sensor.lux_a": _flat_baseline(450.0)}
    test = {"sensor.lux_a": [450.0, 300.0, 80.0, 50.0, 70.0]}  # dropped
    result = analyze_perturbation(baseline, test)
    assert result.decision == "clear"
    assert result.top_match == "sensor.lux_a"
    # peak_delta is signed: should be negative since the value dropped.
    assert result.candidates[0].peak_delta < 0


# ---------- sample count ---------------------------------------------


def test_sample_count_reported() -> None:
    baseline = {"sensor.a": _flat_baseline(20.0)}
    test = {"sensor.a": [20.0, 22.0, 21.0]}
    result = analyze_perturbation(baseline, test)
    assert result.candidates[0].sample_count == 3


# ---------- stddev floor protects against div-by-tiny ----------------


def test_stable_sensor_doesnt_report_infinite_z() -> None:
    """A perfectly-stable sensor (zero baseline stddev) hitting a
    tiny spike must not report z=infinity."""
    baseline = {"sensor.stable": _flat_baseline(20.0)}  # variance=0
    test = {"sensor.stable": [20.0, 20.0001]}  # tiny spike
    result = analyze_perturbation(baseline, test)
    z = result.candidates[0].z_score
    assert z < 100  # well below "infinity"
    # Tiny spike shouldn't beat the threshold either.
    assert not result.candidates[0].spike_detected


# ---------- baseline fallback for missing prior samples --------------


def test_missing_baseline_still_evaluates() -> None:
    """When the baseline window had no samples for an entity, we still
    evaluate using a STDDEV_FLOOR fallback rather than dropping it."""
    test = {"sensor.late_starter": [20.0, 25.0, 24.0]}  # big spike vs first sample
    result = analyze_perturbation({}, test)  # no baseline at all
    # Should evaluate; the first sample becomes the implicit baseline.
    assert len(result.candidates) == 1
    assert result.candidates[0].entity_id == "sensor.late_starter"


# ---------- threshold tuning -----------------------------------------


def test_custom_z_threshold_loosens_detection() -> None:
    baseline = {"sensor.a": _flat_baseline(22.0)}
    test = {"sensor.a": [22.0, 22.5, 22.8]}  # modest delta
    result_strict = analyze_perturbation(baseline, test, z_threshold=5.0)
    result_loose = analyze_perturbation(baseline, test, z_threshold=2.0)
    # Same data, different thresholds → different decisions.
    assert result_strict.decision == "no_signal"
    assert result_loose.decision == "clear"


def test_custom_ambiguity_gap() -> None:
    """Tightening the ambiguity_gap should let close pairs be 'clear'."""
    baseline = {
        "sensor.a": _flat_baseline(22.0),
        "sensor.b": _flat_baseline(22.0),
    }
    test = {
        "sensor.a": [22.0, 24.5],
        "sensor.b": [22.0, 24.0],  # slightly weaker spike
    }
    strict = analyze_perturbation(baseline, test, ambiguity_gap=10.0)
    loose = analyze_perturbation(baseline, test, ambiguity_gap=0.1)
    assert strict.decision == "ambiguous"
    assert loose.decision == "clear"
    assert loose.top_match == "sensor.a"


# ---------- result shape ---------------------------------------------


def test_candidates_sorted_descending_by_z() -> None:
    baseline = {
        "sensor.a": _flat_baseline(22.0),
        "sensor.b": _flat_baseline(22.0),
        "sensor.c": _flat_baseline(22.0),
    }
    test = {
        "sensor.a": [22.0, 22.1],
        "sensor.b": [22.0, 25.0],
        "sensor.c": [22.0, 23.5],
    }
    result = analyze_perturbation(baseline, test)
    zs = [c.z_score for c in result.candidates]
    assert zs == sorted(zs, reverse=True)
