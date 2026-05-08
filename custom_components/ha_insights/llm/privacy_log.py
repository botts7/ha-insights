"""Outbound-call audit log.

Every LLM call writes one row to the `outbound_calls` table so the user can
inspect what left their network. The privacy-log sensor entity (v0.2 phase 2)
surfaces a daily summary based on this table.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..store import InsightStore


async def record_call(
    store: InsightStore,
    *,
    insight_id: str | None,
    agent: str,
    agent_locality: str,
    redaction_mode: str,
    bytes_sent: int,
    bytes_received: int | None,
    success: bool,
    redacted_payload: dict | None = None,
) -> None:
    """Append an entry to outbound_calls."""
    from datetime import UTC, datetime

    payload_json = (
        json.dumps(redacted_payload, sort_keys=True) if redacted_payload else None
    )
    await store._c.execute(  # intentional cross-module write to the same store
        """
        INSERT INTO outbound_calls (
            timestamp, insight_id, agent, agent_locality, redaction_mode,
            bytes_sent, bytes_received, success, redacted_payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now(tz=UTC).timestamp(),
            insight_id,
            agent,
            agent_locality,
            redaction_mode,
            bytes_sent,
            bytes_received,
            1 if success else 0,
            payload_json,
        ),
    )
    await store._c.commit()
