"""Universal helpers shared across every WS handler.

These five (plus the buffer-fetcher) are the only cross-handler
state-touching primitives in the WS layer. They were factored out
during the v1.13 refactor because every handler file we want to
split off — refine / audit / find_my_device / managed_devices /
identify / etc. — pulls in some subset.

Keeping them here means future handler-file moves don't have to
shuttle these definitions around. The Explore dependency map
(memory: ``ha-insights-ws-api-dependency-map``) verified no
handler-to-handler coupling — only handler-to-helper.

## Contract

  - ``_get_store(hass, entry_id=None)`` — resolve the InsightStore
    for a config entry, or the first one if entry_id is None.
    Multi-entry installs default to first-entry behavior pending
    per-call entry_id routing.
  - ``_get_buffer(hass, entry_id=None)`` — same shape, for the
    StateEventBuffer. Used by perturbation_test +
    backfill paths that need recent state samples.
  - ``_audit_attempts(store, attempts, *, insight_id, redactor)`` —
    write one outbound_calls audit row per LLM-failover attempt.
    REFINE + AUDIT linchpin: drops here = privacy log gap. Keep
    backwards-compatible (empty attempts tolerated).
  - ``_resolve_blocked_entities(hass, getter)`` — union per-entity
    opt-out across active config entries.
  - ``_resolve_preferred_agent_id(hass)`` — first non-empty
    preferred-agent across active config entries.
  - ``_require_admin(hass, connection, msg)`` — gate destructive
    or privileged endpoints behind admin status. Sends error
    frame + returns False if rejected.

These helpers re-export from ``ws_api/__init__.py`` so existing
handler call sites stay working without modification. New code
should import from ``._helpers`` directly.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant

from ..const import DOMAIN

if TYPE_CHECKING:
    from ..store import InsightStore


def _get_store(
    hass: HomeAssistant, entry_id: str | None = None
) -> InsightStore | None:
    """Resolve a store from hass.data.

    `entry_id=None` returns the first entry's store — preserves
    single-entry-card backwards compatibility. Pass an explicit entry_id
    to route to a specific config entry's store in multi-entry installs.
    Returns None if the entry doesn't exist or the integration isn't set up.

    NOTE (v1.0): WS handlers currently always call this with the default
    (no entry_id), so multi-entry users will see all reads/writes route
    to the first entry. The integration setup itself is per-entry
    correctly (separate stores, buffers, sensors, digests). Per-call
    entry_id routing through the WS surface is a v1.1 follow-up — the
    mechanism is here, the schemas just don't expose it yet.
    """
    data = hass.data.get(DOMAIN, {})
    if entry_id is not None:
        candidate = data.get(entry_id)
        if isinstance(candidate, dict):
            return candidate.get("store")
        return None
    for value in data.values():
        if isinstance(value, dict) and "store" in value:
            return value["store"]
    return None


def _get_buffer(hass: HomeAssistant, entry_id: str | None = None):
    """Resolve a StateEventBuffer; first entry by default, specific entry_id otherwise."""
    data = hass.data.get(DOMAIN, {})
    if entry_id is not None:
        candidate = data.get(entry_id)
        if isinstance(candidate, dict):
            return candidate.get("buffer")
        return None
    for value in data.values():
        if isinstance(value, dict) and "buffer" in value:
            return value["buffer"]
    return None


async def _audit_attempts(
    store,
    attempts,
    *,
    insight_id: str,
    redactor,
) -> None:
    """Record one outbound_calls row per attempt.

    Failover may walk multiple agents before one succeeds. Earlier failed
    attempts still hit the network (some bytes left); v1.0 review found
    those were getting silently dropped. Each AttemptAudit row becomes
    its own privacy-log entry so the user sees the full picture.

    Empty `attempts` is tolerated for backwards compat / defensive paths.
    """
    from ..llm import derive_agent_locality, record_call

    for attempt in attempts:
        await record_call(
            store,
            insight_id=insight_id,
            agent=(
                str(attempt.chosen_agent_id)
                if attempt.chosen_agent_id
                else "default"
            ),
            agent_locality=derive_agent_locality(attempt.chosen_agent_id),
            redaction_mode=str(redactor.mode),
            bytes_sent=attempt.bytes_sent,
            bytes_received=attempt.bytes_received,
            success=attempt.success,
        )


def _resolve_blocked_entities(hass: HomeAssistant, getter) -> frozenset[str]:
    """Aggregate the per-entity opt-out across active config entries.

    Single-entry common case returns that entry's set; future multi-entry
    setups are already supported by union.
    """
    blocked: set[str] = set()
    for entry in hass.config_entries.async_entries(DOMAIN):
        blocked |= getter(entry)
    return frozenset(blocked)


def _resolve_preferred_agent_id(hass: HomeAssistant) -> str | None:
    """First non-empty preferred LLM agent across active config entries.

    Single-entry common case returns that entry's preference. Multi-entry
    installs pick the first one set — preferences are install-wide
    intent, not per-entry, so first-set wins.
    """
    from ..config_flow import get_preferred_agent_id

    for entry in hass.config_entries.async_entries(DOMAIN):
        preferred = get_preferred_agent_id(entry)
        if preferred:
            return preferred
    return None


def _require_admin(hass: HomeAssistant, connection, msg: dict) -> bool:
    """Gate the per-user-override endpoints behind admin status.

    Returns True if the caller is admin, False if rejected (and an
    error frame has been sent on the connection).
    """
    user = connection.user
    if user is None or not getattr(user, "is_admin", False):
        connection.send_error(
            msg["id"], "admin_required",
            "Setting per-user notification overrides is admin-only.",
        )
        return False
    return True


__all__ = [
    "_audit_attempts",
    "_get_buffer",
    "_get_store",
    "_require_admin",
    "_resolve_blocked_entities",
    "_resolve_preferred_agent_id",
]
