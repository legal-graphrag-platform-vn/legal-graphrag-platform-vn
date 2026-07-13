"""Deterministic reciprocal-rank fusion across retrieval channels."""

from src.retrieval.models import RetrievedUnit


class ReciprocalRankFusion:
    def __init__(self, k: int = 60) -> None:
        if k < 1:
            raise ValueError("RRF k must be positive")
        self._k = k

    def fuse(
        self,
        vector_results: list[RetrievedUnit],
        fulltext_results: list[RetrievedUnit],
        top_n: int = 20,
    ) -> list[RetrievedUnit]:
        return self.fuse_channels(
            {"vector": vector_results, "fulltext": fulltext_results}, top_n=top_n
        )

    def fuse_channels(
        self,
        channels: dict[str, list[RetrievedUnit]],
        *,
        top_n: int,
    ) -> list[RetrievedUnit]:
        if top_n < 1:
            raise ValueError("top_n must be positive")

        scores: dict[str, float] = {}
        units: dict[str, RetrievedUnit] = {}
        for source, results in sorted(channels.items()):
            if source not in {"vector", "fulltext", "graph"}:
                raise ValueError(f"Unsupported retrieval channel: {source}")
            for rank, unit in enumerate(results, start=1):
                scores[unit.id] = scores.get(unit.id, 0.0) + 1.0 / (self._k + rank)
                existing = units.setdefault(unit.id, unit.model_copy(deep=True))
                _merge_source_metadata(existing, unit, source)

        for unit_id, score in scores.items():
            units[unit_id].final_score = score
        return sorted(
            units.values(),
            key=lambda unit: (-(unit.final_score or 0.0), unit.id),
        )[:top_n]


def _merge_source_metadata(
    existing: RetrievedUnit, incoming: RetrievedUnit, source: str
) -> None:
    if source == "vector" and incoming.vector_score is not None:
        existing.vector_score = incoming.vector_score
    elif source == "fulltext" and incoming.bm25_score is not None:
        existing.bm25_score = incoming.bm25_score
    elif source == "graph" and incoming.graph_score is not None:
        existing.graph_score = incoming.graph_score
    existing.retrieval_sources = sorted(set(existing.retrieval_sources) | {source})
