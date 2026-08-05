"""Conversations API Endpoints for List History, Detail, Rename, and Delete.

Rule R1 Compliance: Step comments start with // 1.   , // 2.   , etc.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from api.routes.chat import _resolve_owner
from dependencies import get_repository

router = APIRouter(prefix="/conversations", tags=["conversations"])


class PatchTitleRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)


@router.get("")
async def list_conversations(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    repo=Depends(get_repository),
) -> list[dict[str, Any]]:
    # 1. Resolve current principal (user or anonymous)
    owner, _ = _resolve_owner(request)

    # 2. Query repository for conversation list owned by principal
    conversations = await repo.list_conversations(
        owner=owner,
        limit=limit,
        offset=offset,
    )
    return conversations


@router.get("/{conversation_id}")
async def get_conversation_detail(
    conversation_id: uuid.UUID,
    request: Request,
    repo=Depends(get_repository),
) -> dict[str, Any]:
    # 1. Resolve current principal
    owner, _ = _resolve_owner(request)

    # 2. Fetch conversation transcript details
    detail = await repo.get_conversation_detail(
        conversation_id=conversation_id,
        owner=owner,
    )
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy cuộc trò chuyện.",
        )
    return detail


@router.patch("/{conversation_id}")
async def patch_conversation_title(
    conversation_id: uuid.UUID,
    payload: PatchTitleRequest,
    request: Request,
    repo=Depends(get_repository),
) -> dict[str, Any]:
    # 1. Resolve current principal
    owner, _ = _resolve_owner(request)

    # 2. Update conversation title
    success = await repo.patch_conversation_title(
        conversation_id=conversation_id,
        owner=owner,
        title=payload.title,
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy cuộc trò chuyện để đổi tên.",
        )
    return {"id": str(conversation_id), "title": payload.title.strip()}


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: uuid.UUID,
    request: Request,
    repo=Depends(get_repository),
) -> dict[str, Any]:
    # 1. Resolve current principal
    owner, _ = _resolve_owner(request)

    # 2. Soft delete conversation in repository
    success = await repo.delete_conversation(
        conversation_id=conversation_id,
        owner=owner,
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy cuộc trò chuyện để xóa.",
        )
    return {"message": "Xóa cuộc trò chuyện thành công.", "id": str(conversation_id)}
