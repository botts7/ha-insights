"""Example insight fixtures for first-run demos.

Lets a brand-new install see what HA Insights produces BEFORE
the 14-day buffer has filled up. Without this, new users
install the integration, look at the panel, see an empty list,
and bounce — even though the integration works fine.

The fixtures cover every InsightKind + most detectors so the
panel renders the full visual range (anomaly cards, automation
proposals, audit findings, weather correlation, etc).

Every fixture is tagged with `payload._example = True` so:
  - the card renders a "🎯 EXAMPLE" pill
  - `clear_examples` can find and remove them in one query
  - the Apply button is disabled (these don't reference real
    entities, applying would create a broken automation)

Build sample insights via `build_example_insights()` (returns a
list of Insight objects). Inject via `inject_examples(store)`
and remove via `clear_examples(store)` — both are exposed as
WS endpoints in ws_api.py.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from .insight import Insight, InsightKind

# Tag key used to find + delete example insights. Single string
# constant so the WS handler + store query agree.
EXAMPLE_PAYLOAD_KEY = "_example"


def _ex(
    *,
    kind: InsightKind,
    detector: str,
    title: str,
    confidence: float,
    fingerprint: dict[str, Any],
    payload: dict[str, Any],
    payload_format: str = "automation",
    age_hours: float = 1.0,
    maturity: str = "stable",
) -> Insight:
    """Helper to build an example Insight with consistent shape."""
    full_payload = {
        **payload,
        EXAMPLE_PAYLOAD_KEY: True,
        "_example_maturity_hint": maturity,
    }
    return Insight(
        id=Insight.compute_id(kind, fingerprint),
        kind=kind,
        detector=detector,
        area_id=None,
        title=title,
        confidence=confidence,
        fingerprint=fingerprint,
        payload=full_payload,
        payload_format=payload_format,
        created_at=datetime.now(tz=UTC) - timedelta(hours=age_hours),
    )


def build_example_insights() -> list[Insight]:
    """Return a fresh list of example insights spanning kinds + detectors.

    Generates new IDs each call (timestamp drift is fine — fingerprints
    are stable so re-injecting on top of existing examples replaces
    rather than duplicates).
    """
    return [
        _ex(
            kind=InsightKind.AUTOMATION_PROPOSAL,
            detector="schedule",
            title=(
                "🕐 Living room lights consistently on at 18:42 on weekdays "
                "(11 of last 14 days). Turn into an automation?"
            ),
            confidence=0.92,
            fingerprint={
                "kind": "schedule",
                "entity_id": "light.example_living_room",
            },
            payload={
                "alias": "[EXAMPLE] Living room lights — weekday evening",
                "trigger": [
                    {"platform": "time", "at": "18:42:00"},
                ],
                "condition": [
                    {"condition": "time", "weekday": [
                        "mon", "tue", "wed", "thu", "fri"
                    ]}
                ],
                "action": [
                    {
                        "service": "light.turn_on",
                        "target": {"entity_id": "light.example_living_room"},
                    }
                ],
                "mode": "single",
            },
            age_hours=2,
        ),
        _ex(
            kind=InsightKind.AUTOMATION_PROPOSAL,
            detector="cooccurrence",
            title=(
                "🔗 'Office desk lamp' usually turns on within 2 minutes "
                "of 'Office monitor' (43 of last 50 days). Worth automating?"
            ),
            confidence=0.88,
            fingerprint={
                "kind": "cooccurrence",
                "leader": "switch.example_office_monitor",
                "follower": "light.example_office_desk",
            },
            payload={
                "alias": "[EXAMPLE] Office desk lamp follows monitor",
                "trigger": [
                    {
                        "platform": "state",
                        "entity_id": "switch.example_office_monitor",
                        "to": "on",
                    }
                ],
                "action": [
                    {
                        "service": "light.turn_on",
                        "target": {"entity_id": "light.example_office_desk"},
                    }
                ],
                "mode": "single",
            },
            age_hours=6,
        ),
        _ex(
            kind=InsightKind.ANOMALY,
            detector="orphan_device",
            title=(
                "📡 'Garage motion sensor' hasn't reported in 12 days "
                "(usually fires multiple times daily). Battery dead?"
            ),
            confidence=0.95,
            fingerprint={
                "kind": "orphan_device",
                "entity_id": "binary_sensor.example_garage_motion",
            },
            payload={
                "entity_id": "binary_sensor.example_garage_motion",
                "last_seen": (
                    datetime.now(tz=UTC) - timedelta(days=12)
                ).isoformat(),
                "typical_frequency_per_day": 8.4,
            },
            payload_format="report",
            age_hours=8,
        ),
        _ex(
            kind=InsightKind.AUTOMATION_PROPOSAL,
            detector="phone_charge_reminder",
            title=(
                "📱 Pixel 8 likely to run flat before 22:45: drains ~5.1%/h "
                "in the evening, would have died early on 7 of last 14 "
                "nights. Suggest predictive reminder."
            ),
            confidence=0.81,
            fingerprint={
                "kind": "phone_charge_reminder",
                "entity_id": "sensor.example_pixel_8_battery_level",
            },
            payload={
                "alias": "[EXAMPLE] Pixel 8 predictive charge reminder",
                "trigger": [
                    {"platform": "time", "at": "18:45", "id": "bedtime_minus_4h"},
                ],
                "action": [
                    {
                        "service": "notify.mobile_app_pixel_8",
                        "data": {
                            "title": "Battery won't make it to bedtime",
                            "message": "📱 At 18:45 with current drain you'll be flat by 22:00. Plug in.",
                        },
                    }
                ],
                "mode": "single",
            },
            maturity="experimental",
            age_hours=12,
        ),
        _ex(
            kind=InsightKind.AUTOMATION_PROPOSAL,
            detector="weather_correlation",
            title=(
                "☁️ Kitchen lights fires ~22 min earlier on wet days "
                "(usually 17:14, on rainy days 16:52, 18 days observed). "
                "Consider a weather-aware trigger."
            ),
            confidence=0.74,
            fingerprint={
                "kind": "weather_correlation",
                "entity_id": "light.example_kitchen",
                "axis": "precipitation",
                "class": "wet",
            },
            payload={
                "summary": "Kitchen lights earlier on rainy days",
                "shift_minutes": -22,
                "class_avg_hhmm": "16:52",
                "overall_avg_hhmm": "17:14",
            },
            payload_format="report",
            maturity="experimental",
            age_hours=20,
        ),
        _ex(
            kind=InsightKind.AUTOMATION_IMPROVEMENT,
            detector="automation_audit",
            title=(
                "🔧 Review automation: Wake-up routine — entity "
                "'sensor.example_bedroom_temperature' hasn't reported in "
                "14 days; the condition will never match."
            ),
            confidence=0.91,
            fingerprint={
                "kind": "automation_audit",
                "automation_id": "example.wake_up_routine",
            },
            payload={
                "automation_alias": "Wake-up routine",
                "observation_kinds": ["entity_stale_state"],
                "summary": (
                    "The temperature condition references a sensor that "
                    "stopped reporting two weeks ago. Either replace the "
                    "sensor or remove the condition."
                ),
            },
            payload_format="report",
            age_hours=30,
        ),
    ]


__all__ = [
    "EXAMPLE_PAYLOAD_KEY",
    "build_example_insights",
]
