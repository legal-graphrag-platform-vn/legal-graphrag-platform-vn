"""Auth Endpoints for User Registration, Login, Logout, Me, and Claiming Guest Conversations.

Rule R1 Compliance: Step comments start with // 1.   , // 2.   , etc.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from auth.password import hash_password, verify_password
from auth.principal import PRINCIPAL_COOKIE_NAME, USER_COOKIE_NAME, PrincipalSigner
from dependencies import get_principal_signer, get_repository

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=6, max_length=128)
    full_name: str | None = Field(default=None, max_length=128)


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    response: Response,
    request: Request,
    repo=Depends(get_repository),
    signer: PrincipalSigner = Depends(get_principal_signer),
) -> dict[str, Any]:
    # 1. Check if username already exists in accounts table
    existing = await repo.get_account_by_username(payload.username)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tên đăng nhập đã tồn tại trong hệ thống.",
        )

    # 2. Hash raw password securely using PBKDF2-HMAC-SHA256
    pwd_hash = hash_password(payload.password)

    # 3. Insert user profile and account into database
    user_dict, account_dict = await repo.create_user_with_account(
        username=payload.username,
        password_hash=pwd_hash,
        full_name=payload.full_name,
    )

    # 4. Issue signed user JWT cookie
    token = signer.issue_user_token(
        user_id=user_dict["id"],
        username=account_dict["username"],
    )
    response.set_cookie(
        key=USER_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        path="/",
    )

    # 5. Optionally claim any existing guest conversations if anonymous cookie is present
    anon_cookie = request.cookies.get(PRINCIPAL_COOKIE_NAME)
    claimed_count = 0
    if anon_cookie:
        anon_id = signer.parse(anon_cookie)
        if anon_id is not None:
            claimed_count = await repo.claim_guest_conversations(
                anon_principal_id=anon_id,
                user_id=user_dict["id"],
            )

    return {
        "user_id": str(user_dict["id"]),
        "username": account_dict["username"],
        "full_name": user_dict["full_name"],
        "claimed_conversations": claimed_count,
    }


@router.post("/login")
async def login(
    payload: LoginRequest,
    response: Response,
    request: Request,
    repo=Depends(get_repository),
    signer: PrincipalSigner = Depends(get_principal_signer),
) -> dict[str, Any]:
    # 1. Fetch account details by username
    account = await repo.get_account_by_username(payload.username)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tên đăng nhập hoặc mật khẩu không chính xác.",
        )

    # 2. Verify password against stored PBKDF2 hash
    if not verify_password(payload.password, account["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tên đăng nhập hoặc mật khẩu không chính xác.",
        )

    # 3. Fetch associated user profile
    user = await repo.get_user_by_id(account["user_id"])
    if user is None or not user.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tài khoản của bạn đã bị vô hiệu hóa.",
        )

    # 4. Issue signed user token cookie
    token = signer.issue_user_token(
        user_id=account["user_id"],
        username=account["username"],
    )
    response.set_cookie(
        key=USER_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        path="/",
    )

    # 5. Claim guest conversations if guest cookie is present
    anon_cookie = request.cookies.get(PRINCIPAL_COOKIE_NAME)
    claimed_count = 0
    if anon_cookie:
        anon_id = signer.parse(anon_cookie)
        if anon_id is not None:
            claimed_count = await repo.claim_guest_conversations(
                anon_principal_id=anon_id,
                user_id=account["user_id"],
            )

    return {
        "user_id": str(account["user_id"]),
        "username": account["username"],
        "full_name": user.get("full_name"),
        "claimed_conversations": claimed_count,
        "token": token,
    }


@router.post("/logout")
async def logout(response: Response) -> dict[str, str]:
    # 1. Clear user token cookie
    response.delete_cookie(key=USER_COOKIE_NAME, path="/")
    return {"message": "Đăng xuất thành công."}


@router.get("/me")
async def me(
    request: Request,
    repo=Depends(get_repository),
    signer: PrincipalSigner = Depends(get_principal_signer),
) -> dict[str, Any]:
    # 1. Extract user token from cookie or Authorization header
    user_token = request.cookies.get(USER_COOKIE_NAME)
    if not user_token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            user_token = auth_header[7:].strip()

    # 2. Parse token and verify validity
    if not user_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Chưa đăng nhập.",
        )

    parsed = signer.parse_user_token(user_token)
    if parsed is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token không hợp lệ hoặc đã hết hạn.",
        )

    # 3. Load user profile from database
    user_id, username = parsed
    user = await repo.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy thông tin người dùng.",
        )

    return {
        "user_id": str(user["id"]),
        "username": username,
        "full_name": user.get("full_name"),
        "is_active": user.get("is_active", True),
    }


@router.post("/claim-guest")
async def claim_guest(
    request: Request,
    repo=Depends(get_repository),
    signer: PrincipalSigner = Depends(get_principal_signer),
) -> dict[str, int]:
    # 1. Resolve current user identity
    user_token = request.cookies.get(USER_COOKIE_NAME)
    if not user_token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            user_token = auth_header[7:].strip()

    if not user_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Cần đăng nhập để thực hiện gộp hội thoại.",
        )

    parsed = signer.parse_user_token(user_token)
    if parsed is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token không hợp lệ.",
        )

    # 2. Extract anonymous principal ID from guest cookie
    user_id, _ = parsed
    anon_cookie = request.cookies.get(PRINCIPAL_COOKIE_NAME)
    if not anon_cookie:
        return {"claimed_count": 0}

    anon_id = signer.parse(anon_cookie)
    if anon_id is None:
        return {"claimed_count": 0}

    # 3. Update all guest conversations to belonging to current user_id
    claimed_count = await repo.claim_guest_conversations(
        anon_principal_id=anon_id,
        user_id=user_id,
    )
    return {"claimed_count": claimed_count}
