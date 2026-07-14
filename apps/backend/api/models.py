"""
API Models — Pydantic schemas cho request, response và SSE events.
Single source of truth cho toàn bộ API contract.
"""

from __future__ import annotations

import json
from datetime import date
from enum import Enum
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from src.shared.retrieval_contract import IntentType


# ---------------------------------------------------------------------------
# Enums — phải sync với src/shared/ontology/contract.py
# Test parity: tests/test_contract_parity.py
# ---------------------------------------------------------------------------


class DocumentLegalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    NOT_YET_EFFECTIVE = "NOT_YET_EFFECTIVE"
    PARTIALLY_EFFECTIVE = "PARTIALLY_EFFECTIVE"
    REPLACED = "REPLACED"
    REPEALED = "REPEALED"
    EXPIRED = "EXPIRED"


# ---------------------------------------------------------------------------
# Chat Contract
# ---------------------------------------------------------------------------


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=4000)
    history: list[ChatMessage] = Field(default_factory=list)
    document_ids: list[str] = Field(default_factory=list)
    query_date: date | None = None
    temporal_date: date | None = None
    force_intent: IntentType | None = None
    enable_reranker: bool | None = None

    @model_validator(mode="after")
    def validate_chat_request(self) -> "ChatRequest":
        self.message = self.message.strip()
        if not self.message:
            raise ValueError("Message must not be blank")
        if self.query_date is not None and self.temporal_date is not None:
            if self.query_date != self.temporal_date:
                raise ValueError("query_date conflicts with temporal_date")
        elif self.temporal_date is not None:
            self.query_date = self.temporal_date
        normalized_ids = [value.strip() for value in self.document_ids]
        if any(not value for value in normalized_ids):
            raise ValueError("document_ids must not contain blank values")
        if len(normalized_ids) != len(set(normalized_ids)):
            raise ValueError("document_ids must be unique")
        self.document_ids = normalized_ids
        return self


# ---------------------------------------------------------------------------
# SSE Event Models — không ghép JSON bằng f-string, encode qua đây
# ---------------------------------------------------------------------------


class ChatMetadataData(BaseModel):
    sources: list["RetrievedUnitDTO"] = Field(default_factory=list)
    intent: str
    strategy: str
    retrieval_mode: str
    retrieval_contract_version: str
    answer_contract_version: str
    cannot_answer: bool


class ChatTokenData(BaseModel):
    content: str


class ChatCitationData(BaseModel):
    unit_id: str
    citation_label: str
    document_id: str
    article_id: str | None = None
    clause_id: str | None = None
    deep_link: str


class ChatDoneData(BaseModel):
    status: Literal["completed", "cannot_answer", "error"]
    citation_count: int = 0
    confidence: float | None = None
    provider: str | None = None
    model: str | None = None


class ChatErrorData(BaseModel):
    code: str
    message: str


class ChatStreamEvent(BaseModel):
    event: Literal["metadata", "token", "citation", "error", "done"]
    data: dict[str, Any]


def encode_sse(event: str, data: BaseModel | dict[str, Any]) -> str:
    """
    Encoder chung cho SSE events.
    Đảm bảo ensure_ascii=False (quan trọng cho tiếng Việt).
    """
    if isinstance(data, BaseModel):
        payload = data.model_dump(mode="json")
    else:
        payload = data
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


# ---------------------------------------------------------------------------
# Retrieval Contract — tách hoàn toàn khỏi answer generation
# ---------------------------------------------------------------------------


class RetrievedUnitDTO(BaseModel):
    id: str
    label: Literal["Article", "Clause", "Point"]
    content_raw: str
    citation_label: str

    # 1. Parent IDs đầy đủ để frontend tạo deep link:
    # /explorer?document={document_id}&article={article_id}&clause={clause_id}
    document_id: str
    document_number: str | None = None
    document_title: str | None = None
    title: str | None = None
    source_url: str | None = None
    article_id: str | None = None  # Article ID hoặc parent Article ID
    clause_id: str | None = None  # Clause ID hoặc parent Clause ID
    article_number: str | None = None
    clause_number: str | None = None
    version_family_id: str | None = None

    effective_from: date | None = None
    effective_to: date | None = None
    legal_status: str | None = None
    vector_score: float | None = None
    bm25_score: float | None = None
    graph_score: float | None = None
    rerank_score: float | None = None
    final_score: float | None = None
    deep_link: str
    retrieval_sources: list[Literal["vector", "fulltext", "graph"]]


class GraphPathDTO(BaseModel):
    nodes: list[str]
    relations: list[str]
    relation_ids: list[str]
    path_description: str
    is_temporal_valid: bool


