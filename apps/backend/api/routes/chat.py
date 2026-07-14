"""
POST /api/v1/chat — SSE streaming endpoint.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from api.error_handlers import stream_error_contract
from api.models import ChatRequest, encode_sse
from dependencies import get_chat_service
from services.interfaces import ChatService
from src.generation.errors import AnswerGenerationError
from src.retrieval.errors import RetrievalError

router = APIRouter()


@router.post("/chat")
async def chat(
    request: ChatRequest,
    service: ChatService = Depends(get_chat_service),
) -> StreamingResponse:
    async def generate():
        try:
            # 1.   Stream events từ RAGService
            async for event in service.stream_chat(request):
                yield encode_sse(event.event, event.data)
        except asyncio.CancelledError:
            # 2.   Client ngắt kết nối — không gửi thêm gì, raise để cancel generator
            raise
        except (AnswerGenerationError, RetrievalError) as exc:
            code, message = stream_error_contract(exc)
            yield encode_sse(
                "error",
                {"code": code, "message": message},
            )
            yield encode_sse("done", {"status": "error", "citation_count": 0})
        except Exception:
            yield encode_sse(
                "error",
                {"code": "STREAM_ERROR", "message": "Đã xảy ra lỗi nội bộ."},
            )
            yield encode_sse("done", {"status": "error", "citation_count": 0})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Tắt nginx buffering để stream thật
        },
    )
