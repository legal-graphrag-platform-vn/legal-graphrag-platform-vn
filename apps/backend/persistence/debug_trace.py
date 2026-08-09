"""Durable turn debug-trace store (Plan 21 §4).

Best-effort: the caller must never let a persistence failure here break the
chat response. One row per persisted turn holds the full ordered event list.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from persistence.models import TurnDebugTrace


class TurnDebugTraceStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def save(
        self,
        *,
        trace_id: uuid.UUID,
        conversation_id: uuid.UUID,
        owner_id: uuid.UUID | None,
        status: str,
        events: list[dict[str, Any]],
    ) -> None:
        stmt = insert(TurnDebugTrace).values(
            trace_id=trace_id,
            conversation_id=conversation_id,
            owner_principal_id=owner_id,
            status=status,
            events=events,
        )
        async with self._engine.begin() as conn:
            await conn.execute(stmt)
