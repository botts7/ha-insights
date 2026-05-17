"""Perturbation guidance for passive sensors that can't self-identify.

The v1.10 Phase A identify capability covers entities that can announce
themselves (lights flash, speakers chime, sirens chirp, switches click).
Passive sensors — temp, humidity, illuminance, CO₂, sound — can't.

But most environmental sensors *do* respond to deliberate physical
input:

  - Temperature → place a finger on it / cup a warm hand over it
  - Humidity → breathe on it
  - CO₂ → breathe on it directly
  - Illuminance → flashlight or cover with hand
  - Sound → clap nearby
  - Vibration → tap the housing

So "identify" for passive sensors becomes a TWO-PARTY interaction:

  1. The user perturbs the sensor (touches it, breathes on it, etc.)
  2. HA Insights watches every entity of the same `device_class`,
     z-scores the response, and tells the user which entity actually
     spiked.

The killer outcome is **elimination**: when the user touches what
they think is sensor X but the spike appears on sensor Y, the app
reports "you touched what you said was X but Y actually spiked —
they're probably mislabeled."

This lib defines WHAT perturbation to ask for, per device_class,
plus the expected magnitude (so the z-score threshold can be tuned
per type — a temp spike of 0.5 °C is significant; a CO₂ spike of
50 ppm is noise). The actual detection / ranking lives in
`lib/perturbation_detection.py`; the WS endpoint glue lives in
`ws_api.py`.

## Architecture

Pure function — no HA imports, no side effects. Takes a
`device_class` string (from `state.attributes.device_class`),
returns a `PerturbationGuide` or None.

Per memory `ha_insights_find_my_device_roadmap`, this is the
v1.10 Phase B foundational lib. v1.11 location inference reuses
the same z-score primitive for passive correlation. The two libs
together turn "untouchable passive sensors" into "user-triggerable
via deliberate perturbation."
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PerturbationGuide:
    """How to perturb a sensor of a given device_class, and what to expect.

    device_class: the matching HA device_class.
    instruction: short human-readable instruction the card shows
        ("Place a finger on the sensor for 10 seconds"). Plain
        English, no markup.
    expected_delta: typical magnitude of the response in the sensor's
        native units (°C for temp, %RH for humidity, ppm for CO₂,
        lx for illuminance). Used to scale the z-score threshold so
        a sensor with naturally low noise doesn't false-positive on
        a tiny ambient drift.
    listening_window_s: how long the listening window runs after the
        user clicks "Start." Tuned per device_class — temp needs 10–30s
        (slow thermal mass), illuminance needs <2s (instant optical).
    perturb_duration_s: how long the user should HOLD the perturbation.
        Card uses this for the "Touch the sensor for N seconds" prompt
        and the in-window countdown.
    """

    device_class: str
    instruction: str
    expected_delta: float
    listening_window_s: int
    perturb_duration_s: int


# Per-device_class guides. Tuned for typical home sensor noise floors;
# field calibration will refine.
_GUIDES: dict[str, PerturbationGuide] = {
    "temperature": PerturbationGuide(
        device_class="temperature",
        instruction=(
            "Place a finger on the sensor (or cup a warm hand over it) "
            "for 10–15 seconds."
        ),
        expected_delta=2.0,        # °C
        listening_window_s=30,
        perturb_duration_s=15,
    ),
    "humidity": PerturbationGuide(
        device_class="humidity",
        instruction=(
            "Breathe gently onto the sensor for 5–10 seconds (don't "
            "actually touch it with your mouth)."
        ),
        expected_delta=10.0,       # %RH
        listening_window_s=20,
        perturb_duration_s=10,
    ),
    "carbon_dioxide": PerturbationGuide(
        device_class="carbon_dioxide",
        instruction=(
            "Lean close and breathe out directly onto the sensor for "
            "20–30 seconds."
        ),
        expected_delta=500.0,      # ppm
        listening_window_s=60,
        perturb_duration_s=30,
    ),
    "illuminance": PerturbationGuide(
        device_class="illuminance",
        instruction=(
            "Cover the sensor with your hand (or shine a flashlight "
            "directly at it)."
        ),
        expected_delta=200.0,      # lx
        listening_window_s=10,
        perturb_duration_s=5,
    ),
    "sound_pressure": PerturbationGuide(
        device_class="sound_pressure",
        instruction="Clap loudly near the sensor (or whistle / snap).",
        expected_delta=20.0,       # dB
        listening_window_s=10,
        perturb_duration_s=3,
    ),
    "moisture": PerturbationGuide(
        device_class="moisture",
        instruction=(
            "Touch the sensor probes with a damp finger, or hold a wet "
            "cloth against them."
        ),
        expected_delta=100.0,      # %, varies wildly
        listening_window_s=20,
        perturb_duration_s=10,
    ),
}


# device_classes we DELIBERATELY don't support. Each has a reason —
# documenting prevents future "why isn't X handled?" investigation.
_UNSUPPORTED: dict[str, str] = {
    # Slow integrators or fundamentally unperturbable.
    "pm25": "PM2.5 needs minutes of accumulation; no quick perturbation works.",
    "pm10": "Same as PM2.5.",
    "atmospheric_pressure": "Pressure is essentially constant indoors.",
    "pressure": "Same as atmospheric_pressure.",
    "battery": "Battery level can't be physically perturbed.",
    "signal_strength": "WiFi/Bluetooth RSSI is device-to-AP, not user-to-device.",
    "voltage": "Mains voltage is fixed; perturbing requires unplugging the device.",
    "current": "Same — needs unplug/replug, not a touch.",
    "frequency": "Mains frequency is fixed.",
    "data_rate": "Network throughput, not a physical sensor.",
    # Active sensors with their own identify paths (covered by Phase A).
    "motion": "Use the v1.10 Phase A 'wait for next event' path instead.",
    "occupancy": "Same as motion.",
    "presence": "Same as motion.",
}


def perturbation_guide_for(device_class: str | None) -> PerturbationGuide | None:
    """Return the perturbation guide for a device_class, or None.

    Args:
      device_class: value from `state.attributes.device_class`. None
        or unknown values return None (caller should fall back to
        v1.11 statistical inference for those entities).

    Returns:
      PerturbationGuide for known classes; None when the class is
      unsupported or unknown.
    """
    if not device_class:
        return None
    return _GUIDES.get(device_class.lower())


def is_perturbation_unsupported(device_class: str | None) -> bool:
    """True when this device_class is explicitly known to be
    unperturbable (PM2.5, pressure, battery, etc.).

    Useful for the card UI to differentiate "this sensor can be
    identified by touching it" (button visible) vs "this sensor
    type genuinely can't be perturbed; try statistical correlation
    inference instead" (different UX prompt).
    """
    if not device_class:
        return False
    return device_class.lower() in _UNSUPPORTED


def supported_device_classes() -> list[str]:
    """Return all device_classes this lib knows how to perturb.

    Stable for use in card / WS contracts that need to enumerate
    supported types (e.g. for a dropdown filter or a help string).
    """
    return sorted(_GUIDES.keys())


__all__ = [
    "PerturbationGuide",
    "is_perturbation_unsupported",
    "perturbation_guide_for",
    "supported_device_classes",
]
