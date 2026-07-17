"""Build source-preserving evidence records from retrieval results."""

from src.retrieval.models import EvidenceItem, GraphPath, RetrievedUnit


_EVIDENCE_TYPE = {"vector": "vector", "fulltext": "bm25", "graph": "graph"}


class EvidenceVerifier:
    def verify_and_build(
        self, units: list[RetrievedUnit], graph_paths: list[GraphPath]
    ) -> list[EvidenceItem]:
        evidence: list[EvidenceItem] = []
        for unit in units:
            for source in unit.retrieval_sources:
                evidence.append(
                    EvidenceItem(
                        unit_id=unit.id,
                        evidence_type=_EVIDENCE_TYPE[source],
                        matched_text=unit.content_raw,
                        score=_score_for_source(unit, source),
                        is_eligible=bool(unit.content_raw.strip()),
                    )
                )
            if unit.rerank_score is not None:
                evidence.append(
                    EvidenceItem(
                        unit_id=unit.id,
                        evidence_type="rerank",
                        matched_text=unit.content_raw,
                        score=unit.rerank_score,
                        is_eligible=bool(unit.content_raw.strip()),
                    )
                )

        existing_ids = {item.unit_id for item in evidence}
        for path_index, path in enumerate(graph_paths):
            for node in path.nodes:
                node_id = node.citable_unit_id or node.node_id
                if node_id in existing_ids:
                    continue
                evidence.append(
                    EvidenceItem(
                        unit_id=node_id,
                        evidence_type="graph",
                        matched_text=path.path_description,
                        source_path_id=f"path-{path_index}",
                        is_eligible=False,
                    )
                )
                existing_ids.add(node_id)
        return evidence


def _score_for_source(unit: RetrievedUnit, source: str) -> float | None:
    if source == "vector":
        return unit.vector_score
    if source == "fulltext":
        return unit.bm25_score
    return unit.graph_score
