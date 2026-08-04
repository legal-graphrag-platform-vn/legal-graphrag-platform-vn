"""
POST /api/v1/chat — grounded conversation SSE endpoint (Plan 19 §2, §4).
"""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from api.models import ConversationChatRequest, encode_sse
from auth.principal import PRINCIPAL_COOKIE_NAME
from dependencies import get_chat_service
from persistence.domain import Owner
from persistence.enums import OwnerKind
from persistence.errors import ConversationBusyError, ConversationNotFoundError
from services.interfaces import ChatService

router = APIRouter()


def _resolve_owner(request: Request) -> tuple[Owner, str | None]:
    """Authenticate the signed principal, issuing a fresh cookie when needed."""
    container = request.app.state.container
    signer = getattr(container, "principal_signer", None)
    if signer is None:
        # Mock mode has no signing key; synthesize a throwaway anonymous owner.
        return Owner(
            owner_kind=OwnerKind.ANONYMOUS, owner_principal_id=uuid.uuid4()
        ), None
    authenticated = signer.authenticate(request.cookies.get(PRINCIPAL_COOKIE_NAME))
    return authenticated.owner, authenticated.set_cookie_value


@router.post("/chat")
async def chat(
    request: ConversationChatRequest,
    http_request: Request,
    service: ChatService = Depends(get_chat_service),
) -> StreamingResponse:
    owner, set_cookie = _resolve_owner(http_request)

    async def generate():
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
        except Exception:
            yield encode_sse(
                "error",
                {"code": "STREAM_ERROR", "message": "Đã xảy ra lỗi nội bộ."},
            )
            yield encode_sse("done", {"status": "error", "citation_count": 0})

    response = StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
    if set_cookie is not None:
        settings = http_request.app.state.settings
        response.set_cookie(
            key=PRINCIPAL_COOKIE_NAME,
            value=set_cookie,
            max_age=settings.anonymous_principal_cookie_ttl_days * 86400,
            httponly=True,
            samesite="lax",
            path="/",
            secure=settings.anonymous_principal_cookie_secure,
        )
    return response
