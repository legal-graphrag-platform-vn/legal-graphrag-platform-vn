from typing import List

from src.retrieval.models import EvidenceItem, GraphPath, RetrievedUnit


class EvidenceVerifier:
    """
    Đánh giá độ tin cậy và mức độ đầy đủ của bằng chứng (Evidence) thu thập được.
    """

    def __init__(self, score_threshold: float = 0.5):
        self.score_threshold = score_threshold

    def verify_and_build(self, units: List[RetrievedUnit], graph_paths: List[GraphPath]) -> List[EvidenceItem]:
        """
        Từ các unit đã rerank và graph path, tạo danh sách EvidenceItem.
        Đánh dấu xem evidence có đủ mạnh (is_sufficient) để trả lời không.
        """
        evidence_list = []
        
        # 1. Thu thập từ RetrievedUnits
        for unit in units:
            is_sufficient = False
            # Nếu unit có final_score cao hơn threshold, coi là đủ mạnh
            if unit.final_score is not None and unit.final_score >= self.score_threshold:
                is_sufficient = True
                
            evidence_type = "rerank" if unit.rerank_score is not None else "vector"
                
            evidence = EvidenceItem(
                unit_id=unit.id,
                evidence_type=evidence_type,
                matched_text=unit.content_raw,
                score=unit.final_score,
                is_sufficient=is_sufficient
            )
            evidence_list.append(evidence)
            
        # 2. Thu thập từ GraphPaths
        for path in graph_paths:
            # Gán evidence type là graph
            # Mỗi node trong path có thể coi là 1 evidence liên quan
            for node_id in path.nodes:
                # Tránh trùng lặp nếu node_id đã có trong units
                if not any(e.unit_id == node_id for e in evidence_list):
                    evidence = EvidenceItem(
                        unit_id=node_id,
                        evidence_type="graph",
                        matched_text=path.path_description,
                        is_sufficient=path.is_temporal_valid # Nếu graph path thoả mãn temporal -> đủ mạnh một phần
                    )
                    evidence_list.append(evidence)
                    
        return evidence_list
