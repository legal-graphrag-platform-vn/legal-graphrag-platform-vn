from datetime import date

import pytest

from src.retrieval.models import RetrievalFilters
from src.retrieval.retriever.fulltext import (
    FULLTEXT_INDEX,
    FullTextRetriever,
    escape_lucene_query,
)
from src.retrieval.retriever.vector import VECTOR_INDEXES, VectorRetriever


def _row(unit_id: str, label: str = "Article") -> dict:
    return {
        "id": unit_id,
        "label": label,
        "content_raw": "Nội dung",
        "article_id": "doc_art5",
        "clause_id": "doc_art5_cl1" if label == "Clause" else None,
        "article_number": "5",
        "clause_number": "1" if label == "Clause" else None,
        "document_id": "doc",
        "document_number": "59/2020/QH14",
        "effective_from": date(2021, 1, 1),
        "effective_to": None,
        "score": 0.8,
    }


class FakeEmbeddingGenerator:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def encode(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return [[0.1] * 1024]


class FailingEmbeddingGenerator:
    def encode(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("embedding provider unavailable")


class FakeRepo:
    def __init__(self) -> None:
        self.vector_calls: list[tuple] = []
        self.fulltext_calls: list[tuple] = []

    def vector_search(self, index_name, query_embedding, *, filters, k):
        self.vector_calls.append((index_name, query_embedding, filters, k))
        return [_row(f"{index_name}_unit")]

    def fulltext_search(self, index_name, text_query, *, filters, k):
        self.fulltext_calls.append((index_name, text_query, filters, k))
        return [_row("fulltext_unit")]


def test_vector_retriever_encodes_a_batch_and_queries_both_indexes() -> None:
    repo = FakeRepo()
    encoder = FakeEmbeddingGenerator()
    filters = RetrievalFilters(document_ids=["doc"])

    results = VectorRetriever(repo, encoder).retrieve(
        "vốn điều lệ", filters=filters, top_k=3
    )

    assert encoder.calls == [["vốn điều lệ"]]
    assert [call[0] for call in repo.vector_calls] == list(VECTOR_INDEXES)
    assert len(repo.vector_calls[0][1]) == 1024
    assert len(results) == 2
    assert all(
        result.deep_link.startswith("/documents/doc/units/") for result in results
    )


def test_fulltext_retriever_uses_canonical_index_and_escapes_lucene() -> None:
    repo = FakeRepo()
    results = FullTextRetriever(repo).retrieve("vốn: (điều lệ)", top_k=5)

    assert repo.fulltext_calls[0][0] == FULLTEXT_INDEX
    assert repo.fulltext_calls[0][1] == r"vốn\: \(điều lệ\)"
    assert results[0].retrieval_sources == ["fulltext"]


@pytest.mark.parametrize("query", ["", "   "])
def test_retrievers_reject_empty_query(query: str) -> None:
    repo = FakeRepo()
    with pytest.raises(ValueError):
        FullTextRetriever(repo).retrieve(query)
    with pytest.raises(ValueError):
        VectorRetriever(repo, FakeEmbeddingGenerator()).retrieve(query)


def test_escape_lucene_query_covers_reserved_operators() -> None:
    assert escape_lucene_query('a+b/c:"d"') == 'a\\+b\\/c\\:\\"d\\"'


def test_vector_retriever_propagates_embedding_provider_failure() -> None:
    with pytest.raises(RuntimeError, match="provider unavailable"):
        VectorRetriever(FakeRepo(), FailingEmbeddingGenerator()).retrieve("query")
