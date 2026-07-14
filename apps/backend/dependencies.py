"""
FastAPI DI functions — đọc service từ app.state.container.
"""

from __future__ import annotations

from fastapi import Request

from services.errors import BackendFeatureUnavailableError
from services.interfaces import ChatService, DocumentBrowserService, QueryService


async def get_query_service(request: Request) -> QueryService:
    return request.app.state.container.query_service


async def get_document_service(request: Request) -> DocumentBrowserService:
    return request.app.state.container.document_service


async def get_chat_service(request: Request) -> ChatService:
    service = request.app.state.container.chat_service
    if service is None:
        raise BackendFeatureUnavailableError(
            "Answer generation is not enabled for this runtime profile"
        )
    return service
