"""Typed failures for text-generation adapters.

The base ``TextGenerationError`` lives in ``src/shared`` so the retrieval layer
can catch it without importing infrastructure; it is re-exported here for
adapters that already import from this module.
"""

from __future__ import annotations

from src.shared.llm_errors import TextGenerationError

__all__ = [
    "TextGenerationError",
    "TextGenerationDependencyError",
    "TextGenerationOutputError",
]


class TextGenerationDependencyError(TextGenerationError):
    """A required SDK, network endpoint, or credential was unavailable."""


class TextGenerationOutputError(TextGenerationError):
    """The provider returned an empty or unusable payload."""
