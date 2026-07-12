"""
API Models — Pydantic schemas cho request, response và SSE events.
Single source of truth cho toàn bộ API contract.
"""
from __future__ import annotations

import json
from datetime import date
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


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
    role: Literal["user", "assistant", "system"]
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10_000)
    history: list[ChatMessage] = Field(default_factory=list)
    temporal_date: date | None = None


# ---------------------------------------------------------------------------
# SSE Event Models — không ghép JSON bằng f-string, encode qua đây
# ---------------------------------------------------------------------------

class ChatMetadataData(BaseModel):
    sources: list["RetrievedUnitDTO"] = Field(default_factory=list)
    intent: str
    retrieval_mode: str


class ChatTokenData(BaseModel):
    content: str


class ChatErrorData(BaseModel):
    code: str
    message: str


class ChatStreamEvent(BaseModel):
    event: Literal["metadata", "token", "error", "done"]
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
    return (
        f"event: {event}\n"
        f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
    )


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
    article_id: str | None = None    # Có khi label == "Clause" hoặc "Point"
    clause_id: str | None = None     # Có khi label == "Point"

    effective_from: date | None = None
    effective_to: date | None = None
    final_score: float | None = None


class GraphPathDTO(BaseModel):
    nodes: list[str]
    relations: list[str]
    path_description: str


class QueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=10_000)
    top_k: int = Field(default=10, ge=1, le=50)
    temporal_date: date | None = None   # phải truyền đầy đủ xuống service


class RetrievalResponse(BaseModel):
    """
    Response cho POST /api/v1/query.
    KHÔNG có `answer: str` — answer là trách nhiệm của /chat.
    """
    query: str
    retrieved_units: list[RetrievedUnitDTO]
    intent: str
    retrieval_mode: str
    graph_paths: list[GraphPathDTO]
    metrics: dict[str, int]


# ---------------------------------------------------------------------------
# Document Browser Contract — đủ hierarchy cho accordion UI
# ---------------------------------------------------------------------------

class PointDetail(BaseModel):
    id: str
    label: str        # thường là "a)", "b)", v.v.
    content_raw: str


class ClauseDetail(BaseModel):
    id: str
    number: str
    content_raw: str
    points: list[PointDetail] = Field(default_factory=list)


class ArticleDetail(BaseModel):
    id: str
    number: str
    title: str | None = None     # Optional: không phải điều nào cũng có tiêu đề
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
    relation_type: str          # từ RELATION_ENUM: "AMENDS", "REFERS_TO"...
    affected_units: list[str] = Field(default_factory=list)


class DocumentSummary(BaseModel):
    id: str
    number: str
    title: str | None = None         # Optional — ontology không bảo đảm mọi Document có title
    doc_type: str                    # "Law", "Decree", "Circular"... từ DOCUMENT_TYPES
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
    label: str                   # "Document", "Article", "Clause", "LegalConcept"...
    properties: dict[str, Any]   # number, title, status, v.v.


class GraphEdge(BaseModel):
    source: str
    target: str
    relation_type: str           # từ RELATION_ENUM


class GraphData(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    truncated: bool = False          # True nếu graph bị cắt do hard limit
    total_nodes: int | None = None   # Tổng nodes thực tế trước khi cắt
    total_edges: int | None = None   # Tổng edges thực tế trước khi cắt
    # Khi truncated=True, frontend hiển thị: "Đang hiển thị 500/1.247 nodes"


class PageMeta(BaseModel):
    page: int
    page_size: int
    total: int


class DocumentListResponse(BaseModel):
    items: list[DocumentSummary]
    pagination: PageMeta
