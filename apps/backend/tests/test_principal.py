"""Unit tests for the signed anonymous principal (Plan 19 §2)."""

from __future__ import annotations

import pytest

from auth.principal import PrincipalSigner
from persistence.enums import OwnerKind

_KEY = "x" * 32
_TTL = 180 * 24 * 3600


def _signer(key: str = _KEY) -> PrincipalSigner:
    return PrincipalSigner(key, ttl_seconds=_TTL)


def test_short_key_is_rejected() -> None:
    with pytest.raises(ValueError):
        PrincipalSigner("x" * 31, ttl_seconds=_TTL)


def test_issued_cookie_round_trips() -> None:
    signer = _signer()
    principal_id, cookie = signer.issue(now=1000)
    assert signer.parse(cookie, now=1000) == principal_id


def test_authenticate_reuses_valid_cookie_without_reissue() -> None:
    signer = _signer()
    principal_id, cookie = signer.issue(now=1000)
    result = signer.authenticate(cookie, now=1000)
    assert result.owner.owner_principal_id == principal_id
    assert result.owner.owner_kind is OwnerKind.ANONYMOUS
    assert result.set_cookie_value is None


def test_authenticate_issues_when_cookie_missing() -> None:
    result = _signer().authenticate(None, now=1000)
    assert result.set_cookie_value is not None
    assert result.owner.owner_principal_id is not None


def test_tampered_signature_is_rejected() -> None:
    signer = _signer()
    _, cookie = signer.issue(now=1000)
    payload, _signature = cookie.split(".")
    tampered = f"{payload}.AAAAtampered"
    assert signer.parse(tampered, now=1000) is None


def test_tampered_payload_is_rejected() -> None:
    signer = _signer()
    principal_id, cookie = signer.issue(now=1000)
    _payload, signature = cookie.split(".")
    other_id, other_cookie = signer.issue(now=1000)
    other_payload, _ = other_cookie.split(".")
    forged = f"{other_payload}.{signature}"
    assert signer.parse(forged, now=1000) is None
    assert other_id != principal_id


def test_expired_cookie_is_rejected() -> None:
    signer = _signer()
    _, cookie = signer.issue(now=1000)
    assert signer.parse(cookie, now=1000 + _TTL + 1) is None


def test_future_issued_cookie_is_rejected() -> None:
    signer = _signer()
    _, cookie = signer.issue(now=10_000)
    assert signer.parse(cookie, now=1000) is None


def test_cookie_signed_with_other_key_is_rejected() -> None:
    _, cookie = _signer("a" * 40).issue(now=1000)
    assert _signer("b" * 40).parse(cookie, now=1000) is None


def test_authenticate_reissues_on_tampered_cookie() -> None:
    signer = _signer()
    _, cookie = signer.issue(now=1000)
    payload, _sig = cookie.split(".")
    result = signer.authenticate(f"{payload}.bad", now=1000)
    assert result.set_cookie_value is not None


def test_malformed_cookie_is_rejected() -> None:
    signer = _signer()
    assert signer.parse("not-a-cookie", now=1000) is None
    assert signer.parse("a.b.c", now=1000) is None
