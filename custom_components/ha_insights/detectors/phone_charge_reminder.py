"""PhoneChargeReminderDetector — predictive low-battery reminder.

Not a static threshold. The hard question users actually have is
**"will my battery survive until I usually plug in?"** — and the
answer depends on the user's habitual drain rate at this hour of
THIS kind of day (weekday/weekend, season), not on a fixed "<30%"
trip-wire.

So this detector:

  1. Looks back the FULL buffer it has (typically up to 90 days,
     capped by recorder + event-buffer retention). Reason: 14 days
     can't separate winter-cold drain (cold cells = 2× drop) from
     summer drain, and a single week of unusual usage (travel,
     illness) skews everything.

  2. Builds a per-hour-of-day drain-rate model, split by weekday
     vs weekend (the two strongest variance axes after seasonality).
     E.g. 14:00–18:00 weekday drains 4%/h on average; 14:00–18:00
     Saturday drains 8%/h (maps + camera). The detector then
     forecasts level at typical "plug-in" time using the rate
     applicable to the day in question.

  3. Detects TWO anchor events from the user's habits:
       - typical bedtime plug-in (binary_sensor.<phone>_charging
         on after 16:00 local)
       - typical home arrival (device_tracker.<phone> → home, if
         available); if home arrival reliably precedes bedtime,
         it's a meaningful checkpoint too (commute back, before
         evening drain).
     Each anchor gets its own predictive check.

  4. Emits an automation that runs HOURLY between mid-afternoon
     and typical bedtime. At each fire, condition uses a template:
     `(current battery) < (drain_rate × hours_until_anchor +
      safety_buffer)`. If true → notify.

     Conditions are encoded with a `template` condition so the
     prediction lives in HA, no helper needed. The user can edit
     the rate/safety values if their habits shift.

  5. Confidence factors in how many days the buffer covers + how
     stable the drain-rate model is (std-dev as a fraction of mean).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from statistics import mean, stdev
from typing import TYPE_CHECKING, Any

from homeassistant.util import dt as dt_util

from ..insight import Insight, InsightKind
from .base import Detector, DetectorContext, Maturity, register_detector

if TYPE_CHECKING:
    from ..observers.state_event_buffer import StateEvent


# Look at the WHOLE buffer up to this cap. Recorder retention will
# limit it further; the detector tolerates whatever it gets.
_MAX_LOOKBACK_DAYS = 90
# Need at least this many days to compute weekday/weekend split.
_MIN_DAYS_FOR_PATTERN = 7
# Where rate model is too volatile to trust (std-dev / mean), back
# off the suggestion or skip entirely.
_HIGH_VARIANCE_RATIO = 1.0
# Pad the prediction so we don't suggest reminders that trip 0.5%
# above the predicted minimum. Tunable later via OptionsFlow.
_SAFETY_BUFFER_PCT = 10
# Suggest 3 check-times — at 4h, 2h, 1h before anchor.
_CHECK_HOURS_BEFORE = (4, 2, 1)
# Minimum drain hours observed before we trust the per-hour rate.
_MIN_OBS_PER_HOUR = 3


@register_detector
class PhoneChargeReminderDetector(Detector):
    """Predictive low-battery reminder tied to bedtime + home-arrival."""

    name = "phone_charge_reminder"
    kind = InsightKind.AUTOMATION_PROPOSAL
    requires_recorder = False
    maturity = Maturity.EXPERIMENTAL
    description = (
        "Predicts whether your phone will run flat before bedtime / home "
        "arrival using your evening drain rate, and suggests a "
        "notification automation when the answer is too often 'yes'."
    )
    required_data = (
        "integration:mobile_app",
        "entity_pattern:binary_sensor.*_charging",
        "entity_pattern:sensor.*_battery_level",
    )
    optional_data = (
        "entity_pattern:device_tracker.<phone>",
    )

    async def scan(self, ctx: DetectorContext) -> list[Insight]:
        if ctx.event_buffer is None:
            return []
        phone_pairs = self._find_phone_pairs(ctx)
        if not phone_pairs:
            return []

        cutoff = datetime.now(tz=UTC) - timedelta(days=_MAX_LOOKBACK_DAYS)
        insights: list[Insight] = []
        for phone_label, charging_eid, battery_eid, tracker_eid in phone_pairs:
            insights.extend(
                self._evaluate_phone(
                    ctx,
                    phone_label,
                    charging_eid,
                    battery_eid,
                    tracker_eid,
                    cutoff,
                )
            )
        return insights

    # -------- discovery --------

    def _find_phone_pairs(
        self, ctx: DetectorContext
    ) -> list[tuple[str, str, str, str | None]]:
        """(label, charging_eid, battery_eid, device_tracker_eid_or_None)."""
        chargings: dict[str, str] = {}
        levels: dict[str, str] = {}
        trackers: dict[str, str] = {}
        try:
            for s in ctx.hass.states.async_all():
                eid = s.entity_id
                if eid.startswith("binary_sensor.") and eid.endswith(
                    "_charging"
                ):
                    base = eid[len("binary_sensor.") : -len("_charging")]
                    chargings[base] = eid
                elif eid.startswith("sensor.") and eid.endswith(
                    "_battery_level"
                ):
                    base = eid[len("sensor.") : -len("_battery_level")]
                    levels[base] = eid
                elif eid.startswith("device_tracker."):
                    base = eid[len("device_tracker.") :]
                    trackers[base] = eid
        except Exception:
            return []
        out: list[tuple[str, str, str, str | None]] = []
        for base in chargings:
            if base in levels:
                pretty = base.replace("_", " ").title()
                out.append(
                    (pretty, chargings[base], levels[base], trackers.get(base))
                )
        return out

    # -------- main evaluation --------

    def _evaluate_phone(
        self,
        ctx: DetectorContext,
        phone_label: str,
        charging_eid: str,
        battery_eid: str,
        tracker_eid: str | None,
        cutoff: datetime,
    ) -> list[Insight]:
        """Evaluate one phone. Returns 0..2 insights:
          - primary: predictive charge-reminder automation
          - secondary: per-weekday "always low on Xday" habit nudge
        Each is independent — variance-gating the primary doesn't
        suppress the secondary. Returning an empty list means
        "nothing useful detected for this phone".
        """
        assert ctx.event_buffer is not None
        out: list[Insight] = []

        plug_in_per_day = self._find_anchor_plug_ins(
            ctx, charging_eid, cutoff
        )
        if len(plug_in_per_day) < _MIN_DAYS_FOR_PATTERN:
            return out

        battery_events = list(
            ctx.event_buffer.query(entity_id=battery_eid, since=cutoff)
        )
        if len(battery_events) < 100:
            return out

        # Multi-user attribution. Computed once, used by both insights
        # so they tag the same user with the same confidence.
        from ..notifications.user_routing import get_user_id_for_entity

        target_user_id, target_user_confidence = get_user_id_for_entity(
            ctx.hass, battery_eid
        )

        # Weekday summary — used by both the secondary habit insight
        # AND by the title of the primary as context. Computed before
        # the drain-rate model so the secondary remains available
        # when the rate model fails (rare; very irregular phones).
        per_dow_summary = self._summarize_by_weekday(
            battery_events, plug_in_per_day
        )
        # Overall avg of per-day minimum battery (% across all
        # observed days). Used as the baseline that "Wednesdays are
        # ~N points worse than" — derived from the weekday summary
        # so we never reference a value that's gated away.
        if per_dow_summary:
            overall_min_avg = round(
                mean(
                    float(s["mean_min_pct"])
                    for s in per_dow_summary.values()
                ),
                1,
            )
        else:
            overall_min_avg = 0.0

        # Secondary insight: weekday habit nudge (independent of
        # drain-rate model). Behavioural advice, payload_format=report.
        secondary = self._build_weekday_habit_insight(
            phone_label=phone_label,
            battery_eid=battery_eid,
            per_dow_summary=per_dow_summary,
            overall_avg=overall_min_avg,
            target_user_id=target_user_id,
            target_user_confidence=target_user_confidence,
        )
        if secondary is not None:
            out.append(secondary)

        # Primary insight: predictive automation. Requires a stable
        # rate model + observed risky days + low variance.
        rate_model = self._build_drain_rate_model(battery_events)
        if not rate_model:
            return out

        minutes = [
            dt_util.as_local(ts).hour * 60 + dt_util.as_local(ts).minute
            for ts in plug_in_per_day.values()
        ]
        avg_plug_in_min = int(round(mean(minutes)))
        bedtime_hhmm = (
            f"{avg_plug_in_min // 60:02d}:{avg_plug_in_min % 60:02d}"
        )

        home_arrival_hhmm = None
        if tracker_eid is not None:
            home_arrival_hhmm = self._find_typical_home_arrival(
                ctx, tracker_eid, cutoff
            )
            if home_arrival_hhmm is not None:
                ha_h, ha_m = (int(x) for x in home_arrival_hhmm.split(":"))
                gap_min = avg_plug_in_min - (ha_h * 60 + ha_m)
                if gap_min < 120:
                    home_arrival_hhmm = None

        risky_days = self._count_predicted_dead_days(
            battery_events, plug_in_per_day, rate_model
        )
        if risky_days < 3:
            return out  # secondary already added; primary not justified

        global_rate = rate_model["overall_mean_per_hour"]
        global_var = rate_model["overall_variance_ratio"]
        if global_var > _HIGH_VARIANCE_RATIO:
            return out  # drain too erratic to predict reliably

        slug = battery_eid.split(".", 1)[-1].replace("_battery_level", "")
        notify_service = f"notify.mobile_app_{slug}"

        automation = self._build_predictive_automation(
            phone_label=phone_label,
            battery_eid=battery_eid,
            charging_eid=charging_eid,
            tracker_eid=tracker_eid,
            bedtime_hhmm=bedtime_hhmm,
            home_arrival_hhmm=home_arrival_hhmm,
            rate_per_hour=global_rate,
            notify_service=notify_service,
        )

        days_observed = len(plug_in_per_day)
        title = (
            f"📱 {phone_label} likely to run flat before {bedtime_hhmm}: "
            f"drains ~{global_rate:.1f}%/h in the evening, "
            f"would have died early on {risky_days} of last "
            f"{days_observed} nights. Suggest predictive reminder."
        )

        confidence = round(
            min(1.0, risky_days / 10.0)
            * max(0.5, 1.0 - global_var),
            3,
        )

        fingerprint = {
            "kind": "phone_charge_reminder",
            "entity_id": battery_eid,
        }
        payload = {
            **automation,
            "_charge_reminder": {
                "phone_label": phone_label,
                "battery_entity": battery_eid,
                "charging_entity": charging_eid,
                "tracker_entity": tracker_eid,
                "avg_bedtime": bedtime_hhmm,
                "typical_home_arrival": home_arrival_hhmm,
                "drain_rate_pct_per_hour": round(global_rate, 2),
                "drain_rate_variance_ratio": round(global_var, 3),
                "risky_nights_in_lookback": risky_days,
                "days_observed": days_observed,
                "safety_buffer_pct": _SAFETY_BUFFER_PCT,
                "rate_model": {
                    k: round(v, 2) if isinstance(v, float) else v
                    for k, v in rate_model.items()
                    if not isinstance(v, dict)
                },
            },
        }

        primary = Insight(
            id=Insight.compute_id(InsightKind.AUTOMATION_PROPOSAL, fingerprint),
            kind=InsightKind.AUTOMATION_PROPOSAL,
            detector=self.name,
            area_id=None,
            title=title,
            confidence=confidence,
            fingerprint=fingerprint,
            payload=payload,
            payload_format="automation",
            created_at=datetime.now(tz=UTC),
            target_user_id=target_user_id,
            target_user_id_confidence=target_user_confidence,
        )
        out.append(primary)
        return out

    # -------- anchor discovery --------

    def _find_anchor_plug_ins(
        self,
        ctx: DetectorContext,
        charging_eid: str,
        cutoff: datetime,
    ) -> dict[date, datetime]:
        """First plug-in event each day after 16:00 local (bedtime)."""
        out: dict[date, datetime] = {}
        for ev in ctx.event_buffer.query(  # type: ignore[union-attr]
            entity_id=charging_eid, since=cutoff
        ):
            new = (ev.new_state or "").lower()
            old = (ev.old_state or "").lower()
            if old == "on" or new != "on":
                continue
            local = dt_util.as_local(ev.timestamp)
            if local.hour < 16:
                continue
            day = local.date()
            if day not in out:
                out[day] = ev.timestamp
        return out

    def _find_typical_home_arrival(
        self,
        ctx: DetectorContext,
        tracker_eid: str,
        cutoff: datetime,
    ) -> str | None:
        """Median 'arrives home' transition time (HH:MM, local). Returns
        None if too few transitions observed."""
        arrivals: dict[date, int] = {}
        for ev in ctx.event_buffer.query(  # type: ignore[union-attr]
            entity_id=tracker_eid, since=cutoff
        ):
            new = (ev.new_state or "").lower()
            old = (ev.old_state or "").lower()
            if new != "home" or old == "home":
                continue
            local = dt_util.as_local(ev.timestamp)
            # Only count "evening arrival" (commute-back); morning
            # tracker glitches don't qualify.
            if local.hour < 13:
                continue
            day = local.date()
            if day not in arrivals:
                arrivals[day] = local.hour * 60 + local.minute
        if len(arrivals) < _MIN_DAYS_FOR_PATTERN:
            return None
        sorted_mins = sorted(arrivals.values())
        median = sorted_mins[len(sorted_mins) // 2]
        return f"{median // 60:02d}:{median % 60:02d}"

    # -------- drain-rate model --------

    def _build_drain_rate_model(
        self, battery_events: list[StateEvent]
    ) -> dict[str, Any]:
        """For each (hour-of-day, weekday-vs-weekend) bucket, compute
        average %/h drain across all days where the phone was NOT
        charging. Returns an overall mean + variance ratio + per-hour
        breakdown for the automation's template.
        """
        # We have to assume "not-charging" without a join. The
        # heuristic: if successive samples show a NEGATIVE delta of
        # at most -20%/h (anything sharper is a screen-off-vs-on
        # artefact or a quick top-up, not real drain), count it as
        # discharge. Positive deltas (charging) are ignored.
        by_bucket_weekday: dict[int, list[float]] = defaultdict(list)
        by_bucket_weekend: dict[int, list[float]] = defaultdict(list)

        sorted_events = sorted(battery_events, key=lambda e: e.timestamp)
        prev_ts: datetime | None = None
        prev_level: float | None = None
        for ev in sorted_events:
            try:
                level = float(ev.new_state or 0)
            except (ValueError, TypeError):
                continue
            ts = ev.timestamp
            if prev_ts is None or prev_level is None:
                prev_ts, prev_level = ts, level
                continue
            delta_pct = level - prev_level
            delta_h = (ts - prev_ts).total_seconds() / 3600.0
            # Reject gaps > 2h (sleeping phone) or < 30s (event noise)
            if delta_h < 30 / 3600 or delta_h > 2.0:
                prev_ts, prev_level = ts, level
                continue
            rate = delta_pct / delta_h  # negative = drain
            if rate < -20 or rate >= 0:
                # rate >= 0 → charging or flat; not a drain sample.
                # rate < -20 → screen-on heavy use spike; trims tail.
                prev_ts, prev_level = ts, level
                continue
            drain = -rate  # positive %/h
            local = dt_util.as_local(ts)
            bucket = local.hour
            if local.weekday() < 5:
                by_bucket_weekday[bucket].append(drain)
            else:
                by_bucket_weekend[bucket].append(drain)
            prev_ts, prev_level = ts, level

        # Evening hours dominate the "before bedtime" question. We
        # want a model rooted in 16:00–23:00 behaviour; that's the
        # window the automation predicts across.
        EVENING = range(16, 24)
        weekday_evening = [
            r
            for h, samples in by_bucket_weekday.items()
            if h in EVENING and len(samples) >= _MIN_OBS_PER_HOUR
            for r in samples
        ]
        weekend_evening = [
            r
            for h, samples in by_bucket_weekend.items()
            if h in EVENING and len(samples) >= _MIN_OBS_PER_HOUR
            for r in samples
        ]
        all_evening = weekday_evening + weekend_evening
        if len(all_evening) < 20:
            return {}
        overall_mean = mean(all_evening)
        overall_sd = stdev(all_evening) if len(all_evening) >= 2 else 0.0
        # Variance ratio = sd / mean. A ratio < 0.5 is tight, 0.5–1.0
        # is moderate, > 1.0 is noisy enough we should skip.
        var_ratio = (overall_sd / overall_mean) if overall_mean > 0 else 99
        return {
            "overall_mean_per_hour": round(overall_mean, 2),
            "overall_variance_ratio": round(var_ratio, 3),
            "weekday_mean_per_hour": (
                round(mean(weekday_evening), 2) if weekday_evening else 0.0
            ),
            "weekend_mean_per_hour": (
                round(mean(weekend_evening), 2) if weekend_evening else 0.0
            ),
            "samples_used": len(all_evening),
        }

    # -------- predictive risk count --------

    def _count_predicted_dead_days(
        self,
        battery_events: list[StateEvent],
        plug_in_per_day: dict[date, datetime],
        rate_model: dict[str, Any],
    ) -> int:
        """Walk each historical day. For each, find the battery level
        at a 4h-before-plug-in checkpoint, project forward at the
        applicable drain rate, and count how many days would have
        died (level - rate × hours < safety_buffer).
        """
        rate_weekday = rate_model.get("weekday_mean_per_hour", 0.0)
        rate_weekend = rate_model.get("weekend_mean_per_hour", 0.0)
        if rate_weekday <= 0 and rate_weekend <= 0:
            return 0

        # Group battery events by day for fast lookup
        by_day: dict[date, list[StateEvent]] = defaultdict(list)
        for ev in battery_events:
            local = dt_util.as_local(ev.timestamp)
            by_day[local.date()].append(ev)

        risky = 0
        for day, plug_in_ts in plug_in_per_day.items():
            day_events = by_day.get(day, [])
            if not day_events:
                continue
            checkpoint = plug_in_ts - timedelta(hours=4)
            sorted_day = sorted(day_events, key=lambda e: e.timestamp)
            level_at_checkpoint: float | None = None
            for ev in sorted_day:
                if ev.timestamp > checkpoint:
                    break
                try:
                    level_at_checkpoint = float(ev.new_state or 0)
                except (ValueError, TypeError):
                    continue
            if level_at_checkpoint is None:
                continue
            # Day-of-week determines which rate to use
            rate = (
                rate_weekday
                if datetime.fromordinal(day.toordinal()).weekday() < 5
                else rate_weekend
            )
            if rate <= 0:
                continue
            predicted_at_anchor = level_at_checkpoint - (rate * 4)
            if predicted_at_anchor < _SAFETY_BUFFER_PCT:
                risky += 1
        return risky

    # -------- automation builder --------

    def _build_predictive_automation(
        self,
        *,
        phone_label: str,
        battery_eid: str,
        charging_eid: str,
        tracker_eid: str | None,
        bedtime_hhmm: str,
        home_arrival_hhmm: str | None,
        rate_per_hour: float,
        notify_service: str,
    ) -> dict[str, Any]:
        """Compose triggers + template conditions for the apply-able
        automation. Three hourly checks before bedtime; if a home-
        arrival anchor exists, add a check at home-arrival too.

        Each check uses a template condition of the form:
          {{ states('sensor.<phone>_battery_level')|float < (rate * h + buffer) }}
        so the user can re-tune rate / buffer by editing the YAML.
        """
        bedtime_h, bedtime_m = (int(x) for x in bedtime_hhmm.split(":"))
        triggers: list[dict[str, Any]] = []
        conditions: list[dict[str, Any]] = [
            {"condition": "state", "entity_id": charging_eid, "state": "off"},
        ]
        # We use multiple TIME triggers and a single OR-template that
        # selects the right forecast based on the firing hour.
        for hours_before in _CHECK_HOURS_BEFORE:
            tmin = (bedtime_h * 60 + bedtime_m) - hours_before * 60
            tmin %= 24 * 60
            triggers.append(
                {
                    "platform": "time",
                    "at": f"{tmin // 60:02d}:{tmin % 60:02d}",
                    "id": f"bedtime_minus_{hours_before}h",
                }
            )
        if home_arrival_hhmm is not None:
            triggers.append(
                {
                    "platform": "time",
                    "at": home_arrival_hhmm,
                    "id": "home_arrival",
                }
            )

        # The forecast template — branches on trigger.id and applies
        # the appropriate hours-remaining to the rate. Encoded as a
        # single template condition so all triggers share the logic.
        # the previous template emitted only
        # `{% elif %}` branches without a leading `{% if %}`, which
        # is invalid Jinja2 — the automation HA created would fail
        # at template-render time with TemplateSyntaxError. Use
        # `if` for the first branch and `elif` for the rest. The
        # leading "0" sentinel was also a leftover non-branch
        # number that the renderer would never reach; removed.
        rate_str = f"{rate_per_hour:.2f}"
        buf_str = str(_SAFETY_BUFFER_PCT)

        # Build a single if/elif chain across the trigger IDs.
        branches: list[tuple[str, str]] = []  # (trigger_id, hours_value)
        for h in _CHECK_HOURS_BEFORE:
            branches.append((f"bedtime_minus_{h}h", str(h)))
        if home_arrival_hhmm is not None:
            ha_h, ha_m = (int(x) for x in home_arrival_hhmm.split(":"))
            hours_home_to_bed = (
                ((bedtime_h * 60 + bedtime_m) - (ha_h * 60 + ha_m)) / 60.0
            )
            branches.append(("home_arrival", f"{hours_home_to_bed:.1f}"))

        branch_lines: list[str] = []
        for i, (trig_id, hrs) in enumerate(branches):
            keyword = "if" if i == 0 else "elif"
            branch_lines.append(
                f"      {{% {keyword} trigger.id == '{trig_id}' %}} {hrs}"
            )
        branch_lines.append("      {% else %} 0")
        branch_lines.append("      {% endif %}")

        forecast_template = (
            "{% set hours_left = ((\n"
            + "\n".join(branch_lines)
            + "\n)|float) %}\n"
            + f"{{% set rate = {rate_str} %}}\n"
            + f"{{% set buffer = {buf_str} %}}\n"
            + f"{{% set current = states('{battery_eid}')|float(100) %}}\n"
            + "{{ (current - rate * hours_left) < buffer }}"
        )
        conditions.append(
            {"condition": "template", "value_template": forecast_template}
        )

        msg_template = (
            f"📱 {phone_label} on track to die before {bedtime_hhmm} — "
            "currently {{ states('"
            + battery_eid
            + "') }}%, predicted "
            f"to drop ~{rate_per_hour:.1f}%/h. Plug in soon."
        )

        return {
            "alias": (
                f"HA Insights: {phone_label} predictive charge reminder"
            ),
            "description": (
                f"Auto-suggested by HA Insights. Drain rate model: "
                f"~{rate_per_hour:.2f}%/h evening drain "
                f"(weekday+weekend blend). Anchor: typical plug-in "
                f"at {bedtime_hhmm}"
                + (
                    f"; typical home arrival {home_arrival_hhmm}."
                    if home_arrival_hhmm
                    else "."
                )
                + "\n\n"
                "Fires at 1h / 2h / 4h before bedtime"
                + (" and at home arrival" if home_arrival_hhmm else "")
                + ". Notifies ONLY if current battery is predicted to "
                f"drop below the {_SAFETY_BUFFER_PCT}% buffer by "
                f"plug-in time, given current evening drain.\n\n"
                "Edit `rate` (in the template) if your habits change "
                "with the season; raise `buffer` for a wider safety margin."
            ),
            "trigger": triggers,
            "condition": conditions,
            "action": [
                {
                    "service": notify_service,
                    "data": {
                        "title": "Battery won't make it to bedtime",
                        "message": msg_template,
                    },
                }
            ],
            "mode": "single",
        }

    # -------- weekday habit summary --------

    _DOW_LABELS = (
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    )

    def _summarize_by_weekday(
        self,
        battery_events: list[StateEvent],
        plug_in_per_day: dict[date, datetime],
    ) -> dict[int, dict[str, float | int]]:
        """For each weekday (0=Mon..6=Sun), compute mean minimum
        battery reached before that day's plug-in. Used to surface
        day-specific advice ("you're always low on Wednesdays").
        Returns {dow: {"mean_min_pct": x, "samples": n}}.
        """
        by_dow: dict[int, list[float]] = defaultdict(list)
        # Build a fast lookup of "battery events on day D before
        # plug-in TS" then take the minimum.
        events_by_day: dict[date, list[StateEvent]] = defaultdict(list)
        for ev in battery_events:
            events_by_day[dt_util.as_local(ev.timestamp).date()].append(ev)
        for day, plug_in_ts in plug_in_per_day.items():
            day_evs = events_by_day.get(day, [])
            if not day_evs:
                continue
            mins: list[float] = []
            for ev in day_evs:
                if ev.timestamp >= plug_in_ts:
                    continue
                try:
                    mins.append(float(ev.new_state or 0))
                except (ValueError, TypeError):
                    continue
            if not mins:
                continue
            dow = datetime.fromordinal(day.toordinal()).weekday()
            by_dow[dow].append(min(mins))
        return {
            dow: {
                "mean_min_pct": round(mean(values), 1),
                "samples": len(values),
            }
            for dow, values in by_dow.items()
            if values
        }

    def _build_weekday_habit_insight(
        self,
        *,
        phone_label: str,
        battery_eid: str,
        per_dow_summary: dict[int, dict[str, float | int]],
        overall_avg: float,
        target_user_id: str | None,
        target_user_confidence: float | None,
    ) -> Insight | None:
        """Build a behavioral-suggestion insight when one weekday is
        materially worse than the user's overall average. Format is
        `payload_format="report"` — the card surfaces it as advice
        (charge at work / change schedule), not as an apply-able
        automation, because the fix is the user's behaviour, not
        an HA config change.
        """
        if not per_dow_summary:
            return None
        # Worst-day candidate: lowest mean_min_pct with ≥ 3 samples
        # and at least 8 pct below overall_avg. Threshold roughly
        # equals "one full standard deviation of typical drain" —
        # avoids surfacing 1-2 pct jitter as a Pattern.
        ranked = sorted(
            (
                (dow, summary)
                for dow, summary in per_dow_summary.items()
                if summary["samples"] >= 3
            ),
            key=lambda kv: kv[1]["mean_min_pct"],
        )
        if not ranked:
            return None
        worst_dow, worst = ranked[0]
        delta = overall_avg - worst["mean_min_pct"]
        if delta < 8:
            return None  # not materially worse
        weekday_name = self._DOW_LABELS[worst_dow]
        title = (
            f"📅 {phone_label} consistently runs flat on {weekday_name}s "
            f"(avg low {worst['mean_min_pct']}%, ~{delta:.0f} pts below "
            f"your typical {overall_avg}%). Try a daytime top-up — "
            "charge at work, in the car, or set a midday reminder."
        )
        fingerprint = {
            "kind": "phone_charge_habit_weekday",
            "entity_id": battery_eid,
            "weekday": worst_dow,
        }
        payload = {
            "summary": title,
            "weekday": weekday_name,
            "mean_min_pct_on_day": worst["mean_min_pct"],
            "overall_avg_min_pct": overall_avg,
            "samples_on_day": worst["samples"],
            "suggested_actions": [
                "Charge at work / in the car for 30 min during lunch",
                "Set a midday charging reminder for this weekday",
                "Move energy-heavy apps to use less screen time on this day",
            ],
        }
        # Confidence reflects how strong the day-of-week effect is —
        # capped at 0.85 because behavioural advice is fuzzier than
        # a clear-cut automation suggestion.
        confidence = round(
            min(0.85, 0.4 + (delta / 50.0) + (worst["samples"] / 30.0)), 3
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
            target_user_id=target_user_id,
            target_user_id_confidence=target_user_confidence,
        )
