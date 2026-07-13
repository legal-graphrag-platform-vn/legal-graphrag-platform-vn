"""Internal seed-channel execution; orchestration belongs to RetrievalRuntime."""

from __future__ import annotations

from src.retrieval.errors import RetrievalExecutionError
from src.retrieval.models import RetrievalChannel, RetrievalFilters, RetrievedUnit
from src.retrieval.ports import FullTextChannelPort, VectorChannelPort


class SeedChannelExecutor:
    """Execute only the routed seed channels and return independent ranked lists."""

    def __init__(
        self,
        *,
        vector: VectorChannelPort | None,
        fulltext: FullTextChannelPort | None,
    ) -> None:
        self._vector = vector
        self._fulltext = fulltext

    def execute(
        self,
        query: str,
        channels: tuple[RetrievalChannel, ...],
        *,
        filters: RetrievalFilters,
        candidate_k: int,
    ) -> dict[RetrievalChannel, list[RetrievedUnit]]:
        results: dict[RetrievalChannel, list[RetrievedUnit]] = {}
        for channel in channels:
            if channel is RetrievalChannel.VECTOR:
                if self._vector is None:
                    raise RetrievalExecutionError("Vector channel is not configured")
                results[channel] = self._vector.retrieve(
                    query, filters=filters, top_k=candidate_k
                )
            elif channel is RetrievalChannel.FULLTEXT:
                if self._fulltext is None:
                    raise RetrievalExecutionError("Full-text channel is not configured")
                results[channel] = self._fulltext.retrieve(
                    query, filters=filters, top_k=candidate_k
                )
            else:
                raise RetrievalExecutionError(
                    "GRAPH is not a valid seed retrieval channel"
                )
        return results
