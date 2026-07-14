from __future__ import annotations

from src.retrieval.models import (
    EvidenceItem,
    GraphPath,
    IntentType,
    RetrievalChannel,
    RetrievalContext,
    RetrievedUnit,
    TemporalQuery,
)


def retrieval_context(*, no_results: bool = False) -> RetrievalContext:
    units = [] if no_results else [retrieved_article()]
    return RetrievalContext(
        query="quyền thành lập doanh nghiệp",
        intent=IntentType.FACTUAL,
        temporal=TemporalQuery(has_temporal=False),
        executed_channels=[RetrievalChannel.VECTOR, RetrievalChannel.FULLTEXT],
        retrieved_units=units,
        graph_paths=(
            []
            if no_results
            else [
                GraphPath(
                    nodes=["doc", "doc_art1"],
                    relations=["CONTAINS"],
                    relation_ids=["rel-1"],
                    path_description="Document contains Article 1",
                    is_temporal_valid=True,
                )
            ]
        ),
        evidence=(
            []
            if no_results
            else [
                EvidenceItem(
                    unit_id="doc_art1",
                    evidence_type="vector",
                    matched_text="Quyền thành lập doanh nghiệp",
                    score=0.9,
                    source_path_id="rel-1",
                    is_sufficient=True,
                )
            ]
        ),
        metrics={"total_pipeline_latency_ms": 12},
        retrieval_mode="no_results" if no_results else "hybrid",
        capability_status="no_results" if no_results else "supported",
    )


def retrieved_article() -> RetrievedUnit:
    return RetrievedUnit(
        id="doc_art1",
        label="Article",
        content_raw="Quyền thành lập doanh nghiệp.",
        title="Quyền thành lập doanh nghiệp",
        document_id="doc",
        document_number="01/2026/QH",
        document_title="Luật thử nghiệm",
        source_url="https://example.test/doc",
        article_id="doc_art1",
        article_number="1",
        legal_status="ACTIVE",
        vector_score=0.9,
        bm25_score=0.8,
        final_score=0.7,
        citation_label="Điều 1, 01/2026/QH",
        deep_link="/documents/doc/units/doc_art1",
        retrieval_sources=["vector", "fulltext"],
    )
