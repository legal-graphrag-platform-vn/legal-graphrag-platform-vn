"""Vector retrieval over canonical Article and Clause indexes."""

from src.retrieval.mapping import map_retrieved_unit
from src.retrieval.models import RetrievalFilters, RetrievedUnit
from src.retrieval.ports import EmbeddingPort, VectorSearchPort


VECTOR_INDEXES = ("article_embedding", "clause_embedding")


class VectorRetriever:
    def __init__(
        self, repo: VectorSearchPort, embedding_generator: EmbeddingPort
    ) -> None:
        self._repo = repo
        self._embedding_generator = embedding_generator

    def retrieve(
        self,
        query: str,
        *,
        filters: RetrievalFilters | None = None,
        top_k: int = 10,
    ) -> list[RetrievedUnit]:
        if not query.strip():
            raise ValueError("Vector retrieval query must not be empty")
        if top_k < 1:
            raise ValueError("top_k must be positive")

        query_embedding = self._embedding_generator.encode([query])[0]
        active_filters = filters or RetrievalFilters()
        rows = [
            row
            for index_name in VECTOR_INDEXES
            for row in self._repo.vector_search(
                index_name,
                query_embedding,
                filters=active_filters,
                k=top_k,
            )
        ]
        units = [map_retrieved_unit(row, score_field="vector_score") for row in rows]
        units.sort(key=lambda unit: (-(unit.vector_score or 0.0), unit.id))
        return units[:top_k]
