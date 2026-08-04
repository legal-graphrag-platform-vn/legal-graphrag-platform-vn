"""Fixtures for PostgreSQL-backed conversation store tests (Plan 19).

Gated on CONVERSATION_TEST_DATABASE_URL so the fast suite stays offline.
Each test drives a single event loop and builds its own NullPool engine inside
that loop, which keeps asyncpg connections from leaking across loops on Windows.
Each run resets the public schema so integrity checks stay isolated.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from persistence.models import Base
from persistence.repository import SqlAlchemyConversationStore

_ENV_VAR = "CONVERSATION_TEST_DATABASE_URL"


def _require_db_url() -> str:
    url = os.environ.get(_ENV_VAR)
    if not url:
        pytest.skip(f"{_ENV_VAR} not set; skipping conversation DB integration test")
    return url


@pytest.fixture
def db_url() -> str:
    return _require_db_url()


def build_test_engine(url: str) -> AsyncEngine:
    """NullPool engine bound to the currently running loop."""
    return create_async_engine(url, poolclass=NullPool, future=True)


async def reset_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))


@asynccontextmanager
async def prepared_store(
    url: str,
    *,
    create_tables: bool = True,
) -> AsyncIterator[async_sessionmaker]:
    """Reset the schema, optionally create ORM tables, yield a sessionmaker."""
    engine = build_test_engine(url)
    try:
        await reset_schema(engine)
        if create_tables:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        yield async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    finally:
        await engine.dispose()


@asynccontextmanager
async def prepared_conversation_store(
    url: str,
    *,
    lock_timeout_seconds: float = 1.0,
    lock_poll_interval_seconds: float = 0.02,
) -> AsyncIterator[SqlAlchemyConversationStore]:
    """Reset schema, create ORM tables, yield an owner-scoped store."""
    engine = build_test_engine(url)
    try:
        await reset_schema(engine)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield SqlAlchemyConversationStore(
            engine,
            lock_timeout_seconds=lock_timeout_seconds,
            lock_poll_interval_seconds=lock_poll_interval_seconds,
        )
    finally:
        await engine.dispose()
