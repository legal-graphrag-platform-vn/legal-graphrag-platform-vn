"""Deterministic conversation title derivation (Plan 20 §5).

A rule-based fallback that shortens the first user question into a concise
title without calling an LLM. Kept pure so it is trivially unit-testable and
reusable by both the background auto-title path and the explicit
``/generate-title`` endpoint.
"""

from __future__ import annotations

MAX_TITLE_LENGTH = 50
DEFAULT_TITLE = "Cuộc trò chuyện mới"


def derive_title(first_message: str, *, max_length: int = MAX_TITLE_LENGTH) -> str:
    """Return a concise title derived from the first user message.

    Rules:
      1. Collapse whitespace and trim.
      2. Fall back to the default title when empty.
      3. Truncate to ``max_length`` characters at a word boundary when possible,
         appending an ellipsis.
    """
    # 1. Normalise whitespace into single spaces.
    normalised = " ".join(first_message.split())
    if not normalised:
        return DEFAULT_TITLE

    # 2. Short enough already; return verbatim.
    if len(normalised) <= max_length:
        return normalised

    # 3. Truncate, preferring the last word boundary before the limit.
    truncated = normalised[:max_length].rstrip()
    last_space = truncated.rfind(" ")
    if last_space >= max_length // 2:
        truncated = truncated[:last_space].rstrip()
    return f"{truncated}…"
