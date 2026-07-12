"""
POST /api/v1/chat — SSE streaming endpoint.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from api.models import ChatRequest, encode_sse
from dependencies import get_rag_service
from services.interfaces import RAGService

router = APIRouter()


@router.post("/chat")
async def chat(
    request: ChatRequest,
    service: RAGService = Depends(get_rag_service),
) -> StreamingResponse:
    async def generate():
        try:
            # 1.   Stream events từ RAGService
            async for event in service.stream_chat(request):
                yield encode_sse(event.event, event.data)
        except asyncio.CancelledError:
            # 2.   Client ngắt kết nối — không gửi thêm gì, raise để cancel generator
            raise
        except Exception as exc:
            # 3.   Lỗi giữa stream — gửi error event rồi done, không để client treo
            yield encode_sse("error", {"code": "STREAM_ERROR", "message": str(exc)})
            yield encode_sse("done", {})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",    # Tắt nginx buffering để stream thật
        },
    )
