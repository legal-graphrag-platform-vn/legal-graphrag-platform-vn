"""
Document browser routes — GET /api/v1/documents, /articles.
Tất cả endpoints có pagination và hard limits cho graph.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from api.models import (
    ArticleResponse,
    DocumentDetail,
    DocumentLegalStatus,
    DocumentListResponse,
    GraphData,
)
from dependencies import get_rag_service
from services.interfaces import RAGService

router = APIRouter()


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    doc_type: str | None = None,          # "Law", "Decree", "Circular"...
    issuer: str | None = None,
    status: DocumentLegalStatus | None = None,
    year: int | None = None,
    service: RAGService = Depends(get_rag_service),
) -> DocumentListResponse:
    # 1.   Truyền status.value (string) thay vì enum object vào repository
    filters = {
        "doc_type": doc_type,
        "issuer": issuer,
        "status": status.value if status else None,
        "year": year,
    }
    return await service.list_documents(page, page_size, filters)


@router.get("/documents/{doc_id}", response_model=DocumentDetail)
async def get_document(
    doc_id: str,
    service: RAGService = Depends(get_rag_service),
) -> DocumentDetail:
    # 2.   Chi tiết văn bản với hierarchy đầy đủ Chapter→Article→Clause→Point
    return await service.get_document_detail(doc_id)


@router.get("/documents/{doc_id}/graph", response_model=GraphData)
async def get_document_graph(
    doc_id: str,
    depth: int = Query(default=1, ge=1, le=2),            # Hard limit: depth <= 2
    node_limit: int = Query(default=100, ge=1, le=500),    # Hard limit: nodes <= 500
    edge_limit: int = Query(default=300, ge=1, le=1000),   # Hard limit: edges <= 1000
    service: RAGService = Depends(get_rag_service),
) -> GraphData:
    # 3.   Khi subgraph bị cắt, response có truncated=True + total_nodes/total_edges
    # Frontend hiển thị: "Đang hiển thị 500/1.247 nodes"
    return await service.get_document_graph(doc_id, depth, node_limit, edge_limit)


@router.get("/articles/{article_id}", response_model=ArticleResponse)
async def get_article(
    article_id: str,
    service: RAGService = Depends(get_rag_service),
) -> ArticleResponse:
    # 4.   Trả về article kèm parent DocumentSummary để frontend hiển thị breadcrumb
    return await service.get_article(article_id)
