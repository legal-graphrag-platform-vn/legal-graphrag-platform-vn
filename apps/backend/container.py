"""
DI Container — build và giữ application-level dependencies.
Lưu trong app.state, không dùng global singleton.
"""
from __future__ import annotations

from services.interfaces import RAGService
from services.mock_rag_service import MockRAGService
from settings import Settings


class Container:
    def __init__(self, rag_service: RAGService):
        # 1.   Giữ các dependency
        self.rag_service = rag_service
        self._driver = None  # Sẽ được gán khi APP_MODE=graphrag (Step 4)

    async def close(self) -> None:
        # 2.   Đóng resources khi shutdown
        if self._driver is not None:
            self._driver.close()


def build_container(settings: Settings) -> Container:
    """
    Factory tạo Container theo app_mode.
    """
    if settings.app_mode == "mock":
        # 3.   Mock mode — không cần Neo4j, LLM, hay bất kỳ external service nào
        return Container(rag_service=MockRAGService())

    else:
        # 4.   🔒 LOCKED — chỉ kích hoạt sau Milestone A pass
        # Uncomment khi Step 4 ready:
        # from src.retrieval.retriever.hybrid import HybridRetriever
        # from src.infrastructure.neo4j.document_repo import DocumentRepository
        # from services.graphrag_service import GraphRAGService
        # driver = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))
        # retriever = HybridRetriever(...)
        # repo = DocumentRepository(driver)
        # container = Container(rag_service=GraphRAGService(retriever, repo))
        # container._driver = driver
        # return container
        raise NotImplementedError(
            "APP_MODE=graphrag chưa được kích hoạt. "
            "Cần Milestone A pass trước: vector index ONLINE, graph-quality sạch, "
            "embedding coverage = 100%."
        )
