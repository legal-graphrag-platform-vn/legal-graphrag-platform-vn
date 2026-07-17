from __future__ import annotations

from datetime import date

import pytest

from api.models import QueryRequest
from services.retrieval_mapping import to_retrieval_request, to_retrieval_response
from src.retrieval.errors import RetrievalOutputError
from src.retrieval.models import IntentType
from tests.factories import retrieval_context


def test_request_mapping_preserves_filters_and_limit_semantics() -> None:
    request = QueryRequest(
        query="  hiệu lực Điều 1  ",
        top_k=5,
        candidate_k=20,
        document_ids=["doc-a", "doc-b"],
        query_date=date(2026, 1, 1),
        force_intent=IntentType.VALIDITY,
        enable_reranker=True,
    )

    mapped = to_retrieval_request(request)

    assert mapped.query == "hiệu lực Điều 1"
    assert mapped.top_k == 20
    assert mapped.final_k == 5
    assert mapped.filters.document_ids == ["doc-a", "doc-b"]
    assert mapped.filters.query_date == date(2026, 1, 1)
    assert mapped.force_intent is IntentType.VALIDITY
    assert mapped.enable_reranker is True


@pytest.mark.parametrize(
    "payload",
    [
        {"query": "x", "document_ids": ["doc", "doc"]},
        {"query": "x", "document_ids": [" "]},
        {"query": "x", "top_k": 6, "candidate_k": 5},
        {"query": "   "},
    ],
)
def test_request_contract_rejects_invalid_input(payload: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        QueryRequest.model_validate(payload)


def test_temporal_date_alias_maps_to_canonical_query_date() -> None:
    request = QueryRequest.model_validate(
        {"query": "hiệu lực", "temporal_date": "2026-01-01"}
    )
    assert request.query_date == date(2026, 1, 1)


def test_response_mapping_is_a_lossless_public_projection() -> None:
    response = to_retrieval_response(retrieval_context())

    assert response.contract_version == "retrieval-runtime-v2"
    assert response.executed_channels == ["vector", "fulltext"]
    assert response.retrieved_units[0].article_id == "doc_art1"
    assert response.retrieved_units[0].deep_link == ("/documents/doc/units/doc_art1")
    assert response.retrieved_units[0].retrieval_sources == ["vector", "fulltext"]
    assert response.graph_paths[0].edges[0].relation_id == "rel-1"
    assert response.evidence[0].source_path_id == "rel-1"
    assert response.metrics == {"total_pipeline_latency_ms": 12}
    assert "answer" not in response.model_dump()


def test_response_mapping_preserves_no_results() -> None:
    response = to_retrieval_response(retrieval_context(no_results=True))
    assert response.capability_status == "no_results"
    assert response.retrieved_units == []


def test_response_mapping_rejects_missing_article_ancestry() -> None:
    context = retrieval_context()
    context.retrieved_units[0].article_id = None

    with pytest.raises(RetrievalOutputError, match="requires article_id"):
        to_retrieval_response(context)


def test_response_mapping_rejects_missing_deep_link() -> None:
    context = retrieval_context()
    context.retrieved_units[0].deep_link = ""

    with pytest.raises(RetrievalOutputError, match="requires deep_link"):
        to_retrieval_response(context)
