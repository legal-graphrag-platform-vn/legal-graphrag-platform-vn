from abc import ABC, abstractmethod
from src.retrieval.models import RetrievedUnit


class BaseReranker(ABC):
    """
    Interface chuẩn cho các Reranker models.
    """

    @abstractmethod
    def rerank(
        self, query: str, units: list[RetrievedUnit], top_n: int = 10
    ) -> list[RetrievedUnit]:
        """
        Rerank danh sách các RetrievedUnit dựa trên query.
        Cập nhật rerank_score và final_score cho các unit.
        """
        pass


class FakeReranker(BaseReranker):
    """
    Fake Reranker dùng trong Unit Tests hoặc môi trường không có GPU.
    Chỉ đơn giản là pass-through kết quả cũ và gán lại điểm ngẫu nhiên hoặc giữ nguyên điểm cũ.
    """

    def rerank(
        self, query: str, units: list[RetrievedUnit], top_n: int = 10
    ) -> list[RetrievedUnit]:
        # Giả lập rerank bằng cách lấy chính xác điểm cũ chia 2
        for unit in units:
            unit.rerank_score = (unit.final_score or 0.0) * 0.9
            unit.final_score = unit.rerank_score

        return sorted(
            units,
            key=lambda unit: (-(unit.final_score or 0.0), unit.id),
        )[:top_n]
