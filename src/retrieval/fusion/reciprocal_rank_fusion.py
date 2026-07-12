from typing import List

from src.retrieval.models import RetrievedUnit


class ReciprocalRankFusion:
    """
    Kết hợp kết quả từ Vector Search và BM25 Search sử dụng RRF (Reciprocal Rank Fusion).
    """

    def __init__(self, k: int = 60):
        # Hệ số k trong RRF (mặc định thường là 60)
        self.k = k

    def fuse(
        self, vector_results: List[RetrievedUnit], bm25_results: List[RetrievedUnit], top_n: int = 20
    ) -> List[RetrievedUnit]:
        """
        Gộp và tính điểm RRF cho các unit.
        """
        
        # Từ điển lưu điểm RRF, map theo unit.id
        rrf_scores = {}
        # Từ điển lưu unit object, dùng để truy xuất sau khi tính xong
        unit_map = {}
        
        # Hàm hỗ trợ tính rank
        def add_ranks(results: List[RetrievedUnit], score_type: str):
            for rank, unit in enumerate(results, start=1):
                if unit.id not in rrf_scores:
                    rrf_scores[unit.id] = 0.0
                    unit_map[unit.id] = unit
                    
                # RRF Score = 1 / (k + rank)
                rrf_scores[unit.id] += 1.0 / (self.k + rank)
                
                # Giữ lại metadata score ban đầu để tiện debug/ablation
                existing_unit = unit_map[unit.id]
                if score_type == "vector" and unit.vector_score is not None:
                    existing_unit.vector_score = unit.vector_score
                if score_type == "bm25" and unit.bm25_score is not None:
                    existing_unit.bm25_score = unit.bm25_score

        # 1. Tính rank cho Vector results
        add_ranks(vector_results, "vector")
        
        # 2. Tính rank cho BM25 results
        add_ranks(bm25_results, "bm25")
        
        # 3. Gán điểm RRF vào final_score tạm thời và sắp xếp
        fused_units = []
        for uid, score in rrf_scores.items():
            unit = unit_map[uid]
            # Ta có thể dùng final_score tạm thời cho RRF score trước khi Rerank
            unit.final_score = score
            fused_units.append(unit)
            
        # Sắp xếp giảm dần theo điểm RRF
        fused_units.sort(key=lambda x: x.final_score or 0.0, reverse=True)
        
        # 4. Trả về top_n
        return fused_units[:top_n]
