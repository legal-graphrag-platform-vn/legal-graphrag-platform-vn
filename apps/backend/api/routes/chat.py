"""
POST /api/v1/chat — grounded conversation SSE endpoint (Plan 19 §2, §4).
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from api.models import ConversationChatRequest, encode_sse
from dependencies import get_chat_service, require_user_owner
from observability import bind_trace, clear_trace, log_event
from persistence.errors import ConversationBusyError, ConversationNotFoundError
from services.interfaces import ChatService

router = APIRouter()


@router.post("/chat")
async def chat(
    request: ConversationChatRequest,
    http_request: Request,
    service: ChatService = Depends(get_chat_service),
) -> StreamingResponse:
    # Login required: rejects unauthenticated callers with HTTP 401.
    owner = require_user_owner(http_request)

    async def generate():
        bind_trace(
            turn_id=request.client_turn_id,
            conversation_id=request.conversation_id,
            owner_id=getattr(owner, "owner_principal_id", None),
        )
        log_event("request.received", message_chars=len(request.message))
        try:
            async for event in service.stream_chat(request, owner):
                yield encode_sse(event.event, event.data)
        except asyncio.CancelledError:
            raise
        except ConversationNotFoundError:
            yield encode_sse(
                "error",
                {
                    "code": "CONVERSATION_NOT_FOUND",
                    "message": "Không tìm thấy hội thoại.",
                },
            )
            yield encode_sse("done", {"status": "error", "citation_count": 0})
        except ConversationBusyError:
            log_event("request.busy", "error")
            yield encode_sse(
                "error",
                {
                    "code": "CONVERSATION_BUSY",
                    "message": "Hội thoại đang được xử lý. Vui lòng thử lại sau giây lát.",
                },
            )
            yield encode_sse(
                "done",
                {"status": "error", "citation_count": 0, "retry_after_ms": 1000},
            )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).exception("Chat stream generation error: %s", exc)
            log_event("stream.error", "error", error_type=type(exc).__name__)
            yield encode_sse(
                "error",
                {"code": "STREAM_ERROR", "message": "Đã xảy ra lỗi nội bộ."},
            )
            yield encode_sse("done", {"status": "error", "citation_count": 0})
        finally:
            clear_trace()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
