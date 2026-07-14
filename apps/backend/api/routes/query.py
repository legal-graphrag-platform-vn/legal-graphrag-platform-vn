"""
POST /api/v1/query — Non-streaming retrieval endpoint.
Trả về RetrievalContext đầy đủ, KHÔNG có answer field.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.models import QueryRequest, RetrievalResponse
from dependencies import get_query_service
from services.interfaces import QueryService

router = APIRouter()


@router.post("/query", response_model=RetrievalResponse)
async def query(
    request: QueryRequest,
    service: QueryService = Depends(get_query_service),
) -> RetrievalResponse:
    return await service.retrieve(request)
