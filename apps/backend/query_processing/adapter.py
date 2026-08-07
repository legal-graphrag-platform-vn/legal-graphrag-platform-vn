"""Async adapter over the synchronous five-field query processor.

The core ``QueryProcessor`` (``src/retrieval/nlu``) is synchronous and performs a
blocking LLM call. This adapter runs it on the application-owned bounded executor
(the same runner used for synchronous retrieval) so the event loop is never
blocked, and exposes the async ``QueryProcessorPort`` the chat service depends on.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from services.interfaces import AsyncRetrievalRunner
from src.retrieval.nlu.query_processor import QueryProcessor
from src.shared.retrieval_contract import QueryProcessingResult


class QueryProcessorAdapter:
    def __init__(
        self,
        processor: QueryProcessor,
        runner: AsyncRetrievalRunner,
    ) -> None:
        self._processor = processor
        self._runner = runner

    async def process(
        self,
        current_query: str,
        conversation_history: Sequence[Mapping[str, str]] = (),
    ) -> QueryProcessingResult:
        history = tuple(dict(turn) for turn in conversation_history)
        return await self._runner.run(
            lambda: self._processor.process(current_query, history)
        )
