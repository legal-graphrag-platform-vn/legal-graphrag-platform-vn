"""Startup verification for the conversation store (Plan 19 §3).

Verifies PostgreSQL connectivity and that the applied Alembic revision matches
the migration head. Production is never auto-migrated.
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

_BACKEND_DIR = Path(__file__).resolve().parents[1]


def alembic_head_revision() -> str:
    config = Config(str(_BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    head = ScriptDirectory.from_config(config).get_current_head()
    if head is None:
        raise RuntimeError("No Alembic head revision found for the conversation store")
    return head


async def verify_conversation_store(engine: AsyncEngine) -> None:
    """Fail fast if the store is unreachable or not at the migration head."""
    expected_head = alembic_head_revision()
    async with engine.connect() as connection:
        try:
            result = await connection.execute(
                text("SELECT version_num FROM alembic_version")
            )
        except Exception as exc:
            raise RuntimeError(
                "Conversation store is not migrated; run 'alembic upgrade head'"
            ) from exc
        current = result.scalar()
    if current != expected_head:
        raise RuntimeError(
            "Conversation store Alembic revision mismatch: "
            f"database={current!r} expected={expected_head!r}. "
            "Run 'alembic upgrade head' before serving."
        )
