"""Provider-agnostic LLM ports shared across layers.

Defining the port in ``src/shared`` lets the retrieval domain depend on it while
infrastructure adapters conform to it without importing an inner layer.
"""

from __future__ import annotations

from typing import Protocol


class TextGenerationPort(Protocol):
    """Single-turn text generation with an explicit system/user separation."""

    def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        response_format: str | None = None,
    ) -> str: ...