class EvidenceDTO(BaseModel):
    unit_id: str
    evidence_type: Literal["vector", "bm25", "graph", "temporal", "rerank"]
    matched_text: str | None = None
    score: float | None = None
    source_path_id: str | None = None
    is_sufficient: bool = False


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=4000)
    top_k: int | None = Field(default=None, ge=1, le=200)
    candidate_k: int | None = Field(default=None, ge=1, le=200)
    document_ids: list[str] = Field(default_factory=list)
    query_date: date | None = None
    force_intent: IntentType | None = None
    enable_reranker: bool | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_temporal_date_alias(cls, data: object) -> object:
        if not isinstance(data, dict) or "temporal_date" not in data:
            return data
        normalized = dict(data)
        alias_value = normalized.pop("temporal_date")
        canonical_value = normalized.get("query_date")
        if canonical_value is not None and canonical_value != alias_value:
            raise ValueError("query_date conflicts with temporal_date")
        normalized["query_date"] = alias_value
        return normalized

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Query must not be blank")
        return normalized

    @field_validator("document_ids")
    @classmethod
    def validate_document_ids(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("document_ids must not contain blank values")
        if len(normalized) != len(set(normalized)):
            raise ValueError("document_ids must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_limits(self) -> "QueryRequest":
        if (
            self.top_k is not None
            and self.candidate_k is not None
            and self.top_k > self.candidate_k
        ):
            raise ValueError("top_k must not exceed candidate_k")
        return self


class RetrievalResponse(BaseModel):
    """
    Response cho POST /api/v1/query.
    KHÔNG có `answer: str` — answer là trách nhiệm của /chat.
    """

    contract_version: str
    query: str
    retrieved_units: list[RetrievedUnitDTO]
    intent: str
    strategy: str
    retrieval_mode: str
    executed_channels: list[str]
    force_intent_used: bool
    temporal_source: str
    decision_reason_code: str
    decision_reason: str
    capability_status: Literal["supported", "no_results"]
    filters: dict[str, Any]
    reranker_applied: bool
    graph_paths: list[GraphPathDTO]
    evidence: list[EvidenceDTO]
    metrics: dict[str, Any]


class ValidationIssue(BaseModel):
    location: list[str | int]
    message: str
    error_type: str


class APIErrorResponse(BaseModel):
    code: str
    message: str
    request_id: str | None = None
    details: list[ValidationIssue] | dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Document Browser Contract — đủ hierarchy cho accordion UI
# ---------------------------------------------------------------------------


class PointDetail(BaseModel):
    id: str
    label: str  # thường là "a)", "b)", v.v.
    content_raw: str


class ClauseDetail(BaseModel):
    id: str
    number: str
    content_raw: str
    points: list[PointDetail] = Field(default_factory=list)


class ArticleDetail(BaseModel):
    id: str
    number: str
    title: str | None = None  # Optional: không phải điều nào cũng có tiêu đề
    content_raw: str
    clauses: list[ClauseDetail] = Field(default_factory=list)


class ChapterDetail(BaseModel):
    id: str
    number: str
    title: str | None = None
    articles: list[ArticleDetail] = Field(default_factory=list)


class DocumentRelation(BaseModel):
    doc_id: str
    doc_number: str
    relation_type: str  # từ RELATION_ENUM: "AMENDS", "REFERS_TO"...
    affected_units: list[str] = Field(default_factory=list)


class DocumentSummary(BaseModel):
    id: str
    number: str
    title: str | None = None  # Optional — ontology không bảo đảm mọi Document có title
    doc_type: str  # "Law", "Decree", "Circular"... từ DOCUMENT_TYPES
    issuer_name: str | None = None
    issued_date: date | None = None
    effective_from: date | None = None
    status: DocumentLegalStatus


class DocumentDetail(DocumentSummary):
    chapters: list[ChapterDetail] = Field(default_factory=list)
    # 2. ungrouped_articles: Document có thể chứa Article trực tiếp (không qua Chapter).
    # Ví dụ: Nghị định ngắn thường không có Chương, chỉ có Điều.
    ungrouped_articles: list[ArticleDetail] = Field(default_factory=list)
    relations: list[DocumentRelation] = Field(default_factory=list)


class ArticleResponse(BaseModel):
    """Response cho GET /api/v1/articles/{article_id}"""

    document: DocumentSummary
    article: ArticleDetail
    related_units: list[DocumentRelation] = Field(default_factory=list)


class GraphNode(BaseModel):
    id: str
    label: str  # "Document", "Article", "Clause", "LegalConcept"...
    properties: dict[str, Any]  # number, title, status, v.v.


class GraphEdge(BaseModel):
    source: str
    target: str
    relation_type: str  # từ RELATION_ENUM


class GraphData(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    truncated: bool = False  # True nếu graph bị cắt do hard limit
    total_nodes: int | None = None  # Tổng nodes thực tế trước khi cắt
    total_edges: int | None = None  # Tổng edges thực tế trước khi cắt
    # Khi truncated=True, frontend hiển thị: "Đang hiển thị 500/1.247 nodes"


class PageMeta(BaseModel):
    page: int
    page_size: int
    total: int


class DocumentListResponse(BaseModel):
    items: list[DocumentSummary]
    pagination: PageMeta
