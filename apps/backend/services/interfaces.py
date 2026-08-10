"""
RAGService Protocol — interface chung cho MockRAGService và GraphRAGService.
Cả Mock và Real phải implement đúng interface này.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import AsyncIterator, Protocol, TypeVar

from api.models import (
    ArticleResponse,
    ChatStreamEvent,
    ConversationChatRequest,
    DocumentDetail,
    DocumentListResponse,
    GraphData,
    QueryRequest,
    RetrievalResponse,
)
from persistence.domain import Owner
from src.retrieval.models import PreparedRetrievalRequest, RetrievalContext
from src.retrieval.planning.models import UnlinkedSemanticPlan
from src.retrieval.planning.ports import QueryPlannerPort as QueryPlannerPort
from src.generation.models import AnswerGenerationRequest, AnswerResponse
from src.shared.retrieval_contract import QueryProcessingResult, RetrievalRequest
from src.retrieval.resolved_reference import RetrievalExecutionContext


ResultT = TypeVar("ResultT")


class RetrievalApplicationPort(Protocol):
    async def retrieve_context(
        self,
        request: RetrievalRequest,
        *,
        execution_context: RetrievalExecutionContext | None = None,
    ) -> RetrievalContext: ...


class SyncRetrievalRuntime(Protocol):
    """Minimal runtime surface consumed by the backend adapter."""

    def retrieve(
        self,
        request: RetrievalRequest,
        *,
        execution_context: RetrievalExecutionContext | None = None,
    ) -> RetrievalContext: ...

    def prepare(
        self,
        request: RetrievalRequest,
        *,
        execution_context: RetrievalExecutionContext | None = None,
    ) -> PreparedRetrievalRequest: ...

    def execute(
        self,
        prepared: PreparedRetrievalRequest,
        *,
        plan: UnlinkedSemanticPlan | None = None,
    ) -> RetrievalContext: ...

    def close(self) -> None: ...


class AsyncRetrievalRunner(Protocol):
    async def run(self, call: Callable[[], ResultT]) -> ResultT: ...

    async def aclose(self) -> int: ...


class QueryService(Protocol):
    async def retrieve(self, request: QueryRequest) -> RetrievalResponse: ...


class DocumentBrowserService(Protocol):
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

    async def aclose(self) -> None: ...


class AnswerGeneratorPort(Protocol):
    async def generate(self, request: AnswerGenerationRequest) -> AnswerResponse: ...

    async def aclose(self) -> None: ...


class QueryProcessorPort(Protocol):
    """Async surface over the five-field query processor (Query Processor)."""

    async def process(
        self,
        current_query: str,
        conversation_history: Sequence[Mapping[str, str]] = (),
    ) -> QueryProcessingResult: ...


class ChatService(Protocol):
    async def stream_chat(
        self,
        request: ConversationChatRequest,
        owner: Owner,
    ) -> AsyncIterator[ChatStreamEvent]: ...


class RAGService(ChatService, Protocol):
    async def stream_chat(
        self,
        request: ConversationChatRequest,
        owner: Owner,
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
