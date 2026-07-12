"""
RAGService Protocol — interface chung cho MockRAGService và GraphRAGService.
Cả Mock và Real phải implement đúng interface này.
"""
from __future__ import annotations

from datetime import date
from typing import AsyncIterator, Protocol

from api.models import (
    ArticleResponse,
    ChatRequest,
    ChatStreamEvent,
    DocumentDetail,
    DocumentListResponse,
    GraphData,
    RetrievalResponse,
)


class RAGService(Protocol):
    async def retrieve(
        self,
        query: str,
        top_k: int = 10,
        temporal_date: date | None = None,
    ) -> RetrievalResponse: ...

    async def stream_chat(
        self,
        request: ChatRequest,
    ) -> AsyncIterator[ChatStreamEvent]: ...

    async def list_documents(
        self,
        page: int,
        page_size: int,
        filters: dict,
    ) -> DocumentListResponse: ...

    async def get_document_detail(self, doc_id: str) -> DocumentDetail: ...

    async def get_article(self, article_id: str) -> ArticleResponse: ...

    async def get_document_graph(
        self,
        doc_id: str,
        depth: int,
        node_limit: int,
        edge_limit: int,
    ) -> GraphData: ...
