"""Observers — wire HA events into in-memory data structures.

State events flow into StateEventBuffer; entity registry updates flow into
the rename handler. HA event-bus wiring lands at step 7 alongside the store.
"""
from __future__ import annotations

from .state_event_buffer import StateEvent, StateEventBuffer

__all__ = ["StateEvent", "StateEventBuffer"]
