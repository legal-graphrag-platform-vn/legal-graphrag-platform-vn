"""
FastAPI DI functions — đọc service từ app.state.container.
"""

from __future__ import annotations

from fastapi import Request

from services.errors import BackendFeatureUnavailableError
from services.interfaces import QueryService, RAGService


async def get_query_service(request: Request) -> QueryService:
    return request.app.state.container.query_service


async def get_rag_service(request: Request) -> RAGService:
    service = request.app.state.container.rag_service
    if service is None:
        raise BackendFeatureUnavailableError(
            "This endpoint is not available in retrieval-only GraphRAG mode"
        )
    return service
