"""ButtonPressHabitDetector — pair event.* firings with consequent state
changes to propose apply-able automations.

For each press of a button entity (HA's native `event.*` platform), look
at state changes on OTHER entities within `CONSEQUENT_WINDOW_SEC` (30s by
default). If the same press → consequent pair recurs reliably (5+
occurrences, 60%+ consistency), emit an AUTOMATION_PROPOSAL with a
complete YAML trigger/action block the user can apply with one click.

Example patterns this surfaces:
  - press `event.kitchen_dimmer` (single_press) → `light.kitchen` ON
    → propose: trigger on dimmer single_press, action turn_on light
  - press `event.bedroom_remote` (long_press) → switch.bedside_lamp OFF
    → propose: trigger on remote long_press, action turn_off switch
  - press `event.front_door` (unlocked) → light.entry ON
    → propose: trigger on door unlock, action turn_on entry light

**Maturity: BETA.** The cross-link inference (press → consequent within
30s) is heuristic. Some presses correlate by coincidence — a button
press followed coincidentally by sunset triggering existing automations.
The MIN_CONSISTENCY_PCT (60%) gate filters most of these, but field
testing on diverse installs is needed before promoting to STABLE.

**Native HA primitives only.** No event-bus subscriptions, no parallel
buffers, no per-integration normalizers. Reads from the existing
`state_event_buffer` which captures every `event.*` state_changed
(including the `event_type` attribute since v1.5.19). The proposed
automation YAML uses standard `platform: state` trigger + template
condition on `to_state.attributes.event_type` — portable across HA
versions.

Differs from ManualHabitDetector:
  - ManualHabit looks at the entity the user CHANGES (light, switch).
  - ButtonPressHabit looks at the entity the user PRESSES (event.*)
    and finds what they're trying to make happen.
  - ManualHabit emits time-of-day automations ("at 17:30 turn on X").
  - ButtonPressHabit emits event-triggered automations ("when button
    pressed, do Y").

Differs from CooccurrenceDetector:
  - Cooccurrence is a generic A→B pattern observer (no apply path).
  - ButtonPressHabit is dedicated to actionable button-press patterns
    and ships with the YAML builder for them.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from ..insight import Insight, InsightKind
from .base import Detector, DetectorContext, Maturity, register_detector

if TYPE_CHECKING:
    from ..observers.state_event_buffer import StateEvent

_LOGGER = logging.getLogger(__name__)

# Cross-link window. A button press's "consequence" must happen within
# this window after the press. Tradeoff:
#   - Direct binding (button event → HA automation → service call):
#     typically <500ms end-to-end on a local install
#   - Cloud-relayed action (Tuya/SmartThings/Alexa fallback): 1-5s
#   - Multi-step cascade (button → script → service chain): up to 5s
#   - Lighting transition (button → light fade-in): the FIRE of the
#     state change is immediate; the transition completion is later
#     but we observe the state-change event, not the transition end.
# 5s catches ~95% of legitimate chains while keeping coincidental
# matching rare. At 30s the per-press coincidence rate for any unrelated
# entity is ~1.7%; at 5s it drops to ~0.28%. The 60% consistency gate
# below filters surviving noise but lower window = less work for it.
_CONSEQUENT_WINDOW_SEC = 5.0
_LOOKBACK_DAYS = 14
# Minimum press → consequent pair occurrences before we'll propose.
# Below this, single accidental correlations would generate noise.
_MIN_OCCURRENCES = 5
# Of all presses with this event_type, what fraction must produce the
# same consequent? 60% means "yes this is what the button does, with
# some misses." 100% is too strict (real users sometimes press a
# button mid-action with different intent).
_MIN_CONSISTENCY = 0.60
# Domains where a state change is plausibly the user's intent. We
# don't propose pressing a button to "change a sensor reading."
_VALID_CONSEQUENT_DOMAINS: frozenset[str] = frozenset({
    "light", "switch", "fan", "input_boolean", "lock", "cover",
    "climate", "media_player", "vacuum", "scene", "script",
    "select", "number", "input_select", "input_number",
    "automation",  # firing existing automations is a common pattern
})
# State values we won't propose as a target (transitional / unknown).
_TRANSIENT_STATES: frozenset[str] = frozenset({
    "unavailable", "unknown", "none", "",
})


@register_detector
class ButtonPressHabitDetector(Detector):
    """Detect press → consequent patterns from HA event.* entities."""

    name = "button_press_habit"
    kind = InsightKind.AUTOMATION_PROPOSAL
    requires_recorder = False
    maturity = Maturity.BETA  # new in v1.5.21 / v1.6 Phase 3

    async def scan(self, ctx: DetectorContext) -> list[Insight]:
        if ctx.event_buffer is None:
            return []

        cutoff = datetime.now(tz=UTC) - timedelta(days=_LOOKBACK_DAYS)

        # Phase A: index event.* firings by (entity_id, event_type).
        # Only entities that actually carry an event_type attribute
        # (Phase 1 capture) — older HA versions or non-event-platform
        # entities silently skip.
        firings: dict[tuple[str, str], list[StateEvent]] = defaultdict(list)
        for ev in ctx.event_buffer.query(since=cutoff):
            if ev.domain != "event":
                continue
            if not ev.event_type:
                continue
            firings[(ev.entity_id, ev.event_type)].append(ev)

        if not firings:
            return []

        # Phase B: load ALL post-cutoff events ONCE (already
        # filtered by the buffer's per-area / blocked logic) so we
        # can window-scan them per firing. O(F + S) where F = firings,
        # S = all events post-cutoff. With 14d of events and typical
        # button-press rates, F is small (~dozens to hundreds), so
        # the per-firing window scan is cheap.
        all_events_sorted = sorted(
            ctx.event_buffer.query(since=cutoff),
            key=lambda e: e.timestamp,
        )
        # Pre-compute timestamp index for binary-search windowing.
        all_timestamps = [e.timestamp for e in all_events_sorted]

        # Phase C: for each firing, find state changes within
        # CONSEQUENT_WINDOW_SEC. Tally by (consequent_eid,
        # consequent_state). Skip the firing entity itself.
        # Key = (event_eid, event_type, consequent_eid, consequent_state)
        pairs: dict[tuple[str, str, str, str], list[float]] = defaultdict(
            list
        )

        from bisect import bisect_left

        for (event_eid, event_type), event_firings in firings.items():
            if len(event_firings) < _MIN_OCCURRENCES:
                # Not enough presses to propose anything — skip the
                # expensive consequent scan.
                continue

            for firing in event_firings:
                window_end = firing.timestamp + timedelta(
                    seconds=_CONSEQUENT_WINDOW_SEC
                )
                # Binary-search the first event AFTER the firing
                start = bisect_left(all_timestamps, firing.timestamp)
                # Step forward until we exit the window
                for idx in range(start, len(all_events_sorted)):
                    ev = all_events_sorted[idx]
                    if ev.timestamp > window_end:
                        break
                    if ev.timestamp <= firing.timestamp:
                        # Same-instant or earlier — skip (sorted but
                        # bisect_left can land on equal timestamps)
                        continue
                    if ev.entity_id == event_eid:
                        continue
                    if ev.domain not in _VALID_CONSEQUENT_DOMAINS:
                        continue
                    if not ev.new_state or ev.new_state in _TRANSIENT_STATES:
                        continue
                    # No-op transitions are not "consequences"
                    if ev.new_state == ev.old_state:
                        continue
                    delay_sec = (
                        ev.timestamp - firing.timestamp
                    ).total_seconds()
                    pairs[
                        (event_eid, event_type, ev.entity_id, ev.new_state)
                    ].append(delay_sec)

        # Phase D: filter pairs by occurrence count + consistency.
        insights: list[Insight] = []
        for key, delays in pairs.items():
            event_eid, event_type, consequent_eid, consequent_state = key
            occurrences = len(delays)
            if occurrences < _MIN_OCCURRENCES:
                continue
            # Consistency = pairs / total firings of this event_type.
            # A button you press 20 times that produces this same
            # consequent 18 times is 90% consistent (strong signal).
            # 8 times is 40% (weak, probably coincidental).
            total_firings = len(firings[(event_eid, event_type)])
            if total_firings == 0:
                continue
            consistency = occurrences / total_firings
            if consistency < _MIN_CONSISTENCY:
                continue
            insight = self._build_insight(
                event_eid=event_eid,
                event_type=event_type,
                consequent_eid=consequent_eid,
                consequent_state=consequent_state,
                occurrences=occurrences,
                total_firings=total_firings,
                consistency=consistency,
                delays=delays,
                ctx=ctx,
            )
            if insight is not None:
                insights.append(insight)

        return insights

    def _build_insight(
        self,
        *,
        event_eid: str,
        event_type: str,
        consequent_eid: str,
        consequent_state: str,
        occurrences: int,
        total_firings: int,
        consistency: float,
        delays: list[float],
        ctx: DetectorContext,
    ) -> Insight | None:
        # Median delay for the proposed automation's mental model
        # (50th percentile is more robust than mean for skewed
        # button-press distributions).
        sorted_delays = sorted(delays)
        median_delay = sorted_delays[len(sorted_delays) // 2]

        # Skip if an existing automation already handles this exact
        # press → consequent pair. Detected via the conflict scanner
        # or the simple "is this consequent_eid in any automation
        # that triggers on event_eid" check.
        if self._already_automated(
            event_eid, event_type, consequent_eid, ctx
        ):
            return None

        # Confidence: blend consistency (60-100%) with sample size
        # (5+ occurrences saturates at ~20). Capped at 0.92 because
        # this is a press-to-action inference, not a direct user
        # statement — leaves room for Refine to add nuance.
        sample_factor = min(1.0, occurrences / 20.0)
        confidence = round(
            min(0.92, consistency * 0.7 + sample_factor * 0.25),
            3,
        )

        # Build the trigger/action YAML.
        automation_yaml = self._build_automation_yaml(
            event_eid=event_eid,
            event_type=event_type,
            consequent_eid=consequent_eid,
            consequent_state=consequent_state,
        )
        if automation_yaml is None:
            return None  # consequent domain not buildable yet

        title = (
            f"Pressing {event_eid} ({event_type}) → {consequent_eid} "
            f"becomes {consequent_state} {occurrences}/{total_firings} "
            f"times (~{median_delay:.1f}s delay). Automate it?"
        )

        fingerprint: dict[str, Any] = {
            "kind": "button_press_habit",
            "event_entity_id": event_eid,
            "event_type": event_type,
            "consequent_entity_id": consequent_eid,
            "consequent_state": consequent_state,
        }

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
            payload=automation_yaml,
            payload_format="automation",
            explanation=(
                f"Observed pattern: every time {event_eid} fires "
                f"'{event_type}', {consequent_eid} transitions to "
                f"{consequent_state} within ~{median_delay:.0f}s. "
                f"Saw this {occurrences} of {total_firings} button "
                f"presses ({int(consistency * 100)}% consistency)."
            ),
            created_at=datetime.now(tz=UTC),
        )

    def _build_automation_yaml(
        self,
        *,
        event_eid: str,
        event_type: str,
        consequent_eid: str,
        consequent_state: str,
    ) -> dict[str, Any] | None:
        """Construct a complete automation block. Trigger is a state
        change on the event entity, gated by a template condition on
        the event_type attribute (portable across HA versions).
        Action is the standard service-call for the consequent
        domain."""
        # Map (domain, state) → service. Conservative — only domains
        # where the on/off mapping is unambiguous. Climate, media_player,
        # and select land in v2.
        domain = consequent_eid.split(".", 1)[0]
        service_map: dict[str, dict[str, str]] = {
            "light": {"on": "light.turn_on", "off": "light.turn_off"},
            "switch": {"on": "switch.turn_on", "off": "switch.turn_off"},
            "fan": {"on": "fan.turn_on", "off": "fan.turn_off"},
            "input_boolean": {
                "on": "input_boolean.turn_on",
                "off": "input_boolean.turn_off",
            },
            "lock": {"locked": "lock.lock", "unlocked": "lock.unlock"},
            "cover": {
                "open": "cover.open_cover",
                "closed": "cover.close_cover",
            },
            "scene": {},  # scene.turn_on is the universal service
            "script": {},  # script.{name} or script.turn_on
        }
        if domain == "scene":
            service = "scene.turn_on"
        elif domain == "script":
            service = "script.turn_on"
        elif domain in service_map and consequent_state in service_map[domain]:
            service = service_map[domain][consequent_state]
        else:
            # Unknown mapping — punt rather than emit broken YAML
            return None

        alias = (
            f"When {event_eid} ({event_type}) → "
            f"{consequent_eid} {consequent_state}"
        )
        # 280-char max for HA's automation alias field (legacy limit
        # in some integrations); truncate if needed.
        if len(alias) > 250:
            alias = alias[:247] + "..."

        return {
            "alias": alias,
            "trigger": [
                {
                    "platform": "state",
                    "entity_id": event_eid,
                },
            ],
            "condition": [
                {
                    "condition": "template",
                    # event.* entities carry the fired event type in
                    # attributes; check it inside the template so we
                    # don't fire on attribute-only updates that
                    # weren't actually a press.
                    "value_template": (
                        "{{ trigger.to_state is not none and "
                        f"trigger.to_state.attributes.event_type "
                        f"== '{event_type}' }}"
                    ),
                },
            ],
            "action": [
                {
                    "service": service,
                    "target": {"entity_id": consequent_eid},
                },
            ],
            "mode": "single",
        }

    def _already_automated(
        self,
        event_eid: str,
        event_type: str,
        consequent_eid: str,
        ctx: DetectorContext,
    ) -> bool:
        """Cheap pre-check: skip if any existing automation has BOTH
        a trigger on `event_eid` AND an action targeting
        `consequent_eid`. We don't bother matching event_type
        precisely (the user might already have ONE automation for
        single_press; we don't want to suggest a duplicate that
        differs only in event_type)."""
        automations = ctx.existing_automations or []
        for auto in automations:
            triggers = auto.get("trigger") or []
            if not isinstance(triggers, list):
                triggers = [triggers]
            triggers_match = any(
                isinstance(t, dict)
                and t.get("entity_id") == event_eid
                for t in triggers
            )
            if not triggers_match:
                continue
            actions = auto.get("action") or []
            if not isinstance(actions, list):
                actions = [actions]
            for a in actions:
                if not isinstance(a, dict):
                    continue
                target = a.get("target")
                if isinstance(target, dict):
                    tid = target.get("entity_id")
                    if tid == consequent_eid:
                        return True
                    if isinstance(tid, list) and consequent_eid in tid:
                        return True
                if a.get("entity_id") == consequent_eid:
                    return True
        return False


__all__ = ["ButtonPressHabitDetector"]
