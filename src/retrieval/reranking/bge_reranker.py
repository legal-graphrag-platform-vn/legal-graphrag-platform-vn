import os
from typing import List

from src.retrieval.models import RetrievedUnit
from src.retrieval.reranking.base import BaseReranker

try:
    from FlagEmbedding import FlagReranker
except ImportError:
    FlagReranker = None


class BGEReranker(BaseReranker):
    """
    Sử dụng BAAI/bge-reranker-v2-m3 để đánh giá lại điểm số (rerank)
    giữa câu truy vấn và nội dung của các RetrievedUnit.
    """

    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3"):
        if FlagReranker is None:
            raise ImportError(
                "Thư viện FlagEmbedding chưa được cài đặt. "
                "Vui lòng cài đặt qua `uv add FlagEmbedding` hoặc dùng FakeReranker."
            )
        # Sử dụng fp16 để tăng tốc độ nếu có GPU, mặc định dùng CPU hoặc GPU tùy môi trường
        use_fp16 = os.getenv("RERANKER_FP16", "false").lower() == "true"
        self.reranker = FlagReranker(model_name, use_fp16=use_fp16)

    def rerank(self, query: str, units: List[RetrievedUnit], top_n: int = 10) -> List[RetrievedUnit]:
        if not units:
            return []

        # Chuẩn bị input cho reranker: List of [query, passage]
        pairs = [[query, unit.content_raw] for unit in units]
        
        # Lấy điểm số từ model
        scores = self.reranker.compute_score(pairs)
        
        # Nếu chỉ có 1 phần tử, FlagEmbedding trả về float thay vì list
        if isinstance(scores, float):
            scores = [scores]
            
        # Gán lại điểm cho các units
        for unit, score in zip(units, scores):
            unit.rerank_score = float(score)
            unit.final_score = unit.rerank_score
            
        # Sắp xếp lại theo điểm mới
        units.sort(key=lambda x: x.final_score or -999.0, reverse=True)
        
        return units[:top_n]
