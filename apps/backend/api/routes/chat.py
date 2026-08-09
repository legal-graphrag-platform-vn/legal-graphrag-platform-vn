"""
POST /api/v1/chat — grounded conversation SSE endpoint (Plan 19 §2, §4).
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from api.models import ConversationChatRequest, encode_sse
from dependencies import (
    get_chat_service,
    get_debug_trace_store,
    require_user_owner,
)
from observability import (
    bind_trace,
    clear_trace,
    get_turn_trace,
    log_event,
    overall_status,
    should_persist_turn,
)
from persistence.errors import ConversationBusyError, ConversationNotFoundError
from services.interfaces import ChatService

router = APIRouter()


@router.post("/chat")
async def chat(
    request: ConversationChatRequest,
    http_request: Request,
    service: ChatService = Depends(get_chat_service),
    debug_store=Depends(get_debug_trace_store),
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
            await _persist_debug_trace(debug_store, request, owner)
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


async def _persist_debug_trace(
    debug_store,
    request: ConversationChatRequest,
    owner,
) -> None:
    """Write the collected turn trace to Postgres, best-effort (Plan 21 §4)."""
    if debug_store is None:
        return
    events = get_turn_trace()
    if not should_persist_turn(events):
        return
    try:
        await debug_store.save(
            trace_id=request.client_turn_id,
            conversation_id=request.conversation_id,
            owner_id=getattr(owner, "owner_principal_id", None),
            status=overall_status(events),
            events=events,
        )
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning(
            "Debug trace persist failed: %s", type(exc).__name__
        )
