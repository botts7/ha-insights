"""Habitual override detection — user reverses an automation within T minutes.

When an automation sets `light.hallway` to `on` and the user manually
switches it `off` two minutes later, ONCE that's noise. THREE TIMES across
14 days, on different days, is a habit. The automation likely needs
revising — the user is consistently correcting its behavior.

This is the same "user does X after automation Y within T minutes" signal
that v1.5.45's coactivation lib already captures, but with two key
differences:

  1. Anchor = automation-driven state change (event.context_parent_id is
     not None). v1.5.45 used user-supplied required_entity_ids.
  2. Window is **forward-only**. We don't care about manual events
     BEFORE the automation fires. The asymmetric window is one-sided
     `[anchor_ts, anchor_ts + window]`.

The candidate event must:
  - Be on the SAME entity as the anchor (so we're observing a reversal,
    not a coincidence — a manual `media_player` change after an
    automation flipped a light isn't relevant here).
  - Be a MANUAL event (per the v1.5.45 manual filter — user_id set or
    no HA-side context at all).
  - Result in a DIFFERENT new_state than the automation set
    (`automation set ON, user set OFF` — a clear reversal).

Zero HA imports. Pure function operating on StateEvent-shaped objects.
Used by detectors/habitual_override.py.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Protocol


class _EventLike(Protocol):
    """Duck-typed StateEvent shape — only the fields we read."""

    timestamp: datetime
    entity_id: str
    new_state: str | None
    context_user_id: str | None
    context_parent_id: str | None
    from_bootstrap: bool


@dataclass(frozen=True)
class OverrideStat:
    """One detected habitual override pattern.

    entity_id: the entity being overridden
    automation_state: the state the automation kept setting it to
    manual_state: the state the user kept changing it to (different
                  from automation_state by definition — equal-state
                  no-ops are excluded)
    days_count: distinct calendar days the pattern occurred
    median_lag_seconds: median delay between automation fire and user
                       reversal across all observed occurrences
    sample_pairs: count of (automation, user-reversal) pairs observed
    """

    entity_id: str
    automation_state: str
    manual_state: str
    days_count: int
    median_lag_seconds: float
    sample_pairs: int


def _is_manual(ev: _EventLike) -> bool:
    """Same classification as v1.5.45 lib/coactivation._is_manual.

    Manual = HA UI / mobile / voice (user_id set) OR no HA-side context
    at all (physical switch / external). Excludes events with a
    context_parent_id (children of automation chains).
    """
    if ev.context_user_id is not None:
        return True
    if ev.context_parent_id is None:
        return True
    return False


def _is_automation_driven(ev: _EventLike) -> bool:
    """Automation-driven event: has a parent context (chain child) AND
    no user_id (a user-triggered automation via the UI still has the
    user_id, but the actions it fires are the parent's grandchildren —
    we want pure automation-runtime events, not user-triggered runs).

    The conservative classifier:
      - context_parent_id is not None → parent chain exists → automation
      - context_user_id is None → no human originator

    Both conditions together filter out:
      - Manual events (user_id set, no parent_id)
      - User-triggered automations (user_id set AND parent_id set)
      - Bootstrap/external (no parent, no user)

    Leaving only: pure automation-runtime state changes.
    """
    return ev.context_parent_id is not None and ev.context_user_id is None


def find_habitual_overrides(
    events: Iterable[_EventLike],
    *,
    window_seconds: float = 120.0,
    lookback_days: int = 14,
    min_days: int = 3,
    now: datetime | None = None,
) -> list[OverrideStat]:
    """Return habitual override patterns found in the event buffer.

    Algorithm:
      1. Split events into automation-driven (anchors) and manual
         (candidates), excluding bootstrap fan-out and events older
         than `lookback_days`.
      2. For each anchor at time T on entity E with new_state S_auto,
         walk candidates on the SAME entity E in the forward window
         [T, T + window_seconds]. If the first such candidate has
         new_state != S_auto, record one (entity, S_auto, S_manual,
         day, lag) tuple.
      3. Group tuples by (entity, S_auto, S_manual). Count distinct
         days. If >= `min_days`, emit an OverrideStat.

    Args:
      events: any iterable of StateEvent-shaped objects.
      window_seconds: forward window after each automation fire.
        Default 120 (two minutes) — long enough to capture "user
        notices and undoes", short enough that an unrelated manual
        action 10 minutes later doesn't get pinned to the automation.
      lookback_days: only events from the last N days count. Default
        14 matches the EventBuffer's default retention.
      min_days: floor for the days_count signal. Default 3 — below
        this, noise dominates and we'd false-positive every install.
      now: clock injection for tests.

    Returns:
      List of OverrideStat ordered by days_count descending (strongest
      pattern first), then by entity_id ascending for stable test
      output.
    """
    if now is None:
        now = datetime.now(tz=UTC)
    cutoff = now - timedelta(days=lookback_days)
    window = timedelta(seconds=window_seconds)

    # Per-entity sorted lists of (timestamp, new_state) for anchors and
    # candidates. Grouping by entity is the load-bearing optimization —
    # an override is always same-entity, so we never need to cross-
    # check entity boundaries.
    anchors_by_entity: dict[str, list[tuple[datetime, str]]] = defaultdict(list)
    candidates_by_entity: dict[str, list[tuple[datetime, str]]] = defaultdict(list)

    for ev in events:
        if ev.from_bootstrap:
            continue
        if ev.timestamp < cutoff:
            continue
        if ev.new_state is None:
            continue
        if _is_automation_driven(ev):
            anchors_by_entity[ev.entity_id].append((ev.timestamp, ev.new_state))
        elif _is_manual(ev):
            candidates_by_entity[ev.entity_id].append(
                (ev.timestamp, ev.new_state)
            )

    # (entity, auto_state, manual_state) -> {distinct dates} + lag list
    pattern_days: dict[tuple[str, str, str], set[date]] = defaultdict(set)
    pattern_lags: dict[tuple[str, str, str], list[float]] = defaultdict(list)

    for entity_id, anchors in anchors_by_entity.items():
        candidates = candidates_by_entity.get(entity_id)
        if not candidates:
            continue
        anchors.sort(key=lambda t: t[0])
        candidates.sort(key=lambda t: t[0])

        # Two-pointer: for each anchor, find the FIRST candidate in
        # the forward window. Candidates before the anchor or after
        # the window expires are skipped. One reversal per anchor
        # (the first manual override is the one we count — later
        # manual changes within the same window are likely
        # corrections of the user's own first reversal).
        j = 0
        for anchor_ts, anchor_state in anchors:
            hi = anchor_ts + window
            while j < len(candidates) and candidates[j][0] < anchor_ts:
                j += 1
            k = j
            while k < len(candidates) and candidates[k][0] <= hi:
                cand_ts, cand_state = candidates[k]
                if cand_state != anchor_state:
                    key = (entity_id, anchor_state, cand_state)
                    pattern_days[key].add(cand_ts.date())
                    pattern_lags[key].append(
                        (cand_ts - anchor_ts).total_seconds()
                    )
                    break  # one reversal per anchor
                k += 1

    results: list[OverrideStat] = []
    for (entity_id, auto_state, manual_state), days in pattern_days.items():
        if len(days) < min_days:
            continue
        lags = sorted(pattern_lags[(entity_id, auto_state, manual_state)])
        median = lags[len(lags) // 2] if lags else 0.0
        results.append(
            OverrideStat(
                entity_id=entity_id,
                automation_state=auto_state,
                manual_state=manual_state,
                days_count=len(days),
                median_lag_seconds=median,
                sample_pairs=len(lags),
            )
        )

    # Strongest pattern first, ties broken alphabetically by entity
    # for deterministic test output.
    results.sort(key=lambda r: (-r.days_count, r.entity_id))
    return results


__all__ = ["OverrideStat", "find_habitual_overrides"]
