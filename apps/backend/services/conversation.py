"""Deterministic handling for messages outside the legal retrieval boundary."""

from __future__ import annotations

import re


_GREETING_MESSAGES = frozenset(
    {
        "chào",
        "chào bạn",
        "hello",
        "hey",
        "hi",
        "xin chào",
    }
)

_GREETING_RESPONSE = (
    "Xin chào! Tôi hỗ trợ tra cứu Luật Doanh nghiệp 2020 trên dữ liệu pilot. "
    "Bạn có thể hỏi về điều, khoản, khái niệm hoặc quy định pháp lý cụ thể."
)


def greeting_response(message: str) -> str | None:
    """Return a direct response only when the complete message is a greeting."""
    normalized = re.sub(r"\s+", " ", message.casefold()).strip(" \t\r\n!?.,")
    if normalized in _GREETING_MESSAGES:
        return _GREETING_RESPONSE
    return None
