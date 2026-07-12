"""
POST /api/v1/query — Non-streaming retrieval endpoint.
Trả về RetrievalContext đầy đủ, KHÔNG có answer field.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from api.models import QueryRequest, RetrievalResponse
from dependencies import get_rag_service
from services.interfaces import RAGService

router = APIRouter()


@router.post("/query", response_model=RetrievalResponse)
async def query(
    request: QueryRequest,
    service: RAGService = Depends(get_rag_service),
) -> RetrievalResponse:
    # 1.   temporal_date phải được truyền xuống service — không bị bỏ mất
    return await service.retrieve(
        query=request.query,
        top_k=request.top_k,
        temporal_date=request.temporal_date,
    )
