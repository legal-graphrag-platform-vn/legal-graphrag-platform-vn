from __future__ import annotations

from datetime import date

from src.generation.models import AnswerCandidate, AnswerClaim
from src.retrieval.models import (
    EvidenceItem,
    GraphPath,
    IntentType,
    RetrievalContext,
    RetrievedUnit,
    TemporalQuery,
)
from src.shared.retrieval_contract import RetrievalStrategyType, TemporalSource


def retrieved_unit(
    unit_id: str = "doc_art1",
    *,
    label: str = "Article",
) -> RetrievedUnit:
    article_id = unit_id.split("_cl", 1)[0]
    return RetrievedUnit(
        id=unit_id,
        label=label,
        content_raw="Tổ chức, cá nhân có quyền thành lập và quản lý doanh nghiệp.",
        document_id="doc",
        document_number="01/2026/QH",
        article_id=article_id,
        clause_id=unit_id if label == "Clause" else None,
        article_number="1",
        clause_number="1" if label == "Clause" else None,
        effective_from=date(2021, 1, 1),
        effective_to=None,
        legal_status="ACTIVE",
        citation_label="Điều 1, Luật thử nghiệm",
        deep_link=f"/documents/doc/units/{unit_id}",
        retrieval_sources=["vector"],
    )


def retrieval_context(
    *,
    intent: IntentType = IntentType.FACTUAL,
    no_results: bool = False,
    path_relations: list[str] | None = None,
    temporal: bool = False,
) -> RetrievalContext:
    units = [] if no_results else [retrieved_unit()]
    relations = path_relations or []
    paths = []
    if relations:
        target = retrieved_unit("doc_art2")
        units.append(target)
        paths = [
            GraphPath(
                nodes=[units[0].id, target.id],
                relations=relations,
                relation_ids=[f"rel-{index}" for index, _ in enumerate(relations)],
                path_description="Verified legal path",
                is_temporal_valid=True,
            )
        ]
    query_date = date(2022, 7, 1) if temporal else None
    return RetrievalContext(
        query="Ai có quyền thành lập doanh nghiệp?",
        intent=intent,
        strategy=_strategy(intent),
        temporal=TemporalQuery(
            has_temporal=temporal,
            resolved_from=query_date,
            resolved_to=query_date,
        ),
        temporal_source=(TemporalSource.REQUEST if temporal else TemporalSource.NONE),
        retrieved_units=units,
        graph_paths=paths,
        evidence=(
            []
            if no_results
            else [
                EvidenceItem(
                    unit_id=unit.id,
                    evidence_type="vector",
                    is_sufficient=True,
                )
                for unit in units
            ]
        ),
        metrics={},
        retrieval_mode="no_results" if no_results else "hybrid",
        capability_status="no_results" if no_results else "supported",
    )


def answer_candidate(*, citation_id: str = "doc_art1") -> AnswerCandidate:
    return AnswerCandidate(
        claims=[
            AnswerClaim(
                claim_id="claim-1",
                text="Tổ chức, cá nhân có quyền thành lập doanh nghiệp.",
                citation_ids=[citation_id],
            )
        ],
        reasoning_path_ids=[],
        temporal_assertions=[],
        confidence=0.9,
        cannot_answer=False,
        insufficiency_reason=None,
    )


def _strategy(intent: IntentType) -> RetrievalStrategyType:
    return {
        IntentType.FACTUAL: RetrievalStrategyType.FACTUAL_HYBRID,
        IntentType.DEFINITION: RetrievalStrategyType.DEFINITION_GRAPH,
        IntentType.HIERARCHY: RetrievalStrategyType.HIERARCHY_GRAPH,
        IntentType.MULTI_HOP: RetrievalStrategyType.MULTI_HOP_HYBRID,
        IntentType.VALIDITY: RetrievalStrategyType.VALIDITY_TEMPORAL,
        IntentType.COMPARISON: RetrievalStrategyType.COMPARISON_TEMPORAL,
    }[intent]
