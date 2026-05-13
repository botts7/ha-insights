"""ManualHabitDetector — surface manual habits the user should automate.

The Tier-1 differentiator detector. Where StreakDetector flags an
emerging routine ("light X → on, 4 days in a row at ~17:30"), this one
goes the next step:

  1. The state changes are MANUAL (HA's event context carries a
     user_id, meaning a human pressed a button / spoke / tapped the
     app — not an automation, not a system update).
  2. NO existing automation already handles this pattern.
  3. We can build a complete, apply-able automation YAML for it.

The output is a high-confidence AUTOMATION_PROPOSAL with
`payload_format="automation"` — the existing apply pipeline writes it
straight to automations.yaml. Confidence is intentionally high (≥ 0.85)
because we're suggesting a write, not just an observation.

Differs from StreakDetector:
  * Streak emits even when an automation already exists (with a
    "🔁 already automated" pill). Manual habit SKIPS those, so the
    user only sees genuinely-new automation opportunities.
  * Streak fires at 3+ days. Manual habit requires 5+ days at a tight
    time bucket (≤ 20 min stddev).
  * Streak's payload is informational. Manual habit's payload is a
    complete `automation:` block.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from itertools import pairwise
from typing import TYPE_CHECKING, Any

from homeassistant.util import dt as dt_util

from ..insight import Insight, InsightKind
from .base import Detector, DetectorContext, register_detector

if TYPE_CHECKING:
    from ..observers.state_event_buffer import StateEvent


# Tighter bar than StreakDetector since this detector proposes a write.
_MIN_MANUAL_DAYS = 5
_TIME_STDDEV_MAX_MIN = 20.0
_LOOKBACK_DAYS = 14
# A "manual" event is one where HA's context.user_id is non-None.
# Automation actions and integration polling have user_id = None.

# Domain → (state-value → service) mapping. Drives the auto-generated
# automation action. Conservative: only domains where the binary
# on/off mapping is obvious. Climate / media_player suggest patterns
# but their actions need more context (mode, source) so we skip them
# in the MVP; v2 can add per-domain custom builders.
_DOMAIN_SERVICE_MAP: dict[str, dict[str, str]] = {
    "light": {"on": "light.turn_on", "off": "light.turn_off"},
    "switch": {"on": "switch.turn_on", "off": "switch.turn_off"},
    "fan": {"on": "fan.turn_on", "off": "fan.turn_off"},
    "input_boolean": {
        "on": "input_boolean.turn_on",
        "off": "input_boolean.turn_off",
    },
    "lock": {"locked": "lock.lock", "unlocked": "lock.unlock"},
    "cover": {"open": "cover.open_cover", "closed": "cover.close_cover"},
}


@register_detector
class ManualHabitDetector(Detector):
    """Detect manual user habits + suggest automations to handle them."""

    name = "manual_habit"
    kind = InsightKind.AUTOMATION_PROPOSAL
    requires_recorder = False

    async def scan(self, ctx: DetectorContext) -> list[Insight]:
        if ctx.event_buffer is None:
            return []

        # Filter buffer to MANUAL events only. Bucket by (entity, target_state).
        cutoff = datetime.now(tz=UTC) - timedelta(days=_LOOKBACK_DAYS)
        groups: dict[tuple[str, str], list["StateEvent"]] = defaultdict(list)
        for ev in ctx.event_buffer.query(since=cutoff):
            if not self._is_candidate_event(ev):
                continue
            assert ev.new_state is not None
            groups[(ev.entity_id, ev.new_state)].append(ev)

        # Build the set of (entity_id, normalized-time-bucket) signatures
        # that EXISTING automations already handle. Skip any group whose
        # signature matches — the user already covered that case.
        already_handled = self._signatures_of_existing_automations(ctx)

        insights: list[Insight] = []
        for (entity_id, new_state), events in groups.items():
            insight = self._evaluate_group(
                entity_id, new_state, events, already_handled
            )
            if insight is not None:
                insights.append(insight)
        return insights

    # -------- candidate filter --------

    def _is_candidate_event(self, ev: "StateEvent") -> bool:
        if ev.new_state is None or ev.new_state == ev.old_state:
            return False
        # Manual-only. context_user_id None = automation / system change.
        if ev.context_user_id is None:
            return False
        if ev.domain in self.domains_default_blocked:
            return False
        if ev.domain not in _DOMAIN_SERVICE_MAP:
            return False
        if ev.new_state not in _DOMAIN_SERVICE_MAP[ev.domain]:
            return False
        return True

    # -------- evaluation --------

    def _evaluate_group(
        self,
        entity_id: str,
        new_state: str,
        events: list["StateEvent"],
        already_handled: set[tuple[str, str, int]],
    ) -> Insight | None:
        # First-event-per-day (local time) clustering.
        per_day: dict[date, datetime] = {}
        for ev in events:
            local_ts = dt_util.as_local(ev.timestamp)
            day = local_ts.date()
            if day not in per_day or ev.timestamp < per_day[day]:
                per_day[day] = ev.timestamp

        if len(per_day) < _MIN_MANUAL_DAYS:
            return None

        # Longest consecutive-day run.
        sorted_days = sorted(per_day.keys())
        longest_run: list[date] = []
        current_run: list[date] = [sorted_days[0]]
        for prev, cur in pairwise(sorted_days):
            if (cur - prev).days == 1:
                current_run.append(cur)
            else:
                if len(current_run) > len(longest_run):
                    longest_run = current_run
                current_run = [cur]
        if len(current_run) > len(longest_run):
            longest_run = current_run

        if len(longest_run) < _MIN_MANUAL_DAYS:
            return None

        # Time-of-day clustering (LOCAL TIME — buffer is UTC).
        streak_times_local = [dt_util.as_local(per_day[d]) for d in longest_run]
        minutes_past_midnight = [
            t.hour * 60 + t.minute + t.second / 60.0
            for t in streak_times_local
        ]
        avg = sum(minutes_past_midnight) / len(minutes_past_midnight)
        stddev = math.sqrt(
            sum((m - avg) ** 2 for m in minutes_past_midnight)
            / len(minutes_past_midnight)
        )
        if stddev > _TIME_STDDEV_MAX_MIN:
            return None

        avg_minute = round(avg)
        avg_hour = avg_minute // 60
        avg_min_within = avg_minute % 60
        avg_time_str = time(hour=avg_hour, minute=avg_min_within).strftime(
            "%H:%M:%S"
        )

        # If a current automation already handles (entity, state, ~time),
        # we have nothing to offer. Skip.
        bucket = self._time_bucket(avg_hour, avg_min_within)
        if (entity_id, new_state, bucket) in already_handled:
            return None

        # Build the apply-able automation YAML.
        automation = self._build_automation_yaml(
            entity_id, new_state, avg_time_str, len(longest_run), per_day
        )

        confidence = round(
            min(1.0, len(longest_run) / 7.0)
            * max(0.0, 1.0 - stddev / 30.0),
            3,
        )

        title = (
            f"You manually set {entity_id} → {new_state} "
            f"{len(longest_run)} days in a row at ~{avg_time_str[:5]}. "
            "Automate it?"
        )

        fingerprint: dict[str, Any] = {
            "entity_id": entity_id,
            "new_state": new_state,
            "time_bucket": bucket,
            "kind": "manual_habit",
        }

        payload = {
            **automation,
            "_manual_habit": {
                "entity_id": entity_id,
                "new_state": new_state,
                "days_count": len(longest_run),
                "avg_time": avg_time_str,
                "time_stddev_min": round(stddev, 1),
                "first_day": longest_run[0].isoformat(),
                "last_day": longest_run[-1].isoformat(),
            },
        }

        return Insight(
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
        )

    # -------- automation YAML builder --------

    def _build_automation_yaml(
        self,
        entity_id: str,
        target_state: str,
        avg_time: str,
        days_count: int,
        per_day: dict[date, datetime],
    ) -> dict[str, Any]:
        domain = entity_id.split(".", 1)[0]
        service = _DOMAIN_SERVICE_MAP[domain][target_state]
        # Truncate avg_time to HH:MM so HA's `time:` platform accepts it.
        hhmm = avg_time[:5]
        alias = (
            f"HA Insights: {entity_id} → {target_state} @ {hhmm}"
        )
        return {
            "alias": alias,
            "description": (
                f"Auto-suggested by HA Insights: you manually set "
                f"{entity_id} → {target_state} on {days_count} consecutive "
                f"days at ~{hhmm}. This automation fires at that time. "
                "Edit / disable / delete freely."
            ),
            "trigger": [{"platform": "time", "at": hhmm}],
            "condition": [],
            "action": [
                {
                    "service": service,
                    "target": {"entity_id": entity_id},
                }
            ],
            "mode": "single",
        }

    # -------- existing-automation cross-reference --------

    def _signatures_of_existing_automations(
        self, ctx: DetectorContext
    ) -> set[tuple[str, str, int]]:
        """Return set of (entity_id, target_state, time_bucket) for
        every (time-trigger → entity-action) shape already covered by
        the user's automations. Used to skip suggesting duplicates."""
        sigs: set[tuple[str, str, int]] = set()
        existing = ctx.existing_automations or []
        for auto in existing:
            triggers = auto.get("trigger") or []
            if isinstance(triggers, dict):
                triggers = [triggers]
            time_triggers: list[str] = []
            for trig in triggers:
                if not isinstance(trig, dict):
                    continue
                if trig.get("platform") != "time":
                    continue
                at = trig.get("at")
                if isinstance(at, str):
                    time_triggers.append(at)
                elif isinstance(at, list):
                    time_triggers.extend(t for t in at if isinstance(t, str))
            if not time_triggers:
                continue
            actions = auto.get("action") or []
            if isinstance(actions, dict):
                actions = [actions]
            for act in actions:
                if not isinstance(act, dict):
                    continue
                svc = act.get("service") or ""
                if not isinstance(svc, str) or "." not in svc:
                    continue
                try:
                    svc_domain, svc_call = svc.split(".", 1)
                except ValueError:
                    continue
                # Reverse the service → target-state mapping
                state_map = _DOMAIN_SERVICE_MAP.get(svc_domain) or {}
                inferred_state: str | None = None
                for state_val, mapped_svc in state_map.items():
                    if mapped_svc == svc:
                        inferred_state = state_val
                        break
                if inferred_state is None:
                    continue
                target = act.get("target") or {}
                eids: list[str] = []
                if isinstance(target.get("entity_id"), str):
                    eids.append(target["entity_id"])
                elif isinstance(target.get("entity_id"), list):
                    eids.extend(
                        e for e in target["entity_id"] if isinstance(e, str)
                    )
                # entity_id directly on the service call (legacy form)
                if isinstance(act.get("entity_id"), str):
                    eids.append(act["entity_id"])
                elif isinstance(act.get("entity_id"), list):
                    eids.extend(
                        e for e in act["entity_id"] if isinstance(e, str)
                    )
                for eid in eids:
                    for ttrig in time_triggers:
                        bucket = self._bucket_from_str(ttrig)
                        if bucket is not None:
                            sigs.add((eid, inferred_state, bucket))
        return sigs

    @staticmethod
    def _time_bucket(hour: int, minute: int) -> int:
        """Coarse bucket: 30-minute granularity. So `17:35` and `17:52`
        share a bucket → consider it the same time-of-day."""
        return hour * 2 + (1 if minute >= 30 else 0)

    def _bucket_from_str(self, hhmm: str) -> int | None:
        try:
            h, m = hhmm.split(":")[:2]
            return self._time_bucket(int(h), int(m))
        except (ValueError, IndexError):
            return None
