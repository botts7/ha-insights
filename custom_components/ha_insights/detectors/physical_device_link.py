"""PhysicalDeviceLinkDetector — same-physical-device detection by
event-stream correlation.

The v1.10.3 static dedup catches duplicate entities by registry
identifiers (MAC, Bluetooth, Zigbee IEEE, IP, identifier overlap,
mfr+model+via_device). That covers maybe 50–70% of typical
duplicates. The rest hide:

- Govee Cloud + Govee BLE — different internal device IDs in each
  integration; no shared identifier reaches HA
- Aqara via Zigbee2MQTT + same device via ZHA during a migration
- HACS custom component + manufacturer's official integration
  pointed at the same hardware
- ESPHome reflash of a former cloud device, both entries lingering

For those, the only signal is the values themselves. If two
temperature sensors report identical (or near-identical) readings
over a week — r > 0.95 with hundreds of aligned samples — they're
almost certainly the same physical sensor seen through two
integrations.

## What this detector emits

`InsightKind.PATTERN_OBSERVATION` — "FYI, these N entities look
like the same physical device." NOT an automation proposal; nothing
to "apply." The user reads it and decides whether to:
  - Mark the duplicate's device as "managed externally" (v1.7.7
    flag) so its insights get suppressed
  - Remove the duplicate integration
  - Just acknowledge the dedup and move on

## Maturity: BETA

Correlation thresholds need real-install calibration before
promoting to STABLE. r > 0.95 over a week is a strong signal but
not infallible — two thermostats in the same room can correlate
that highly, two outdoor sensors on the same side of the house
likewise.

## Cost / pre-filtering

Per scan we evaluate O(N²) pairs within each `device_class`.
Aggressive pre-filtering keeps this tractable:

  - Same `device_class` only (we wouldn't compare a temp sensor to
    a humidity sensor, even if they happen to correlate)
  - Same-`device_id` pairs skipped (HA already groups those)
  - Pairs already flagged by static dedup (v1.10.3) skipped — no
    point piling on a stronger static signal with a weaker
    correlation finding
  - Both entities must have ≥ MIN_EVENTS_PER_ENTITY events in the
    lookback window
  - Both entities must have ≥ MIN_VARIANCE in their values
    (a battery sensor stuck at 100% will "correlate" with anything)

On a 100-entity install with 30 temp + 20 humid + 50 other, that's
30² + 20² + … ≈ 1300 pairs evaluated, each with O(bins) compute
where bins ≈ 1000 for a 7-day lookback at 10-min bins. ~1M ops
total — well within the per-detector budget.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from ..insight import Insight, InsightKind
from ..lib.correlation_primitives import (
    MIN_SAMPLES_FOR_CORR,
    CorrelationResult,
    time_aligned_correlation,
)
from .base import Detector, DetectorContext, Maturity, register_detector

if TYPE_CHECKING:
    pass


# Lookback window. Long enough to capture meaningful diurnal
# correlation (24h+) but short enough that recent install changes
# don't poison the result. 7 days is the sweet spot — same as
# StateShiftDetector's pre-shift window.
_LOOKBACK_DAYS = 7

# Bin size for time-aligned correlation. 10 min absorbs integration-
# cadence differences (one polls at 30s, another at 5min) while
# preserving enough resolution to catch real coupling.
_BIN_SIZE_SECONDS = 600.0

# Threshold for emitting an insight. r > 0.95 is the "implausibly
# high" threshold — two real-world sensors at the same location
# typically correlate r ≈ 0.85-0.92; r > 0.95 over hundreds of
# samples is almost always the same physical sensor.
_R_THRESHOLD = 0.95

# Minimum events per entity in the lookback. Below this, correlation
# is too noisy to act on.
_MIN_EVENTS_PER_ENTITY = 30

# Hard cap on insights per scan. Pathological installs (many
# duplicates) shouldn't flood the panel.
_MAX_INSIGHTS_PER_SCAN = 15

# Domains where this detector applies. Same-physical-device dedup
# only makes sense for sensors with continuous numeric values; for
# `switch` / `light` / `binary_sensor` the relevant primitive is
# timing (handled by other detectors), not value correlation.
_RELEVANT_DOMAINS: frozenset[str] = frozenset({"sensor"})


@register_detector
class PhysicalDeviceLinkDetector(Detector):
    """Detect entity pairs that look like the same physical device
    by value-stream correlation."""

    name = "physical_device_link"
    kind = InsightKind.PATTERN_OBSERVATION
    requires_recorder = False
    maturity = Maturity.BETA
    description = (
        "Spots entity pairs that produce implausibly correlated values "
        "(r > 0.95 over 7 days). The most common cause is one physical "
        "device exposed through two integrations (Tuya cloud + BLE "
        "scanner; Govee Cloud + Govee BLE; Hue Bridge + Matter bridge). "
        "Complements v1.10.3's static-identifier dedup with a "
        "behavioural signal that catches the cases registry data misses."
    )
    required_data = ("feature:event_buffer",)

    async def scan(self, ctx: DetectorContext) -> list[Insight]:
        if ctx.event_buffer is None:
            return []

        now_utc = datetime.now(tz=UTC).replace(microsecond=0)
        cutoff = now_utc - timedelta(days=_LOOKBACK_DAYS)
        start_ts = cutoff.timestamp()
        end_ts = now_utc.timestamp()

        # Collect per-entity event streams as (ts, float_value) tuples.
        # Pre-filter at collection time so we never materialize event
        # lists we can't use (saves memory on huge installs).
        by_entity: dict[str, list[tuple[float, float]]] = defaultdict(list)
        device_class_of: dict[str, str] = {}
        for ev in ctx.event_buffer.query(since=cutoff):
            domain = ev.entity_id.split(".", 1)[0] if "." in ev.entity_id else ""
            if domain not in _RELEVANT_DOMAINS:
                continue
            if ev.entity_id in ctx.blocked_entities:
                continue
            if domain in self.domains_default_blocked:
                continue
            if ev.new_state is None:
                continue
            try:
                value = float(ev.new_state)
            except (TypeError, ValueError):
                continue
            by_entity[ev.entity_id].append((ev.timestamp.timestamp(), value))

        # Group entities by device_class (read from live state attrs,
        # since the event buffer doesn't carry it). We only compare
        # within a class — temperature vs humidity correlation is
        # almost always coincidental.
        for eid in list(by_entity.keys()):
            if len(by_entity[eid]) < _MIN_EVENTS_PER_ENTITY:
                del by_entity[eid]
                continue
            state = ctx.hass.states.get(eid)
            if state is None:
                del by_entity[eid]
                continue
            dc = state.attributes.get("device_class")
            if not isinstance(dc, str):
                del by_entity[eid]
                continue
            device_class_of[eid] = dc.lower()

        by_class: dict[str, list[str]] = defaultdict(list)
        for eid, dc in device_class_of.items():
            by_class[dc].append(eid)

        # Build the set of pairs already flagged by static dedup so
        # we don't pile on. Cheap: derive from the device registry
        # connections / identifiers — same logic as the v1.10.3 lib
        # but compressed to a pair-level skip set.
        static_dedup_pairs = self._collect_static_dedup_pairs(ctx)

        insights: list[Insight] = []
        for dc, eids in by_class.items():
            if len(eids) < 2:
                continue
            # Sort for deterministic pair ordering.
            sorted_eids = sorted(eids)
            for i in range(len(sorted_eids)):
                for j in range(i + 1, len(sorted_eids)):
                    eid_a = sorted_eids[i]
                    eid_b = sorted_eids[j]
                    # Same-device_id pairs are skipped — HA already
                    # treats them as one device.
                    if self._same_device(ctx, eid_a, eid_b):
                        continue
                    # Static dedup already caught this one.
                    if (eid_a, eid_b) in static_dedup_pairs or (
                        eid_b, eid_a
                    ) in static_dedup_pairs:
                        continue
                    result = time_aligned_correlation(
                        by_entity[eid_a],
                        by_entity[eid_b],
                        bin_size_seconds=_BIN_SIZE_SECONDS,
                        start_ts=start_ts,
                        end_ts=end_ts,
                    )
                    if abs(result.r) < _R_THRESHOLD:
                        continue
                    if result.n_samples < MIN_SAMPLES_FOR_CORR:
                        continue
                    insights.append(
                        self._build_insight(
                            eid_a=eid_a,
                            eid_b=eid_b,
                            device_class=dc,
                            result=result,
                        )
                    )
                    if len(insights) >= _MAX_INSIGHTS_PER_SCAN:
                        return insights

        return insights

    def _same_device(
        self, ctx: DetectorContext, eid_a: str, eid_b: str
    ) -> bool:
        """True when both entities share a device_id in HA's
        registry. We never flag those as 'same physical device' —
        HA already groups them.

        Defensive: wraps the whole lookup in try/except because
        non-HA `hass` objects (test mocks, dev-mode shells) will
        produce confusing failures otherwise — MagicMock.async_get
        returns a child mock whose `.device_id` is also a mock that
        compares equal to itself for every entity, falsely
        suppressing every candidate pair.
        """
        try:
            from homeassistant.helpers import entity_registry as er

            e_reg = er.async_get(ctx.hass)
            a = e_reg.async_get(eid_a)
            b = e_reg.async_get(eid_b)
            if a is None or b is None:
                return False
            # Use isinstance to guard against mock objects that
            # return non-string device_ids that compare equal to
            # themselves spuriously.
            if not (
                isinstance(a.device_id, str)
                and isinstance(b.device_id, str)
            ):
                return False
            return a.device_id == b.device_id
        except (ImportError, AttributeError, TypeError):
            return False

    def _collect_static_dedup_pairs(
        self, ctx: DetectorContext
    ) -> set[tuple[str, str]]:
        """Build the (a, b) pair set that v1.10.3's static-signal
        dedup would catch. Avoids running the v1.10.3 path for every
        pair (which would query the registry inside the inner loop).

        Defensive — same reasoning as `_same_device`: non-HA hass
        objects produce confusing iteration over MagicMock attribute
        proxies that fabricate phantom pairs and over-filter."""
        try:
            from homeassistant.helpers import device_registry as dr
            from homeassistant.helpers import entity_registry as er
        except ImportError:
            return set()
        try:
            e_reg = er.async_get(ctx.hass)
            d_reg = dr.async_get(ctx.hass)
            # Validate the registry is a real registry, not a mock —
            # check that `.entities.values()` yields entries with
            # string entity_ids.
            entities_iter = e_reg.entities.values()
        except (AttributeError, TypeError):
            return set()
        by_signal: dict[tuple[str, str], list[str]] = defaultdict(list)
        try:
            for ent in entities_iter:
                if not isinstance(ent.entity_id, str):
                    return set()  # not a real registry
                if ent.device_id is None:
                    continue
                dev = d_reg.async_get(ent.device_id)
                if dev is None:
                    continue
                for ct, cv in (dev.connections or set()):
                    if isinstance(ct, str) and isinstance(cv, str) and cv:
                        by_signal[(ct, cv.lower())].append(ent.entity_id)
                for ct, cv in (dev.identifiers or set()):
                    if isinstance(ct, str) and isinstance(cv, str) and cv:
                        by_signal[(f"id:{ct}", cv)].append(ent.entity_id)
        except (AttributeError, TypeError):
            return set()
        pairs: set[tuple[str, str]] = set()
        for eids in by_signal.values():
            if len(eids) < 2:
                continue
            for i in range(len(eids)):
                for j in range(i + 1, len(eids)):
                    a, b = sorted([eids[i], eids[j]])
                    pairs.add((a, b))
        return pairs

    def _collect_static_dedup_pairs(
        self, ctx: DetectorContext
    ) -> set[tuple[str, str]]:
        """Build the (a, b) pair set that v1.10.3's static-signal
        dedup would catch. Avoids running the v1.10.3 path for every
        pair (which would query the registry inside the inner loop)."""
        try:
            from homeassistant.helpers import device_registry as dr
            from homeassistant.helpers import entity_registry as er
        except ImportError:
            return set()
        e_reg = er.async_get(ctx.hass)
        d_reg = dr.async_get(ctx.hass)
        # Map identifier-value → list of entity_ids that share it.
        # Same value across devices ⇒ all those entities are likely-
        # same-physical.
        by_signal: dict[tuple[str, str], list[str]] = defaultdict(list)
        for ent in e_reg.entities.values():
            if ent.device_id is None:
                continue
            dev = d_reg.async_get(ent.device_id)
            if dev is None:
                continue
            # v1.14.11: HA device.connections + device.identifiers
            # used to always be 2-tuples of (domain, value). Some HA
            # versions now emit 3+ element tuples for certain
            # integrations (extra metadata), which broke the original
            # `for ct, cv in ...` unpacking with ValueError. Tolerate
            # both shapes by taking only the first two elements; skip
            # anything malformed (None, 1-tuple, non-iterable).
            for conn in (dev.connections or set()):
                if not conn or len(conn) < 2:
                    continue
                ct, cv = conn[0], conn[1]
                if isinstance(ct, str) and isinstance(cv, str) and cv:
                    by_signal[(ct, cv.lower())].append(ent.entity_id)
            for ident in (dev.identifiers or set()):
                if not ident or len(ident) < 2:
                    continue
                ct, cv = ident[0], ident[1]
                if isinstance(ct, str) and isinstance(cv, str) and cv:
                    by_signal[(f"id:{ct}", cv)].append(ent.entity_id)
        pairs: set[tuple[str, str]] = set()
        for eids in by_signal.values():
            if len(eids) < 2:
                continue
            for i in range(len(eids)):
                for j in range(i + 1, len(eids)):
                    a, b = sorted([eids[i], eids[j]])
                    pairs.add((a, b))
        return pairs

    def _build_insight(
        self,
        *,
        eid_a: str,
        eid_b: str,
        device_class: str,
        result: CorrelationResult,
    ) -> Insight:
        """Construct the PATTERN_OBSERVATION insight for one
        correlated pair."""
        # Order deterministically for the fingerprint so the same pair
        # always produces the same insight ID across scans.
        #
        # **v1.12.7 rename**: keys were `entity_a`/`entity_b` until the
        # agent review caught two bugs from that schema:
        #   - `lib/managed_externally.py::_is_entity_field_key` walks
        #     fingerprints looking for keys matching `entity_id`,
        #     `*_entity_id`, `*_eid`, etc. `entity_a`/`entity_b` matched
        #     none of those, so insights from this detector could NOT
        #     be suppressed by marking either entity's device as
        #     managed-externally.
        #   - `detectors/__init__.py::_dedup_grouped_insights` buckets
        #     by fingerprints containing the literal `entity_id` key.
        #     Without it, every dup-pair landed in its own `_solo_`
        #     bucket and the panel got flooded on installs with many
        #     duplicates.
        # Using `entity_id` for the canonical (sorted-first) entity
        # and `peer_entity_id` for the partner gives both walkers the
        # keys they expect AND keeps semantic clarity for human
        # readers of the insight payload.
        a, b = sorted([eid_a, eid_b])
        fingerprint = {
            "kind": "physical_device_link",
            "entity_id": a,
            "peer_entity_id": b,
        }
        lag_note = ""
        if result.best_lag_bins != 0:
            lag_min = abs(result.best_lag_bins) * (_BIN_SIZE_SECONDS / 60.0)
            lag_note = (
                f" (at lag ~{int(lag_min)}min — likely clock drift "
                "between integrations)"
            )
        title = (
            f"{a} and {b} look like the same physical device "
            f"(r={result.r:.2f}{lag_note})"
        )
        payload: dict[str, Any] = {
            "type": "history-graph",
            "title": (
                f"Same physical device? {a} ↔ {b}"
            ),
            "entities": [a, b],
            "hours_to_show": 24 * _LOOKBACK_DAYS,
            "_physical_device_link": {
                # v1.12.7 — renamed from entity_a/entity_b to match
                # the fingerprint keys (entity_id is the canonical
                # sorted-first entity, peer_entity_id its partner).
                # Card v1.x renderers should switch on these names.
                "entity_id": a,
                "peer_entity_id": b,
                "device_class": device_class,
                "pearson_r": result.r,
                "n_aligned_samples": result.n_samples,
                "best_lag_bins": result.best_lag_bins,
                "lookback_days": _LOOKBACK_DAYS,
            },
        }
        explanation = (
            f"Over the last {_LOOKBACK_DAYS} days, these two "
            f"{device_class} entities reported values correlated at "
            f"r={result.r:.2f} across {result.n_samples} aligned "
            "10-minute bins. Two real-world sensors at the same "
            "location typically correlate r ≈ 0.85–0.92; this is "
            "high enough that they're probably the same physical "
            "sensor seen through two different integrations.\n\n"
            "Common causes: Tuya cloud + BLE scanner, Govee Cloud + "
            "Govee BLE, Hue Bridge + Matter bridging the same Hue "
            "device, Zigbee2MQTT + ZHA during a migration.\n\n"
            "Decide whether to: mark one device as 'managed externally' "
            "(v1.7.7 flag), remove the duplicate integration, or "
            "acknowledge and move on. This is informational; the "
            "detector won't act on it."
        )
        return Insight(
            id=Insight.compute_id(InsightKind.PATTERN_OBSERVATION, fingerprint),
            kind=InsightKind.PATTERN_OBSERVATION,
            detector=self.name,
            area_id=None,
            title=title,
            confidence=round(result.confidence, 3),
            fingerprint=fingerprint,
            payload=payload,
            payload_format="card",
            explanation=explanation,
            created_at=datetime.now(tz=UTC),
        )
