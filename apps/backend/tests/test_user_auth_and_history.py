"""Unit tests for Password Hashing, User Token Principal Resolution, and Auth APIs."""

from __future__ import annotations

import uuid

from auth.password import hash_password, verify_password
from auth.principal import PrincipalSigner
from persistence.enums import OwnerKind


def test_password_hashing_and_verification():
    raw_pwd = "SuperSecretPassword123"
    pwd_hash = hash_password(raw_pwd)

    assert pwd_hash != raw_pwd
    assert ":" in pwd_hash
    assert verify_password(raw_pwd, pwd_hash) is True
    assert verify_password("WrongPassword", pwd_hash) is False


def test_user_token_issuance_and_parsing():
    signer = PrincipalSigner("0" * 32, ttl_seconds=3600)
    user_id = uuid.uuid4()
    username = "testuser"

    token = signer.issue_user_token(user_id=user_id, username=username)
    assert isinstance(token, str)
    assert "." in token

    parsed = signer.parse_user_token(token)
    assert parsed is not None
    parsed_id, parsed_name = parsed
    assert parsed_id == user_id
    assert parsed_name == username


def test_principal_signer_user_authentication():
    signer = PrincipalSigner("0" * 32, ttl_seconds=3600)
    user_id = uuid.uuid4()
    token = signer.issue_user_token(user_id=user_id, username="alice")

    # 1. Authenticate with user token
    authenticated = signer.authenticate(cookie_value=None, user_token=token)
    assert authenticated.owner.owner_kind == OwnerKind.USER
    assert authenticated.owner.owner_principal_id == user_id
    assert authenticated.set_cookie_value is None

    # 2. Authenticate fallback to anonymous when user token is invalid
    authenticated_anon = signer.authenticate(cookie_value=None, user_token="invalid.token")
    assert authenticated_anon.owner.owner_kind == OwnerKind.ANONYMOUS
    assert authenticated_anon.set_cookie_value is not None
