"""SQLite-backed persistence for HA Insights.

Holds insights, pseudonym map, outbound-call audit log, and applied-history
snapshots. State events are in-memory by default (StateEventBuffer) with
optional persistence here.
"""
from __future__ import annotations

from .store import InsightStore

__all__ = ["InsightStore"]
