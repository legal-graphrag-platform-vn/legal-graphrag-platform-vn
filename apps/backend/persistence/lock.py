"""PostgreSQL session-level advisory lock for per-conversation serialization.

The lock key is a signed 64-bit integer derived deterministically from the first
eight bytes of SHA-256(conversation_id.bytes). The lock is held on one pooled
connection for the whole turn; committing the short begin/finalize transactions
does not release a session-level advisory lock (Plan 19 §3).
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

_LOCK_BYTES = 8


def conversation_lock_key(conversation_id: uuid.UUID) -> int:
    digest = hashlib.sha256(conversation_id.bytes).digest()
    return int.from_bytes(digest[:_LOCK_BYTES], byteorder="big", signed=True)


async def try_advisory_lock(conn: AsyncConnection, key: int) -> bool:
    result = await conn.execute(
        text("SELECT pg_try_advisory_lock(:key)"),
        {"key": key},
    )
    acquired = bool(result.scalar())
    # End the implicit transaction so later conn.begin() blocks start clean;
    # a session-level advisory lock survives the commit.
    await conn.commit()
    return acquired


async def advisory_unlock(conn: AsyncConnection, key: int) -> bool:
    result = await conn.execute(
        text("SELECT pg_advisory_unlock(:key)"),
        {"key": key},
    )
    released = bool(result.scalar())
    await conn.commit()
    return released


async def acquire_with_deadline(
    conn: AsyncConnection,
    key: int,
    *,
    timeout_seconds: float,
    poll_interval_seconds: float,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    monotonic: Callable[[], float] | None = None,
) -> bool:
    """Poll pg_try_advisory_lock until acquired or the deadline passes."""
    clock = monotonic or asyncio.get_running_loop().time
    deadline = clock() + timeout_seconds
    while True:
        if await try_advisory_lock(conn, key):
            return True
        if clock() >= deadline:
            return False
        await sleep(poll_interval_seconds)
