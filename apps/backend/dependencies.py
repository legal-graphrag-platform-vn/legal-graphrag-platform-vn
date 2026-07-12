"""
FastAPI DI functions — đọc service từ app.state.container.
"""
from __future__ import annotations

from fastapi import Request

from services.interfaces import RAGService


def get_rag_service(request: Request) -> RAGService:
    # 1.   Lấy RAGService từ container đã được inject vào app.state trong lifespan
    return request.app.state.container.rag_service
