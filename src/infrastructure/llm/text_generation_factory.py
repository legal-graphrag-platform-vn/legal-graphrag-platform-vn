"""Composition root that selects a text-generation provider from configuration.

Switch providers with ``LLM_PROVIDER`` ("gemini" | "ollama"). No provider client
is created at import time — only when this factory is called.
"""

from __future__ import annotations

import os
from typing import Mapping

from src.infrastructure.llm.errors import TextGenerationDependencyError
from src.infrastructure.llm.gemini_text_provider import GeminiTextProvider
from src.infrastructure.llm.ollama_text_provider import OllamaTextProvider
from src.shared.llm_ports import TextGenerationPort

_DEFAULT_PROVIDER = "gemini"
_DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
_DEFAULT_OLLAMA_MODEL = "qwen3:4b"
_DEFAULT_OLLAMA_HOST = "http://localhost:11434"


def build_text_generator(
    *,
    provider: str | None = None,
    env: Mapping[str, str] | None = None,
) -> TextGenerationPort:
    """Build the configured text-generation adapter.

    ``provider`` overrides ``LLM_PROVIDER``; ``env`` overrides ``os.environ``
    (useful for tests). Unknown providers fail explicitly.
    """
    environ = env if env is not None else os.environ
    selected = (
        (provider or environ.get("LLM_PROVIDER", _DEFAULT_PROVIDER)).strip().lower()
    )

    if selected == "gemini":
        return GeminiTextProvider(
            api_key=environ.get("GEMINI_API_KEY")
            or environ.get("GOOGLE_API_KEY")
            or "",
            model=environ.get("GEMINI_QUERY_MODEL", _DEFAULT_GEMINI_MODEL),
        )
    if selected == "ollama":
        return OllamaTextProvider(
            model=environ.get("OLLAMA_MODEL", _DEFAULT_OLLAMA_MODEL),
            host=environ.get("OLLAMA_HOST", _DEFAULT_OLLAMA_HOST),
        )
    raise TextGenerationDependencyError(
        f"Unsupported LLM_PROVIDER: {selected!r} (expected 'gemini' or 'ollama')"
    )
