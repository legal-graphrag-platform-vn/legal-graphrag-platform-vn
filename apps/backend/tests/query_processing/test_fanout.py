"""Hermetic tests for Stage 2 subquery fan-out and context merging."""

from __future__ import annotations

from query_processing.fanout import build_subquery_requests, merge_contexts
from src.retrieval.models import EvidenceItem
from src.shared.retrieval_contract import (
    IntentType,
    PlanType,
    ProcessingStatus,
    QueryProcessingResult,
    SubqueryDTO,
    SubqueryIntent,
)
from tests.factories import retrieval_context, retrieved_article


def _two_subquery_result() -> QueryProcessingResult:
    return QueryProcessingResult(
        status=ProcessingStatus.READY,
        standalone_query="so sánh A và B",
        plan_type=PlanType.COMPARISON,
        subqueries=[
            SubqueryDTO(
                id="q1", query="A là gì", intent=SubqueryIntent.DEFINITION, depends_on=[]
            ),
            SubqueryDTO(
                id="q2", query="B là gì", intent=SubqueryIntent.FACTUAL, depends_on=[]
            ),
        ],
        clarification_question=None,
    )


def test_build_subquery_requests_routes_each_by_own_intent() -> None:
    requests = build_subquery_requests(
        _two_subquery_result(),
        document_ids=["doc"],
        query_date=None,
        enable_reranker=None,
    )

    assert [r.query for r in requests] == ["A là gì", "B là gì"]
    assert [r.force_intent for r in requests] == [
        IntentType.DEFINITION,
        IntentType.FACTUAL,
    ]
    assert all(r.filters.document_ids == ["doc"] for r in requests)


def test_merge_single_context_only_replaces_query() -> None:
    merged = merge_contexts([retrieval_context()], query="Q mới")
    assert merged.query == "Q mới"
    assert [u.id for u in merged.retrieved_units] == ["doc_art1"]


def test_merge_dedupes_units_and_unions_evidence() -> None:
    ctx1 = retrieval_context()  # retrieved unit + evidence for doc_art1
    unit2 = retrieved_article().model_copy(
        update={"id": "doc_art2", "article_id": "doc_art2"}
    )
    evidence2 = EvidenceItem(
        unit_id="doc_art2",
        evidence_type="vector",
        matched_text="B",
        score=0.5,
        source_path_id="rel-1",
        is_eligible=True,
    )
    ctx2 = ctx1.model_copy(
        update={
            "retrieved_units": [unit2, retrieved_article()],
            "evidence": [evidence2],
        }
    )

    merged = merge_contexts([ctx1, ctx2], query="merged")

    assert [u.id for u in merged.retrieved_units] == ["doc_art1", "doc_art2"]
    assert {e.unit_id for e in merged.evidence} == {"doc_art1", "doc_art2"}
    assert merged.metrics["subquery_count"] == 2
    assert merged.query == "merged"
