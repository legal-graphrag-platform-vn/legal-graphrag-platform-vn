"""Signed anonymous principal issued as an HttpOnly cookie (Plan 19 §2).

Cookie value: ``<payload_b64>.<hmac_b64>`` where payload is ``v:<uuid_hex>:<issued_at>``.
The HMAC-SHA256 signature is verified in constant time. A tampered or expired
cookie is treated as absent, and a fresh principal is issued.
"""

from __future__ import annotations

import base64
import hmac
import time
import uuid
from dataclasses import dataclass
from hashlib import sha256

from persistence.domain import Owner
from persistence.enums import OwnerKind

PRINCIPAL_COOKIE_NAME = "graphrag_anon_principal"
PRINCIPAL_VERSION = 1
_MIN_KEY_BYTES = 32


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    """The resolved owner plus a cookie value to set when it was reissued."""

    owner: Owner
    set_cookie_value: str | None


class PrincipalSigner:
    def __init__(self, signing_key: str, *, ttl_seconds: int) -> None:
        if len(signing_key.encode("utf-8")) < _MIN_KEY_BYTES:
            raise ValueError("Signing key must be at least 32 bytes")
        if ttl_seconds <= 0:
            raise ValueError("TTL must be positive")
        self._key = signing_key.encode("utf-8")
        self._ttl_seconds = ttl_seconds

    def _sign(self, payload_b64: str) -> str:
        digest = hmac.new(self._key, payload_b64.encode("ascii"), sha256).digest()
        return _b64encode(digest)

    def issue(self, *, now: int | None = None) -> tuple[uuid.UUID, str]:
        principal_id = uuid.uuid4()
        return principal_id, self._encode(principal_id, now or int(time.time()))

    def _encode(self, principal_id: uuid.UUID, issued_at: int) -> str:
        payload = f"{PRINCIPAL_VERSION}:{principal_id.hex}:{issued_at}"
        payload_b64 = _b64encode(payload.encode("ascii"))
        return f"{payload_b64}.{self._sign(payload_b64)}"

    def parse(self, cookie_value: str, *, now: int | None = None) -> uuid.UUID | None:
        """Return the principal id, or None when tampered, malformed or expired."""
        parts = cookie_value.split(".")
        if len(parts) != 2:
            return None
        payload_b64, signature = parts
        if not hmac.compare_digest(signature, self._sign(payload_b64)):
            return None
        try:
            payload = _b64decode(payload_b64).decode("ascii")
            version_str, principal_hex, issued_str = payload.split(":")
            version = int(version_str)
            issued_at = int(issued_str)
            principal_id = uuid.UUID(hex=principal_hex)
        except (ValueError, UnicodeDecodeError):
            return None
        if version != PRINCIPAL_VERSION:
            return None
        current = now or int(time.time())
        if issued_at > current + 60 or current - issued_at > self._ttl_seconds:
            return None
        return principal_id

    def authenticate(
        self, cookie_value: str | None, *, now: int | None = None
    ) -> AuthenticatedPrincipal:
        """Resolve an owner from the cookie, issuing a fresh one when needed."""
        if cookie_value:
            principal_id = self.parse(cookie_value, now=now)
            if principal_id is not None:
                return AuthenticatedPrincipal(
                    owner=_owner(principal_id),
                    set_cookie_value=None,
                )
        principal_id, fresh_cookie = self.issue(now=now)
        return AuthenticatedPrincipal(
            owner=_owner(principal_id),
            set_cookie_value=fresh_cookie,
        )


def _owner(principal_id: uuid.UUID) -> Owner:
    return Owner(owner_kind=OwnerKind.ANONYMOUS, owner_principal_id=principal_id)
