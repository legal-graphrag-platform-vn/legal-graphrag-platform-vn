from typing import Any

from src.retrieval.evidence.verifier import EvidenceVerifier
from src.retrieval.models import (
    GraphPath,
    IntentType,
    RetrievalChannel,
    RetrievalContext,
    RetrievalDecision,
    RetrievalFilters,
    RetrievedUnit,
    TemporalQuery,
)


class ContextBuilder:
    """
    Tập hợp và đóng gói tất cả các thành phần Retrieval thành RetrievalContext hoàn chỉnh.
    """

    def __init__(self, verifier: EvidenceVerifier):
        self.verifier = verifier

    def build_context(
        self,
        query: str,
        intent: IntentType,
        temporal: TemporalQuery,
        units: list[RetrievedUnit],
        graph_paths: list[GraphPath],
        metrics: dict[str, Any],
        *,
        decision: RetrievalDecision | None = None,
        filters: RetrievalFilters | None = None,
        executed_channels: list[RetrievalChannel] | None = None,
        reranker_applied: bool = False,
    ) -> RetrievalContext:
        """
        Build RetrievalContext.
        Quyết định retrieval_mode và penalty.
        """

        # 1. Xác định retrieval mode
        sources = {source for unit in units for source in unit.retrieval_sources}
        if not units and not graph_paths:
            retrieval_mode = "no_results"
            confidence_penalty = True
        elif sources == {"vector"} and not graph_paths:
            retrieval_mode = "vector_only"
            confidence_penalty = True
        elif sources == {"fulltext"} and not graph_paths:
            retrieval_mode = "fulltext_only"
            confidence_penalty = True
        elif "graph" in sources or graph_paths:
            retrieval_mode = "vector_graph" if "fulltext" not in sources else "hybrid"
            confidence_penalty = False
        else:
            retrieval_mode = "hybrid"
            confidence_penalty = False

        # 2. Sinh Evidence từ verifier
        evidence = self.verifier.verify_and_build(units, graph_paths)

        # 3. Tính toán lại Metrics bổ sung nếu cần
        final_metrics = metrics.copy()
        final_metrics["total_evidence_items"] = len(evidence)
        final_metrics["sufficient_evidence_items"] = sum(
            1 for e in evidence if e.is_sufficient
        )

        # 4. Trả về Bundle
        context_fields: dict[str, Any] = {}
        if decision is not None:
            context_fields = {
                "contract_version": decision.contract_version,
                "strategy": decision.strategy,
                "temporal_source": decision.temporal_source,
                "decision_reason_code": decision.decision_reason_code,
                "decision_reason": decision.decision_reason,
                "force_intent_used": decision.force_intent_used,
                "filters_applied": filters or RetrievalFilters(),
                "executed_channels": executed_channels or [],
                "reranker_applied": reranker_applied,
                "capability_status": "supported" if units else "no_results",
            }
        return RetrievalContext(
            query=query,
            intent=intent,
            temporal=temporal,
            retrieved_units=units,
            graph_paths=graph_paths,
            evidence=evidence,
            metrics=final_metrics,
            retrieval_mode=retrieval_mode,
            confidence_penalty=confidence_penalty,
            **context_fields,
        )
