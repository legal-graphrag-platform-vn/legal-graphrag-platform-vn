"""Async SQLAlchemy engine and session factory for the context store.

The pool holds a session-level advisory lock for the whole turn, so pool
sizing is validated against answer concurrency in Settings.validate_runtime.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


@dataclass(frozen=True)
class EngineConfig:
    database_url: str
    pool_size: int
    max_overflow: int
    pool_timeout_seconds: float


def create_engine(config: EngineConfig) -> AsyncEngine:
    if not config.database_url.startswith("postgresql+asyncpg://"):
        raise ValueError("DATABASE_URL must use the postgresql+asyncpg driver")
    return create_async_engine(
        config.database_url,
        pool_size=config.pool_size,
        max_overflow=config.max_overflow,
        pool_timeout=config.pool_timeout_seconds,
        pool_pre_ping=True,
        future=True,
    )


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        engine,
        expire_on_commit=False,
        autoflush=False,
    )
