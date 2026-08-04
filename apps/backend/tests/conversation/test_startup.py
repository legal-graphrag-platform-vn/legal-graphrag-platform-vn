"""Startup verification for the conversation store (Plan 19 §3).

Marked ``conversation_db``; requires CONVERSATION_TEST_DATABASE_URL.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from conversation.startup import verify_conversation_store
from tests.conversation.conftest import build_test_engine, reset_schema

pytestmark = pytest.mark.conversation_db

_BACKEND_DIR = Path(__file__).resolve().parents[2]


async def _verify(db_url: str) -> None:
    engine = build_test_engine(db_url)
    try:
        await verify_conversation_store(engine)
    finally:
        await engine.dispose()


async def _reset(db_url: str) -> None:
    engine = build_test_engine(db_url)
    try:
        await reset_schema(engine)
    finally:
        await engine.dispose()


def test_unmigrated_store_is_rejected(db_url: str) -> None:
    asyncio.run(_reset(db_url))
    with pytest.raises(RuntimeError, match="not migrated"):
        asyncio.run(_verify(db_url))


def test_migrated_store_passes_verification(db_url: str, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", db_url)
    asyncio.run(_reset(db_url))
    config = Config(str(_BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    command.upgrade(config, "head")

    asyncio.run(_verify(db_url))
