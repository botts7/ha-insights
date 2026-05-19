"""WS handlers for the v1.15 PWA companion-scanner stream (experimental).

Three handlers + a per-connection registry, all related to receiving
BLE RSSI samples streamed from a phone-resident PWA (`find-my-ha`)
into HA Insights' live-find machinery:

  - ``ws_companion_scan_subscribe`` — opens a stream for a target
    entity. Returns a ``subscription_id`` (uuid4) the PWA quotes on
    every subsequent sample, plus the server-side rate cap.
  - ``ws_companion_scan_sample`` — fire-and-forget RSSI reading.
    Rate-limited (min interval 250 ms), stale-drop (samples whose
    ``ts_ms`` is > 60 s behind wall-clock), and threaded through the
    shared EMA smoothing helper (``ble_find.apply_rssi_ema``) so the
    card UI handles phone + stationary-proxy samples uniformly.
  - ``ws_companion_scan_unsubscribe`` — idempotent teardown. Auto-
    invoked when the WS connection drops via the standard HA
    ``connection.subscriptions`` cleanup hook.

**Maturity: experimental.** The PWA itself is v0.2 / early-access at
the time of v1.15.0 release. Behaviour, message names, and the
sample-rate cap may evolve before v1.16. Stable contract docs live
at ``find-my-ha/docs/WS_PROTOCOL.md``.

**Privacy / audit.** Subscribe + unsubscribe each write one row to
``outbound_calls`` via ``record_call`` (agent=``companion-scan``,
agent_locality=``local``, redaction_mode=``local``). Individual
samples are NOT logged — at 4 Hz × 10 min = 2400 rows per session
that'd swamp the privacy log without telling the user anything they
don't already get from the subscribe row. Instead, the unsubscribe
row's ``redacted_payload`` carries an aggregate summary (sample
count, session duration, entity_id).

**Subscription lifecycle.** Per spec
(``find-my-ha/docs/WS_PROTOCOL.md`` §"Server-side behavior"):

  - One PWA subscription per ``(HA user, entity_id)`` tuple — a new
    subscribe for the same pair replaces the previous one (we send
    an unsubscribe audit row for the displaced subscription so the
    privacy log stays honest).
  - Samples older than 60 s (per ``ts_ms``) are silently dropped.
  - Sample rate above ``max_sample_rate_hz`` (4 Hz) keeps the most
    recent in the window — no warning back to the PWA, it shouldn't
    be sending that fast anyway.
  - Subscriptions auto-tear-down when the WS connection closes.
    The 10-minute idle-timeout from the spec is enforced lazily in
    the sample path (a sample arriving past the idle window finds
    nothing to deliver to and is silently ignored — equivalent
    user-visible behaviour to an active sweeper without the
    scheduling cost).

**Hook into BLE smoothing.** ``apply_rssi_ema`` lives next door in
``ble_find.py`` (extracted in v1.15.0 from the inline EMA that
``ws_ble_live_find`` used). Both code paths share the same alpha
constant, so a phone-sourced sample and a proxy-sourced sample
smooth identically. Downstream events use the same shape as the
BLE live-find event (``rssi_raw``, ``rssi_smoothed``, ``scanner``)
plus a ``source: "companion"`` discriminator so the card can label
the bucket if it wants to.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import callback

from ._helpers import _get_store, _require_admin
from .ble_find import apply_rssi_ema

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


# --- Tunables (matched to the WS_PROTOCOL.md spec) ---

# Server-side rate cap echoed back to the PWA in the subscribe ack.
# Spec: 4 Hz. Higher than the typical BLE advertisement rate (~1 Hz),
# but phones can multiplex multiple advertisers per scan window so
# the cap accommodates burst arrivals without dropping every other.
MAX_SAMPLE_RATE_HZ: int = 4

# Minimum gap between accepted samples per subscription. Derived
# from MAX_SAMPLE_RATE_HZ; kept as its own constant so tests can
# import it without a magic number.
_MIN_SAMPLE_INTERVAL_S: float = 1.0 / MAX_SAMPLE_RATE_HZ

# Phone-clock vs server-clock skew tolerance. Samples whose
# ``ts_ms`` claims to be > this many seconds older than server
# wall-clock are dropped (stale buffer drain after lost connection,
# or a phone with a badly-set clock).
_MAX_SAMPLE_AGE_S: float = 60.0

# Idle timeout — a subscription with no samples for this many
# seconds is considered abandoned. We don't actively sweep; the
# next sample after this window just doesn't find a peer.
_IDLE_TIMEOUT_S: float = 600.0  # 10 min, matches spec


# --- Per-connection subscription registry ---

# Keyed by ``id(connection)`` so the registry doesn't have to be
# touched on connection close — the per-connection cleanup callback
# we register via ``connection.subscriptions`` is responsible for
# removing entries when the WS drops. ``id()`` is safe because the
# entry's lifetime is strictly less than the connection object's:
# the cleanup hook fires before the connection is gc'd.
_SUBSCRIPTIONS: dict[str, dict[str, Any]] = {}


def _subscription_key_for_user_entity(
    user_id: str | None, entity_id: str
) -> tuple[str, str]:
    """Identity tuple for the "one subscription per (user, entity)" rule."""
    return (user_id or "anonymous", entity_id)


def _find_existing_for_user_entity(
    user_id: str | None, entity_id: str
) -> str | None:
    """Return the subscription_id of an active sub for this (user, entity), if any.

    Used to enforce the spec rule: a new subscribe for the same
    (user, entity) replaces the previous one.
    """
    key = _subscription_key_for_user_entity(user_id, entity_id)
    for sub_id, rec in _SUBSCRIPTIONS.items():
        if rec.get("user_entity_key") == key:
            return sub_id
    return None


async def _audit_subscribe(
    hass: HomeAssistant,
    *,
    entity_id: str,
    ble_mac: str | None,
    event: str,
    extra_payload: dict | None = None,
) -> None:
    """Write one ``outbound_calls`` row for a subscribe/unsubscribe event.

    Samples are NOT audited individually (see module docstring).
    ``event`` is one of ``subscribe`` / ``unsubscribe`` / ``replaced``.
    """
    try:
        store = _get_store(hass)
        if store is None:
            return
        from ..llm.privacy_log import record_call

        payload: dict[str, Any] = {
            "event": event,
            "entity_id": entity_id,
        }
        if ble_mac:
            payload["ble_mac"] = ble_mac
        if extra_payload:
            payload.update(extra_payload)
        await record_call(
            store,
            insight_id=None,
            agent="companion-scan",
            agent_locality="local",
            redaction_mode="local",
            bytes_sent=0,
            bytes_received=0,
            success=True,
            redacted_payload=payload,
        )
    except Exception:
        # Audit must never break the user-facing flow.
        _LOGGER.debug(
            "companion_scan audit (%s) failed for %s",
            event,
            entity_id,
            exc_info=True,
        )


def _teardown_subscription(
    hass: HomeAssistant,
    subscription_id: str,
    *,
    reason: str,
) -> dict[str, Any] | None:
    """Remove a subscription from the registry; return the popped record (or None).

    Synchronous so it can be called from the per-connection cleanup
    callback (which HA invokes from the connection-close handler, a
    sync context). The audit row is scheduled via ``hass.async_create_task``
    so we don't block close.
    """
    rec = _SUBSCRIPTIONS.pop(subscription_id, None)
    if rec is None:
        return None
    duration_s = max(0.0, time.monotonic() - rec.get("started_monotonic", 0.0))
    summary = {
        "samples_accepted": rec.get("samples_accepted", 0),
        "samples_dropped_stale": rec.get("samples_dropped_stale", 0),
        "samples_dropped_rate": rec.get("samples_dropped_rate", 0),
        "duration_s": round(duration_s, 2),
        "reason": reason,
    }
    hass.async_create_task(
        _audit_subscribe(
            hass,
            entity_id=rec["entity_id"],
            ble_mac=rec.get("ble_mac"),
            event="unsubscribe",
            extra_payload=summary,
        )
    )
    return rec


# --- Handlers ---


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/companion_scan_subscribe",
        vol.Required("entity_id"): str,
        vol.Optional("ble_mac"): vol.Any(str, None),
    }
)
@websocket_api.async_response
async def ws_companion_scan_subscribe(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Open a companion-scan stream for a target entity.

    Admin-gated — streaming subscriptions consume server resources
    and route arbitrary RSSI claims into the live-find pipeline.
    The PWA itself is loaded behind HA's standard long-lived-token
    auth, but we layer admin on top for parity with
    ``ws_ble_live_find``.
    """
    if not _require_admin(hass, connection, msg):
        return

    entity_id = msg["entity_id"]
    ble_mac_raw = msg.get("ble_mac")
    ble_mac: str | None = None
    if isinstance(ble_mac_raw, str) and ble_mac_raw.strip():
        ble_mac = (
            ble_mac_raw.strip()
            .upper()
            .replace("-", ":")
            .replace("_", ":")
        )

    user = connection.user
    user_id = getattr(user, "id", None)

    # Enforce "one subscription per (user, entity)" — replace any
    # existing one. The displaced subscription gets its own
    # unsubscribe audit row so the privacy log stays honest about
    # session boundaries.
    existing = _find_existing_for_user_entity(user_id, entity_id)
    if existing is not None:
        _teardown_subscription(hass, existing, reason="replaced")

    subscription_id = uuid.uuid4().hex
    now_mono = time.monotonic()
    _SUBSCRIPTIONS[subscription_id] = {
        "subscription_id": subscription_id,
        "entity_id": entity_id,
        "ble_mac": ble_mac,
        "user_entity_key": _subscription_key_for_user_entity(
            user_id, entity_id
        ),
        "connection_id": id(connection),
        "msg_id": msg["id"],
        "started_monotonic": now_mono,
        "last_sample_monotonic": 0.0,
        "ema_value": None,
        "samples_accepted": 0,
        "samples_dropped_stale": 0,
        "samples_dropped_rate": 0,
    }

    # Per-connection cleanup hook. HA's WS framework calls every
    # entry in ``connection.subscriptions`` when the connection
    # closes. We register a no-arg cancel-style callable keyed by
    # the subscribe msg id (consistent with ``ws_ble_live_find``).
    @callback
    def _cleanup_on_close() -> None:
        # Idempotent — _teardown_subscription is a no-op if the
        # client already called unsubscribe explicitly.
        _teardown_subscription(
            hass, subscription_id, reason="connection_closed"
        )

    connection.subscriptions[msg["id"]] = _cleanup_on_close

    await _audit_subscribe(
        hass,
        entity_id=entity_id,
        ble_mac=ble_mac,
        event="subscribe",
    )

    connection.send_result(
        msg["id"],
        {
            "subscription_id": subscription_id,
            "max_sample_rate_hz": MAX_SAMPLE_RATE_HZ,
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/companion_scan_sample",
        vol.Required("subscription_id"): str,
        vol.Required("rssi"): vol.Coerce(int),
        vol.Required("ts_ms"): vol.Coerce(int),
        vol.Optional("device_name"): vol.Any(str, None),
    }
)
@callback
def ws_companion_scan_sample(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Receive a single RSSI sample.

    Fire-and-forget per the WS protocol — we send a `result` ack so
    HA's WS framework is happy (it expects every command msg to be
    answered exactly once), but the PWA treats the reply as
    confirmation-of-receipt only. RSSI processing happens before the
    ack is sent so the spec's behaviour (drop stale, rate-limit, etc.)
    is observable from the ack ordering if needed.

    Sample-path validation is intentionally strict-but-quiet:

      - Unknown ``subscription_id`` → error (PWA bug, surface it).
      - Subscription belongs to a different connection → error
        (token-sharing or replay; refuse to thread).
      - Stale ``ts_ms`` → drop silently (counted in
        ``samples_dropped_stale``, surfaced on unsubscribe).
      - Above the rate cap → drop silently (counted in
        ``samples_dropped_rate``).
    """
    subscription_id = msg["subscription_id"]
    rec = _SUBSCRIPTIONS.get(subscription_id)
    if rec is None:
        connection.send_error(
            msg["id"],
            "unknown_subscription",
            "subscription_id is not active; subscribe first.",
        )
        return

    # Cross-connection guard: a subscription belongs to the connection
    # that created it. If the PWA reconnected, it must re-subscribe.
    if rec.get("connection_id") != id(connection):
        connection.send_error(
            msg["id"],
            "wrong_connection",
            "subscription_id belongs to a different WS connection; "
            "re-subscribe on this one.",
        )
        return

    now_mono = time.monotonic()
    now_wall = time.time()

    # Idle-timeout lazy enforcement — if the subscription has been
    # quiet beyond the spec's 10-min window, treat the next sample
    # as arriving on a dead subscription. Tear down and refuse.
    last_mono = rec.get("last_sample_monotonic") or rec["started_monotonic"]
    if (now_mono - last_mono) > _IDLE_TIMEOUT_S:
        _teardown_subscription(
            hass, subscription_id, reason="idle_timeout"
        )
        connection.send_error(
            msg["id"],
            "idle_timeout",
            "subscription idle for >10 min; subscribe again.",
        )
        return

    # Stale-sample drop: phone-clock ts_ms vs server wall-clock.
    # ts_ms in the future (clock skew) is fine — we only care about
    # samples that claim to be old. A wall-clock comparison is
    # intentional (not monotonic) because ts_ms is the phone's
    # wall-clock too.
    sample_age_s = now_wall - (msg["ts_ms"] / 1000.0)
    if sample_age_s > _MAX_SAMPLE_AGE_S:
        rec["samples_dropped_stale"] = rec.get("samples_dropped_stale", 0) + 1
        connection.send_result(msg["id"])
        return

    # Rate-limit: drop samples arriving faster than the cap. We use
    # monotonic time on the *server* side — the phone's ts_ms is
    # untrusted for rate enforcement (a misbehaving sender could
    # fake-timestamp samples to bypass).
    last_accepted_mono = rec.get("last_sample_monotonic", 0.0)
    if (
        last_accepted_mono > 0.0
        and (now_mono - last_accepted_mono) < _MIN_SAMPLE_INTERVAL_S
    ):
        rec["samples_dropped_rate"] = rec.get("samples_dropped_rate", 0) + 1
        connection.send_result(msg["id"])
        return

    # Accepted: feed into the shared EMA smoothing pipeline and
    # forward a live event to the WS client.
    try:
        raw_rssi = float(msg["rssi"])
    except (TypeError, ValueError):
        connection.send_error(
            msg["id"], "bad_rssi", "rssi must be a number."
        )
        return

    ema = apply_rssi_ema(rec.get("ema_value"), raw_rssi)
    rec["ema_value"] = ema
    rec["last_sample_monotonic"] = now_mono
    rec["samples_accepted"] = rec.get("samples_accepted", 0) + 1

    # Forward as an event on the *subscribe* msg id so the PWA
    # multiplexes samples and ack-events on the same channel as
    # ble_live_find does. Card-renderer code can treat companion
    # and proxy events with the same handler; ``source`` lets it
    # discriminate if desired.
    device_name = msg.get("device_name")
    event_payload: dict[str, Any] = {
        "rssi_raw": int(raw_rssi),
        "rssi_smoothed": round(ema, 1),
        "scanner": "companion",
        "source": "companion",
        "subscription_id": subscription_id,
    }
    if isinstance(device_name, str) and device_name:
        event_payload["device_name"] = device_name
    try:
        connection.send_event(rec["msg_id"], event_payload)
    except Exception:
        # If the originating subscribe msg id is gone (connection
        # is closing, etc.), the cleanup hook will catch up. Don't
        # leak the exception into the sample ack.
        _LOGGER.debug(
            "companion_scan send_event failed for sub %s",
            subscription_id,
            exc_info=True,
        )

    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_insights/companion_scan_unsubscribe",
        vol.Required("subscription_id"): str,
    }
)
@callback
def ws_companion_scan_unsubscribe(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Idempotent teardown of a companion-scan subscription.

    Per spec, repeated unsubscribes for the same ``subscription_id``
    succeed silently — the second call simply has nothing to tear
    down. We don't error in that case (cleaner PWA error handling).
    """
    subscription_id = msg["subscription_id"]
    rec = _SUBSCRIPTIONS.get(subscription_id)
    # Cross-connection guard only when the sub actually exists —
    # idempotent unsubscribe should still succeed if the sub is
    # already gone.
    if rec is not None and rec.get("connection_id") != id(connection):
        connection.send_error(
            msg["id"],
            "wrong_connection",
            "subscription_id belongs to a different WS connection.",
        )
        return

    # Also drop the per-connection cleanup hook for the original
    # subscribe msg id so we don't double-audit on connection close.
    if rec is not None:
        original_msg_id = rec.get("msg_id")
        if original_msg_id is not None:
            connection.subscriptions.pop(original_msg_id, None)

    _teardown_subscription(
        hass, subscription_id, reason="client_unsubscribe"
    )
    connection.send_result(msg["id"])


__all__ = [
    "MAX_SAMPLE_RATE_HZ",
    "ws_companion_scan_sample",
    "ws_companion_scan_subscribe",
    "ws_companion_scan_unsubscribe",
]
