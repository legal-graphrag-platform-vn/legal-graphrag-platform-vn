from typing import Dict, List

from src.retrieval.evidence.verifier import EvidenceVerifier
from src.retrieval.models import (
    GraphPath,
    IntentType,
    RetrievalContext,
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
        units: List[RetrievedUnit],
        graph_paths: List[GraphPath],
        metrics: Dict[str, int]
    ) -> RetrievalContext:
        """
        Build RetrievalContext.
        Quyết định retrieval_mode và penalty.
        """
        
        # 1. Xác định retrieval mode
        if not units and not graph_paths:
            retrieval_mode = "text_only_fallback"
            confidence_penalty = True
        elif not graph_paths:
            retrieval_mode = "vector_only"
            confidence_penalty = True
        else:
            retrieval_mode = "hybrid"
            confidence_penalty = False

        # 2. Sinh Evidence từ verifier
        evidence = self.verifier.verify_and_build(units, graph_paths)

        # 3. Tính toán lại Metrics bổ sung nếu cần
        final_metrics = metrics.copy()
        final_metrics["total_evidence_items"] = len(evidence)
        final_metrics["sufficient_evidence_items"] = sum(1 for e in evidence if e.is_sufficient)

        # 4. Trả về Bundle
        return RetrievalContext(
            query=query,
            intent=intent,
            temporal=temporal,
            retrieved_units=units,
            graph_paths=graph_paths,
            evidence=evidence,
            metrics=final_metrics,
            retrieval_mode=retrieval_mode,
            confidence_penalty=confidence_penalty
        )
