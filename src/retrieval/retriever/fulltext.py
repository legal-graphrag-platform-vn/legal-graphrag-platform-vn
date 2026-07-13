"""Neo4j full-text retrieval for Article and Clause legal units."""

import re

from src.retrieval.mapping import map_retrieved_unit
from src.retrieval.models import RetrievalFilters, RetrievedUnit
from src.retrieval.ports import FullTextSearchPort


FULLTEXT_INDEX = "legal_article_clause_fulltext"
_LUCENE_SPECIAL = re.compile(r'([+\-!(){}\[\]^"~*?:\\/]|&&|\|\|)')


def escape_lucene_query(value: str) -> str:
    return _LUCENE_SPECIAL.sub(r"\\\1", value).strip()


class FullTextRetriever:
    def __init__(self, repo: FullTextSearchPort) -> None:
        self._repo = repo

    def retrieve(
        self,
        query: str,
        *,
        filters: RetrievalFilters | None = None,
        top_k: int = 10,
    ) -> list[RetrievedUnit]:
        escaped_query = escape_lucene_query(query)
        if not escaped_query:
            raise ValueError("Full-text retrieval query must not be empty")
        if top_k < 1:
            raise ValueError("top_k must be positive")

        rows = self._repo.fulltext_search(
            FULLTEXT_INDEX,
            escaped_query,
            filters=filters or RetrievalFilters(),
            k=top_k,
        )
        units = [map_retrieved_unit(row, score_field="bm25_score") for row in rows]
        units.sort(key=lambda unit: (-(unit.bm25_score or 0.0), unit.id))
        return units[:top_k]
