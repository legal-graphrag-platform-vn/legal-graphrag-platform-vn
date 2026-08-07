"""Password hashing and verification utility using PBKDF2-HMAC-SHA256."""

from __future__ import annotations

import base64
import hashlib
import os

_SALT_BYTES = 16
_ITERATIONS = 100_000


def hash_password(password: str) -> str:
    """Hash a raw password with a random salt using PBKDF2-HMAC-SHA256."""
    # 1. Generate a random cryptographically secure salt
    salt = os.urandom(_SALT_BYTES)
    
    # 2. Derive key using PBKDF2 HMAC SHA256
    key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        _ITERATIONS,
    )
    
    # 3. Format result as salt_b64:key_b64
    salt_b64 = base64.b64encode(salt).decode("ascii")
    key_b64 = base64.b64encode(key).decode("ascii")
    return f"{salt_b64}:{key_b64}"


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a raw password against a stored salt:key hash."""
    # 1. Parse salt and key from stored hash string
    try:
        salt_b64, key_b64 = password_hash.split(":")
        salt = base64.b64decode(salt_b64)
        expected_key = base64.b64decode(key_b64)
    except (ValueError, Exception):
        return False
    
    # 2. Compute key for the provided password
    computed_key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        _ITERATIONS,
    )
    
    # 3. Compare keys in constant time
    return hashlib.sha256(computed_key).digest() == hashlib.sha256(expected_key).digest()
