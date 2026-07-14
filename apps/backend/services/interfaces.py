"""
RAGService Protocol — interface chung cho MockRAGService và GraphRAGService.
Cả Mock và Real phải implement đúng interface này.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import AsyncIterator, Protocol, TypeVar

from api.models import (
    ArticleResponse,
    ChatRequest,
    ChatStreamEvent,
    DocumentDetail,
    DocumentListResponse,
    GraphData,
    QueryRequest,
    RetrievalResponse,
)
from src.retrieval.models import RetrievalContext
from src.generation.models import AnswerGenerationRequest, AnswerResponse
from src.shared.retrieval_contract import RetrievalRequest


ResultT = TypeVar("ResultT")


class RetrievalApplicationPort(Protocol):
    async def retrieve_context(
        self,
        request: RetrievalRequest,
    ) -> RetrievalContext: ...


class SyncRetrievalRuntime(Protocol):
    """Minimal runtime surface consumed by the backend adapter."""

    def retrieve(self, request: RetrievalRequest) -> RetrievalContext: ...

    def close(self) -> None: ...


class AsyncRetrievalRunner(Protocol):
    async def run(self, call: Callable[[], ResultT]) -> ResultT: ...

    async def aclose(self) -> int: ...


class QueryService(Protocol):
    async def retrieve(self, request: QueryRequest) -> RetrievalResponse: ...


class AnswerGeneratorPort(Protocol):
    async def generate(self, request: AnswerGenerationRequest) -> AnswerResponse: ...

    async def aclose(self) -> None: ...


class ChatService(Protocol):
    async def stream_chat(
        self,
        request: ChatRequest,
    ) -> AsyncIterator[ChatStreamEvent]: ...


class RAGService(ChatService, Protocol):
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
