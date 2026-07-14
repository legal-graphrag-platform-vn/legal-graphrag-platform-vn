"""Bound synchronous retrieval without pretending threads can be killed."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import TypeVar

from services.errors import BackendRetrievalClosedError, BackendRetrievalTimeoutError


logger = logging.getLogger(__name__)
ResultT = TypeVar("ResultT")


class BoundedRetrievalRunner:
    def __init__(
        self,
        *,
        max_concurrency: int,
        timeout_seconds: float,
        shutdown_grace_seconds: float,
        executor: ThreadPoolExecutor | None = None,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if shutdown_grace_seconds < 0:
            raise ValueError("shutdown_grace_seconds must not be negative")
        self._executor = executor or ThreadPoolExecutor(
            max_workers=max_concurrency,
            thread_name_prefix="retrieval",
        )
        self._capacity = asyncio.Semaphore(max_concurrency)
        self._timeout_seconds = timeout_seconds
        self._shutdown_grace_seconds = shutdown_grace_seconds
        self._accepting = True
        self._active: dict[Future[object], asyncio.Task[None]] = {}

    async def run(self, call: Callable[[], ResultT]) -> ResultT:
        concurrent_future: Future[ResultT] | None = None
        try:
            async with asyncio.timeout(self._timeout_seconds):
                await self._capacity.acquire()
                if not self._accepting:
                    self._capacity.release()
                    raise BackendRetrievalClosedError(
                        "Retrieval runner is shutting down"
                    )
                loop = asyncio.get_running_loop()
                async_future: asyncio.Future[ResultT] = loop.create_future()
                try:
                    concurrent_future = self._executor.submit(call)
                except Exception:
                    self._capacity.release()
                    raise
                self._track(concurrent_future, async_future)
                async_future.add_done_callback(_consume_future_result)
                return await asyncio.shield(async_future)
        except TimeoutError as exc:
            self._cancel_queued(concurrent_future)
            raise BackendRetrievalTimeoutError(
                f"Retrieval exceeded {self._timeout_seconds:g} seconds"
            ) from exc
        except asyncio.CancelledError:
            self._cancel_queued(concurrent_future)
            raise

    async def aclose(self) -> int:
        if not self._accepting:
            return self.active_count
        self._accepting = False
        active = self._active_snapshot()
        for future in active:
            self._cancel_queued(future)

        if active and self._shutdown_grace_seconds > 0:
            deadline = asyncio.get_running_loop().time() + self._shutdown_grace_seconds
            while self.active_count and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.01)
        unfinished = self._active_snapshot()
        self._executor.shutdown(wait=False, cancel_futures=True)
        if unfinished:
            logger.warning(
                "Retrieval shutdown grace expired: unfinished_workers=%d",
                len(unfinished),
            )
        return len(unfinished)

    @property
    def active_count(self) -> int:
        return len(self._active_snapshot())

    def _track(
        self,
        future: Future[object],
        result_future: asyncio.Future[object],
    ) -> None:
        monitor = asyncio.create_task(self._monitor(future, result_future))
        self._active[future] = monitor

    async def _monitor(
        self,
        future: Future[object],
        result_future: asyncio.Future[object],
    ) -> None:
        try:
            while not future.done():
                await asyncio.sleep(0.005)
            if future.cancelled():
                result_future.cancel()
                return
            error = future.exception()
            if error is not None:
                if not result_future.done():
                    result_future.set_exception(error)
                return
            if not result_future.done():
                result_future.set_result(future.result())
        finally:
            self._active.pop(future, None)
            self._capacity.release()

    def _cancel_queued(self, future: Future[object] | None) -> None:
        if future is None:
            return
        future.cancel()

    def _active_snapshot(self) -> list[Future[object]]:
        return list(self._active)


def _consume_future_result(future: asyncio.Future[object]) -> None:
    if future.cancelled():
        return
    try:
        future.exception()
    except asyncio.CancelledError:
        return
