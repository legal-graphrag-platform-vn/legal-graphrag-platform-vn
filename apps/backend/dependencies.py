"""
FastAPI DI functions — đọc service từ app.state.container.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, Request, status

from auth.principal import USER_COOKIE_NAME
from persistence.domain import Owner
from persistence.enums import OwnerKind
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


def get_debug_trace_store(request: Request):
    """Optional durable debug-trace store; None when not configured (Plan 21)."""
    return getattr(request.app.state.container, "debug_trace_store", None)


def get_repository(request: Request):
    repo = getattr(request.app.state.container, "conversation_repo", None)
    if repo is None:
        raise BackendFeatureUnavailableError(
            "Conversation repository is not enabled for this runtime profile"
        )
    return repo


def get_principal_signer(request: Request):
    signer = getattr(request.app.state.container, "principal_signer", None)
    if signer is None:
        raise BackendFeatureUnavailableError(
            "Principal signer is not configured"
        )
    return signer


def _extract_user_token(request: Request) -> str | None:
    """Read the user token from the auth cookie or an Authorization Bearer header."""
    token = request.cookies.get(USER_COOKIE_NAME)
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
    return token or None


def require_user_owner(request: Request) -> Owner:
    """Require an authenticated USER principal (login-only mode).

    Anonymous access is disabled: chat and conversation endpoints reject
    unauthenticated callers with HTTP 401. The signed anonymous principal code
    remains in place but is no longer used to grant access.
    """
    container = request.app.state.container
    signer = getattr(container, "principal_signer", None)
    if signer is None:
        # 1. Mock mode has no signing key; use a throwaway user identity.
        return Owner(owner_kind=OwnerKind.USER, owner_principal_id=uuid.uuid4())

    # 2. Parse the user token; reject when missing, tampered or expired.
    token = _extract_user_token(request)
    parsed = signer.parse_user_token(token) if token else None
    if parsed is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Vui lòng đăng nhập để sử dụng tính năng này.",
        )
    user_id, _ = parsed
    return Owner(owner_kind=OwnerKind.USER, owner_principal_id=user_id)
