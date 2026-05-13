"""WeatherCorrelationDetector — find habits that shift with the weather.

Why this matters: a lot of human routines look "random" in pure
time-of-day pattern detectors but make perfect sense when overlaid
on weather. "Coffee at 6:30 most days, but 6:00 on cold mornings."
"Kitchen lights at 17:00 normally, 16:15 when it's raining."
"Heating set higher on damp days regardless of outdoor temp."

This detector finds those correlations by joining habit anchor times
against the weather state at that anchor, then testing whether time
of action varies by weather class beyond what natural jitter would
explain.

Methodology (deterministic, no model training):
  1. Discover weather entities: `weather.*` (with state +
     attributes.temperature) and any `sensor.*_temperature` /
     `sensor.outdoor_temperature` it can find.
  2. For each "habit-class" entity (lights, climate, media_player,
     coffee makers — switch, light, climate domains), gather all
     state-change events at "normal hours" of the last lookback.
  3. For each event, bin its weather context: cold (<10°C) / mild /
     warm (>22°C) and dry/wet (state in "rainy","pouring","snowy").
  4. If a bin's mean-action-time differs by ≥ 15 minutes from the
     overall mean AND has at least 5 days of evidence, emit a
     correlation insight describing the shift in plain English.

Outputs are `AUTOMATION_PROPOSAL` with `payload_format="report"`:
the user can decide whether to encode the correlation as an
automation (e.g. "trigger porch lights 30 min earlier on rainy
days") — we just surface the finding.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from statistics import mean
from typing import TYPE_CHECKING, Any

from homeassistant.util import dt as dt_util

from ..insight import Insight, InsightKind
from .base import Detector, DetectorContext, register_detector

if TYPE_CHECKING:
    from ..observers.state_event_buffer import StateEvent


_LOOKBACK_DAYS = 60
_MIN_DAYS_PER_BIN = 5
_MIN_SHIFT_MINUTES = 15
# Only consider these domains — devices where a meaningful "action
# time" exists. Sensors, presence trackers, etc don't qualify.
_HABIT_DOMAINS = frozenset({"light", "switch", "climate", "media_player", "cover"})
# Cold/warm thresholds in Celsius. Tuned for typical European
# climates; could become user-configurable later.
_COLD_THRESHOLD_C = 10.0
_WARM_THRESHOLD_C = 22.0
_WET_WEATHER_STATES = frozenset(
    {"rainy", "pouring", "snowy", "snowy-rainy", "lightning-rainy", "lightning", "hail"}
)


@register_detector
class WeatherCorrelationDetector(Detector):
    """Detect habit-time shifts correlated with weather conditions."""

    name = "weather_correlation"
    kind = InsightKind.AUTOMATION_PROPOSAL
    requires_recorder = False
    description = (
        "Finds habit timings that shift with weather — earlier kitchen "
        "lights on rainy days, coffee earlier on cold mornings, etc — "
        "and surfaces them as actionable correlations."
    )
    required_data = (
        "domain:weather",
    )
    optional_data = (
        "entity:sensor.outdoor_temperature",
        "entity_pattern:sensor.*_temperature",
    )

    async def scan(self, ctx: DetectorContext) -> list[Insight]:
        if ctx.event_buffer is None:
            return []
        weather_eid = self._pick_weather_entity(ctx)
        if weather_eid is None:
            return []
        # Outdoor-temp sensor is optional — when present it lets us
        # classify days by temperature. Without one we still detect
        # precipitation-class correlations (rainy vs dry).
        temp_eid = self._pick_outdoor_temp_sensor(ctx)
        cutoff = datetime.now(tz=UTC) - timedelta(days=_LOOKBACK_DAYS)
        day_context = self._build_daily_weather_context(
            ctx, weather_eid, temp_eid, cutoff
        )
        if not day_context:
            return []

        # Find habit candidates
        habit_eids = self._find_habit_entities(ctx)
        if not habit_eids:
            return []

        insights: list[Insight] = []
        for eid in habit_eids:
            ins = self._evaluate_entity(ctx, eid, day_context, cutoff)
            if ins is not None:
                insights.append(ins)
        return insights

    # -------- discovery --------

    def _pick_weather_entity(self, ctx: DetectorContext) -> str | None:
        """First `weather.*` entity with a usable state."""
        try:
            for s in ctx.hass.states.async_all():
                if s.entity_id.startswith("weather.") and s.state:
                    return s.entity_id
        except Exception:  # noqa: BLE001
            return None
        return None

    def _pick_outdoor_temp_sensor(
        self, ctx: DetectorContext
    ) -> str | None:
        """Prefer a `sensor.outdoor_temperature` or `_outside_temp`;
        fall back to any `sensor.*_temperature` whose state parses as
        a float. Returns None if nothing usable — temperature axis is
        optional, the detector still runs on precipitation alone."""
        candidates_priority: list[str] = []
        try:
            for s in ctx.hass.states.async_all():
                if not s.entity_id.startswith("sensor."):
                    continue
                eid = s.entity_id
                try:
                    float(s.state)
                except (TypeError, ValueError):
                    continue
                if eid.endswith(
                    ("_outdoor_temperature", "_outside_temperature", "_temperature_outdoor")
                ) or eid == "sensor.outdoor_temperature":
                    return eid  # explicit match wins
                if eid.endswith("_temperature"):
                    candidates_priority.append(eid)
        except Exception:  # noqa: BLE001
            return None
        return candidates_priority[0] if candidates_priority else None

    def _find_habit_entities(self, ctx: DetectorContext) -> list[str]:
        out: list[str] = []
        try:
            for s in ctx.hass.states.async_all():
                domain = s.entity_id.split(".", 1)[0]
                if domain in _HABIT_DOMAINS:
                    out.append(s.entity_id)
        except Exception:  # noqa: BLE001
            return []
        return out

    # -------- weather context per day --------

    def _build_daily_weather_context(
        self,
        ctx: DetectorContext,
        weather_eid: str,
        temp_eid: str | None,
        cutoff: datetime,
    ) -> dict[date, dict[str, str]]:
        """For each day, return {temperature_class, precipitation_class,
        weather_state}.

        - Precipitation class derives from the most-seen `weather.*`
          state across the day (rainy/pouring/snowy → wet, else dry).
        - Temperature class derives from the daily mean reading of
          `temp_eid` (a `sensor.*` whose state is parseable as a
          float). When no temp sensor is available, every day is
          tagged "unknown" and the temperature axis is ignored
          downstream — we still detect precipitation correlations.

        Critically we DO NOT read `ev.attributes` here. StateEvent
        carries only `(timestamp, entity_id, domain, area_id,
        old_state, new_state, context_user_id)` — historical
        attributes aren't replayed. Hence the separate temp sensor.
        """
        from collections import Counter

        states_by_day: dict[date, list[str]] = defaultdict(list)
        temps_by_day: dict[date, list[float]] = defaultdict(list)

        for ev in ctx.event_buffer.query(  # type: ignore[union-attr]
            entity_id=weather_eid, since=cutoff
        ):
            local = dt_util.as_local(ev.timestamp)
            states_by_day[local.date()].append((ev.new_state or "").lower())

        if temp_eid is not None:
            for ev in ctx.event_buffer.query(  # type: ignore[union-attr]
                entity_id=temp_eid, since=cutoff
            ):
                try:
                    val = float(ev.new_state or "")
                except (TypeError, ValueError):
                    continue
                local = dt_util.as_local(ev.timestamp)
                temps_by_day[local.date()].append(val)

        if not states_by_day:
            return {}

        out: dict[date, dict[str, str]] = {}
        for day, states in states_by_day.items():
            top_state = Counter(states).most_common(1)[0][0] if states else ""
            temps = temps_by_day.get(day, [])
            if temps:
                avg_temp = mean(temps)
                if avg_temp < _COLD_THRESHOLD_C:
                    temp_class = "cold"
                elif avg_temp > _WARM_THRESHOLD_C:
                    temp_class = "warm"
                else:
                    temp_class = "mild"
            else:
                temp_class = "unknown"
            precip_class = (
                "wet" if top_state in _WET_WEATHER_STATES else "dry"
            )
            out[day] = {
                "temperature_class": temp_class,
                "precipitation_class": precip_class,
                "weather_state": top_state,
            }
        return out

    # -------- entity-level evaluation --------

    def _evaluate_entity(
        self,
        ctx: DetectorContext,
        eid: str,
        day_context: dict[date, dict[str, str]],
        cutoff: datetime,
    ) -> Insight | None:
        """Look for systematic time-of-day shifts conditional on weather
        class. Returns at most one insight per habit entity, choosing
        the strongest correlation found.
        """
        # Take only "active" transitions: off → on, idle → playing,
        # cover transitions to open. Filtering noise out of the
        # event stream is what gives the per-day anchor a chance
        # to be stable.
        events = ctx.event_buffer.query(  # type: ignore[union-attr]
            entity_id=eid, since=cutoff
        )
        anchor_minutes_by_day: dict[date, int] = {}
        for ev in events:
            new = (ev.new_state or "").lower()
            old = (ev.old_state or "").lower()
            if not self._is_active_transition(eid, old, new):
                continue
            local = dt_util.as_local(ev.timestamp)
            day = local.date()
            if day in anchor_minutes_by_day:
                continue  # first activation of the day only
            anchor_minutes_by_day[day] = local.hour * 60 + local.minute
        if len(anchor_minutes_by_day) < 2 * _MIN_DAYS_PER_BIN:
            return None  # not enough data to split

        overall_mean = mean(anchor_minutes_by_day.values())

        # Group days by weather class — temperature and precip both
        # tested independently; we pick whichever shows the biggest
        # shift.
        by_temp: dict[str, list[int]] = defaultdict(list)
        by_precip: dict[str, list[int]] = defaultdict(list)
        for day, minutes in anchor_minutes_by_day.items():
            ctx_for_day = day_context.get(day)
            if ctx_for_day is None:
                continue
            by_temp[ctx_for_day["temperature_class"]].append(minutes)
            by_precip[ctx_for_day["precipitation_class"]].append(minutes)

        best_shift_minutes = 0.0
        best_class: str | None = None
        best_axis: str | None = None
        best_mean: float = overall_mean
        best_samples = 0
        for axis_name, buckets in (
            ("temperature", by_temp),
            ("precipitation", by_precip),
        ):
            for cls, samples in buckets.items():
                if cls == "unknown" or len(samples) < _MIN_DAYS_PER_BIN:
                    continue
                cls_mean = mean(samples)
                shift = cls_mean - overall_mean
                if abs(shift) > abs(best_shift_minutes):
                    best_shift_minutes = shift
                    best_class = cls
                    best_axis = axis_name
                    best_mean = cls_mean
                    best_samples = len(samples)
        if (
            best_class is None
            or abs(best_shift_minutes) < _MIN_SHIFT_MINUTES
        ):
            return None

        direction = "earlier" if best_shift_minutes < 0 else "later"
        overall_hhmm = self._fmt_hhmm(overall_mean)
        class_hhmm = self._fmt_hhmm(best_mean)
        # Friendly name
        friendly = (
            ctx.hass.states.get(eid).attributes.get("friendly_name")
            if ctx.hass.states.get(eid) is not None
            else eid
        ) or eid

        title = (
            f"☁️ {friendly} fires ~{abs(int(best_shift_minutes))} min "
            f"{direction} on {best_class} {best_axis} days "
            f"(usually {overall_hhmm}, on {best_class} days {class_hhmm}, "
            f"{best_samples} days observed). Consider a weather-aware "
            "trigger."
        )

        fingerprint = {
            "kind": "weather_correlation",
            "entity_id": eid,
            "axis": best_axis,
            "class": best_class,
        }
        payload = {
            "summary": title,
            "entity_id": eid,
            "axis": best_axis,
            "class": best_class,
            "shift_minutes": round(best_shift_minutes, 1),
            "overall_avg_hhmm": overall_hhmm,
            "class_avg_hhmm": class_hhmm,
            "samples_in_class": best_samples,
            "suggested_automation_sketch": {
                "trigger": "time / sun / state with weather condition",
                "condition": {
                    "weather_class": best_class,
                    "axis": best_axis,
                },
                "action": f"target {eid} {direction}",
            },
        }
        confidence = round(
            min(
                0.9,
                0.4
                + (abs(best_shift_minutes) / 120.0)
                + (best_samples / 30.0),
            ),
            3,
        )
        return Insight(
            id=Insight.compute_id(
                InsightKind.AUTOMATION_PROPOSAL, fingerprint
            ),
            kind=InsightKind.AUTOMATION_PROPOSAL,
            detector=self.name,
            area_id=None,
            title=title,
            confidence=confidence,
            fingerprint=fingerprint,
            payload=payload,
            payload_format="report",
            created_at=datetime.now(tz=UTC),
        )

    @staticmethod
    def _is_active_transition(eid: str, old: str, new: str) -> bool:
        domain = eid.split(".", 1)[0]
        if domain in ("light", "switch"):
            return old != "on" and new == "on"
        if domain == "cover":
            return old != "open" and new == "open"
        if domain == "media_player":
            return old in ("idle", "off", "paused", "") and new == "playing"
        if domain == "climate":
            return old in ("off", "") and new in ("heat", "cool", "auto", "heat_cool")
        return False

    @staticmethod
    def _fmt_hhmm(minutes: float) -> str:
        m = int(round(minutes))
        return f"{m // 60:02d}:{m % 60:02d}"
